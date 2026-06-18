"""TDD: Data Source Status API endpoints and data_service.

Tests cover:
- data_service get_data_source_statuses() with DB-first and filesystem fallback
- /api/data-sources/status route contract shape and JSON-serializable payload
- P1 dual-source/fallback metadata contract for Data Ingestion
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.encoders import jsonable_encoder
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.main import api_data_sources_status
from apps.api.services.source_service import get_data_status_summary
from database.models.analysis import DataSourceStatus, ensure_analysis_tables
from tests.fixtures.news.replay import materialize_news_replay

_P0_NEWS_SOURCE_ROLES = {
    "jin10_feishu": "supplemental",
    "fed_rss": "official_primary",
    "bls_calendar": "official_primary",
    "bea_calendar": "official_primary",
    "eia_energy": "official_primary",
    "gdelt_news": "aggregator",
    "google_news_rss": "aggregator",
    "reuters_public_news": "wire_public_candidate",
}

_JIN10_MULTI_ENTRY_EXPECTATIONS = {
    "jin10_mcp_flash": ("news", "mcp", "mcp"),
    "jin10_mcp_calendar": ("news", "calendar", "mcp"),
    "jin10_mcp_market": ("technical", "mcp", "mcp"),
    "jin10_xnews_public": ("news", "scraper", "http_document"),
    "jin10_datacenter_reports": ("macro", "structured", "js_data_script"),
    "jin10_svip_reports": ("reports", "scraper", "vip_browser_profile"),
}


# ── Helpers ──


def _relative_to(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def _latest_materialized_file(base: Path) -> Path:
    files = sorted(base.glob("*/*.json"))
    assert files, f"No fixture files materialized under {base}"
    return files[-1]


def _materialize_manual_news_fixture(tmp_path: Path, *, include_collectors: bool, include_outputs: bool) -> dict:
    return materialize_news_replay(
        tmp_path,
        scenario="manual_news_p011_live",
        include_features=True,
        include_collectors=include_collectors,
        include_outputs=include_outputs,
    )


def _write_collection_diagnostics(path: Path) -> None:
    cooldown_path = path.parents[4] / "parsed" / "news" / "gdelt" / "2026-06-11" / "cooldown-fed_inflation.json"
    _write_json(
        cooldown_path,
        {
            "source_key": "gdelt_news",
            "query_group": "fed_inflation",
            "reason_code": "rate_limited",
            "reason": "HTTP 429 from https://api.gdeltproject.org/api/v2/doc/doc",
            "written_at": "2026-06-11T12:00:00+00:00",
            "cooldown_seconds": 900,
            "cooldown_until": "2026-06-11T12:15:00+00:00",
        },
    )
    _write_json(
        path,
        {
            "retrieved_date": "2026-06-11",
            "run_id": "run-news",
            "collector_statuses": [
                {
                    "collector": "fed_rss",
                    "status": "success",
                    "items": 1,
                    "unavailable_feeds": 0,
                    "warnings": [],
                },
                {
                    "collector": "gdelt_news",
                    "status": "unavailable",
                    "items": 0,
                    "unavailable_feeds": 1,
                    "warnings": ["gdelt_news:fed_inflation cooldown_active: GDELT query group is in local cooldown until 2026-06-11T12:15:00+00:00"],
                },
            ],
            "source_ref_count": 2,
            "latest_collector_status_by_collector": {
                "fed_rss": {
                    "collector": "fed_rss",
                    "status": "success",
                    "items": 1,
                    "unavailable_feeds": 0,
                    "warnings": [],
                },
                "gdelt_news": {
                    "collector": "gdelt_news",
                    "status": "unavailable",
                    "items": 0,
                    "unavailable_feeds": 1,
                    "warnings": ["gdelt_news:fed_inflation cooldown_active: GDELT query group is in local cooldown until 2026-06-11T12:15:00+00:00"],
                },
            },
            "latest_source_status_by_source_key": {
                "fed_rss": {
                    "source_ref_count": 1,
                    "status": "available",
                    "source_ref_statuses": ["available"],
                    "reason_codes": [],
                    "warnings": [],
                },
                "gdelt_news": {
                    "source_ref_count": 1,
                    "status": "rate_limited",
                    "source_ref_statuses": ["rate_limited"],
                    "reason_codes": ["cooldown_active"],
                    "warnings": ["gdelt_news:fed_inflation cooldown_active: GDELT query group is in local cooldown until 2026-06-11T12:15:00+00:00"],
                    "source_refs": [
                        {
                            "source_ref": "gdelt_news:fed_inflation",
                            "source": "gdelt_news",
                            "query_group": "fed_inflation",
                            "status": "rate_limited",
                            "reason_code": "cooldown_active",
                            "warning": "gdelt_news:fed_inflation cooldown_active: GDELT query group is in local cooldown until 2026-06-11T12:15:00+00:00",
                            "parsed_path": "parsed/news/gdelt/2026-06-11/cooldown-fed_inflation.json",
                        }
                    ],
                },
            },
            "summary": {
                "collector_count": 2,
                "warning_count": 1,
                "warnings": ["gdelt_news:fed_inflation cooldown_active: GDELT query group is in local cooldown until 2026-06-11T12:15:00+00:00"],
                "source_key_count": 2,
            },
        },
    )


@pytest.fixture(autouse=True)
def _isolated_data_source_project_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr("apps.api.data_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.source_service._PROJECT_ROOT", tmp_path)
    return tmp_path


def _db_session() -> Session:
    """Create in-memory SQLite session with analysis tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_source(session: Session, **overrides) -> DataSourceStatus:
    """Create and return a single DataSourceStatus record."""
    defaults = {
        "source_key": "fred",
        "source_name": "FRED",
        "source_group": "macro",
        "source_type": "api",
        "access_method": "fred_api",
        "configured": True,
        "raw_ingested": True,
        "parsed": True,
        "analysis_ready": True,
        "latest_raw_time": datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc),
        "latest_parsed_time": datetime(2026, 5, 16, 10, 5, tzinfo=timezone.utc),
        "latest_snapshot_id": "snap-001",
        "row_count": 42,
        "status": "ok",
        "error_message": None,
        "last_run_id": "run-001",
        "next_run_time": None,
        "source_metadata": {},
    }
    defaults.update(overrides)
    status = DataSourceStatus(**defaults)
    session.add(status)
    session.commit()
    return status


def _sources_by_key(payload: dict) -> dict[str, dict]:
    return {src["source_key"]: src for src in payload["sources"]}


def _api_status_payload() -> dict:
    with patch("apps.api.data_service._try_db_session", return_value=None):
        return jsonable_encoder(api_data_sources_status())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── data_service tests ──


def test_data_service_returns_statuses_from_db() -> None:
    """When DB is available and has records, row data is preserved."""
    from apps.api.data_service import get_data_source_statuses

    session = _db_session()
    _seed_source(session)

    with patch("apps.api.data_service._try_db_session", return_value=session):
        result = get_data_source_statuses()

    assert "sources" in result
    sources = _sources_by_key(result)
    assert "fred" in sources
    src = sources["fred"]
    assert src["source_name"] == "FRED"
    assert src["configured"] is True
    assert src["raw_ingested"] is True
    assert src["parsed"] is True
    assert src["analysis_ready"] is True
    assert src["status"] == "ok"
    assert "latest_raw_time" in src
    assert "latest_parsed_time" in src
    assert src["latest_update_time"] == "2026-05-16T10:05:00"
    assert src["metadata"]["database_tables"] == ["data_source_status", "analysis_snapshots.macro"]
    assert src["metadata"]["polling_strategy"]["mode"] == "scheduled_batch"
    assert src["metadata"]["pressure_profile"]["level"] == "low"


def test_data_service_returns_multiple_sources() -> None:
    """Multiple DB source records are all returned without dropping them."""
    from apps.api.data_service import get_data_source_statuses

    session = _db_session()
    for key in ["fred", "fed", "treasury", "dxy"]:
        _seed_source(session, source_key=key, source_name=key.upper())

    with patch("apps.api.data_service._try_db_session", return_value=session):
        result = get_data_source_statuses()
    keys = {s["source_key"] for s in result["sources"]}
    assert {"fred", "fed", "treasury", "dxy"}.issubset(keys)


def test_data_service_each_source_has_four_booleans() -> None:
    """Every returned source must have all four boolean status flags."""
    from apps.api.data_service import get_data_source_statuses

    session = _db_session()
    _seed_source(session, source_key="partial_source", configured=True, raw_ingested=True, parsed=False, analysis_ready=False)

    with patch("apps.api.data_service._try_db_session", return_value=session):
        result = get_data_source_statuses()
    src = _sources_by_key(result)["partial_source"]
    for key in ["configured", "raw_ingested", "parsed", "analysis_ready"]:
        assert key in src, f"Missing field {key}"
        assert isinstance(src[key], bool), f"{key} must be bool, got {type(src[key])}"


def test_data_service_exposes_readiness_and_gate_states() -> None:
    """Readiness/gating semantics are derived in the output layer only."""
    from apps.api.data_service import get_data_source_statuses

    session = _db_session()
    _seed_source(
        session,
        source_key="ready_source",
        source_name="Ready Source",
        configured=True,
        raw_ingested=True,
        parsed=True,
        analysis_ready=True,
        status="ok",
    )
    _seed_source(
        session,
        source_key="degraded_source",
        source_name="Degraded Source",
        configured=True,
        raw_ingested=True,
        parsed=False,
        analysis_ready=False,
        status="partial",
    )
    _seed_source(
        session,
        source_key="blocked_source",
        source_name="Blocked Source",
        configured=True,
        raw_ingested=False,
        parsed=False,
        analysis_ready=False,
        status="not_connected",
        error_message="missing api key",
    )

    with patch("apps.api.data_service._try_db_session", return_value=session):
        result = get_data_source_statuses()

    sources = _sources_by_key(result)
    assert sources["ready_source"]["readiness_state"] == "ready"
    assert sources["ready_source"]["gate_state"] == "open"
    assert sources["ready_source"]["gating_reason"] == "analysis_ready"

    assert sources["degraded_source"]["readiness_state"] == "degraded"
    assert sources["degraded_source"]["gate_state"] == "degraded"
    assert sources["degraded_source"]["gating_reason"] == "status_partial"

    assert sources["blocked_source"]["readiness_state"] == "blocked"
    assert sources["blocked_source"]["gate_state"] == "closed"
    assert sources["blocked_source"]["gating_reason"] == "error_message"


def test_data_service_handles_empty_db() -> None:
    """When DB is available but has no records, return compatible sources list."""
    from apps.api.data_service import get_data_source_statuses

    session = _db_session()

    with patch("apps.api.data_service._try_db_session", return_value=session):
        result = get_data_source_statuses()
    assert "sources" in result
    assert isinstance(result["sources"], list)


def test_data_service_db_unavailable_fallback() -> None:
    """When DB is unavailable, data_service returns sensible fallback rows."""
    from apps.api.data_service import get_data_source_statuses

    with patch("apps.api.data_service._try_db_session", return_value=None):
        result = get_data_source_statuses()

    assert "sources" in result
    assert isinstance(result["sources"], list)
    for src in result["sources"]:
        assert "source_key" in src
        assert "source_name" in src
        assert isinstance(src["configured"], bool)
        assert isinstance(src["raw_ingested"], bool)
        assert isinstance(src["parsed"], bool)
        assert isinstance(src["analysis_ready"], bool)
        assert "status" in src


def test_data_service_db_rows_are_enriched_with_dual_source_contract() -> None:
    """Even with sparse DB rows, the API contract exposes FRED/OpenBB/Jin10 roles."""
    from apps.api.data_service import get_data_source_statuses

    session = _db_session()
    _seed_source(session, source_key="fred", source_name="FRED", source_metadata={"custom": "keep-me"})

    with patch("apps.api.data_service._try_db_session", return_value=session):
        result = get_data_source_statuses()

    sources = _sources_by_key(result)
    assert {"fred", "openbb_macro", "jin10_news"}.issubset(sources)

    fred = sources["fred"]
    assert fred["metadata"]["provider_role"] == "official_primary"
    assert "openbb_macro" in fred["metadata"]["fallback_sources"]
    assert fred["metadata"]["custom"] == "keep-me"

    openbb = sources["openbb_macro"]
    assert openbb["metadata"]["provider_role"] == "fallback"
    assert "fred" in openbb["metadata"]["fallback_for"]
    assert isinstance(openbb["configured"], bool)

    jin10 = sources["jin10_news"]
    assert jin10["metadata"]["provider_role"] == "supplemental"
    assert isinstance(jin10["metadata"]["fallback_for"], list)
    assert set(_P0_NEWS_SOURCE_ROLES).issubset(sources)


def test_data_service_filesystem_fallback_exposes_dual_source_contract() -> None:
    """Filesystem fallback still returns explicit source-role metadata for frontend."""
    from apps.api.data_service import get_data_source_statuses

    with patch("apps.api.data_service._try_db_session", return_value=None):
        result = get_data_source_statuses()

    sources = _sources_by_key(result)
    assert {"fred", "openbb_macro", "jin10_news"}.issubset(sources)
    assert sources["fred"]["metadata"]["provider_role"] == "official_primary"
    assert "openbb_macro" in sources["fred"]["metadata"]["fallback_sources"]
    assert sources["openbb_macro"]["metadata"]["provider_role"] == "fallback"
    assert "fred" in sources["openbb_macro"]["metadata"]["fallback_for"]
    assert sources["jin10_news"]["metadata"]["provider_role"] == "supplemental"


def test_data_service_filesystem_fallback_exposes_jin10_multi_entry_sources(tmp_path: Path) -> None:
    """Jin10 lanes are separately observable while aggregate jin10_news remains compatible."""
    from apps.api.data_service import get_data_source_statuses

    with patch("apps.api.data_service._try_db_session", return_value=None), patch(
        "apps.api.data_service._PROJECT_ROOT", tmp_path
    ):
        result = get_data_source_statuses()

    sources = _sources_by_key(result)
    assert "jin10_news" in sources
    for source_key, (source_group, source_type, access_method) in _JIN10_MULTI_ENTRY_EXPECTATIONS.items():
        src = sources[source_key]
        assert src["source_group"] == source_group
        assert src["source_type"] == source_type
        assert src["access_method"] == access_method
        assert src["status"] == "not_connected"
        assert src["metadata"]["provider_role"] == "supplemental"
        assert src["metadata"]["frontend_label"]
        assert src["metadata"]["artifact_layers"]
        assert src["metadata"]["polling_strategy"]["mode"]
        assert src["metadata"]["pressure_profile"]["level"]


def test_data_service_filesystem_fallback_exposes_p0_news_sources(tmp_path: Path) -> None:
    """P0 news/event sources are visible in a clean filesystem fallback."""
    from apps.api.data_service import get_data_source_statuses

    with patch("apps.api.data_service._try_db_session", return_value=None), patch(
        "apps.api.data_service._PROJECT_ROOT", tmp_path
    ):
        result = get_data_source_statuses()

    sources = _sources_by_key(result)
    assert set(_P0_NEWS_SOURCE_ROLES).issubset(sources)
    for source_key, provider_role in _P0_NEWS_SOURCE_ROLES.items():
        src = sources[source_key]
        assert src["source_group"] == "news"
        assert src["configured"] is False
        assert src["raw_ingested"] is False
        assert src["parsed"] is False
        assert src["analysis_ready"] is False
        assert src["status"] == "not_connected"
        assert src["metadata"]["provider_role"] == provider_role
        assert "frontend_label" in src["metadata"]
        if source_key == "reuters_public_news":
            assert src["metadata"]["priority_level"] == "P0.5"
            assert src["metadata"]["authorized_wire"] is False
        assert src["readiness_state"] == "not_configured"
        assert src["gate_state"] == "closed"
        assert src["gating_reason"] == "not_configured"


def test_data_service_filesystem_fallback_attaches_news_feature_artifacts(tmp_path: Path) -> None:
    """News sources with raw/parsed artifacts expose latest feature-run metadata for Data Ingestion."""
    from apps.api.services.source_service import get_data_source_statuses

    replay = _materialize_manual_news_fixture(tmp_path, include_collectors=True, include_outputs=False)
    raw_path = _latest_materialized_file(tmp_path / "storage" / "raw" / "news" / "fed_rss")
    parsed_path = _latest_materialized_file(tmp_path / "storage" / "parsed" / "news" / "fed_rss")
    feature_dir = replay["brief_path"].parent

    with patch("apps.api.services.source_service._try_db_session", return_value=None), patch(
        "apps.api.services.source_service._PROJECT_ROOT", tmp_path
    ):
        result = get_data_source_statuses()

    fed_rss = _sources_by_key(result)["fed_rss"]
    assert fed_rss["configured"] is True
    assert fed_rss["raw_ingested"] is True
    assert fed_rss["parsed"] is True
    assert fed_rss["analysis_ready"] is True
    assert fed_rss["status"] == "ok"
    assert fed_rss["last_run_id"] == replay["feature_run_id"]
    assert fed_rss["metadata"]["collector_raw_artifact_path"] == _relative_to(tmp_path, raw_path)
    assert fed_rss["metadata"]["collector_parsed_artifact_path"] == _relative_to(tmp_path, parsed_path)
    assert fed_rss["metadata"]["artifact_path"] == _relative_to(tmp_path, replay["brief_path"])
    assert fed_rss["metadata"]["brief_artifact_path"] == _relative_to(tmp_path, replay["brief_path"])
    assert fed_rss["metadata"]["event_candidates_artifact_path"] == _relative_to(tmp_path, feature_dir / "event_candidates.json")
    assert fed_rss["metadata"]["impact_assessments_artifact_path"] == _relative_to(tmp_path, feature_dir / "impact_assessments.json")
    assert fed_rss["metadata"]["report_events_artifact_path"] == _relative_to(tmp_path, feature_dir / "report_events.json")
    assert fed_rss["metadata"]["market_reactions_artifact_path"] == _relative_to(tmp_path, feature_dir / "market_reactions.json")
    assert fed_rss["metadata"]["latest_feature_date"] == replay["feature_date"]
    assert fed_rss["metadata"]["latest_feature_run_id"] == replay["feature_run_id"]
    assert fed_rss["metadata"]["database_tables"] == ["data_source_status", "analysis_snapshots.news"]
    assert fed_rss["metadata"]["polling_strategy"]["mode"] == "rss_poll"
    assert fed_rss["metadata"]["pressure_profile"]["level"] == "medium"
    assert fed_rss["metadata"]["confirmed_event_count"] >= 1
    assert fed_rss["metadata"]["candidate_event_count"] >= 1
    assert fed_rss["metadata"]["calendar_event_count"] >= 0

    gdelt = _sources_by_key(result)["gdelt_news"]
    assert gdelt["configured"] is False
    assert gdelt["analysis_ready"] is False
    assert gdelt["status"] == "not_connected"
    assert "artifact_path" not in gdelt["metadata"]


def test_data_service_filesystem_fallback_attaches_news_collection_diagnostics(tmp_path: Path) -> None:
    from apps.api.services.source_service import get_data_source_statuses

    replay = _materialize_manual_news_fixture(tmp_path, include_collectors=True, include_outputs=False)
    _write_collection_diagnostics(replay["feature_dir"] / "collection_diagnostics.json")

    with patch("apps.api.services.source_service._try_db_session", return_value=None), patch(
        "apps.api.services.source_service._PROJECT_ROOT", tmp_path
    ):
        result = get_data_source_statuses()

    fed_rss = _sources_by_key(result)["fed_rss"]
    gdelt = _sources_by_key(result)["gdelt_news"]

    assert fed_rss["metadata"]["collection_diagnostics_artifact_path"] == _relative_to(
        tmp_path, replay["feature_dir"] / "collection_diagnostics.json"
    )
    assert fed_rss["metadata"]["latest_collection_status"] == "available"
    assert fed_rss["metadata"]["latest_source_ref_count"] == 1
    assert fed_rss["metadata"]["latest_source_ref_statuses"] == ["available"]
    assert fed_rss["metadata"]["latest_reason_codes"] == []
    assert fed_rss["metadata"]["latest_collection_warnings"] == []
    assert fed_rss["metadata"]["latest_collector_runtime"]["status"] == "success"

    assert gdelt["metadata"]["collection_diagnostics_artifact_path"] == _relative_to(
        tmp_path, replay["feature_dir"] / "collection_diagnostics.json"
    )
    assert gdelt["metadata"]["latest_collection_status"] == "rate_limited"
    assert gdelt["metadata"]["latest_source_ref_count"] == 1
    assert gdelt["metadata"]["latest_source_ref_statuses"] == ["rate_limited"]
    assert gdelt["metadata"]["latest_reason_codes"] == ["cooldown_active"]
    assert len(gdelt["metadata"]["latest_collection_warnings"]) == 1
    assert gdelt["metadata"]["latest_collector_runtime"]["status"] == "unavailable"
    assert gdelt["metadata"]["latest_cooldown"] == {
        "active": True,
        "status": "rate_limited",
        "reason_code": "cooldown_active",
        "source_ref": "gdelt_news:fed_inflation",
        "query_group": "fed_inflation",
        "warning": "gdelt_news:fed_inflation cooldown_active: GDELT query group is in local cooldown until 2026-06-11T12:15:00+00:00",
        "parsed_path": "parsed/news/gdelt/2026-06-11/cooldown-fed_inflation.json",
        "cooldown_until": "2026-06-11T12:15:00+00:00",
        "cooldown_seconds": 900,
        "written_at": "2026-06-11T12:00:00+00:00",
        "reason": "HTTP 429 from https://api.gdeltproject.org/api/v2/doc/doc",
    }
    assert fed_rss["metadata"]["latest_health_at"] == _mtime_iso(replay["feature_dir"] / "collection_diagnostics.json")
    assert fed_rss["metadata"]["health_state"] == "healthy"
    assert gdelt["metadata"]["latest_health_at"] == _mtime_iso(replay["feature_dir"] / "collection_diagnostics.json")
    assert gdelt["metadata"]["health_state"] == "cooldown"


def test_data_service_db_rows_are_augmented_with_news_feature_artifacts(tmp_path: Path) -> None:
    """DB-backed rows still expose filesystem-backed news artifact metadata."""
    from apps.api.services.source_service import get_data_source_statuses

    session = _db_session()
    _seed_source(
        session,
        source_key="fed_rss",
        source_name="Federal Reserve RSS",
        source_group="news",
        source_type="rss",
        access_method="feedparser+httpx",
        configured=False,
        raw_ingested=False,
        parsed=False,
        analysis_ready=False,
        status="not_connected",
        latest_raw_time=None,
        latest_parsed_time=None,
        last_run_id=None,
    )
    _write_json(
        tmp_path / "storage" / "raw" / "news" / "fed_rss" / "2026-06-10" / "feed-raw.json",
        {"items": []},
    )
    _write_json(
        tmp_path / "storage" / "parsed" / "news" / "fed_rss" / "2026-06-10" / "feed-parsed.json",
        {"items": []},
    )
    _write_json(
        tmp_path / "storage" / "features" / "news" / "2026-06-10" / "run-009" / "daily_market_brief.json",
        {"daily_market_brief": {"confirmed_events": [], "candidate_events": [], "unconfirmed_risks": [], "next_7d_calendar": [], "source_refs": []}},
    )

    with patch("apps.api.services.source_service._try_db_session", return_value=session), patch(
        "apps.api.services.source_service._PROJECT_ROOT", tmp_path
    ):
        result = get_data_source_statuses()

    fed_rss = _sources_by_key(result)["fed_rss"]
    assert fed_rss["configured"] is True
    assert fed_rss["parsed"] is True
    assert fed_rss["analysis_ready"] is True
    assert fed_rss["last_run_id"] == "run-009"
    assert fed_rss["metadata"]["brief_artifact_path"] == "storage/features/news/2026-06-10/run-009/daily_market_brief.json"


def test_data_service_extracts_latest_news_raw_ref_from_feature_artifact(tmp_path: Path) -> None:
    from apps.api.services.source_service import get_data_source_statuses

    trigger_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "daily_analysis_triggers.json"
    _write_json(
        trigger_path,
        {
            "as_of": "2026-06-12T10:07:33+00:00",
            "triggers": [
                {
                    "trigger_id": "old",
                    "source_title": "old event",
                    "created_at": "2026-06-12T09:00:00+00:00",
                    "source_url": "https://flash.jin10.com/detail/old",
                    "source_refs": [{"source_ref": "old-ref", "raw_path": "raw/news/jin10_feishu/old.json"}],
                },
                {
                    "trigger_id": "new",
                    "source_title": "new event",
                    "created_at": "2026-06-12T10:00:00+00:00",
                    "source_url": "https://flash.jin10.com/detail/new",
                    "source_refs": [{"source_ref": "new-ref", "raw_path": "raw/news/jin10_feishu/new.json"}],
                },
            ],
        },
    )

    with patch("apps.api.services.source_service._try_db_session", return_value=None), patch(
        "apps.api.services.source_service._PROJECT_ROOT", tmp_path
    ):
        result = get_data_source_statuses()

    jin10_news = _sources_by_key(result)["jin10_news"]
    raw_ref = jin10_news["metadata"]["latest_raw_ref"]
    assert raw_ref["url"] == "https://flash.jin10.com/detail/new"
    assert raw_ref["raw_path"] == "raw/news/jin10_feishu/new.json"
    assert raw_ref["source_ref"] == "new-ref"
    assert jin10_news["metadata"]["latest_raw_url"] == "https://flash.jin10.com/detail/new"
    assert jin10_news["metadata"]["pressure_profile"]["upgrade_required"] is True


# ── route contract tests ──


def test_api_route_returns_sources_payload() -> None:
    """Route returns the expected top-level payload shape."""
    data = _api_status_payload()
    assert isinstance(data, dict)
    assert "sources" in data
    assert isinstance(data["sources"], list)


def test_api_route_each_source_has_required_fields() -> None:
    """Each source in route payload has the required field set."""
    data = _api_status_payload()

    if data["sources"]:
        src = data["sources"][0]
        required_fields = [
            "source_key", "source_name", "source_group", "source_type",
            "access_method", "configured", "raw_ingested", "parsed",
            "analysis_ready", "latest_raw_time", "latest_parsed_time",
            "latest_snapshot_id", "row_count", "status", "error_message",
            "last_run_id", "next_run_time", "metadata",
            "readiness_state", "gate_state", "gating_reason",
        ]
        for field in required_fields:
            assert field in src, f"Missing field: {field}"


def test_api_route_no_object_object_in_payload() -> None:
    """Payload must not contain raw unformatted nested objects as strings."""
    data = _api_status_payload()
    raw = str(data)
    assert "[object Object]" not in raw, "Payload should not contain [object Object]"
    for src in data["sources"]:
        assert isinstance(src.get("metadata"), (dict, type(None))), f"metadata should be dict, got {type(src.get('metadata'))}"


def test_api_route_four_booleans_are_present() -> None:
    """All four boolean layers exist in route payload."""
    data = _api_status_payload()

    if data["sources"]:
        src = data["sources"][0]
        for key in ["configured", "raw_ingested", "parsed", "analysis_ready"]:
            assert key in src
            assert isinstance(src[key], bool)
        assert src["readiness_state"] in {"ready", "degraded", "blocked", "not_configured"}
        assert src["gate_state"] in {"open", "degraded", "closed"}
        assert isinstance(src["gating_reason"], str)


def test_api_route_exposes_readiness_contract_on_known_fallback_sources() -> None:
    """Clean fallback rows expose the gating contract for frontend consumption."""
    data = _api_status_payload()
    sources = _sources_by_key(data)

    assert sources["fred"]["readiness_state"] == "not_configured"
    assert sources["fred"]["gate_state"] == "closed"
    assert sources["fred"]["gating_reason"] == "not_configured"


def test_api_route_exposes_dual_source_metadata_contract() -> None:
    """Route contract includes stable metadata for frontend role rendering."""
    data = _api_status_payload()

    sources = _sources_by_key(data)
    assert {"fred", "openbb_macro", "jin10_news"}.issubset(sources)

    fred_meta = sources["fred"]["metadata"]
    openbb_meta = sources["openbb_macro"]["metadata"]
    jin10_meta = sources["jin10_news"]["metadata"]

    assert fred_meta["provider_role"] == "official_primary"
    assert isinstance(fred_meta["fallback_sources"], list)
    assert "openbb_macro" in fred_meta["fallback_sources"]

    assert openbb_meta["provider_role"] == "fallback"
    assert isinstance(openbb_meta["fallback_for"], list)
    assert "fred" in openbb_meta["fallback_for"]

    assert jin10_meta["provider_role"] == "supplemental"
    assert isinstance(jin10_meta["fallback_for"], list)


def test_data_status_summary_marks_live_when_all_sources_ok() -> None:
    """Summary API returns LIVE only when all known sources are available."""
    payload = {
        "sources": [
            {
                "source_key": "fred",
                "source_name": "FRED",
                "status": "ok",
                "metadata": {"frontend_label": "FRED"},
            },
            {
                "source_key": "openbb_macro",
                "source_name": "OpenBB Macro/Market",
                "status": "ok",
                "metadata": {"frontend_label": "OpenBB 宏观/市场补充源"},
            },
        ]
    }

    with patch("apps.api.services.source_service.get_data_source_statuses", return_value=payload), patch(
        "apps.api.services.source_service._try_db_session", return_value=None
    ):
        result = get_data_status_summary()

    assert result["overall_status"] == "LIVE"
    assert result["missing_sources"] == []
    assert result["latest_run"] is None
    assert result["snapshot_id"] is None


def test_data_status_summary_marks_partial_and_lists_missing_sources() -> None:
    """Unavailable upstreams must remain visible in the summary contract."""
    payload = {
        "sources": [
            {
                "source_key": "fred",
                "source_name": "FRED",
                "status": "ok",
                "metadata": {"frontend_label": "FRED 官方宏观主源"},
            },
            {
                "source_key": "jin10_news",
                "source_name": "Jin10 News",
                "status": "not_connected",
                "metadata": {"frontend_label": "Jin10 新闻/日历补充源"},
            },
            {
                "source_key": "cme_daily_bulletin",
                "source_name": "CME Daily Bulletin",
                "status": "partial",
                "metadata": {"frontend_label": "CME 官方公告"},
            },
        ]
    }

    with patch("apps.api.services.source_service.get_data_source_statuses", return_value=payload), patch(
        "apps.api.services.source_service._try_db_session", return_value=None
    ):
        result = get_data_status_summary()

    assert result["overall_status"] == "PARTIAL"
    assert result["missing_sources"] == ["Jin10 新闻/日历补充源"]
    assert result["sources"][0]["status"] == "LIVE"
    assert result["sources"][1]["status"] == "UNAVAILABLE"
    assert result["sources"][2]["status"] == "PARTIAL"


def test_data_status_summary_exposes_latest_health_signal() -> None:
    """Summary read model should surface the latest health timestamp and state."""
    payload = {
        "sources": [
            {
                "source_key": "fred",
                "source_name": "FRED",
                "status": "ok",
                "metadata": {
                    "frontend_label": "FRED 官方宏观主源",
                    "latest_health_at": "2026-06-11T12:05:00+00:00",
                    "health_state": "healthy",
                },
            },
            {
                "source_key": "gdelt_news",
                "source_name": "GDELT DOC News Radar",
                "status": "not_connected",
                "metadata": {
                    "frontend_label": "GDELT 全球新闻雷达",
                    "latest_health_at": "2026-06-11T12:15:00+00:00",
                    "health_state": "cooldown",
                },
            },
        ]
    }

    with patch("apps.api.services.source_service.get_data_source_statuses", return_value=payload), patch(
        "apps.api.services.source_service._try_db_session", return_value=None
    ):
        result = get_data_status_summary()

    assert result["sources"][0]["latest_health_at"] == "2026-06-11T12:05:00+00:00"
    assert result["sources"][0]["health_state"] == "healthy"
    assert result["sources"][1]["latest_health_at"] == "2026-06-11T12:15:00+00:00"
    assert result["sources"][1]["health_state"] == "cooldown"


def test_api_data_sources_status_http_smoke() -> None:
    """Route function remains JSON-serializable without relying on TestClient startup hooks."""
    with patch("apps.api.data_service._try_db_session", return_value=None):
        data = jsonable_encoder(api_data_sources_status())
    sources = _sources_by_key(data)
    assert {"fred", "openbb_macro", "jin10_news"}.issubset(sources)
    assert set(_P0_NEWS_SOURCE_ROLES).issubset(sources)
    assert sources["fred"]["metadata"]["provider_role"] == "official_primary"
    assert sources["openbb_macro"]["metadata"]["provider_role"] == "fallback"
    assert sources["jin10_news"]["metadata"]["provider_role"] == "supplemental"
