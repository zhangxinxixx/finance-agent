"""CME worker pipeline — download → parse → ingest → options analysis.

Chains the existing CME modules into the premarket worker flow.
Each step is dispatched by name via ``run_cme_step``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from apps.analysis.options.report import render_options_report_markdown
from apps.analysis.options.snapshot import build_options_snapshot, snapshot_to_dict
from apps.analysis.options.visual_report import build_options_visual_report_vm
from apps.collectors.cme.downloader import CmeRawFile, download_cme_pdf
from apps.output.artifacts import artifact_run_dir
from apps.parsers.cme.pdf_parser import CmePdfParseResult, parse_pg64_pdf
from apps.renderer.html.options_visual import render_options_visual_html
from database.queries.warehouse_cme import (
    WarehouseCmeOptionRow as CmeOptionRow, WarehouseCmeReadError,
    get_available_cme_trade_dates, get_cme_option_rows, get_cme_option_rows_multi_date,
    build_cme_selected_lineage,
)
from database.queries.cme import (
    CmeIngestResult,
    ingest_cme_parse_result,
)
from apps.features.options.calibration import calibrate_walls
from apps.features.options.reconcile import reconcile_cme_versions
from apps.features.options.selection import select_expiry_window

# ---------------------------------------------------------------------------
# Step names that belong to the CME pipeline
# ---------------------------------------------------------------------------

CME_STEPS = {"cme_download", "cme_parse", "cme_ingest", "option_wall"}

# ---------------------------------------------------------------------------
# Pipeline state — threaded through each step
# ---------------------------------------------------------------------------


@dataclass
class CmePipelineState:
    """Holds intermediate results for the CME pipeline."""

    raw_file: CmeRawFile | None = None
    parse_result: CmePdfParseResult | None = None
    ingest_result: CmeIngestResult | None = None
    snapshot_dict: dict[str, Any] | None = None
    report_md: str | None = None
    reconciliation: dict[str, Any] = field(default_factory=dict)
    step_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def run_cme_step(
    step_name: str,
    state: CmePipelineState,
    *,
    db: DBSession,
    storage_root: Path = Path("./storage"),
    run_id: str | None = None,
    product: str = "OG",
    section_file: str = "Section64_Metals_Option_Products.pdf",
) -> dict[str, Any]:
    """Execute a single CME pipeline step and update *state*.

    Returns a summary dict for the step (suitable for task logging).

    Raises on failure; the caller is responsible for marking the task step
    as failed.
    """
    dispatch = {
        "cme_download": _step_download,
        "cme_parse": _step_parse,
        "cme_ingest": _step_ingest,
        "option_wall": _step_options_analysis,
    }

    fn = dispatch.get(step_name)
    if fn is None:
        raise ValueError(f"Unknown CME step: {step_name!r}")

    summary = fn(
        state,
        db=db,
        storage_root=storage_root,
        run_id=run_id,
        product=product,
        section_file=section_file,
    )
    state.step_summaries[step_name] = summary
    return summary


# ---------------------------------------------------------------------------
# Individual step implementations
# ---------------------------------------------------------------------------


def _step_download(
    state: CmePipelineState,
    *,
    db: DBSession,
    storage_root: Path,
    run_id: str | None,
    product: str,
    section_file: str,
) -> dict[str, Any]:
    """Step 1: Download CME Daily Bulletin PDF and archive to storage."""

    raw_file = download_cme_pdf(
        section_file=section_file,
        storage_root=storage_root,
    )
    state.raw_file = raw_file
    return {
        "step": "cme_download",
        "status": "success",
        "report_date": raw_file.report_date,
        "sha256": raw_file.sha256,
        "bytes": raw_file.bytes,
        "raw_path": raw_file.raw_path,
    }


def _step_parse(
    state: CmePipelineState,
    *,
    db: DBSession,
    storage_root: Path,
    run_id: str | None,
    product: str,
    section_file: str,
) -> dict[str, Any]:
    """Step 2: Parse the PG64 PDF into structured rows and archive the parse result."""

    if state.raw_file is None:
        raise RuntimeError("cme_parse requires cme_download to have completed first")

    pdf_path = storage_root / state.raw_file.raw_path
    if not pdf_path.exists():
        raise FileNotFoundError(f"Archived PDF not found: {pdf_path}")

    parse_result = parse_pg64_pdf(pdf_path, product=product)
    state.parse_result = parse_result
    parsed_dir = artifact_run_dir(
        storage_root,
        layer="parsed",
        domain="cme",
        date=parse_result.trade_date,
        run_id=run_id,
    )
    parsed_dir.mkdir(parents=True, exist_ok=True)
    parsed_path = parsed_dir / "cme_parse_result.json"
    parsed_path.write_text(
        json.dumps(parse_result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "step": "cme_parse",
        "status": "success",
        "trade_date": parse_result.trade_date,
        "detail_rows": len(parse_result.detail_rows),
        "summary_rows": len(parse_result.summary_rows),
        "warnings": len(parse_result.warnings),
        "parsed_path": str(parsed_path),
    }


def _step_ingest(
    state: CmePipelineState,
    *,
    db: DBSession,
    storage_root: Path,
    run_id: str | None,
    product: str,
    section_file: str,
) -> dict[str, Any]:
    """Step 3: Ingest parse result into DB and write summary JSON."""

    if state.raw_file is None:
        raise RuntimeError("cme_ingest requires cme_download to have completed first")
    if state.parse_result is None:
        raise RuntimeError("cme_ingest requires cme_parse to have completed first")

    pdf_path = storage_root / state.raw_file.raw_path

    ingest_result = ingest_cme_parse_result(
        db,
        raw_pdf_path=pdf_path,
        parse_result=state.parse_result,
        source_url=state.raw_file.source_url,
        section=section_file.replace(".pdf", ""),
    )
    from apps.data_layer.collection_ingestion import ingest_collection_records

    warehouse_ingestion = ingest_collection_records(
        db, "cme-options", record_ids=[ingest_result.raw_file_id], storage_root=storage_root,
        run_id=run_id,
        raw_sources=[{"raw_path": state.raw_file.raw_path, "source_key": "cme_daily_bulletin",
                      "source_url": state.raw_file.source_url, "collected_at": state.raw_file.retrieved_at,
                      "sha256": state.raw_file.sha256, "expected_records": ingest_result.total_rows}],
    )
    db.commit()
    if warehouse_ingestion.get("status") != "loaded":
        raise RuntimeError("DWD_CME_COLLECTION_NOT_LOADED")
    state.ingest_result = ingest_result

    # Write cme_ingest_summary.json
    report_date = ingest_result.report_date
    out_dir = artifact_run_dir(
        storage_root,
        layer="outputs",
        domain="cme",
        date=report_date,
        run_id=run_id,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "cme_ingest_summary.json"
    summary_path.write_text(
        json.dumps(ingest_result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "step": "cme_ingest",
        "status": "success",
        "raw_file_id": ingest_result.raw_file_id,
        "report_date": ingest_result.report_date,
        "inserted_rows": ingest_result.inserted_rows,
        "existing_rows": ingest_result.existing_rows,
        "total_rows": ingest_result.total_rows,
        "replaced_rows": ingest_result.replaced_rows,
        "version_type": ingest_result.version_type,
        "summary_path": str(summary_path),
        "warehouse": warehouse_ingestion,
    }


def _map_parse_status(parse_result: CmePdfParseResult | None) -> str:
    """Map parse_result.status into the internal source_status used by option snapshots.

    ``PRELIMINARY`` normalises to ``PRELIM`` so downstream data-quality
    counting (which matches on ``PRELIM*`` prefixes) works consistently.
    ``FINAL`` stays ``FINAL``.  ``UNKNOWN`` or missing parse → ``PRELIM_assumed``
    (explicitly documented fallback — "assumed preliminary").
    """
    if parse_result is None:
        return "PRELIM_assumed"
    raw = (parse_result.status or "").strip().upper()
    if raw == "PRELIMINARY":
        return "PRELIM"
    if raw == "FINAL":
        return "FINAL"
    return "PRELIM_assumed"


def _step_options_analysis(
    state: CmePipelineState,
    *,
    db: DBSession,
    storage_root: Path,
    run_id: str | None,
    product: str,
    section_file: str,
) -> dict[str, Any]:
    """Step 4: Run options analysis and write feature JSON + Markdown report."""

    if state.ingest_result is None:
        raise RuntimeError("option_wall requires cme_ingest to have completed first")

    report_date = state.ingest_result.report_date

    # Read the FINAL-preferred option rows from DB and convert to dicts for the
    # analysis pipeline.  ``get_cme_option_rows`` already preserves the
    # exchange's PRELIMINARY rows while preferring FINAL for the current view.
    option_rows = get_cme_option_rows(db, report_date=report_date, product=product)
    if not option_rows:
        return {
            "step": "option_wall",
            "status": "skipped",
            "reason": f"No option rows found for report_date={report_date}, product={product}",
        }

    raw_rows = [_row_to_dict(row) for row in option_rows]

    # The downloaded file in this run is not necessarily the file selected for
    # analysis: a PRELIM retry can run after a FINAL bulletin was already
    # ingested.  Build lineage from the selected DB rows before setting the
    # feature revision, source URL, or input IDs so the feature cannot claim
    # FINAL while pointing back to the current PRELIM download.
    selected_lineage = _selected_cme_lineage(db, option_rows)

    # Run the full analysis pipeline
    source_status = _map_parse_status(state.parse_result)
    source_url = state.raw_file.source_url if state.raw_file else None
    input_ids: dict[str, Any] = {}
    selected_versions = {
        str(getattr(row, "version_type", "") or "").strip().upper()
        for row in option_rows
        if isinstance(getattr(row, "version_type", ""), str)
    }
    if "FINAL" in selected_versions:
        source_status = "FINAL"
    elif "PRELIMINARY" in selected_versions:
        source_status = "PRELIM"

    selected_raw_ids = selected_lineage["raw_file_ids"]
    selected_shas = selected_lineage["raw_file_sha256s"]
    selected_parse_ids = selected_lineage["parse_run_ids"]
    input_ids["warehouse_fact_ids"] = sorted(row.warehouse_fact_id for row in option_rows)
    input_ids["warehouse_batch_ids"] = sorted({row.batch_id for row in option_rows})
    input_ids["warehouse_versions"] = sorted({row.version_sha256 for row in option_rows})
    if selected_raw_ids:
        input_ids["raw_file_id"] = selected_raw_ids[0]
        input_ids["raw_file_ids"] = selected_raw_ids
    elif state.ingest_result and state.ingest_result.raw_file_id:
        input_ids["raw_file_id"] = str(state.ingest_result.raw_file_id)
    if selected_shas:
        input_ids["raw_file_sha256"] = selected_shas[0]
        input_ids["raw_file_sha256s"] = selected_shas
    elif state.raw_file:
        input_ids["raw_file_sha256"] = state.raw_file.sha256
    if selected_parse_ids:
        input_ids["parse_run_id"] = selected_parse_ids[0]
        input_ids["parse_run_ids"] = selected_parse_ids
    if selected_lineage["source_urls"]:
        source_url = selected_lineage["source_urls"][0]

    # Dynamic window: always include the nearest eligible expiry, then fill
    # the remaining slot(s) by total OI.  The selection metadata is persisted
    # with the feature so a report never looks like a full-chain calculation
    # when only a compact window was selected.
    expiry_selection = select_expiry_window(
        raw_rows,
        trade_date=report_date,
        # Select the nearest eligible expiry plus the top two OI expiries.
        # Three is the maximum union size; using 2 here would silently drop
        # one of the requested OI leaders whenever the nearest is different.
        max_expiries=3,
        top_n_oi=2,
    )
    near_expiries = expiry_selection.selected_expiries

    # When a FINAL bulletin arrives after a PRELIMINARY bulletin, retain both
    # row sets and record a row-level diff.  The DB query's default FINAL
    # preference makes the FINAL set the current feature input automatically.
    current_versions = selected_versions
    if "FINAL" in current_versions:
        # A PRELIM parse can be retried after FINAL has already been ingested;
        # the DB's FINAL-preferred row set is authoritative for this feature.
        source_status = "FINAL"
    elif "PRELIMINARY" in current_versions:
        source_status = "PRELIM"
    reconciliation: dict[str, Any]
    if "FINAL" in current_versions:
        try:
            prelim_orm = get_cme_option_rows(
                db, report_date=report_date, product=product, version_type="PRELIMINARY",
            )
        except WarehouseCmeReadError as exc:
            if str(exc) != "DWD_CME_FACTS_MISSING":
                raise
            prelim_orm = []
        final_orm = get_cme_option_rows(
            db, report_date=report_date, product=product, version_type="FINAL",
        )
        try:
            prelim_source_ids = sorted(
                {
                    str(getattr(row, "raw_file_id"))
                    for row in prelim_orm
                    if isinstance(getattr(row, "raw_file_id", None), str)
                }
            )
            final_source_ids = sorted(
                {
                    str(getattr(row, "raw_file_id"))
                    for row in final_orm
                    if isinstance(getattr(row, "raw_file_id", None), str)
                }
            )
            reconciliation = reconcile_cme_versions(
                [_row_to_dict(row) for row in prelim_orm],
                [_row_to_dict(row) for row in final_orm],
                report_date=report_date,
                product=product,
                source_refs=[
                    {
                        "source": "dwh_fact_cme_option",
                        "version_type": "PRELIMINARY",
                        "report_date": report_date,
                        "raw_file_ids": prelim_source_ids,
                    },
                    {
                        "source": "dwh_fact_cme_option",
                        "version_type": "FINAL",
                        "report_date": report_date,
                        "raw_file_ids": final_source_ids,
                    },
                ],
            )
        except ValueError as exc:
            # A malformed comparison must not contaminate the current FINAL
            # feature.  Keep the feature usable and expose the audit failure.
            reconciliation = {
                "schema_version": "cme_options_reconciliation.v1",
                "report_date": report_date,
                "product": product,
                "status": "unavailable",
                "current_selection": "FINAL",
                "feature_version": "cme_options_analysis.v2",
                "error": str(exc),
                "source_refs": [],
            }
    else:
        reconciliation = reconcile_cme_versions(
            raw_rows,
            [],
            report_date=report_date,
            product=product,
            source_refs=[
                {
                    "source": "dwh_fact_cme_option",
                    "version_type": "PRELIMINARY" if "PRELIMINARY" in current_versions else source_status,
                    "report_date": report_date,
                }
            ],
        )

    raw_sha = input_ids.get("raw_file_sha256")
    revision_source = raw_sha[:12] if isinstance(raw_sha, str) else "unversioned"
    feature_revision = f"cme_options_analysis.v2:{source_status.upper()}:{revision_source}"
    reconciliation = {
        **reconciliation,
        "feature_revision": feature_revision,
        "selected_feature_revision": feature_revision,
    }
    state.reconciliation = reconciliation

    result = build_options_snapshot(
        raw_rows,
        product=product,
        trade_date=report_date,
        expiries=near_expiries,
        data_source_status=source_status,
        data_source_url=source_url,
        input_snapshot_ids=input_ids,
        expiry_selection=expiry_selection.to_dict(),
        reconciliation=reconciliation,
        feature_version="cme_options_analysis.v2",
        feature_revision=feature_revision,
    )

    # ── P4-06: multi-day wall calibration with near-month filter ────
    try:
        available_dates = get_available_cme_trade_dates(db, product=product, limit=6)
        if len(available_dates) >= 2:
            multi_rows = get_cme_option_rows_multi_date(db, trade_dates=available_dates, product=product)
            # Filter to the selected dynamic expiry window for cross-date comparison.
            multi_dicts: dict[str, list[dict[str, Any]]] = {}
            for date, rows in multi_rows.items():
                filtered = [r for r in rows if (r.expiry if hasattr(r, 'expiry') else r.get('expiry')) in near_expiries]
                if filtered:
                    multi_dicts[date] = [_row_to_dict(r) for r in filtered]
            if multi_dicts:
                cal_result = calibrate_walls(
                    multi_dicts,
                    current_trade_date=report_date,
                    lookback_days=5,
                )
                import dataclasses as _dc
                result = _dc.replace(result, calibration=cal_result)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Multi-day calibration failed — continuing without calibration")

    snapshot_dict = snapshot_to_dict(result)
    snapshot_dict["selected_source_refs"] = selected_lineage.get("source_refs", [])
    snapshot_dict["data_source"]["source_refs"] = selected_lineage.get("source_refs", [])
    report_md = render_options_report_markdown(result)
    visual_vm = build_options_visual_report_vm(result)
    visual_json = visual_vm.to_dict()
    visual_html = render_options_visual_html(visual_vm)

    state.snapshot_dict = snapshot_dict
    state.report_md = report_md

    features_dir = artifact_run_dir(
        storage_root,
        layer="features",
        domain="cme",
        date=report_date,
        run_id=run_id,
    )
    outputs_dir = artifact_run_dir(
        storage_root,
        layer="outputs",
        domain="cme",
        date=report_date,
        run_id=run_id,
    )
    features_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    json_path = features_dir / "options_analysis.json"
    json_path.write_text(
        json.dumps(snapshot_dict, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    md_path = outputs_dir / "options_analysis.md"
    md_path.write_text(report_md, encoding="utf-8")
    visual_json_path = outputs_dir / "options_visual_report.json"
    visual_json_path.write_text(
        json.dumps(visual_json, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    visual_html_path = outputs_dir / "options_visual_report.html"
    visual_html_path.write_text(visual_html, encoding="utf-8")

    return {
        "step": "option_wall",
        "status": "success",
        "trade_date": report_date,
        "product": product,
        "feature_version": result.feature_version,
        "feature_revision": result.feature_revision,
        "expiries": result.expiries,
        "row_count": len(result.normalized_rows),
        "walls_count": len(result.scored_walls),
        "intent_type": result.intent.primary_intent.intent_type.value,
        "gamma_zero": result.netgex.gamma_zero,
        "gex_semantics": result.gex_semantics,
        "expiry_selection": result.expiry_selection,
        "reconciliation": result.reconciliation,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "visual_json_path": str(visual_json_path),
        "html_path": str(visual_html_path),
        "data_source_status": result.data_source_status,
        "data_quality_categories": {
            "rows_missing_settlement": result.data_quality.rows_missing_settlement,
            "rows_missing_delta": result.data_quality.rows_missing_delta,
            "zero_oi": result.data_quality.zero_oi_count,
            "low_oi": result.data_quality.low_oi_count,
            "proxy_strikes": result.data_quality.proxy_strike_count,
            "prelim_data": result.data_quality.prelim_data_count,
        },
        "input_snapshot_ids": result.input_snapshot_ids,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _selected_cme_lineage(db: DBSession, option_rows: list[CmeOptionRow]) -> dict[str, Any]:
    """Use selected immutable DWD lineage, including PRELIM retries after FINAL."""
    return build_cme_selected_lineage(option_rows)


def _row_to_dict(row: CmeOptionRow) -> dict[str, Any]:
    """Convert a CmeOptionRow ORM object to a dict for ``build_options_snapshot``."""
    return {
        "trade_date": row.trade_date,
        "report_date": row.report_date,
        "version_type": row.version_type,
        "product_code": row.product_code,
        "underlying": row.underlying,
        "expiry": row.expiry,
        "strike": row.strike,
        "option_type": row.option_type,
        "settlement": row.settlement,
        "delta": row.delta,
        "open_interest": row.open_interest,
        "oi_change": row.oi_change,
        "total_volume": row.total_volume,
        "block_volume": row.block_volume,
        "pnt_volume": row.pnt_volume,
        "globex_volume": row.globex_volume,
        "outcry_volume": row.outcry_volume,
        "exercises": row.exercises,
        "pt_change": row.pt_change,
        "raw_file_id": row.raw_file_id,
    }
