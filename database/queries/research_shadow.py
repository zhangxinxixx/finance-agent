"""Verify registered research artifacts before counting live Shadow sessions."""

from hashlib import sha256
import json
from pathlib import Path
import uuid

from sqlalchemy import select

from apps.analysis.research_shadow import evaluate_shadow_readiness
from apps.features.research.state import payload_hash
from database.models.analysis import AgentOutput, AnalysisSnapshot, LLMCallAudit
from database.models.execution import RunArtifact
from database.models.task import TaskRun
from database.queries.market_state import _storage_path
from database.queries.analysis import _sha256_hex


def shadow_readiness(db, *, storage_root):
    root = Path(storage_root).resolve()
    artifacts = db.scalars(select(RunArtifact).where(RunArtifact.file_path.endswith("/production_shadow_record.v1.json")).order_by(RunArtifact.created_at.desc()).limit(2000)).all()
    verified, errors = [], []
    for artifact in artifacts:
        try:
            path = _storage_path(artifact.file_path, root)
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != artifact.sha256:
                raise ValueError("shadow record file hash mismatch")
            record = json.loads(raw)
            run = db.get(TaskRun, uuid.UUID(str(artifact.run_id)))
            source = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == record["snapshot_id"]))
            if (run is None or record["run_id"] != str(run.id) or source is None or source.run_id != str(run.id)
                    or run.name != "premarket" or run.task_type != "premarket" or run.snapshot_id != source.snapshot_id
                    or source.asset != "XAUUSD" or source.payload.get("asset") != source.asset
                    or source.trade_date.isoformat() != source.payload["trade_date"]):
                raise ValueError("shadow record lineage mismatch")
            expected = root/"analysis"/"gold_mainlines"/record["trade_date"]/str(run.id)/"production_shadow_record.v1.json"
            if path.resolve() != expected.resolve() or payload_hash(source.payload) != record["source_snapshot_sha256"]:
                raise ValueError("shadow record input mismatch")
            flow = source.payload["gold_workflow"]
            if (record["trade_date"] != run.trade_date or record["trade_date"] != source.payload["trade_date"]
                    or record["analysis_time"] != source.payload["snapshot_time"]
                    or record["session_quality"] != flow["report_session_quality"]
                    or record["state_record"] != flow["state_record"]
                    or record["versions"] != source.payload["research_versions"]
                    or record["source_health"] != flow["core_source_health"]
                    or _sha256_hex(source.payload) != source.payload_sha256):
                raise ValueError("shadow record projection mismatch")
            source_path = _storage_path(source.artifact_path, root)
            if json.loads(source_path.read_text()) != source.payload:
                raise ValueError("shadow source artifact mismatch")
            versions = record["versions"]
            version_path = _storage_path(versions["artifact_ref"],root)
            if sha256(version_path.read_bytes()).hexdigest() != versions["sha256"]:
                raise ValueError("version manifest hash mismatch")
            manifest = json.loads(version_path.read_text())
            if payload_hash(manifest) != versions["manifest_id"]:
                raise ValueError("version manifest identity mismatch")
            for item in manifest["files"].values():
                blob = _storage_path(item["artifact_ref"], root)
                if sha256(blob.read_bytes()).hexdigest() != item["sha256"]:
                    raise ValueError("version source blob hash mismatch")
            model = record["model"]
            agent = db.scalar(select(AgentOutput).where(AgentOutput.run_id == str(run.id), AgentOutput.snapshot_id == source.snapshot_id,
                                                       AgentOutput.agent_name == model["agent_name"], AgentOutput.module == model["module"], AgentOutput.version == model["version"]))
            if agent is None or _sha256_hex(agent.payload) != agent.payload_sha256:
                raise ValueError("recorded model output missing or hash mismatch")
            synthesis = (agent.payload.get("input_payload") or {}).get("research_synthesis", {})
            # The registered input determines the contract, including old records
            # without a projected report version or self-declared quality fields.
            record["reader_report_version"] = flow.get("reader_report_version")
            quality_required = (record["reader_report_version"] == "gold_reader.v4"
                                or "research_quality_standard" in synthesis or bool(synthesis.get("quality_gate_version")))
            if quality_required and (synthesis.get("quality_eligible") is not True
                                     or synthesis.get("review_status") != "pass"
                                     or (synthesis.get("macro_review") or {}).get("status") != "pass"):
                raise ValueError("recorded research quality not eligible")
            raw_output = agent.payload.get("llm_raw_output") or ""
            prompt_messages = agent.payload.get("prompt_messages") or []
            provenance_complete = (
                synthesis.get("status") == "success"
                and synthesis.get("generated_by") == "llm"
                and all(
                    isinstance(value, str) and value.strip()
                    for value in (
                        synthesis.get("schema_version"),
                        synthesis.get("generated_by"),
                        agent.payload.get("llm_model"),
                        agent.payload.get("llm_provider"),
                        agent.payload.get("llm_audit_id"),
                    )
                )
                and isinstance(prompt_messages, list)
                and bool(prompt_messages)
                and isinstance(raw_output, str)
                and bool(raw_output.strip())
            )
            if (agent.asset != source.asset or agent.trade_date != source.trade_date
                    or agent.payload.get("agent_name") != model["agent_name"] or agent.payload.get("module") != model["module"]
                    or agent.payload.get("version") != model["version"]
                    or agent.payload.get("snapshot_id") != source.snapshot_id
                    or agent.payload.get("llm_provider") != model["provider"]
                    or synthesis.get("schema_version") != model["schema_version"] or synthesis.get("status") != model["status"]
                    or (agent.payload.get("llm_raw_output") is not None and not isinstance(agent.payload["llm_raw_output"], str))):
                raise ValueError("recorded model projection mismatch")
            if ("generated_by" in model and synthesis.get("generated_by") != model["generated_by"]
                    or "provenance_complete" in model and provenance_complete is not model["provenance_complete"]
                    or "payload_sha256" in model and _sha256_hex(agent.payload) != model["payload_sha256"]):
                raise ValueError("recorded model completeness mismatch")
            if (payload_hash(agent.payload.get("prompt_messages") or []) != model["prompt_sha256"]
                    or sha256((agent.payload.get("llm_raw_output") or "").encode()).hexdigest() != model["response_sha256"]
                    or agent.payload.get("llm_model") != model["llm_model"]
                    or agent.payload.get("llm_audit_id") != model["audit_id"]):
                raise ValueError("recorded model provenance mismatch")
            if provenance_complete:
                audit = db.get(LLMCallAudit, model["audit_id"])
                if (audit is None or audit.status != "success" or audit.caller != "research_synthesis.enrich_research_coordinator"
                        or audit.run_id != str(run.id) or audit.snapshot_id != source.snapshot_id
                        or audit.provider_resolved != model["provider"] or audit.model_resolved != model["llm_model"]
                        or audit.response_sha256 != model["response_sha256"]):
                    raise ValueError("recorded model audit mismatch")
            report_output = record.get("report_output")
            if report_output:
                selected = db.scalar(select(AgentOutput).where(
                    AgentOutput.run_id == str(run.id), AgentOutput.snapshot_id == source.snapshot_id,
                    AgentOutput.agent_name == report_output["agent_name"],
                    AgentOutput.module == report_output["module"], AgentOutput.version == report_output["version"],
                ))
                selected_synthesis = ((selected.payload.get("input_payload") or {}).get("research_synthesis", {}) if selected is not None else {})
                expected_kind = (
                    "model_coordinator"
                    if selected is not None and selected.agent_name == model["agent_name"] and selected.module == model["module"]
                    else "deterministic_safe_fallback"
                )
                if (selected is None or _sha256_hex(selected.payload) != selected.payload_sha256
                        or _sha256_hex(selected.payload) != report_output["payload_sha256"]
                        or selected.status != report_output["agent_status"]
                        or expected_kind != report_output["selection_kind"]
                        or selected_synthesis.get("status") != report_output["synthesis_status"]
                        or selected_synthesis.get("generated_by") != report_output["synthesis_generated_by"]):
                    raise ValueError("recorded report output mismatch")
            record.update(task_status=run.status.value, artifacts_verified=True)
            verified.append(record)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append({"run_id":str(artifact.run_id),"reason":str(exc)})
    return {**evaluate_shadow_readiness(verified),"registered_records":len(artifacts),"artifact_errors":errors}
