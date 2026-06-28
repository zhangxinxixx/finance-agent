"""P4-03 Task observability tests — step payload records and enriched status API."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app, _step_to_out, _try_parse_json
from database.models.task import StepStatus, TaskStatus, TaskStep

# ── DB-dependent tests require DATABASE_URL ────────────────────────────
requires_db = pytest.mark.skipif(
    os.getenv("FINANCE_AGENT_RUN_DB_TESTS") != "1",
    reason="set FINANCE_AGENT_RUN_DB_TESTS=1 to run legacy PostgreSQL task API tests",
)

client = TestClient(app)


# ── Unit: _try_parse_json ─────────────────────────────────────────────

def test_try_parse_json_valid():
    assert _try_parse_json('{"a": 1}') == {"a": 1}


def test_try_parse_json_none():
    assert _try_parse_json(None) is None


def test_try_parse_json_invalid():
    assert _try_parse_json("{bad json") is None


def test_try_parse_json_empty_object():
    assert _try_parse_json("{}") == {}


# ── Unit: _step_to_out maps all fields ─────────────────────────────────

def test_step_to_out_includes_p4_03_fields():
    step = TaskStep(
        id=uuid.uuid4(),
        task_run_id=uuid.uuid4(),
        name="macro_collect",
        status=StepStatus.success,
        step_order=0,
        input_json='{"run_id": "r1"}',
        output_json='{"status": "success"}',
        error_json=None,
        retryable=True,
        blocked_reason=None,
    )
    out = _step_to_out(step)
    assert out.id == str(step.id)
    assert out.step_order == 0
    assert out.input_json == {"run_id": "r1"}
    assert out.output_json == {"status": "success"}
    assert out.error_json is None
    assert out.retryable is True
    assert out.blocked_reason is None


def test_step_to_out_with_error_json():
    step = TaskStep(
        id=uuid.uuid4(),
        task_run_id=uuid.uuid4(),
        name="cme_download",
        status=StepStatus.failed,
        step_order=3,
        input_json=None,
        output_json=None,
        error_json='{"exception_type": "RuntimeError", "message": "boom"}',
        retryable=False,
        blocked_reason=None,
    )
    out = _step_to_out(step)
    assert out.status == "failed"
    assert out.error_json == {"exception_type": "RuntimeError", "message": "boom"}
    assert out.retryable is False


def test_step_to_out_blocked():
    step = TaskStep(
        id=uuid.uuid4(),
        task_run_id=uuid.uuid4(),
        name="option_wall",
        status=StepStatus.blocked,
        step_order=5,
        input_json=None,
        output_json=None,
        error_json=None,
        retryable=False,
        blocked_reason="Upstream cme_parse failed",
    )
    out = _step_to_out(step)
    assert out.status == "blocked"
    assert out.blocked_reason == "Upstream cme_parse failed"


# ── Integration: API returns enriched step payload ────────────────────

@requires_db
def test_get_task_includes_p4_03_fields():
    """Steps returned by GET /tasks/{id} include step_order and observability fields."""
    resp = client.post("/tasks/premarket")
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    resp2 = client.get(f"/tasks/{task_id}")
    assert resp2.status_code == 200
    body = resp2.json()
    steps = body["steps"]
    assert len(steps) == 8  # premarket step count

    # Every step should have the new P4-03 fields (defaults)
    for step in steps:
        assert "step_order" in step
        assert "input_json" in step
        assert "output_json" in step
        assert "error_json" in step
        assert "retryable" in step
        assert "blocked_reason" in step
        assert step["retryable"] is True  # default


@requires_db
def test_get_task_logs_includes_p4_03_fields():
    """Steps returned by GET /tasks/{id}/logs include step_order and observability fields."""
    resp = client.post("/tasks/premarket")
    task_id = resp.json()["task_id"]

    resp2 = client.get(f"/tasks/{task_id}/logs")
    assert resp2.status_code == 200
    steps = resp2.json()
    for step in steps:
        assert "step_order" in step
        assert "input_json" in step
        assert "retryable" in step


@requires_db
def test_get_nonexistent_task_returns_404():
    resp = client.get(f"/tasks/{uuid.uuid4()}")
    assert resp.status_code == 404


@requires_db
def test_get_task_with_invalid_id_returns_400():
    resp = client.get("/tasks/not-a-uuid")
    assert resp.status_code == 400


# ── Enums: new status values exist ────────────────────────────────────

def test_task_status_includes_blocked_cancelled_stale():
    values = {e.value for e in TaskStatus}
    assert "blocked" in values
    assert "cancelled" in values
    assert "stale" in values
    # old values still present
    assert "pending" in values
    assert "running" in values
    assert "success" in values
    assert "failed" in values
    assert "partial_success" in values


def test_step_status_includes_blocked():
    values = {e.value for e in StepStatus}
    assert "blocked" in values
    assert "pending" in values
    assert "running" in values
    assert "success" in values
    assert "failed" in values
    assert "skipped" in values
