from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.services import dashboard_research_service as service
from database.models.analysis import AgentOutput, AnalysisBase, AnalysisSnapshot
from database.models.report import ReportArtifact, ReportBase, ReportItem
from database.models.task import Base, TaskRun, TaskStatus


@pytest.fixture
def research_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    for base in (Base, AnalysisBase, ReportBase):
        base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(service, "_try_db_session", factory)
    monkeypatch.setattr(service, "_PROJECT_ROOT", tmp_path)

    def add(run_id, hour, *, value=2.68, broken=False, narrative="研究叙述", section_id="model_research"):
        sid = f"XAUUSD:2026-09-17:{run_id}"
        path = tmp_path / "storage" / run_id
        path.mkdir(parents=True)
        payload = {"run_id": run_id, "snapshot_id": sid, "snapshot_time": f"2026-09-17T{hour:02d}:00:00Z",
                   "macro": {"data": {"as_of": "2026-09-17", "indicators": {"REAL10Y": {"value": value}}}},
                   "options": {"data": {"trade_date": "2026-09-17", "parameters": {"f_value": 3700},
                                          "data_source": {"status": "PRELIM"}}},
                   "source_refs": [{"source": "FRED", "symbol": "REAL10Y"}],
                   "gold_workflow": {"state": {"accepted_state": "S5", "candidate_state": "S4", "transition_status": "PENDING"}}}
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        snapshot_path = path / "snapshot.json"
        snapshot_path.write_bytes(encoded)
        report_path = path / "report.json"
        report_bytes = json.dumps({"version": {"run_id": run_id, "snapshot_id": sid, "trade_date": "2026-09-17",
                                   "source_agent_outputs": [{"status": "success", "research_synthesis_status": "success"}]},
                                   "sections": [{"section_id": section_id, "body": narrative}]}).encode()
        report_path.write_bytes(report_bytes)
        with factory() as db:
            db.add(TaskRun(id=UUID(run_id), name="premarket", task_type="premarket", status=TaskStatus.success,
                           snapshot_id=sid, trade_date="2026-09-17"))
            db.add(AnalysisSnapshot(snapshot_id=sid, run_id=run_id, asset="XAUUSD", trade_date=date(2026, 9, 17),
                                    status="success", payload=payload, payload_sha256=hashlib.sha256(encoded).hexdigest(),
                                    artifact_path=str(snapshot_path)))
            report = ReportItem(report_id=run_id, family="observation_report_markdown", title="research", asset="XAUUSD",
                                trade_date=date(2026, 9, 17), run_id=run_id, snapshot_id=sid,
                                created_at=datetime(2026, 9, 17, hour, tzinfo=UTC))
            report.artifacts.append(ReportArtifact(artifact_id=run_id, artifact_type="structured_json",
                                                   file_path=str(report_path), sha256=hashlib.sha256(report_bytes).hexdigest(),
                                                   artifact_metadata={"run_id": run_id, "snapshot_id": sid}))
            db.add(report)
            db.commit()
        if broken:
            report_path.write_text("{}")
        return snapshot_path

    yield add, factory
    engine.dispose()


def test_latest_research_uses_creation_time_not_uuid_and_preserves_state(research_store):
    add, factory = research_store
    add("ffffffff-ffff-ffff-ffff-ffffffffffff", 9, value=2.41)
    add("00000000-0000-0000-0000-00000000000a", 10)
    result = service.get_dashboard_research_context()
    assert result["status"] == "available"
    assert result["macro"]["indicators"]["REAL10Y"]["value"] == 2.68
    assert result["authority"] == "observation_only" and result["publish_allowed"] is False
    assert result["state"] == {"accepted_state": "S5", "candidate_state": "S4", "transition_status": "PENDING"}
    with factory() as db:
        snapshot = db.query(AnalysisSnapshot).filter_by(run_id=result["run_id"]).one()
        assert snapshot.payload["gold_workflow"]["state"]["accepted_state"] == "S5"


def test_corrupt_latest_report_does_not_fall_back_to_old_research(research_store):
    add, _ = research_store
    add("ffffffff-ffff-ffff-ffff-ffffffffffff", 9)
    add("00000000-0000-0000-0000-00000000000a", 10, broken=True)
    result = service.get_dashboard_research_context()
    assert result["status"] == "unavailable"
    assert result["run_id"] == "00000000-0000-0000-0000-00000000000a"
    assert "macro" not in result
    assert "options" not in result
    assert result.get("facts_status") != "available"
    assert "summary" not in result
    assert "final_trade_plan" not in result


@pytest.mark.parametrize("blocked,broken_report", [(True, False), (False, False), (True, True)])
def test_newer_snapshot_keeps_current_unavailable_and_history_requires_explicit_verified_read(research_store, blocked, broken_report):
    add, factory = research_store
    old_id, new_id = "ffffffff-ffff-ffff-ffff-ffffffffffff", "00000000-0000-0000-0000-00000000000a"
    add(old_id, 9, broken=broken_report)
    with factory() as db:
        old_snapshot = db.query(AnalysisSnapshot).filter_by(run_id=old_id).one()
        old_snapshot.created_at = datetime(2026, 9, 17, 9, tzinfo=UTC)
        db.add(AnalysisSnapshot(snapshot_id="newer-engineering-snapshot", run_id=new_id,
                               asset="XAUUSD", trade_date=date(2026, 9, 17), status="blocked" if blocked else "success",
                               payload={"input_validation": {"can_analyze": not blocked}},
                               payload_sha256="engineering", artifact_path="unread-new-snapshot.json",
                               created_at=datetime(2026, 9, 17, 11, tzinfo=UTC)))
        db.commit()
    ordinary = service.get_dashboard_research_context()
    assert ordinary["status"] == "unavailable" and ordinary["run_id"] == new_id
    assert "historical_research" not in ordinary
    reading = service.get_dashboard_research_context(include_historical=True)
    assert reading["status"] == "unavailable" and reading["run_id"] == new_id
    assert "summary" not in reading and "final_trade_plan" not in reading
    if broken_report:
        assert "historical_research" not in reading
    else:
        historical = reading["historical_research"]
        assert historical["historical_only"] is True and historical["run_id"] == old_id
        assert historical["final_trade_plan"]["execution_ready"] is False


@pytest.mark.parametrize("section_id", ["model_research", "research_judgment"])
def test_complete_verified_body_preserves_markdown_evidence_and_observation_authority(research_store, section_id):
    add, factory = research_store
    run_id = "00000000-0000-0000-0000-00000000000a"
    body = ("\n# 黄金研究｜2026-09-17\n\n当前判断：观察中。\n\n以下链条支持黄金：\n\n"
            + "证据段落：实际利率与美元需同窗口验证。\n\n" * 350
            + "## 中间证据\n\n官方 Treasury，2026-09-17：[来源](https://treasury.test/real-yields)。\n\n"
            + "反证段落：利率抬升仍可能抵消避险支持。\n\n" * 100
            + "## 事件开关与末尾风险\n\n政策事件后重新核验；本报告不授予发布资格或策略权限。\n")
    assert len(body) > 6000
    add(run_id, 10, narrative=body, section_id=section_id)
    with factory() as db:
        snapshot = db.query(AnalysisSnapshot).filter_by(run_id=run_id).one()
        original_payload = snapshot.payload
        original_hash = snapshot.payload_sha256
        report = db.get(ReportItem, run_id)
        original_record_status = (report.data_status, report.lifecycle_status)
        db.add(AgentOutput(snapshot_id=snapshot.snapshot_id, asset="XAUUSD", trade_date=date(2026, 9, 17),
                           run_id=run_id, agent_name="coordinator_agent", module="test", status="success",
                           bias="neutral", confidence=0.5, summary="可变摘要不能替代归档正文",
                           payload={"summary": "可变摘要不能替代归档正文"}, payload_sha256="test-only"))
        db.commit()
    result = service.get_dashboard_research_context()
    assert result["status"] == "available"
    assert result["summary"] == body
    assert result["final_trade_plan"]["report_id"] == run_id
    assert result["final_trade_plan"]["snapshot_id"] == result["snapshot_id"]
    assert result["final_trade_plan"]["execution_ready"] is False
    assert "## 中间证据" in result["summary"]
    assert "[来源](https://treasury.test/real-yields)" in result["summary"]
    assert result["summary"].endswith("本报告不授予发布资格或策略权限。\n")
    assert result["authority"] == "observation_only"
    assert result["publish_allowed"] is False
    assert result["state"] == {"accepted_state": "S5", "candidate_state": "S4", "transition_status": "PENDING"}
    with factory() as db:
        snapshot = db.query(AnalysisSnapshot).filter_by(run_id=run_id).one()
        assert snapshot.payload == original_payload
        assert snapshot.payload_sha256 == original_hash
        assert db.get(TaskRun, UUID(run_id)).status == TaskStatus.success
        report = db.get(ReportItem, run_id)
        assert (report.data_status, report.lifecycle_status) == original_record_status


def test_snapshot_payload_tampering_is_rejected(research_store):
    add, _ = research_store
    path = add("00000000-0000-0000-0000-00000000000a", 10)
    data = json.loads(path.read_text())
    data["macro"]["data"]["indicators"]["REAL10Y"]["value"] = 99
    path.write_text(json.dumps(data))
    result = service.get_dashboard_research_context()
    assert result["status"] == "unavailable"
    assert result["reason"] == "research_identity_or_artifact_unverified"


@pytest.mark.parametrize('unavailable', [True, False, 'stale', 'mock', 'fallback', 'manual_required'])
def test_latest_failed_or_unverified_legacy_research_does_not_inherit_authority(research_store, unavailable):
    add, factory = research_store
    add('ffffffff-ffff-ffff-ffff-ffffffffffff', 9)
    run_id = '00000000-0000-0000-0000-00000000000a'
    add(run_id, 10, narrative='旧缓存/规则回退文本')
    with factory() as db:
        if unavailable:
            db.get(ReportItem, run_id).data_status = 'unavailable' if unavailable is True else unavailable
        else:
            artifact = db.get(ReportArtifact, run_id)
            path = service.Path(artifact.file_path)
            report = json.loads(path.read_text())
            report['version'].pop('source_agent_outputs')
            content = json.dumps(report).encode()
            path.write_bytes(content)
            artifact.sha256 = hashlib.sha256(content).hexdigest()
        db.commit()
    result = service.get_dashboard_research_context()
    assert result['status'] == 'unavailable'
    assert result['run_id'] == run_id
    assert result.get('facts_status') != 'available'


@pytest.mark.parametrize("body", [None, "", "   ", "\n \t\n", "## 结论", "# 研究\n## 证据\n### 风险",
                                 "# 研究\n\n## 证据\n\n### 风险\n", "研究标题\n====", {"summary": "not prose"}])
def test_missing_model_narrative_cannot_display_rule_fallback_as_research(research_store, body):
    from pathlib import Path

    add, factory = research_store
    run_id = "00000000-0000-0000-0000-00000000000a"
    add(run_id, 10)
    with factory() as db:
        artifact = db.get(ReportArtifact, run_id)
        path = Path(artifact.file_path)
        content = json.loads(path.read_text())
        content["sections"] = [{"section_id": "rule_fallback", "body": "only a data table"}]
        if body is not None:
            content["sections"].append({"section_id": "model_research", "body": body})
        encoded = json.dumps(content).encode()
        path.write_bytes(encoded)
        artifact.sha256 = hashlib.sha256(encoded).hexdigest()
        db.commit()
    result = service.get_dashboard_research_context()
    assert result["status"] == "unavailable"
    assert result["reason"] == "research_narrative_unavailable"
    assert result["report_id"] == run_id
    assert result["trade_date"] == "2026-09-17"
    assert result["publish_allowed"] is False
    assert result["facts_status"] == "available"
    assert result["macro"]["indicators"]["REAL10Y"]["value"] == 2.68
    assert result["options"]["parameters"]["f_value"] == 3700
    assert result["source_refs"] == [{"source": "FRED", "symbol": "REAL10Y"}]
    assert "bias" not in result and "state" not in result
    assert "summary" not in result
    assert "final_trade_plan" not in result


@pytest.fixture
def historical_detail_service(research_store, monkeypatch, tmp_path):
    from apps.api.services import report_service

    monkeypatch.setattr(report_service._storage, "_PROJECT_ROOT", tmp_path)
    # Isolate unrelated enrichments from runtime stores; retain the actual
    # registered-detail builder, authority gates and verified projection.
    for name in ("_enrich_report_detail_with_lineage_warnings", "_enrich_report_detail_with_llm_audits"):
        monkeypatch.setattr(report_service._detail, name, lambda db, detail: detail)
    for name in ("_enrich_macro_report_lineage", "_enrich_report_detail_with_market_odds",
                 "_enrich_report_detail_with_gold_macro_context", "_with_result_identity"):
        monkeypatch.setattr(report_service._detail, name, lambda detail: detail)
    return report_service


def test_historical_detail_projects_requested_registration_and_preserves_archive(research_store, historical_detail_service):
    add, factory = research_store
    old = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    new = "00000000-0000-0000-0000-00000000000a"
    body = ("## 一句话结论\n\n旧报告等待确认；保留完整段落。\n\n"
            "| 路径 | 宏观条件 | 价格条件 | 失效条件 |\n|---|---|---|---|\n"
            "| 上涨 | 利率回落 | 站稳 3721.25 | 跌回 3721.25 |")
    path = add(old, 9, narrative=body)
    add(new, 10, narrative="## 一句话结论\n\n新报告。")
    report_path = path.parent / "report.json"
    before = report_path.read_bytes()
    with factory() as db:
        detail = historical_detail_service.get_report_detail(db, old)
        plan = detail.structured_payload["_reader_trade_plan"]
        assert plan["report_id"] == old and plan["run_id"] == old
        assert plan["snapshot_id"] == db.get(ReportItem, old).snapshot_id
        assert plan["as_of"] == "2026-09-17T09:00:00Z"
        assert plan["summary"] == "旧报告等待确认；保留完整段落。"
        assert plan["scenarios"][0]["price_conditions"] == "站稳 3721.25"
        assert detail.structured_payload["sections"][0]["body"] == body
        assert plan["execution_ready"] is False and plan["status"] == "waiting"
    assert report_path.read_bytes() == before
    assert "_reader_trade_plan" not in json.loads(before)


@pytest.mark.parametrize("failure", ["hash", "identity", "quality", "body", "run", "snapshot"])
def test_historical_detail_excludes_unverified_plan(research_store, historical_detail_service, failure):
    from pathlib import Path

    add, factory = research_store
    old = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    add(old, 9, narrative="## 一句话结论\n\n旧报告。")
    add("00000000-0000-0000-0000-00000000000a", 10, narrative="## 一句话结论\n\n新报告。")
    with factory() as db:
        artifact = db.get(ReportArtifact, old)
        path = Path(artifact.file_path)
        content = json.loads(path.read_text())
        # Even an archived reader field cannot bypass validation.
        content["_reader_trade_plan"] = {"report_id": "leaked", "execution_ready": True}
        if failure == "identity":
            content["version"]["run_id"] = "different-run"
        elif failure == "quality":
            content["version"]["source_agent_outputs"][0]["research_synthesis_status"] = "rule_fallback"
        elif failure == "body":
            content["sections"][0]["body"] = ""
        elif failure == "run":
            db.get(TaskRun, UUID(old)).status = TaskStatus.failed
        elif failure == "snapshot":
            db.get(TaskRun, UUID(old)).snapshot_id = "different-snapshot"
        encoded = json.dumps(content).encode()
        path.write_bytes(encoded)
        if failure != "hash":
            artifact.sha256 = hashlib.sha256(encoded).hexdigest()
        db.commit()
        detail = historical_detail_service.get_report_detail(db, old)
        assert "_reader_trade_plan" not in detail.structured_payload
        assert path.read_bytes() == encoded


def test_optional_projection_failure_does_not_mask_other_detail_errors(research_store, historical_detail_service, monkeypatch):
    add, factory = research_store
    run_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    add(run_id, 9)

    def fail(*args):
        raise RuntimeError("isolated failure")

    monkeypatch.setattr(service, "_project_report", fail)
    with factory() as db:
        detail = historical_detail_service.get_report_detail(db, run_id)
        assert "_reader_trade_plan" not in detail.structured_payload
        monkeypatch.setattr(historical_detail_service._detail, "_enrich_report_detail_with_market_odds", fail)
        with pytest.raises(RuntimeError, match="isolated failure"):
            historical_detail_service.get_report_detail(db, run_id)


def test_other_report_family_cannot_supply_archived_reader_plan(research_store, historical_detail_service, monkeypatch):
    from pathlib import Path

    add, factory = research_store
    run_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    add(run_id, 9)
    monkeypatch.setattr(service, "_project_report", lambda *args: pytest.fail("must only project registered observation reports"))
    with factory() as db:
        db.get(ReportItem, run_id).family = "macro"
        artifact = db.get(ReportArtifact, run_id)
        path = Path(artifact.file_path)
        content = json.loads(path.read_text())
        content["_reader_trade_plan"] = {"execution_ready": True}
        encoded = json.dumps(content).encode()
        path.write_bytes(encoded)
        artifact.sha256 = hashlib.sha256(encoded).hexdigest()
        db.commit()
        detail = historical_detail_service.get_report_detail(db, run_id)
        assert "_reader_trade_plan" not in detail.structured_payload
        assert path.read_bytes() == encoded


def test_research_path_cannot_escape_storage(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    with pytest.raises(ValueError, match="outside storage"):
        service._read_registered_json(str(outside), tmp_path)


def test_hash_valid_but_cross_run_report_is_rejected(research_store):
    add, factory = research_store
    run_id = "00000000-0000-0000-0000-00000000000a"
    add(run_id, 10)
    with factory() as db:
        artifact = db.get(ReportArtifact, run_id)
        from pathlib import Path
        path = Path(artifact.file_path)
        content = json.loads(path.read_text())
        content["version"]["run_id"] = "wrong-run"
        data = json.dumps(content).encode()
        path.write_bytes(data)
        artifact.sha256 = hashlib.sha256(data).hexdigest()
        db.commit()
    assert service.get_dashboard_research_context()["status"] == "unavailable"


def test_latest_registration_without_artifacts_does_not_read_old_report(research_store):
    add, factory = research_store
    add("ffffffff-ffff-ffff-ffff-ffffffffffff", 9)
    new_id = "00000000-0000-0000-0000-00000000000a"
    add(new_id, 10)
    with factory() as db:
        report = db.get(ReportItem, new_id)
        report.artifacts.clear()
        db.commit()
    result = service.get_dashboard_research_context()
    assert result["status"] == "unavailable"
    assert result["run_id"] == new_id


def test_database_unavailable_is_distinct_from_no_research(monkeypatch):
    monkeypatch.setattr(service, "_try_db_session", lambda: None)
    assert service.get_dashboard_research_context() == {
        "status": "unavailable", "reason": "research_database_unavailable"}


def test_latest_blocked_snapshot_without_report_does_not_fall_back(research_store):
    add, factory = research_store
    add("ffffffff-ffff-ffff-ffff-ffffffffffff", 9)
    new_id = "00000000-0000-0000-0000-00000000000b"
    payload = {"run_id": new_id, "snapshot_id": "blocked-new-snapshot", "snapshot_time": "2026-09-17T11:00:00Z",
               "input_validation": {"schema_version": "analysis_input_validation.v1", "status": "blocked", "can_analyze": False,
                                    "reason_codes": ["no_trusted_current_spot_observation"]}}
    with factory() as db:
        db.add(AnalysisSnapshot(snapshot_id=payload["snapshot_id"], run_id=new_id, asset="XAUUSD", trade_date=date(2026, 9, 17),
            status="blocked", payload=payload, payload_sha256="test-only", artifact_path="diagnostic/unused.json"))
        db.commit()
    result = service.get_dashboard_research_context()
    assert result["status"] == "unavailable"
    assert result["run_id"] == new_id
    assert result["reason"] == "input_validation_blocked"
    assert result["reason_codes"] == ["no_trusted_current_spot_observation"]
    assert "summary" not in result and "macro" not in result


def test_hash_verified_rule_fallback_narrative_is_not_complete_research(research_store):
    from pathlib import Path
    add, factory = research_store
    run_id = "00000000-0000-0000-0000-00000000000b"
    add(run_id, 10)
    with factory() as db:
        artifact = db.get(ReportArtifact, run_id)
        path = Path(artifact.file_path)
        content = json.loads(path.read_text())
        content["version"]["source_agent_outputs"] = [{"agent_name": "coordinator_agent", "research_synthesis_status": "rule_fallback"}]
        encoded = json.dumps(content).encode()
        path.write_bytes(encoded)
        artifact.sha256 = hashlib.sha256(encoded).hexdigest()
        db.commit()
    result = service.get_dashboard_research_context()
    assert result["status"] == "unavailable"
    assert result["reason"] == "research_generation_failed"
    assert "summary" not in result
