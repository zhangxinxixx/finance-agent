from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from apps.api.schemas.common import DataStatus
from apps.monitoring.source_probe_runner import SourceProbeRunner, build_source_probe_check

OBSERVED_AT = datetime(2026, 7, 14, 3, 0, tzinfo=timezone.utc)


def _response(*, source_key: str, status: str = "ok", data_status: DataStatus = DataStatus.live):
    return SimpleNamespace(
        source_key=source_key,
        status=status,
        data_status=data_status,
        summary={"method": "test"} if status == "ok" else {"reason_code": "probe_degraded", "reason": "limited data"},
        preview=[{"id": "1"}],
        source_refs=[{"source_id": source_key, "status": status}],
        artifact_refs=[{"file_path": f"storage/probes/{source_key}/parsed.json"}],
        run_id="probe-run-1",
        audit_id="probe-audit-1",
        duration_ms=12,
    )


def test_build_source_probe_check_preserves_audit_and_artifact_refs() -> None:
    check = build_source_probe_check(response=_response(source_key="jin10_mcp_market"), observed_at=OBSERVED_AT)

    assert check.status == "ok"
    assert check.latest_artifact_ref == "storage/probes/jin10_mcp_market/parsed.json"
    assert check.metadata["run_id"] == "probe-run-1"
    assert check.metadata["audit_id"] == "probe-audit-1"
    assert check.metadata["preview_count"] == 1


def test_build_source_probe_check_blocks_manual_required_research_source() -> None:
    check = build_source_probe_check(
        response=_response(
            source_key="jin10_svip_reports",
            status="manual_required",
            data_status=DataStatus.manual_required,
        ),
        observed_at=OBSERVED_AT,
    )

    assert check.status == "blocked"
    assert check.severity == "critical"
    assert "knowledge_distillation" in check.blocked_capabilities
    assert check.reason_code == "probe_degraded"


def test_source_probe_runner_converts_runtime_failure_to_health_check() -> None:
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    def failing_probe(*args, **kwargs):
        raise RuntimeError("database unavailable")

    checks = SourceProbeRunner(session_factory=Session, probe=failing_probe).run(
        observed_at=OBSERVED_AT,
        source_keys=("jin10_mcp_flash",),
    )

    assert len(checks) == 1
    assert checks[0].status == "unavailable"
    assert checks[0].reason_code == "source_probe_execution_failed"
    assert checks[0].metadata["error_type"] == "RuntimeError"
