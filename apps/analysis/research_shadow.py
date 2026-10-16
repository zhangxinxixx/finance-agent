"""Reproducible research records and honest, evidence-based shadow counting."""

from datetime import UTC, date, datetime
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
from zoneinfo import ZoneInfo

from apps.features.research.state import payload_hash

SKILLS = ("gold-market-analysis", "macro-rates-analysis", "liquidity-analysis", "gold-flow-analysis", "cme-gold-options-analysis")


def _immutable(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("immutable provenance artifact conflict: " + str(path))


def archive_research_versions(storage_root, *, repo_root=None):
    """Capture actual working code and Skills, including uncommitted changes."""
    root = Path(repo_root or Path(__file__).resolve().parents[2])
    storage = Path(storage_root)
    files = []
    for folder in ("apps", "database", "dagster_finance"):
        for directory, children, names in os.walk(root / folder):
            children[:] = [name for name in children if name not in {"node_modules", ".venv", ".git", "dist", "build", "__pycache__", ".pytest_cache"}]
            files.extend(Path(directory) / name for name in names if Path(name).suffix in {".py", ".md"})
    files.extend(root/name for name in ("uv.lock", "pyproject.toml", ".python-version") if (root/name).is_file())
    quality_standard = root / "docs/evals/gold-research-quality-v1.md"
    if quality_standard.is_file():
        files.append(quality_standard)
    files.extend(root/".agents"/"skills"/name/"SKILL.md" for name in SKILLS)
    manifest = {}
    for path in sorted(set(files)):
        if not path.is_file():
            raise ValueError("required provenance file missing: " + str(path))
        data = path.read_bytes()
        digest = sha256(data).hexdigest()
        target = storage/"features"/"research_provenance"/"blobs"/digest
        _immutable(target, data)
        manifest[path.relative_to(root).as_posix()] = {"sha256": digest, "artifact_ref": target.relative_to(storage).as_posix()}
    packages = {}
    for name in ("pydantic", "pandas", "numpy", "scipy", "SQLAlchemy", "dagster"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not_installed"
    payload = {"schema_version": "research_versions.v1", "python": platform.python_version(), "packages": packages, "files": manifest,
               "skill_versions": {name: manifest[f".agents/skills/{name}/SKILL.md"]["sha256"] for name in SKILLS},
               "rule_version": "gold_research_state.v1", "workflow_version": "gold_workflow.v2+production_shadow.v1", "replay_mode": "frozen_inputs_and_recorded_model_output; new_model_generation_is_not_bit_reproducible"}
    digest = payload_hash(payload)
    target = storage/"features"/"research_provenance"/(digest+".json")
    _immutable(target, json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2).encode())
    return {"schema_version": payload["schema_version"], "manifest_id": digest, "artifact_ref": target.relative_to(storage).as_posix(), "sha256": sha256(target.read_bytes()).hexdigest(),
            "skill_versions": payload["skill_versions"], "rule_version": payload["rule_version"], "workflow_version": payload["workflow_version"], "replay_mode": payload["replay_mode"]}


def _attribute(output, name, default=None):
    return getattr(output, name, default)


def _json_payload_sha256(output):
    if hasattr(output, "model_dump"):
        payload = output.model_dump(mode="json")
    else:
        payload = vars(output)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return sha256(raw).hexdigest()


def _synthesis(output):
    payload = _attribute(output, "input_payload", {}) or {}
    return payload.get("research_synthesis", {}) if isinstance(payload, dict) else {}


def _model_record(coordinator):
    synthesis = _synthesis(coordinator)
    messages = _attribute(coordinator, "prompt_messages") or []
    raw_output = _attribute(coordinator, "llm_raw_output") or ""
    required_strings = (
        synthesis.get("schema_version"),
        synthesis.get("generated_by"),
        _attribute(coordinator, "llm_model"),
        _attribute(coordinator, "llm_provider"),
        _attribute(coordinator, "llm_audit_id"),
    )
    provenance_complete = (
        synthesis.get("generation_status", synthesis.get("status")) == "success"
        and synthesis.get("generated_by") == "llm"
        and all(isinstance(value, str) and value.strip() for value in required_strings)
        and isinstance(messages, list)
        and bool(messages)
        and isinstance(raw_output, str)
        and bool(raw_output.strip())
    )
    return {
        "agent_name": _attribute(coordinator, "agent_name"),
        "module": _attribute(coordinator, "module"),
        "version": _attribute(coordinator, "version"),
        "schema_version": synthesis.get("schema_version"),
        "status": synthesis.get("status"),
        **({'quality_review_required': True} if 'research_quality_standard' in synthesis else {}),
        **{key: synthesis[key] for key in ('generation_status', 'review_status', 'quality_eligible',
                                          'quality_gate_version') if key in synthesis},
        "generated_by": synthesis.get("generated_by"),
        "provenance_complete": provenance_complete,
        "llm_model": _attribute(coordinator, "llm_model"),
        "provider": _attribute(coordinator, "llm_provider"),
        "audit_id": _attribute(coordinator, "llm_audit_id"),
        "prompt_sha256": payload_hash(messages),
        "response_sha256": sha256(raw_output.encode()).hexdigest(),
        "payload_sha256": _json_payload_sha256(coordinator),
    }


def _report_output_record(output, *, model_coordinator):
    synthesis = _synthesis(output)
    is_model_output = (
        _attribute(output, "agent_name") == _attribute(model_coordinator, "agent_name")
        and _attribute(output, "module") == _attribute(model_coordinator, "module")
    )
    status = _attribute(output, "status")
    return {
        "agent_name": _attribute(output, "agent_name"),
        "module": _attribute(output, "module"),
        "version": _attribute(output, "version"),
        "agent_status": getattr(status, "value", status),
        "selection_kind": "model_coordinator" if is_model_output else "deterministic_safe_fallback",
        "synthesis_status": synthesis.get("status"),
        "synthesis_generated_by": synthesis.get("generated_by"),
        "payload_sha256": _json_payload_sha256(output),
    }


def build_shadow_record(snapshot, coordinator, *, created_at, report_output=None):
    flow = snapshot["gold_workflow"]
    selected_output = report_output or coordinator
    return {
        "schema_version": "gold_shadow_record.v1", "product": "Gold Research Agent v0.9 — Production Shadow",
        "run_id": snapshot["run_id"], "snapshot_id": snapshot["snapshot_id"], "analysis_time": snapshot["snapshot_time"],
        "recorded_at": created_at.isoformat(), "trade_date": snapshot["trade_date"], "run_mode": "live_shadow",
        "state_record": flow["state_record"], "versions": snapshot.get("research_versions", {}),
        "reader_report_version": flow.get("reader_report_version"),
        "model": _model_record(coordinator),
        "report_output": _report_output_record(selected_output, model_coordinator=coordinator),
        "source_snapshot_sha256": payload_hash(snapshot), "session_quality": flow.get("report_session_quality", {}),
        "data_quality": flow["quality_gate"], "source_health": flow.get("core_source_health", {}),
        "scenario_scores": flow["scenario_engine"], "event_observations": _verified_event_observations(snapshot),
        "event_coverage_status": "requires_verified_release_and_post_event_completed_report", "calibration_status": "uncalibrated",
        "automatic_trading_allowed": False,
    }


def _verified_event_observations(snapshot):
    """Only released official events with full timestamps, never future calendars."""
    events = snapshot.get("news", {}).get("data", {}).get("official_events", {}).get("data", {}).get("events", [])
    names = {"nfp_release":"NFP", "employment_situation":"NFP", "cpi_release":"CPI", "consumer_price_index":"CPI", "fomc_statement":"FOMC", "fomc_rate_decision":"FOMC"}
    result = []
    for item in events:
        kind = names.get(item.get("event_type") or item.get("title"))
        refs = [x for x in item.get("source_refs", []) if x.get("raw_path") and x.get("source_type") == "official"]
        if kind and refs and item.get("occurred_at"):
            result.append({"event_type":kind,"released_at":item["occurred_at"],"verified":True,"source_refs":refs})
    employment = snapshot.get("daily_research", {}).get("employment", {}).get("release_context", {})
    if employment.get("source_kind") == "bls_release_html" and employment.get("release_datetime") and employment.get("status") in {"available","partial"} and employment.get("source_refs"):
        result.append({"event_type":"NFP","released_at":employment["release_datetime"],"verified":True,"source_refs":employment["source_refs"]})
    return result


def evaluate_shadow_readiness(records, *, minimum_days=20):
    """Count verified successful sessions once; replays and scheduled events don't count."""
    days, events, rejected = set(), set(), []
    for record in records:
        try:
            completed = record.get("task_status") == "success"
            t = datetime.fromisoformat(record["analysis_time"].replace("Z", "+00:00")).astimezone(UTC)
            trade_day = date.fromisoformat(record["trade_date"])
            session = record.get("session_quality", {})
            model = record.get("model", {})
            eligible = (record.get("run_mode") == "live_shadow" and completed and record.get("artifacts_verified") is True
                        and model.get("status") == "success" and model.get("generated_by") == "llm"
                        and model.get("provenance_complete") is True and bool(record.get("report_output"))
                        and (not (record.get('reader_report_version') == 'gold_reader.v4'
                                  or model.get('quality_gate_version') or model.get('quality_review_required'))
                             or (model.get('quality_eligible') is True and model.get('review_status') == 'pass'))
                        and record["trade_date"] == trade_day.isoformat()
                        and trade_day <= t.astimezone(ZoneInfo("Asia/Shanghai")).date()
                        and session.get("session_type") == "NORMAL" and trade_day.weekday() < 5)
            if not eligible:
                rejected.append(record.get("run_id"))
                continue
            days.add(record["trade_date"])
            for event in record.get("event_observations", []):
                released = datetime.fromisoformat(event["released_at"].replace("Z", "+00:00")).astimezone(UTC)
                if event.get("verified") is True and event.get("source_refs") and event.get("event_type") in {"NFP", "CPI", "FOMC"} and released <= t and (t-released).total_seconds() <= 2*86400:
                    events.add(event["event_type"])
        except (KeyError, TypeError, ValueError):
            rejected.append(record.get("run_id"))
    missing = sorted({"NFP", "CPI", "FOMC"}-events)
    return {"schema_version": "gold_shadow_readiness.v1", "verified_trading_days": len(days), "minimum_trading_days": minimum_days, "covered_events": sorted(events), "missing_events": missing,
            "time_and_event_gate_passed": len(days) >= minimum_days and not missing,
            "production_v1_approved": False, "reason": "时间与事件覆盖仅是七项验收的一部分；仅完整模型分析成功的真实日计数，规则降级不计；源健康、状态、CME对账及重放仍须分别验收", "calibration_status": "uncalibrated", "rejected_run_ids": rejected}
