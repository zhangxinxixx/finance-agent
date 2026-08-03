"""HTTP acceptance tests for Slice C: Gold Policy report delivery API.

The test materializes a real v2 Gold Policy daily-close bundle from the frozen
premarket snapshot fixture, registers it through the Slice B registry sink into
SQLite, and asserts the existing read-only API endpoints deliver it correctly.

Only ``tmp_path`` and an in-memory SQLite database are mutated.  No Gold
adapter/runtime/bundle verifier/registry sink is mocked.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.analysis.gold_policy.daily_close_store import verify_gold_daily_close_bundle
from apps.worker.report_registry_sink import register_gold_policy_report_bundle
from database.models.analysis import ensure_analysis_tables
from database.models.report import ensure_report_tables


_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "gold_daily_report"
_FIXTURE_NAME = "premarket_snapshot_2026-07-07.json"
_FIXTURE_PATH = _FIXTURE_DIR / _FIXTURE_NAME
_FIXTURE_SOURCE_SHA256 = "85dd2f24075812d62206ee12d1e5fea37d892e3cb2c9360a3c73d0a3e07a4d97"

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


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _materialize_snapshot(tmp_path: Path) -> tuple[Path, str, str]:
    """Copy the frozen fixture into the formal snapshot layout under tmp_path/storage."""

    fixture_bytes = _FIXTURE_PATH.read_bytes()
    digest = hashlib.sha256(fixture_bytes).hexdigest()
    assert digest == _FIXTURE_SOURCE_SHA256, f"fixture sha mismatch: {digest}"
    payload = json.loads(fixture_bytes.decode("utf-8"))
    trade_date = payload["trade_date"]
    run_id = payload["run_id"]
    snapshot_dir = tmp_path / "storage" / "features" / "snapshots" / "XAUUSD" / trade_date / run_id
    snapshot_dir.mkdir(parents=True)
    target = snapshot_dir / "premarket_snapshot.json"
    target.write_bytes(fixture_bytes)
    return target, trade_date, run_id


def _run_with_jin10_disabled(storage_root: Path, trade_date: str) -> dict:
    from scripts import run_gold_daily_report as report

    previous = os.environ.get("FINANCE_AGENT_DISABLE_JIN10")
    os.environ["FINANCE_AGENT_DISABLE_JIN10"] = "true"
    try:
        return report.run_gold_daily_report(
            trade_date=trade_date,
            storage_root=storage_root,
        )
    finally:
        if previous is None:
            os.environ.pop("FINANCE_AGENT_DISABLE_JIN10", None)
        else:
            os.environ["FINANCE_AGENT_DISABLE_JIN10"] = previous


@pytest.fixture
def _gold_policy_delivery_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Materialize a real v2 bundle, register it, and wire the API to tmp_path."""

    from apps.api.services import report_service

    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    _materialize_snapshot(tmp_path)
    result = _run_with_jin10_disabled(storage_root, "2026-07-07")
    assert result["status"] == "completed", result
    report_paths = [Path(path) for path in result["report_paths"]]
    bundle_path = report_paths[0].parent
    verification = verify_gold_daily_close_bundle(
        storage_root=storage_root,
        bundle_path=bundle_path,
    )
    assert verification.status == "valid", verification

    factory = _make_session_factory()
    with factory() as db:
        report_id = register_gold_policy_report_bundle(
            db,
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
        db.commit()

    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.data_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services._storage._PROJECT_ROOT", tmp_path)

    # Inject the test session into the API services that consult _try_db_session.
    def _test_session_factory():
        return factory()

    monkeypatch.setattr("apps.api.services._storage._try_db_session", _test_session_factory)
    monkeypatch.setattr("apps.api.data_service._try_db_session", _test_session_factory)

    yield {
        "tmp_path": tmp_path,
        "factory": factory,
        "report_id": report_id,
        "bundle_path": bundle_path,
        "trade_date": result["trade_date"],
        "run_id": result["run_id"],
    }


def _client_with_session(db_session) -> TestClient:
    from apps.api.main import app
    from database.models.engine import get_db

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_reports_index_lists_gold_policy_daily_report(
    _gold_policy_delivery_env,
) -> None:
    env = _gold_policy_delivery_env
    factory = env["factory"]
    report_id = env["report_id"]
    trade_date = env["trade_date"]
    run_id = env["run_id"]

    with factory() as db:
        client = _client_with_session(db)
        try:
            response = client.get("/api/reports/index")
        finally:
            from apps.api.main import app

            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    matched = [item for item in payload.get("reports", []) if item.get("report_id") == report_id]
    assert matched, f"gold_policy_daily report not in index: {payload}"
    item = matched[0]
    assert item["type"] == "gold_policy_daily"
    assert item["family"] == "gold_policy_daily_report"
    assert item["trade_date"] == trade_date
    assert item["run_id"] == run_id
    assert item["available"] is True


def test_report_detail_returns_v2_structured_payload_and_identity(
    _gold_policy_delivery_env,
) -> None:
    env = _gold_policy_delivery_env
    factory = env["factory"]
    report_id = env["report_id"]

    with factory() as db:
        client = _client_with_session(db)
        try:
            response = client.get(f"/api/reports/{report_id}")
        finally:
            from apps.api.main import app

            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_id"] == report_id
    assert payload["family"] == "gold_policy_daily_report"
    assert payload["data_status"] == "partial"
    assert payload["lifecycle_status"] == "needs_review"
    assert len(payload["artifacts"]) == 9
    assert payload["input_snapshot_ids"]
    assert payload["report_identity"] is not None
    assert payload["report_identity"].get("canonical_receipt_id")
    assert payload["report_identity"].get("manifest_schema_version") == ("gold_policy_report_manifest.v2")
    assert payload["report_identity"].get("structured_schema_version") == ("gold_policy_report_structured.v2")

    structured = payload["structured_payload"]
    assert structured is not None
    assert structured["schema_version"] == "gold_policy_report_structured.v2"
    assert len(structured["sections"]) == 11
    assert [section["section_id"] for section in structured["sections"]] == list(_V2_SECTION_ORDER)


def test_report_analysis_endpoint_hits_analysis_md(_gold_policy_delivery_env) -> None:
    env = _gold_policy_delivery_env
    factory = env["factory"]
    report_id = env["report_id"]
    bundle_path: Path = env["bundle_path"]

    with factory() as db:
        client = _client_with_session(db)
        try:
            response = client.get(f"/api/reports/{report_id}/analysis")
        finally:
            from apps.api.main import app

            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    expected = (bundle_path / "analysis.md").read_text(encoding="utf-8")
    assert payload["content"] == expected
    assert payload["path"].endswith("analysis.md")


def test_report_visual_endpoint_hits_visual_html(_gold_policy_delivery_env) -> None:
    env = _gold_policy_delivery_env
    factory = env["factory"]
    report_id = env["report_id"]
    bundle_path: Path = env["bundle_path"]

    with factory() as db:
        client = _client_with_session(db)
        try:
            response = client.get(f"/api/reports/{report_id}/visual")
        finally:
            from apps.api.main import app

            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    expected = (bundle_path / "visual.html").read_text(encoding="utf-8")
    assert payload["content"] == expected
    assert payload["path"].endswith("visual.html")
    assert "<section " in payload["content"]
    assert "data-section-id=" in payload["content"]


def test_report_evidence_endpoint_hits_evidence_json(_gold_policy_delivery_env) -> None:
    env = _gold_policy_delivery_env
    factory = env["factory"]
    report_id = env["report_id"]
    bundle_path: Path = env["bundle_path"]

    with factory() as db:
        client = _client_with_session(db)
        try:
            response = client.get(f"/api/reports/{report_id}/evidence")
        finally:
            from apps.api.main import app

            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    expected = json.loads((bundle_path / "evidence.json").read_text(encoding="utf-8"))
    assert payload["content"] == expected
    assert payload["path"].endswith("evidence.json")
    assert payload["content"]["schema_version"] == "gold_policy_report_evidence.v2"
    # The picker must not pick data_quality, manifest, or structured payloads.
    assert payload["content"]["schema_version"] != "gold_policy_report_manifest.v2"
    assert payload["content"]["schema_version"] != "gold_policy_report_structured.v2"
    assert payload["content"]["schema_version"] != "gold_policy_report_data_quality.v2"


def test_legacy_structured_json_fallback_when_no_named_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy fallback: a single arbitrary structured_json still serves /evidence."""

    from apps.api.services import report_service
    from database.queries.report import upsert_report_artifact, upsert_report_item

    factory = _make_session_factory()
    with factory() as session:
        upsert_report_item(
            session,
            {
                "report_id": "legacy-structured-001",
                "family": "macro",
                "report_type": "daily_macro",
                "title": "Legacy Structured Report",
                "asset": "XAUUSD",
                "trade_date": "2026-05-26",
                "run_id": "run-legacy-001",
                "snapshot_id": "snap-legacy-001",
                "data_status": "live",
                "lifecycle_status": "generated",
                "source_refs": [
                    {
                        "source_id": "src-001",
                        "source_name": "Macro Feed",
                        "source_type": "api",
                        "status": "available",
                    }
                ],
                "metadata": {"template_version": "v1"},
            },
        )
        # Single structured_json whose basename is NOT report_structured.json
        # nor evidence.json; Detail and /evidence must still pick it via legacy
        # fallback (first structured_json).
        upsert_report_artifact(
            session,
            {
                "artifact_id": "legacy-structured-001:structured",
                "report_id": "legacy-structured-001",
                "artifact_type": "structured_json",
                "file_path": "storage/outputs/reports/2026-05-26/legacy-structured-001/legacy_payload.json",
                "status": "generated",
                "content_type": "application/json",
                "is_primary": True,
            },
        )
        session.commit()

    legacy_payload = {"hello": "world", "schema_version": "legacy.v0"}
    legacy_path = tmp_path / "storage/outputs/reports/2026-05-26/legacy-structured-001/legacy_payload.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        client = _client_with_session(db)
        try:
            detail_response = client.get("/api/reports/legacy-structured-001")
            evidence_response = client.get("/api/reports/legacy-structured-001/evidence")
        finally:
            from apps.api.main import app

            app.dependency_overrides.clear()

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["structured_payload"] == legacy_payload

    assert evidence_response.status_code == 200
    evidence = evidence_response.json()
    assert evidence["content"] == legacy_payload
    assert evidence["path"].endswith("legacy_payload.json")
