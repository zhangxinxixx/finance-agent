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
from database.models.cme import CmeOptionRow
from database.queries.cme import (
    CmeIngestResult,
    get_available_cme_trade_dates,
    get_cme_option_rows,
    get_cme_option_rows_multi_date,
    ingest_cme_parse_result,
)
from apps.features.options.calibration import calibrate_walls

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
    db.commit()
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
        "summary_path": str(summary_path),
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

    # Read option rows from DB and convert to dicts for the analysis pipeline
    option_rows = get_cme_option_rows(db, report_date=report_date, product=product)
    if not option_rows:
        return {
            "step": "option_wall",
            "status": "skipped",
            "reason": f"No option rows found for report_date={report_date}, product={product}",
        }

    raw_rows = [_row_to_dict(row) for row in option_rows]

    # Run the full analysis pipeline
    source_status = _map_parse_status(state.parse_result)
    source_url = state.raw_file.source_url if state.raw_file else None
    input_ids: dict[str, str] = {}
    if state.raw_file:
        input_ids["raw_file_sha256"] = state.raw_file.sha256
    if state.ingest_result and state.ingest_result.raw_file_id:
        input_ids["raw_file_id"] = str(state.ingest_result.raw_file_id)
    if state.ingest_result and state.ingest_result.parse_run_id:
        # Guard against MagicMock truthiness in tests
        pr_id = state.ingest_result.parse_run_id
        if isinstance(pr_id, str):
            input_ids["parse_run_id"] = pr_id

    # P2-11: only use the two nearest-month expiries for analysis
    from apps.features.options.black76 import sort_expiry_codes

    all_expiries = sorted({row.get("expiry") or "" for row in raw_rows if row.get("expiry")})
    near_expiries = sort_expiry_codes(all_expiries)[:2]

    result = build_options_snapshot(
        raw_rows,
        product=product,
        trade_date=report_date,
        expiries=near_expiries,
        data_source_status=source_status,
        data_source_url=source_url,
        input_snapshot_ids=input_ids,
    )

    # ── P4-06: multi-day wall calibration with near-month filter ────
    try:
        available_dates = get_available_cme_trade_dates(db, product=product, limit=6)
        if len(available_dates) >= 2:
            multi_rows = get_cme_option_rows_multi_date(db, trade_dates=available_dates, product=product)
            # Filter to near-month expiries only for cross-date comparison
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
        "expiries": result.expiries,
        "row_count": len(result.normalized_rows),
        "walls_count": len(result.scored_walls),
        "intent_type": result.intent.primary_intent.intent_type.value,
        "gamma_zero": result.netgex.gamma_zero,
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
    }
