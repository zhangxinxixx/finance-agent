from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.analysis.strategy.schemas import StrategyCardOutput
from apps.output.artifacts import _validate_path_component, normalize_run_id
from apps.runtime.immutable_artifact import (
    immutable_json_item,
    immutable_text_item,
    write_immutable_artifact_bundle,
)

# ──────────────────────────────────────────────────────────────────────
# path builder
# ──────────────────────────────────────────────────────────────────────


def _safe_artifact_dir(
    storage_root: Path | str,
    *,
    artifact_type: str,
    asset: str,
    trade_date: str,
    run_id: str,
) -> Path:
    """Build a safe artifact directory under storage/outputs/<artifact_type>/<asset>/<trade_date>/<run_id>.

    Every component is validated against path traversal and the final
    resolved path is checked with is_relative_to the storage root.
    """
    safe_type = _validate_path_component("artifact_type", artifact_type)
    safe_asset = _validate_path_component("asset", asset)
    safe_date = _validate_path_component("trade_date", trade_date)
    safe_run = normalize_run_id(run_id)

    storage_dir = Path(storage_root).resolve()
    artifact_dir = (storage_dir / "outputs" / safe_type / safe_asset / safe_date / safe_run).resolve()

    if not artifact_dir.is_relative_to(storage_dir):
        raise ValueError("artifact path escapes storage root")
    return artifact_dir


# ──────────────────────────────────────────────────────────────────────
# final report writer
# ──────────────────────────────────────────────────────────────────────


def write_final_report(
    *,
    storage_root: Path | str,
    markdown: str,
    asset: str = "XAUUSD",
    trade_date: str,
    run_id: str,
    overwrite: bool = False,
    structured_report: Any | None = None,  # P4-04: StructuredReportOutput dict
    artifact_type: str = "final_report",
) -> dict:
    """Write ``final_report.md`` to the artifact directory.

    P4-04: Also writes ``structured_report.json`` when ``structured_report``
    is provided.

    Returns a summary dict with ``artifact_type``, ``paths`` list, and
    ``skipped`` bool for downstream logging / auditing.

    With the default ``overwrite=False``, an identical bundle is returned as
    skipped while conflicting content raises ``FileExistsError``.
    """
    artifact_dir = _safe_artifact_dir(
        storage_root,
        artifact_type=artifact_type,
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
    )

    target_path = artifact_dir / "final_report.md"

    paths: list[str] = [str(target_path)]
    structured_payload: dict[str, Any] | None = None
    if structured_report is not None:
        if hasattr(structured_report, "model_dump"):
            structured_payload = structured_report.model_dump(mode="json")
        elif isinstance(structured_report, dict):
            structured_payload = dict(structured_report)
        else:
            raise TypeError("structured_report must be a mapping or Pydantic model")

    if overwrite:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_text(markdown, encoding="utf-8")
        if structured_payload is not None:
            json_path = artifact_dir / "structured_report.json"
            json_path.write_text(
                json.dumps(structured_payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            paths.append(str(json_path))
        skipped = False
    else:
        items = [immutable_text_item(target_path, markdown)]
        if structured_payload is not None:
            json_path = artifact_dir / "structured_report.json"
            items.append(immutable_json_item(json_path, structured_payload))
            paths.append(str(json_path))
        write_results = write_immutable_artifact_bundle(items, storage_root=storage_root)
        skipped = not any(item.written for item in write_results)

    return {
        "artifact_type": artifact_type,
        "paths": paths,
        "skipped": skipped,
    }


# ──────────────────────────────────────────────────────────────────────
# strategy card writer
# ──────────────────────────────────────────────────────────────────────

_STRATEGY_CARD_MD_TEMPLATE = """\
# XAUUSD Strategy Card

- version: {version}
- asset: {asset}
- trade_date: {trade_date}
- run_id: {run_id}
- created_at: {created_at}
- is_trade_instruction: {is_trade_instruction}

## Research View

- bias: {bias}
- confidence: {confidence:.2f}

### Scenario Summary

{scenario_summary}

### Key Option Levels (from prior findings only)

{key_levels}

## Risk Points

{risk_points}

## Invalid Conditions

{invalid_conditions}

## Watchlist

{watchlist}

## Data Provenance

- input_snapshot_ids:
{input_snapshot_ids}

- source_refs:
{source_refs}

## Disclaimer

Research output only; not investment advice, not an automatic trading system,
and not an executable market action signal. It contains no order plan,
risk bracket, profit-taking plan, or executable entry plan.
"""


def _render_strategy_card_markdown(card: StrategyCardOutput) -> str:
    """Render a StrategyCardOutput to a deterministic Markdown string."""

    key_levels = "\n".join(f"- {lvl}" for lvl in card.key_levels_from_options) or "- none"

    risk_points = "\n".join(f"- {rp}" for rp in card.risk_points) or "- none"
    invalid_conditions = "\n".join(f"- {ic}" for ic in card.invalid_conditions) or "- none"
    watchlist = "\n".join(f"- {w}" for w in card.watchlist) or "- none"

    input_snapshot_ids = "\n".join(
        f"  - {k}: {v}" for k, v in sorted(card.input_snapshot_ids.items())
    ) or "  - none"

    source_refs = "\n".join(
        f"  - {'; '.join(f'{k}: {v}' for k, v in sorted(ref.items()))}"
        for ref in card.source_refs
    ) or "  - none"

    return _STRATEGY_CARD_MD_TEMPLATE.format(
        version=card.version,
        asset=card.asset,
        trade_date=card.trade_date,
        run_id=card.run_id,
        created_at=card.created_at.isoformat(),
        is_trade_instruction=card.is_trade_instruction,
        bias=card.bias.value,
        confidence=card.confidence,
        scenario_summary=card.scenario_summary,
        key_levels=key_levels,
        risk_points=risk_points,
        invalid_conditions=invalid_conditions,
        watchlist=watchlist,
        input_snapshot_ids=input_snapshot_ids,
        source_refs=source_refs,
    )


def write_strategy_card(
    *,
    storage_root: Path | str,
    card: StrategyCardOutput,
    overwrite: bool = False,
    artifact_type: str = "strategy_card",
) -> dict:
    """Write ``strategy_card.json`` and ``strategy_card.md`` to the artifact directory.

    Returns a summary dict with ``artifact_type``, ``paths`` list, and
    ``skipped`` bool.

    With the default ``overwrite=False``, an identical bundle is returned as
    skipped while conflicting content raises ``FileExistsError`` before either
    file is changed.
    """
    artifact_dir = _safe_artifact_dir(
        storage_root,
        artifact_type=artifact_type,
        asset=card.asset,
        trade_date=card.trade_date,
        run_id=card.run_id,
    )

    json_path = artifact_dir / "strategy_card.json"
    md_path = artifact_dir / "strategy_card.md"

    if overwrite:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(card.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        md_path.write_text(_render_strategy_card_markdown(card), encoding="utf-8")
        skipped = False
    else:
        write_results = write_immutable_artifact_bundle(
            [
                immutable_json_item(json_path, card.model_dump(mode="json")),
                immutable_text_item(md_path, _render_strategy_card_markdown(card)),
            ],
            storage_root=storage_root,
        )
        skipped = not any(item.written for item in write_results)

    return {
        "artifact_type": artifact_type,
        "paths": [str(json_path), str(md_path)],
        "skipped": skipped,
    }
