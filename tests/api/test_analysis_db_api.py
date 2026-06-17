"""TDD: API DB-backed reads — verify DB-first path and filesystem fallback.

All tests use in-memory SQLite; no dependency on local PostgreSQL.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.main import app
from database.models.analysis import ensure_analysis_tables

# ── Test fixtures ──

_PROJECT_ROOT_PATCH = "apps.api.data_service._PROJECT_ROOT"
_SESSION_REF = "apps.api.data_service._try_db_session"


def _make_inmem_session():
    """Create an in-memory SQLite session with analysis tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session()


def _upsert_final(session, **overrides):
    """Upsert a FinalAnalysisResult with minimal defaults + overrides."""
    from database.queries.analysis import upsert_final_analysis_result

    payload = {
        "asset": "XAUUSD",
        "trade_date": "2026-05-14",
        "run_id": "run-001",
        "snapshot_id": "snap-001",
        "analysis_snapshot_db_id": None,
        "final_bias": "bullish",
        "confidence": 0.7200,
        "market_state": "risk-on",
        "scenario_summary": "Gold bullish",
        "is_trade_instruction": False,
        "input_snapshot_ids": {},
        "source_refs": [],
        "source_agent_outputs": [],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": [],
        "strategy_card": {"bias": "bullish", "confidence": 0.8, "asset": "XAUUSD"},
        "run_summaries": {},
        "payload": {"final": "report"},
    }
    payload.update(overrides)
    # Keep strategy_card under overrides control
    if "strategy_card" in overrides:
        payload["strategy_card"] = overrides.pop("strategy_card")

    paths = {
        "final_report_path": f"storage/outputs/final_report/XAUUSD/{payload['trade_date']}/{payload['run_id']}/final_report.md",
        "strategy_card_json_path": f"storage/outputs/strategy_card/XAUUSD/{payload['trade_date']}/{payload['run_id']}/strategy_card.json",
        "strategy_card_md_path": f"storage/outputs/strategy_card/XAUUSD/{payload['trade_date']}/{payload['run_id']}/strategy_card.md",
        "run_summary_path": f"storage/outputs/run/{payload['trade_date']}/{payload['run_id']}/step_summaries.json",
        "final_report_sha256": "abc123",
        "strategy_card_sha256": "def456",
    }
    return upsert_final_analysis_result(session, payload=payload, paths=paths)


def _upsert_analysis_snapshot(session, **overrides):
    """Upsert an AnalysisSnapshot with minimal defaults + overrides."""
    from database.queries.analysis import upsert_analysis_snapshot

    payload = {
        "snapshot_id": "snap-001",
        "asset": "XAUUSD",
        "trade_date": "2026-05-14",
        "run_id": "run-001",
        "snapshot_time": "2026-05-14T10:00:00Z",
        "status": "success",
        "input_snapshot_ids": {"macro": "macro-001"},
        "source_refs": [],
        "macro": {
            "status": "available",
            "data": {
                "indicators": {
                    "REAL_10Y": {"value": 1.2, "daily_change": -0.20, "weekly_change": -0.40},
                    "DXY": {"value": 100.0, "daily_change": -0.8, "weekly_change": -2.0},
                    "DGS2": {"value": 3.8, "daily_change": -0.15},
                    "DGS10": {"value": 3.5, "daily_change": -0.12},
                    "T10YIE": {"value": 2.3, "daily_change": -0.05},
                    "ON_RRP_USAGE": {"value": 200.0, "daily_change": -50.0},
                    "TGA": {"value": 400.0, "daily_change": -30.0},
                    "SOFR": {"value": 4.3, "daily_change": -0.02},
                    "EFFR": {"value": 4.35, "daily_change": -0.02},
                    "IORB": {"value": 4.4, "daily_change": 0.0},
                }
            },
        },
        "options": None,
        "positioning": None,
        "news": None,
        "technical": None,
        "payload": {"full": "snapshot_data"},
    }
    payload.update(overrides)
    artifact_path = f"storage/features/snapshots/XAUUSD/{payload['trade_date']}/{payload['run_id']}/premarket_snapshot.json"
    return upsert_analysis_snapshot(session, payload=payload, artifact_path=artifact_path)


def _make_tree(root: Path, files: dict[str, str | None]) -> None:
    """按 {relative_path: content} 创建目录和文件；content=None 则只建目录。"""
    for rel, content in files.items():
        p = root / rel
        if content is None:
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════
# get_final_report_latest — DB-first
# ═══════════════════════════════════════════════════════════════════


def test_get_final_report_latest_from_db(tmp_path: Path):
    """DB has the final result with a valid file path → returns from DB."""
    from apps.api.data_service import get_final_report_latest

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    md_content = "# Final Report\nDB-backed content"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": md_content,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report_latest()

    assert data is not None
    assert data["asset"] == "XAUUSD"
    assert data["trade_date"] == "2026-05-14"
    assert data["run_id"] == "run-001"
    assert data["content"] == md_content
    assert data["format"] == "markdown"


def test_get_final_report_latest_db_no_record_falls_back_to_fs(tmp_path: Path):
    """DB available but no matching record → filesystem fallback succeeds."""
    from apps.api.data_service import get_final_report_latest

    session = _make_inmem_session()  # empty DB

    md = "# From filesystem"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": md,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report_latest()

    assert data is not None
    assert data["content"] == md


def test_get_final_report_latest_db_unavailable_falls_back_to_fs(tmp_path: Path):
    """DB unavailable → filesystem fallback succeeds."""
    from apps.api.data_service import get_final_report_latest

    md = "# Filesystem only"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": md,
    })

    def _fake_try_db():
        return None  # DB unavailable

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report_latest()

    assert data is not None
    assert data["content"] == md


def test_get_final_report_latest_db_file_missing_falls_back_to_fs(tmp_path: Path):
    """DB has record but the file at final_report_path doesn't exist → filesystem fallback."""
    from apps.api.data_service import get_final_report_latest

    session = _make_inmem_session()
    _upsert_final(session)  # references a file that doesn't exist
    session.commit()

    md = "# From filesystem"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": md,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report_latest()

    assert data is not None
    assert data["content"] == md  # fell back to filesystem


# ═══════════════════════════════════════════════════════════════════
# get_final_report (exact) — DB-first
# ═══════════════════════════════════════════════════════════════════


def test_get_final_report_exact_from_db(tmp_path: Path):
    """DB has the exact record → returns from DB."""
    from apps.api.data_service import get_final_report

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    md = "# Exact via DB"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": md,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report(date="2026-05-14", run_id="run-001")

    assert data is not None
    assert data["content"] == md


def test_get_final_report_exact_db_no_record_falls_back(tmp_path: Path):
    """DB no matching record → filesystem fallback succeeds."""
    from apps.api.data_service import get_final_report

    session = _make_inmem_session()
    md = "# Exact filesystem"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": md,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report(date="2026-05-14", run_id="run-001")

    assert data is not None
    assert data["content"] == md


def test_get_final_report_exact_db_unavailable_falls_back(tmp_path: Path):
    """DB unavailable → filesystem finds the file."""
    from apps.api.data_service import get_final_report

    md = "# DB down, FS ok"
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": md,
    })

    def _fake_try_db():
        return None

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report(date="2026-05-14", run_id="run-001")

    assert data is not None
    assert data["content"] == md


# ═══════════════════════════════════════════════════════════════════
# get_strategy_card_latest — DB-first
# ═══════════════════════════════════════════════════════════════════


def test_get_strategy_card_latest_from_db_json_only(tmp_path: Path):
    """DB has strategy_card JSON but no md file → returns JSON from DB, no markdown."""
    from apps.api.data_service import get_strategy_card_latest

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    # No strategy_card.md file created on disk
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/": None,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card_latest()

    assert data is not None
    assert data["asset"] == "XAUUSD"
    assert data["trade_date"] == "2026-05-14"
    assert data["run_id"] == "run-001"
    assert data["json"]["bias"] == "bullish"
    assert data["json"]["confidence"] == 0.8
    assert "markdown" not in data


def test_get_strategy_card_latest_backfills_market_regime_from_analysis_snapshot(tmp_path: Path):
    """DB strategy_card JSON without market_regime should be enriched from analysis snapshot."""
    from apps.api.data_service import get_strategy_card_latest

    session = _make_inmem_session()
    snap = _upsert_analysis_snapshot(session)
    _upsert_final(
        session,
        analysis_snapshot_db_id=snap.id,
        strategy_card={"bias": "bullish", "confidence": 0.8, "asset": "XAUUSD"},
    )
    session.commit()

    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/": None,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card_latest()

    assert data is not None
    assert data["market_regime"] == "trend_tailwind"
    assert data["json"]["market_regime"] == "trend_tailwind"


def test_get_strategy_card_latest_from_db_with_md(tmp_path: Path):
    """DB has strategy_card and the md file exists → returns both JSON and markdown."""
    from apps.api.data_service import get_strategy_card_latest

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    sc_md = "# Strategy Card\nFrom DB with MD"
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.md": sc_md,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card_latest()

    assert data is not None
    assert data["json"]["bias"] == "bullish"
    assert data["markdown"] == sc_md
    assert "json" in data["paths"]


def test_get_strategy_card_latest_db_no_record_falls_back_to_fs(tmp_path: Path):
    """DB no matching record → filesystem fallback succeeds."""
    from apps.api.data_service import get_strategy_card_latest

    session = _make_inmem_session()
    sc_json = json.dumps({"bias": "bearish", "confidence": 0.6})

    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card_latest()

    assert data is not None
    assert data["json"]["bias"] == "bearish"


def test_get_strategy_card_latest_db_unavailable_falls_back_to_fs(tmp_path: Path):
    """DB unavailable → filesystem fallback succeeds."""
    from apps.api.data_service import get_strategy_card_latest

    sc_json = json.dumps({"bias": "neutral", "confidence": 0.5})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return None

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card_latest()

    assert data is not None
    assert data["json"]["bias"] == "neutral"


def test_get_strategy_card_latest_prefers_newer_filesystem_artifact_over_older_db(tmp_path: Path):
    """DB 较旧时，latest 应优先返回文件系统里的更新产物。"""
    from apps.api.data_service import get_strategy_card_latest

    session = _make_inmem_session()
    _upsert_final(session, trade_date="2026-06-08", run_id="db-run")
    session.commit()

    sc_json = json.dumps({"bias": "neutral", "confidence": 0.55, "asset": "XAUUSD"})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-06-10/fs-run/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card_latest()

    assert data is not None
    assert data["trade_date"] == "2026-06-10"
    assert data["run_id"] == "fs-run"
    assert data["json"]["confidence"] == 0.55


# ═══════════════════════════════════════════════════════════════════
# get_strategy_card (exact) — DB-first
# ═══════════════════════════════════════════════════════════════════


def test_get_strategy_card_exact_from_db(tmp_path: Path):
    """DB has the exact strategy card → returns from DB."""
    from apps.api.data_service import get_strategy_card

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    sc_md = "# Exact SC from DB"
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.md": sc_md,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card(date="2026-05-14", run_id="run-001")

    assert data is not None
    assert data["json"]["bias"] == "bullish"
    assert data["markdown"] == sc_md


def test_get_strategy_card_exact_db_no_record_falls_back(tmp_path: Path):
    """DB no matching record → filesystem fallback succeeds."""
    from apps.api.data_service import get_strategy_card

    session = _make_inmem_session()
    sc_json = json.dumps({"bias": "mixed", "confidence": 0.4})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card(date="2026-05-14", run_id="run-001")

    assert data is not None
    assert data["json"]["bias"] == "mixed"


def test_get_strategy_card_exact_db_unavailable_falls_back(tmp_path: Path):
    """DB unavailable → filesystem finds the file."""
    from apps.api.data_service import get_strategy_card

    sc_json = json.dumps({"bias": "bearish", "confidence": 0.7})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return None

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card(date="2026-05-14", run_id="run-001")

    assert data is not None
    assert data["json"]["bias"] == "bearish"


# ═══════════════════════════════════════════════════════════════════
# list_reports_index — DB-augmented
# ═══════════════════════════════════════════════════════════════════


def test_list_reports_index_db_has_final_and_strategy(tmp_path: Path):
    """DB has records → reports index includes DB entries for final_report + strategy_card."""
    from apps.api.data_service import list_reports_index

    session = _make_inmem_session()
    _upsert_final(session)
    _upsert_final(session, trade_date="2026-05-13", run_id="run-older",
                   strategy_card={"bias": "neutral", "confidence": 0.5})
    session.commit()

    # Create actual files for the DB entries
    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": "fr",
        "storage/outputs/final_report/XAUUSD/2026-05-13/run-older/final_report.md": "fr2",
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.json": "{}",
        "storage/outputs/strategy_card/XAUUSD/2026-05-13/run-older/strategy_card.json": "{}",
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        index = list_reports_index()

    assert index["asset"] == "XAUUSD"
    reports = index["reports"]

    final_reports = [r for r in reports if r["type"] == "final_report"]
    strategy_reports = [r for r in reports if r["type"] == "strategy_card"]

    # Both should come from DB
    assert len(final_reports) >= 2
    assert len(strategy_reports) >= 2

    fr_dates = {r["trade_date"] for r in final_reports}
    assert "2026-05-14" in fr_dates
    assert "2026-05-13" in fr_dates

    # Latest first
    assert final_reports[0]["trade_date"] == "2026-05-14"
    assert final_reports[0]["available"] is True


def test_list_reports_index_db_unavailable_falls_back_to_fs(tmp_path: Path):
    """DB unavailable → filesystem scan works for all report types."""
    from apps.api.data_service import list_reports_index

    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": "fr",
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.json": "{}",
    })

    def _fake_try_db():
        return None

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        index = list_reports_index()

    assert index["asset"] == "XAUUSD"
    reports = index["reports"]
    types = {r["type"] for r in reports}
    assert "final_report" in types
    assert "strategy_card" in types


def test_list_reports_index_db_empty_falls_back_to_fs(tmp_path: Path):
    """DB available but empty → filesystem scan succeeds."""
    from apps.api.data_service import list_reports_index

    session = _make_inmem_session()  # empty

    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": "fr",
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        index = list_reports_index()

    assert len([r for r in index["reports"] if r["type"] == "final_report"]) >= 1


# ═══════════════════════════════════════════════════════════════════
# Shape compatibility — return dicts match existing contract
# ═══════════════════════════════════════════════════════════════════


def test_final_report_latest_shape_from_db_matches_contract(tmp_path: Path):
    """DB-backed return dict has all keys present in filesystem return dict."""
    from apps.api.data_service import get_final_report_latest

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    _make_tree(tmp_path, {
        "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md": "test",
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_final_report_latest()

    assert data is not None
    for key in ("asset", "trade_date", "run_id", "content", "format", "path"):
        assert key in data, f"Missing key {key}"
    assert isinstance(data["content"], str)
    assert data["format"] == "markdown"


def test_strategy_card_latest_shape_from_db_matches_contract(tmp_path: Path):
    """DB-backed strategy card return dict has all required keys."""
    from apps.api.data_service import get_strategy_card_latest

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/": None,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        data = get_strategy_card_latest()

    assert data is not None
    for key in ("asset", "trade_date", "run_id", "json", "paths"):
        assert key in data, f"Missing key {key}"
    assert isinstance(data["json"], dict)
    assert isinstance(data["paths"], dict)


# ═══════════════════════════════════════════════════════════════════
# list_strategy_cards — DB-first
# ═══════════════════════════════════════════════════════════════════


def test_list_strategy_cards_two_cards_sorted_by_date(tmp_path: Path):
    """DB has two strategy cards → list returns them sorted by latest trade_date first."""
    from apps.api.data_service import list_strategy_cards

    session = _make_inmem_session()
    _upsert_final(session, trade_date="2026-05-14", run_id="run-new",
                   strategy_card={"bias": "bullish", "confidence": 0.9})
    _upsert_final(session, trade_date="2026-05-10", run_id="run-old",
                   strategy_card={"bias": "bearish", "confidence": 0.4})
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = list_strategy_cards()

    assert result["asset"] == "XAUUSD"
    assert result["count"] == 2
    items = result["items"]
    assert len(items) == 2
    assert items[0]["trade_date"] == "2026-05-14"
    assert items[0]["bias"] == "bullish"
    assert items[1]["trade_date"] == "2026-05-10"
    assert items[1]["bias"] == "bearish"
    # Summary items should NOT contain json or markdown
    for item in items:
        assert "json" not in item
        assert "markdown" not in item


def test_list_strategy_cards_limit(tmp_path: Path):
    """list_strategy_cards respects limit parameter."""
    from apps.api.data_service import list_strategy_cards

    session = _make_inmem_session()
    _upsert_final(session, trade_date="2026-05-14", run_id="run-1",
                   strategy_card={"bias": "bullish"})
    _upsert_final(session, trade_date="2026-05-13", run_id="run-2",
                   strategy_card={"bias": "bearish"})
    _upsert_final(session, trade_date="2026-05-12", run_id="run-3",
                   strategy_card={"bias": "neutral"})
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = list_strategy_cards(limit=2)

    assert result["count"] == 2
    assert len(result["items"]) == 2
    assert result["items"][0]["trade_date"] == "2026-05-14"


def test_list_strategy_cards_db_empty_falls_back_to_fs(tmp_path: Path):
    """DB available but empty → filesystem fallback."""
    from apps.api.data_service import list_strategy_cards

    session = _make_inmem_session()
    sc_json = json.dumps({"bias": "bullish", "confidence": 0.7})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = list_strategy_cards()

    assert result["count"] == 1
    assert result["items"][0]["bias"] == "bullish"


def test_list_strategy_cards_db_unavailable_falls_back_to_fs(tmp_path: Path):
    """DB unavailable → filesystem fallback."""
    from apps.api.data_service import list_strategy_cards

    sc_json = json.dumps({"bias": "neutral", "confidence": 0.5})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return None

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = list_strategy_cards()

    assert result["count"] == 1


def test_list_strategy_assets_groups_by_asset(tmp_path: Path):
    """Strategy asset summary should expose discovered assets with sample counts."""
    from apps.api.data_service import list_strategy_assets

    session = _make_inmem_session()
    _upsert_final(
        session,
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="run-xau-1",
        snapshot_id="snap-xau-1",
        strategy_card={"bias": "bullish", "confidence": 0.8, "asset": "XAUUSD", "market_regime": "range"},
    )
    _upsert_final(
        session,
        asset="BTCUSD",
        trade_date="2026-05-15",
        run_id="run-btc-1",
        snapshot_id="snap-btc-1",
        strategy_card={"bias": "bearish", "confidence": 0.6, "asset": "BTCUSD", "market_regime": "trend"},
    )
    _upsert_final(
        session,
        asset="BTCUSD",
        trade_date="2026-05-14",
        run_id="run-btc-2",
        snapshot_id="snap-btc-2",
        strategy_card={"bias": "neutral", "confidence": 0.5, "asset": "BTCUSD", "market_regime": "range"},
    )
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = list_strategy_assets()

    assert result["count"] == 2
    by_asset = {item["asset"]: item for item in result["items"]}
    assert by_asset["XAUUSD"]["sample_size"] == 1
    assert by_asset["XAUUSD"]["latest_trade_date"] == "2026-05-14"
    assert by_asset["XAUUSD"]["latest_run_id"] == "run-xau-1"
    assert by_asset["XAUUSD"]["regime_counts"] == [{"market_regime": "range", "sample_size": 1}]
    assert by_asset["BTCUSD"]["sample_size"] == 2
    assert by_asset["BTCUSD"]["latest_trade_date"] == "2026-05-15"
    assert by_asset["BTCUSD"]["latest_run_id"] == "run-btc-1"
    assert by_asset["BTCUSD"]["regime_counts"] == [
        {"market_regime": "range", "sample_size": 1},
        {"market_regime": "trend", "sample_size": 1},
    ]


def test_list_strategy_assets_falls_back_to_analysis_snapshot_regime(tmp_path: Path):
    """When strategy_card omits market_regime, analysis snapshot should backfill the asset summary."""
    from apps.api.data_service import list_strategy_assets

    session = _make_inmem_session()
    snap = _upsert_analysis_snapshot(session)
    _upsert_final(
        session,
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="run-xau-1",
        snapshot_id="snap-xau-1",
        analysis_snapshot_db_id=snap.id,
        strategy_card={"bias": "bullish", "confidence": 0.8, "asset": "XAUUSD"},
    )
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = list_strategy_assets()

    assert result["count"] == 1
    item = result["items"][0]
    assert item["asset"] == "XAUUSD"
    assert item["regime_counts"] == [{"market_regime": "trend_tailwind", "sample_size": 1}]


def test_strategy_asset_route_returns_summary(tmp_path: Path):
    """/api/strategy-cards/assets should expose the asset summary read model."""
    client = TestClient(app)
    with (
        mock.patch(
            "apps.api.main.list_strategy_assets",
            return_value={
                "count": 1,
                "items": [
                    {
                        "asset": "XAUUSD",
                        "sample_size": 1,
                        "latest_trade_date": "2026-05-14",
                        "latest_run_id": "run-xau-1",
                        "latest_snapshot_id": "snap-xau-1",
                    }
                ],
            },
        ),
    ):
        response = client.get("/api/strategy-cards/assets")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["asset"] == "XAUUSD"
    assert data["items"][0]["sample_size"] == 1


# ═══════════════════════════════════════════════════════════════════
# get_strategy_card_by_id — DB-first
# ═══════════════════════════════════════════════════════════════════


def test_get_strategy_card_by_id_uses_strategy_card_id(tmp_path: Path):
    """strategy_card_id from strategy_card JSON is used as primary ID."""
    from apps.api.data_service import get_strategy_card_by_id

    session = _make_inmem_session()
    _upsert_final(session, strategy_card={
        "strategy_card_id": "sc-abc-123", "bias": "bullish", "confidence": 0.9,
    })
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        detail = get_strategy_card_by_id("sc-abc-123")

    assert detail is not None
    assert detail["strategy_card_id"] == "sc-abc-123"
    assert detail["bias"] == "bullish"
    assert "json" in detail


def test_get_strategy_card_by_id_fallback_to_run_id(tmp_path: Path):
    """When strategy_card has no strategy_card_id, run_id is used."""
    from apps.api.data_service import get_strategy_card_by_id

    session = _make_inmem_session()
    _upsert_final(session, run_id="run-xyz",
                   strategy_card={"bias": "bearish", "confidence": 0.6})
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        detail = get_strategy_card_by_id("run-xyz")

    assert detail is not None
    assert detail["strategy_card_id"] == "run-xyz"
    assert detail["run_id"] == "run-xyz"
    assert detail["bias"] == "bearish"


def test_get_strategy_card_by_id_fallback_to_snapshot_id(tmp_path: Path):
    """Can also find by snapshot_id."""
    from apps.api.data_service import get_strategy_card_by_id

    session = _make_inmem_session()
    _upsert_final(session, run_id="run-aaa", snapshot_id="snap-bbb",
                   strategy_card={"bias": "neutral", "confidence": 0.5})
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        detail = get_strategy_card_by_id("snap-bbb")

    assert detail is not None
    assert detail["snapshot_id"] == "snap-bbb"


def test_get_strategy_card_by_id_not_found(tmp_path: Path):
    """Returns None when no matching card exists."""
    from apps.api.data_service import get_strategy_card_by_id

    session = _make_inmem_session()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        detail = get_strategy_card_by_id("nonexistent")

    assert detail is None


def test_get_strategy_card_by_id_falls_back_to_fs(tmp_path: Path):
    """DB unavailable → filesystem fallback finds card by run_id."""
    from apps.api.data_service import get_strategy_card_by_id

    sc_json = json.dumps({"bias": "bullish", "confidence": 0.85})
    _make_tree(tmp_path, {
        "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-1/strategy_card.json": sc_json,
    })

    def _fake_try_db():
        return None

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        detail = get_strategy_card_by_id("run-1")

    assert detail is not None
    assert detail["strategy_card_id"] == "run-1"
    assert detail["bias"] == "bullish"
    assert "json" in detail


# ═══════════════════════════════════════════════════════════════════
# get_strategy_card_read_model_latest — compatibility
# ═══════════════════════════════════════════════════════════════════


def test_read_model_latest_does_not_break_singular_latest(tmp_path: Path):
    """get_strategy_card_read_model_latest works independently of get_strategy_card_latest."""
    from apps.api.data_service import get_strategy_card_latest, get_strategy_card_read_model_latest

    session = _make_inmem_session()
    _upsert_final(session, trade_date="2026-05-14", run_id="run-1",
                   strategy_card={"strategy_card_id": "sc-1", "bias": "bullish", "confidence": 0.9})
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        singular = get_strategy_card_latest()
        read_model = get_strategy_card_read_model_latest()

    # Singular latest still works
    assert singular is not None
    assert singular["trade_date"] == "2026-05-14"

    # Read model latest also works
    assert read_model is not None
    assert read_model["strategy_card_id"] == "sc-1"
    assert read_model["bias"] == "bullish"
    assert "json" in read_model


def test_read_model_latest_returns_none_when_no_cards(tmp_path: Path):
    """Returns None when no strategy cards exist."""
    from apps.api.data_service import get_strategy_card_read_model_latest

    session = _make_inmem_session()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = get_strategy_card_read_model_latest()

    assert result is None


def test_read_model_latest_includes_selected_strategy_card_id(tmp_path: Path):
    """Plural latest endpoint data shape must include a stable selected card id for frontend state."""
    from apps.api.data_service import get_strategy_card_read_model_latest

    session = _make_inmem_session()
    _upsert_final(
        session,
        trade_date="2026-05-14",
        run_id="run-selected",
        snapshot_id="snap-selected",
        strategy_card={"strategy_card_id": "sc-selected", "bias": "bullish", "confidence": 0.81},
    )
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        result = get_strategy_card_read_model_latest()

    assert result is not None
    assert result["strategy_card_id"] == "sc-selected"
    assert result["run_id"] == "run-selected"
    assert result["snapshot_id"] == "snap-selected"
    assert result["bias"] == "bullish"


def test_list_reports_index_shape_from_db_matches_contract(tmp_path: Path):
    """DB-backed reports index has correct structure."""
    from apps.api.data_service import list_reports_index

    session = _make_inmem_session()
    _upsert_final(session)
    session.commit()

    def _fake_try_db():
        return session

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(_SESSION_REF, _fake_try_db),
    ):
        index = list_reports_index()

    assert "asset" in index
    assert "reports" in index
    assert isinstance(index["reports"], list)
    for r in index["reports"]:
        for key in ("type", "trade_date", "run_id", "format", "available"):
            assert key in r, f"Missing key {key} in report entry"
