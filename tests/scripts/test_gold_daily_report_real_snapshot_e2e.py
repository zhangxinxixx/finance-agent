"""Frozen real premarket snapshot E2E for the Gold Policy daily report.

This test freezes one real local premarket artifact and proves the
``run_gold_daily_report`` entry point can complete a v2 report bundle without
monkeypatching ``prepare_gold_policy_runtime_inputs`` and without invoking
Jin10, Reportory, or an LLM.  The fixture is a byte-for-byte copy of the
canonical storage snapshot; see ``_FIXTURE_SOURCE_PATH`` below for the
authoritative source and ``_FIXTURE_SOURCE_SHA256`` for its SHA-256.

Frozen source:
    storage/features/snapshots/XAUUSD/2026-07-07/xauusd-20260707-composite/premarket_snapshot.json
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from apps.analysis.gold_policy.daily_close_store import verify_gold_daily_close_bundle
from scripts import run_gold_daily_report as report


_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "gold_daily_report"
_FIXTURE_NAME = "premarket_snapshot_2026-07-07.json"
_FIXTURE_PATH = _FIXTURE_DIR / _FIXTURE_NAME
_FIXTURE_SOURCE_PATH = "storage/features/snapshots/XAUUSD/2026-07-07/xauusd-20260707-composite/premarket_snapshot.json"
_FIXTURE_SOURCE_SHA256 = "85dd2f24075812d62206ee12d1e5fea37d892e3cb2c9360a3c73d0a3e07a4d97"

_REPORT_FILES = (
    "source.md",
    "analysis.md",
    "visual.html",
    "report_structured.json",
    "evidence.json",
    "data_quality.json",
    "report_manifest.json",
    "strategy_card.json",
    "strategy_card.md",
)

_V2_SECTION_ORDER = (
    "executive_summary",
    "macro_background",
    "price_attribution",
    "state_transition",
    "strategy",
    "key_level_map",
    "scenarios",
    "major_events",
    "fundamental_change",
    "risks",
    "traceability",
)

_TRIGGERED_STRATEGY_STATUSES = {
    "LONG_RESEARCH_TRIGGERED",
    "SHORT_RESEARCH_TRIGGERED",
}


def _assert_fixture_is_frozen() -> None:
    """Verify the in-repo fixture is a byte-for-byte copy of the source."""

    assert _FIXTURE_PATH.is_file(), f"fixture missing: {_FIXTURE_PATH}"
    digest = hashlib.sha256(_FIXTURE_PATH.read_bytes()).hexdigest()
    assert digest == _FIXTURE_SOURCE_SHA256, f"fixture sha256 mismatch: expected {_FIXTURE_SOURCE_SHA256}, got {digest}"


def _materialize_snapshot(tmp_path: Path) -> tuple[Path, str]:
    """Copy the frozen fixture into the formal snapshot layout under tmp_path."""

    fixture_bytes = _FIXTURE_PATH.read_bytes()
    payload = json.loads(fixture_bytes.decode("utf-8"))
    trade_date = payload["trade_date"]
    run_id = payload["run_id"]
    snapshot_dir = tmp_path / "features" / "snapshots" / "XAUUSD" / trade_date / run_id
    snapshot_dir.mkdir(parents=True)
    target = snapshot_dir / "premarket_snapshot.json"
    target.write_bytes(fixture_bytes)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == _FIXTURE_SOURCE_SHA256
    return target, trade_date


def _run_with_jin10_disabled(tmp_path: Path, trade_date: str) -> dict:
    """Invoke ``run_gold_daily_report`` with the Jin10 disable boundary set."""

    previous = os.environ.get("FINANCE_AGENT_DISABLE_JIN10")
    os.environ["FINANCE_AGENT_DISABLE_JIN10"] = "true"
    try:
        return report.run_gold_daily_report(
            trade_date=trade_date,
            storage_root=tmp_path,
        )
    finally:
        if previous is None:
            os.environ.pop("FINANCE_AGENT_DISABLE_JIN10", None)
        else:
            os.environ["FINANCE_AGENT_DISABLE_JIN10"] = previous


def test_frozen_real_premarket_snapshot_completes_v2_bundle_idempotently(
    tmp_path: Path,
) -> None:
    """The real premarket snapshot completes a v2 daily-close bundle idempotently.

    This exercises the formal adapter (``prepare_gold_policy_runtime_inputs``),
    the canonical-predecessor resolver, the runtime controls builder, the
    deterministic loop, the typed renderer, the report bundle writer, and the
    full bundle verifier.  No function is monkeypatched.
    """

    _assert_fixture_is_frozen()
    snapshot_path, trade_date = _materialize_snapshot(tmp_path)

    first = _run_with_jin10_disabled(tmp_path, trade_date)

    assert first["status"] == "completed", first
    assert first["jin10"] == "not_used"
    assert first["trade_date"] == trade_date
    assert first["snapshot_path"] == str(snapshot_path)
    assert first["report_status"] in {"observe", "degraded"}, first

    report_paths = [Path(path) for path in first["report_paths"]]
    assert len(report_paths) == 9
    assert {path.name for path in report_paths} == set(_REPORT_FILES)
    assert all(path.is_file() for path in report_paths)
    assert all(path.parent == report_paths[0].parent for path in report_paths)

    bundle_path = report_paths[0].parent
    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=bundle_path,
    )
    assert verification.status == "valid", verification
    assert verification.receipt is not None
    assert verification.receipt.action.value in {"bootstrap", "advance", "maintain", "hold"}

    structured = json.loads((bundle_path / "report_structured.json").read_text(encoding="utf-8"))
    assert structured["schema_version"] == "gold_policy_report_structured.v2"
    assert structured["language_generation"] == "not_invoked"
    assert tuple(section["section_id"] for section in structured["sections"]) == _V2_SECTION_ORDER
    assert len(structured["sections"]) == 11

    visual_html = (bundle_path / "visual.html").read_text(encoding="utf-8")
    assert visual_html.lstrip().startswith("<!doctype html>")
    assert "<pre>" not in visual_html
    assert "<section " in visual_html
    assert "data-section-id=" in visual_html
    assert "data-fact-id=" in visual_html

    strategy = json.loads((bundle_path / "strategy_card.json").read_text(encoding="utf-8"))
    assert strategy["status"] not in _TRIGGERED_STRATEGY_STATUSES
    assert strategy["language_generation"] == "not_invoked"

    data_quality = json.loads((bundle_path / "data_quality.json").read_text(encoding="utf-8"))
    assert "TRIGGERED_STRATEGY" in data_quality["prohibited_outputs"]
    assert data_quality["language_generation"] == "not_invoked"

    second = _run_with_jin10_disabled(tmp_path, trade_date)
    assert second == first, "second run must be idempotent and reuse the existing completed bundle"

    runs_root = tmp_path / "analysis" / "gold_mainlines" / trade_date
    if runs_root.is_dir():
        run_dirs = [path for path in runs_root.iterdir() if path.is_dir() and (path / "daily_close").is_dir()]
        assert len(run_dirs) == 1, f"idempotent rerun must not create a second run directory: {run_dirs}"
