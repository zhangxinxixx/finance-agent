"""Actual registry -> SQLite -> HTTP contracts; no patched response or live service."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_store import persist_gold_daily_close_run
from apps.worker.report_registry_sink import register_gold_policy_report_bundle
from database.models.analysis import AnalysisSnapshot
from database.models.report import ReportArtifact, ReportItem
from tests.analysis.test_gold_daily_close_loop import _confirmed_support_break, _v2_snapshot
from tests.analysis.test_gold_daily_close_store import _bootstrap_v2_pair
from tests.analysis.test_gold_strategy_policy import _policy_input, _snapshot
from tests.api.test_gold_policy_report_delivery_api import _client_with_session, _make_session_factory


@pytest.fixture
def registered_gold(tmp_path, monkeypatch):
    """Real, verified bundles from existing frozen inputs; everything stays under tmp_path."""
    factory = _make_session_factory()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr("apps.api.services._storage._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.data_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services._storage._try_db_session", factory)
    monkeypatch.setattr("apps.api.data_service._try_db_session", factory)

    def register(status="accepted", run_id="gold-contract-a"):
        loop_input, _ = _bootstrap_v2_pair()
        if status == "accepted":
            level, decision = _confirmed_support_break(loop_input.decision_as_of)
            loop_input = loop_input.model_copy(
                update={
                    "key_levels": (level,),
                    "key_level_decisions": (decision,),
                    "key_level_proof": (decision,),
                }
            )
        elif status == "degraded":
            feature = _v2_snapshot(
                _snapshot("feature_snapshot_v1_bearish_2025-01-21.json"),
                us10y={"value": None, "quality_status": "blocked", "freshness_status": "missing"},
            )
            support = _policy_input(feature=feature)
            loop_input = loop_input.model_copy(
                update={
                    "current_feature": feature,
                    "options_regime": support.options_regime,
                    "event_risk": support.event_risk,
                }
            )
        else:
            assert status == "observe"
        result = evaluate_gold_daily_close_loop(loop_input)
        assert result.model_invocations == 0
        storage = tmp_path / "storage" / "reports" / "contracts" / run_id
        write = persist_gold_daily_close_run(
            storage_root=storage,
            run_id=run_id,
            loop_input=loop_input,
            result=result,
        )
        quality = json.loads((write.bundle_path / "data_quality.json").read_text())
        assert quality["publication_status"] == status
        with factory() as db:
            report_id = register_gold_policy_report_bundle(db, storage_root=storage, bundle_path=write.bundle_path)
            db.commit()
        return report_id

    return {"register": register, "factory": factory, "root": tmp_path}


def read_views(env, report_id, *, case):
    with env["factory"]() as db:
        client = _client_with_session(db)
        try:
            index = client.get("/api/reports/index")
            dates = client.get("/api/reports/dates")
            detail = client.get(f"/api/reports/{report_id}")
            analysis = client.get(f"/api/reports/{report_id}/analysis")
        finally:
            from apps.api.main import app

            app.dependency_overrides.clear()
    assert index.status_code == dates.status_code == 200
    views = {
        "case": case,
        "report_id": report_id,
        "index": index.json(),
        "dates": dates.json(),
        "detail_status": detail.status_code,
        "detail": detail.json(),
        "analysis_status": analysis.status_code,
        "analysis": analysis.json(),
    }
    evidence = os.environ.get("FINANCE_AGENT_REPORT_CONTRACT_EVIDENCE")
    if evidence:
        target = Path(evidence)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{case}.json").write_text(json.dumps(views, ensure_ascii=False, indent=2) + "\n")
    return views


def index_row(views, report_id):
    return next(row for row in views["index"]["reports"] if row["report_id"] == report_id)


@pytest.mark.parametrize(
    "status,data,lifecycle,allowed",
    [
        ("accepted", "live", "snapshot_bound", True),
        ("observe", "partial", "needs_review", False),
        ("degraded", "partial", "needs_review", False),
    ],
)
def test_registered_gold_index_detail_and_registry_only_dates(registered_gold, status, data, lifecycle, allowed):
    env = registered_gold
    report_id = env["register"](status)
    views = read_views(env, report_id, case=status)
    row, detail = index_row(views, report_id), views["detail"]
    assert views["detail_status"] == views["analysis_status"] == 200
    assert row["publication_status"] == detail["publication_status"] == status
    assert row["data_status"] == detail["data_status"] == data
    assert row["lifecycle_status"] == detail["lifecycle_status"] == lifecycle
    assert row["publish_allowed"] is detail["publish_allowed"] is allowed
    assert row["output_mode"] == detail["output_mode"] == ("accepted" if allowed else "observe")
    assert row["review_status"] is None  # Registry did not persist an approval.
    assert row.get("research_identity") is None  # No AnalysisSnapshot row was registered.
    for key in ("report_id", "run_id", "snapshot_id", "trade_date"):
        assert row[key] == detail[key]
    assert row["report_identity"] == detail["report_identity"]
    with env["factory"]() as db:
        stored = db.get(ReportItem, report_id)
        assert row["report_identity"]["canonical_receipt_id"] == stored.report_metadata["canonical_receipt_id"]
        assert row["report_identity"]["authority_result_id"] == stored.report_metadata["authority_result_id"]
        assert stored.data_status == data and stored.lifecycle_status == lifecycle
    assert views["dates"] == {
        "asset": "XAUUSD",
        "total_dates": 1,
        "dates": [
            {
                "trade_date": row["trade_date"],
                "modules": ["gold_policy_daily"],
                "latest_run_id": row["run_id"],
                "has_final_report": False,
                "has_strategy_card": False,
            }
        ],
    }


@pytest.mark.parametrize("lifecycle,allowed", [("published", True), ("archived", False)])
def test_registered_gold_publication_fact_and_history_are_separate(registered_gold, lifecycle, allowed):
    env = registered_gold
    report_id = env["register"]()
    with env["factory"]() as db:
        row = db.get(ReportItem, report_id)
        row.lifecycle_status = lifecycle  # Explicit persisted fact, never inferred from accepted.
        if lifecycle == "published":
            row.report_metadata = {**row.report_metadata, "review_status": "approved"}
        db.commit()
    views = read_views(env, report_id, case=lifecycle)
    row, detail = index_row(views, report_id), views["detail"]
    assert row["publication_status"] == detail["publication_status"] == "accepted"
    assert row["lifecycle_status"] == detail["lifecycle_status"] == lifecycle
    assert row["publish_allowed"] is detail["publish_allowed"] is allowed
    if lifecycle == "published":
        assert row["review_status"] == detail["review_status"] == "approved"


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "unknown",
        "unknown-shape",
        "mode",
        "receipt",
        "receipt-revision",
        "writer",
        "snapshot",
        "typed-permission",
        "artifact-publication",
    ],
)
def test_registered_gold_missing_or_conflicting_metadata_never_grants_permission(registered_gold, fault):
    env = registered_gold
    good_id = env["register"](run_id="gold-contract-good")
    report_id = env["register"](run_id="gold-contract-fault")
    with env["factory"]() as db:
        row = db.get(ReportItem, report_id)
        metadata = dict(row.report_metadata)
        if fault == "empty":
            metadata = {}
        elif fault == "unknown":
            metadata["publication_status"] = "future-unknown"
        elif fault == "unknown-shape":
            metadata["publication_status"] = {"unknown": "accepted"}
        elif fault == "mode":
            metadata["output_mode"] = "observe"
        elif fault == "receipt":
            metadata["canonical_receipt_id"] = "foreign-receipt"
        elif fault == "receipt-revision":
            metadata["canonical_receipt_revision_no"] += 1
        elif fault == "writer":
            metadata.pop("writer")
        elif fault == "snapshot":
            row.snapshot_id = "foreign-snapshot"
        elif fault == "typed-permission":
            metadata["publish_allowed"] = "true"
        elif fault == "artifact-publication":
            artifact = db.query(ReportArtifact).filter_by(report_id=report_id).first()
            artifact.artifact_metadata = {**artifact.artifact_metadata, "publication_status": "observe"}
        row.report_metadata = metadata
        db.commit()
    views = read_views(env, report_id, case=f"fault-{fault}")
    row, detail = index_row(views, report_id), views["detail"]
    assert row["publish_allowed"] is None and detail["publish_allowed"] is None
    assert index_row(views, good_id)["publish_allowed"] is True
    assert row["report_identity"] == detail["report_identity"]
    if fault in {"empty", "unknown", "unknown-shape", "mode", "artifact-publication"}:
        assert row["publication_status"] is None and detail["publication_status"] is None
    if fault in {"receipt", "receipt-revision", "snapshot"}:
        assert row["report_identity"] is None
    assert row.get("research_identity") is None


@pytest.mark.parametrize("status,explicit,expected", [("accepted", False, False), ("observe", True, False)])
def test_explicit_permission_cannot_override_restrictions(registered_gold, status, explicit, expected):
    env = registered_gold
    report_id = env["register"](status)
    with env["factory"]() as db:
        row = db.get(ReportItem, report_id)
        row.report_metadata = {**row.report_metadata, "publish_allowed": explicit}
        db.commit()
    views = read_views(env, report_id, case=f"explicit-{status}")
    assert index_row(views, report_id)["publish_allowed"] is expected
    assert views["detail"]["publish_allowed"] is expected


@pytest.mark.parametrize("purge", ["report", "artifact"])
def test_purged_gold_never_reappears_in_index_dates_or_detail(registered_gold, purge):
    env = registered_gold
    report_id = env["register"]()
    with env["factory"]() as db:
        if purge == "report":
            db.get(ReportItem, report_id).lifecycle_status = "purged"
        else:
            db.query(ReportArtifact).filter_by(report_id=report_id).first().status = "purged"
        db.commit()
    views = read_views(env, report_id, case=f"purged-{purge}")
    assert not any(row["report_id"] == report_id for row in views["index"]["reports"])
    assert views["dates"]["dates"] == []
    assert views["detail_status"] == 404


def test_same_day_distinct_runs_keep_their_own_receipts_and_latest_run(registered_gold):
    env = registered_gold
    first = env["register"]("accepted", "gold-contract-a")
    second = env["register"]("observe", "gold-contract-b")
    with env["factory"]() as db:
        for report_id, minute in [(first, 1), (second, 2)]:
            for artifact in db.query(ReportArtifact).filter_by(report_id=report_id):
                artifact.generated_at = datetime(2025, 1, 21, 22, minute, tzinfo=timezone.utc)
        db.commit()
    views = read_views(env, second, case="same-day-runs")
    rows = [row for row in views["index"]["reports"] if row["type"] == "gold_policy_daily"]
    assert [row["report_id"] for row in rows] == [second, first]
    assert rows[0]["publish_allowed"] is False and rows[1]["publish_allowed"] is True
    assert rows[0]["report_identity"]["canonical_receipt_id"] != rows[1]["report_identity"]["canonical_receipt_id"]
    assert views["dates"]["dates"][0]["latest_run_id"] == "gold-contract-b"
    assert views["detail"]["report_identity"] == rows[0]["report_identity"]


def test_registry_only_gold_date_has_its_own_module(registered_gold):
    env = registered_gold
    report_id = env["register"]()
    views = read_views(env, report_id, case="registry-only-dates")
    assert views["dates"]["total_dates"] == 1
    assert views["dates"]["dates"][0]["modules"] == ["gold_policy_daily"]
    assert views["dates"]["dates"][0]["has_final_report"] is False


def test_gold_date_mixes_with_legacy_modules_without_impersonating_final(registered_gold):
    env = registered_gold
    report_id = env["register"]()
    snapshot = env["root"] / "storage/features/snapshots/XAUUSD/2025-01-21/macro-run/premarket_snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(json.dumps({"macro": {"status": "available"}}))
    old_time = datetime(2025, 1, 20, tzinfo=timezone.utc).timestamp()
    os.utime(snapshot, (old_time, old_time))
    views = read_views(env, report_id, case="mixed-dates")
    date = views["dates"]["dates"][0]
    assert date["modules"] == ["gold_policy_daily", "macro"]
    assert date["latest_run_id"] == "gold-contract-a"
    assert date["has_final_report"] is False
    with env["factory"]() as db:
        db.query(ReportArtifact).filter_by(report_id=report_id).delete()
        db.commit()
    unavailable = read_views(env, report_id, case="unavailable-dates")
    assert not any(row["report_id"] == report_id for row in unavailable["index"]["reports"])
    assert unavailable["detail"]["data_status"] == "unavailable"
    assert unavailable["detail"]["publish_allowed"] is None
    assert unavailable["dates"]["dates"][0]["modules"] == ["macro"]


@pytest.mark.parametrize("binding", ["matching", "row-run", "payload-run", "payload-snapshot", "payload-date"])
def test_research_identity_requires_the_exact_registered_snapshot(registered_gold, binding):
    import hashlib

    env = registered_gold
    report_id = env["register"]()
    with env["factory"]() as db:
        item = db.get(ReportItem, report_id)
        payload = {
            "snapshot_id": item.snapshot_id,
            "run_id": item.run_id,
            "trade_date": item.trade_date.isoformat(),
            "snapshot_time": "2025-01-21T21:00:00Z",
        }
        if binding == "payload-run":
            payload["run_id"] = "another-run"
        elif binding == "payload-snapshot":
            payload["snapshot_id"] = "another-snapshot"
        elif binding == "payload-date":
            payload["trade_date"] = "2025-01-22"
        raw = json.dumps(payload).encode()
        artifact = env["root"] / "storage/features/contract-snapshot.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(raw)
        db.add(
            AnalysisSnapshot(
                snapshot_id=item.snapshot_id,
                asset="XAUUSD",
                trade_date=item.trade_date,
                run_id="another-run" if binding == "row-run" else item.run_id,
                payload=payload,
                payload_sha256=hashlib.sha256(raw).hexdigest(),
                artifact_path=str(artifact),
            )
        )
        db.commit()
    views = read_views(env, report_id, case=f"research-{binding}")
    row, detail = index_row(views, report_id), views["detail"]
    if binding == "matching":
        assert row["research_identity"] == detail["research_identity"]
        assert row["research_identity"]["data_as_of"] == "2025-01-21T21:00:00+00:00"
        for key in ("report_id", "run_id", "snapshot_id", "trade_date"):
            assert row["research_identity"][key] == row[key]
    else:
        assert row.get("research_identity") is None
        assert detail["research_identity"]["data_as_of"] is None
