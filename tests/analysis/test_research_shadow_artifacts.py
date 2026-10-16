from datetime import UTC, date, datetime
from hashlib import sha256
import json
from types import SimpleNamespace
import uuid

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.analysis.research_shadow import SKILLS, archive_research_versions, build_shadow_record
from database.models.analysis import AgentOutput, AnalysisSnapshot, LLMCallAudit, ensure_analysis_tables
from database.models.execution import RunArtifact
from database.models.task import TaskRun, TaskStatus
from database.queries.analysis import _sha256_hex
from database.queries.research_shadow import shadow_readiness


@pytest.mark.parametrize('quality_case', ['legacy', 'v4_pass', 'v4_stripped'])
def test_registered_shadow_requires_exact_source_model_and_version_blobs(tmp_path, quality_case):
    repo, storage = tmp_path / "repo", tmp_path / "storage"
    for name in SKILLS:
        path = repo / ".agents" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(name)
    versions = archive_research_versions(storage, repo_root=repo)
    engine = create_engine("sqlite://")
    ensure_analysis_tables(engine)
    TaskRun.__table__.create(engine)
    RunArtifact.__table__.create(engine)
    run_id = uuid.uuid4()
    now = datetime(2026, 9, 8, 8, tzinfo=UTC)
    flow = {"state_record": {"candidate_state": "S4"}, "report_session_quality": {"session_type": "NORMAL"},
            "quality_gate": {}, "core_source_health": {}, "scenario_engine": {}}
    snapshot = {"asset": "XAUUSD", "run_id": str(run_id), "snapshot_id": "test-shadow", "trade_date": "2026-09-08",
                "snapshot_time": now.isoformat(), "gold_workflow": flow, "research_versions": versions}
    agent_payload = {"agent_name": "coordinator_agent", "module": "coordinator", "version": "1.0", "status": "success", "snapshot_id": snapshot["snapshot_id"], "input_payload": {"research_synthesis": {"schema_version": "research_synthesis.v2", "status": "success", "generated_by": "llm"}},
                     "llm_model": "recorded-test", "llm_provider": "fixture", "llm_audit_id": "fixture",
                     "prompt_messages": [{"role": "user", "content": "recorded input"}], "llm_raw_output": "recorded output"}
    if quality_case.startswith('v4'):
        flow['reader_report_version'] = 'gold_reader.v4'
    if quality_case == 'v4_pass':
        agent_payload['input_payload']['research_synthesis'].update(
            research_quality_standard={'version': 'synthetic-fixture'}, quality_gate_version='research_quality_gate.v1',
            generation_status='success', review_status='pass', quality_eligible=True, macro_review={'status': 'pass'})
    record = build_shadow_record(snapshot, SimpleNamespace(**agent_payload), created_at=now)
    if quality_case == 'v4_stripped':
        # Simulate an old record format: the DB must recover the v4 contract
        # from the registered input, never from model/record self-declarations.
        record.pop('reader_report_version', None)
    record_path = storage / "analysis" / "gold_mainlines" / "2026-09-08" / str(run_id) / "production_shadow_record.v1.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps(record))
    source_path = storage / "source.json"
    source_path.write_text(json.dumps(snapshot))
    with Session(engine) as db:
        db.add(TaskRun(id=run_id, name="premarket", task_type="premarket", status=TaskStatus.success, trade_date="2026-09-08", snapshot_id=snapshot["snapshot_id"]))
        db.add(AnalysisSnapshot(snapshot_id=snapshot["snapshot_id"], asset="XAUUSD", trade_date=date(2026, 9, 8), run_id=str(run_id),
                                payload=snapshot, payload_sha256=_sha256_hex(snapshot), artifact_path=str(source_path)))
        db.add(AgentOutput(snapshot_id=snapshot["snapshot_id"], asset="XAUUSD", trade_date=date(2026, 9, 8), run_id=str(run_id),
                           agent_name="coordinator_agent", module="coordinator", status="success", bias="mixed", confidence=0.5,
                           payload=agent_payload, payload_sha256=_sha256_hex(agent_payload)))
        db.add(LLMCallAudit(
            id="fixture", call_id=str(uuid.uuid4()), status="success",
            caller="research_synthesis.enrich_research_coordinator",
            provider_resolved="fixture", model_resolved="recorded-test",
            request_config={}, request_messages=agent_payload["prompt_messages"],
            request_sha256="request-fixture",
            response_text=agent_payload["llm_raw_output"],
            response_sha256=sha256(agent_payload["llm_raw_output"].encode()).hexdigest(),
            usage={}, attempts=[], context={}, source_refs=[], run_id=str(run_id),
            snapshot_id=snapshot["snapshot_id"], trade_date=date(2026, 9, 8),
        ))
        artifact = RunArtifact(run_id=run_id, artifact_type="structured_json", file_path=str(record_path), sha256=sha256(record_path.read_bytes()).hexdigest())
        db.add(artifact)
        db.commit()
        if quality_case == 'v4_stripped':
            before = record_path.read_bytes()
            result = shadow_readiness(db, storage_root=storage)
            assert result['verified_trading_days'] == 0
            assert 'recorded research quality not eligible' in result['artifact_errors'][0]['reason']
            assert record_path.read_bytes() == before
            return
        assert shadow_readiness(db, storage_root=storage)["verified_trading_days"] == 1

        # Re-hashing a forged record is insufficient: it must match its input.
        record["session_quality"] = {"session_type": "HOLIDAY"}
        record_path.write_text(json.dumps(record))
        artifact.sha256 = sha256(record_path.read_bytes()).hexdigest()
        db.flush()
        result = shadow_readiness(db, storage_root=storage)
        assert result["verified_trading_days"] == 0
        assert "projection mismatch" in result["artifact_errors"][0]["reason"]

        record["session_quality"] = flow["report_session_quality"]
        record_path.write_text(json.dumps(record))
        artifact.sha256 = sha256(record_path.read_bytes()).hexdigest()
        db.flush()
        manifest = json.loads((storage / versions["artifact_ref"]).read_text())
        blob = storage / next(iter(manifest["files"].values()))["artifact_ref"]
        blob.write_text("corrupted")
        result = shadow_readiness(db, storage_root=storage)
        assert result["verified_trading_days"] == 0
        assert "blob hash mismatch" in result["artifact_errors"][0]["reason"]
