from __future__ import annotations

import pytest
from dagster import SkipReason, build_schedule_context

from dagster_finance.schedules.premarket_schedule import premarket_daily_schedule


def test_premarket_daily_schedule_skips_when_source_readiness_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.api.services.pipeline_contract_service.build_premarket_pipeline_source_readiness",
        lambda: {"source_readiness_summary": {"decision_counts": {"blocked": 1}}},
    )

    result = premarket_daily_schedule(build_schedule_context())

    assert isinstance(result, SkipReason)
    assert "blocked" in result.skip_message


def test_premarket_daily_schedule_returns_original_launch_payload_when_source_readiness_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.api.services.pipeline_contract_service.build_premarket_pipeline_source_readiness",
        lambda: {"source_readiness_summary": {"decision_counts": {"blocked": 0}}},
    )

    result = premarket_daily_schedule(build_schedule_context())

    assert result == {}
