"""Report facts remain readable only after the latest registered bundle verifies."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from apps.api.routes import macro_routes
from apps.api.services import macro_service
from database.models.analysis import AnalysisSnapshot
from database.models.report import ReportArtifact
from database.models.task import TaskRun
from tests.api import test_dashboard_research_service as _research_fixtures

research_store = _research_fixtures.research_store


OLD_RUN = "ffffffff-ffff-ffff-ffff-ffffffffffff"
NEW_RUN = "00000000-0000-0000-0000-00000000000a"


@pytest.fixture
def macro_route(monkeypatch):
    # Exercise the route and real service without a runtime app or thread portal.
    monkeypatch.setattr(macro_routes, "get_macro_latest", macro_service.get_macro_latest)
    monkeypatch.setattr(macro_service, "_get_macro_latest_from_db",
                        lambda: pytest.fail("must not substitute legacy macro"))
    monkeypatch.setattr(macro_service, "_latest_date_dir",
                        lambda _: pytest.fail("must not substitute filesystem macro"))
    return macro_routes.api_macro_latest


@pytest.mark.parametrize("narrative", ["研究叙述", None, "## 结论"])
def test_macro_api_returns_verified_frozen_facts_without_requiring_narrative(research_store, macro_route, narrative):
    add, _ = research_store
    add(OLD_RUN, 9, value=1.23)
    add(NEW_RUN, 10, narrative=narrative)
    result = macro_route()
    assert result["indicators"]["REAL10Y"]["value"] == 2.68
    assert result["run_id"] == NEW_RUN
    assert result["snapshot_id"] == f"XAUUSD:2026-09-17:{NEW_RUN}"
    assert result["as_of"] == result["trade_date"] == "2026-09-17"
    assert result["facts_status"] == "available"
    assert result["research_status"] == ("available" if narrative == "研究叙述" else "unavailable")
    assert result["source_refs"] == [{"source": "FRED", "symbol": "REAL10Y"}]
    assert "bias" not in result and "direction" not in result


@pytest.mark.parametrize("corruption", ["report_bytes", "snapshot_bytes", "snapshot_hash", "run_identity", "report_identity", "path_escape"])
def test_macro_api_rejects_corrupt_latest_missing_narrative_without_old_fallback(research_store, macro_route, corruption, tmp_path):
    from uuid import UUID

    add, factory = research_store
    add(OLD_RUN, 9, value=1.23)
    snapshot_path = add(NEW_RUN, 10, narrative=None)
    with factory() as db:
        artifact = db.get(ReportArtifact, NEW_RUN)
        snapshot = db.query(AnalysisSnapshot).filter_by(run_id=NEW_RUN).one()
        if corruption == "report_bytes":
            Path(artifact.file_path).write_text("{}")
        elif corruption == "snapshot_bytes":
            snapshot_path.write_text("{}")
        elif corruption == "snapshot_hash":
            snapshot.payload_sha256 = "0" * 64
        elif corruption == "run_identity":
            db.get(TaskRun, UUID(NEW_RUN)).snapshot_id = "other-snapshot"
        elif corruption == "report_identity":
            artifact.artifact_metadata = {"run_id": OLD_RUN, "snapshot_id": snapshot.snapshot_id}
        elif corruption == "path_escape":
            outside = tmp_path / "outside.json"
            outside.write_bytes(Path(artifact.file_path).read_bytes())
            artifact.file_path = str(outside)
        db.commit()
    with pytest.raises(HTTPException) as caught:
        macro_route()
    assert caught.value.status_code == 404


def test_macro_database_unavailable_does_not_read_legacy(monkeypatch, macro_route):
    monkeypatch.setattr("apps.api.services.dashboard_research_service._try_db_session", lambda: None)
    with pytest.raises(HTTPException) as caught:
        macro_route()
    assert caught.value.status_code == 404
