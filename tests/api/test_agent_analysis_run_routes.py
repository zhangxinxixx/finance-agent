from __future__ import annotations

import pytest
from fastapi import HTTPException
from apps.api.main import app
from apps.api.routes.agent_analysis_run_routes import api_run_agent_analysis


def test_manual_analysis_is_retired_without_starting_a_thread(monkeypatch) -> None:
    import threading

    def fail_start(*args, **kwargs):
        raise AssertionError("retired endpoint must not dispatch a thread")
    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(HTTPException) as error:
        api_run_agent_analysis(date="2026-07-11", force=True)
    assert error.value.status_code == 410
    detail = error.value.detail
    assert detail["code"] == "manual_analysis_retired"
    paths = {route.path for route in app.routes}
    assert detail["run_url"] in paths
    assert detail["preflight_url"] in paths
