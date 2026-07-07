from __future__ import annotations

from apps.api.routes import agent_analysis_run_routes


def test_agent_analysis_run_route_dispatches_direct_service_calls(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_analysis_run_routes,
        "run_market_regime_async",
        lambda target_date: calls.append(("market_regime", target_date)),
    )
    monkeypatch.setattr(
        agent_analysis_run_routes,
        "run_event_impact_async",
        lambda target_date: calls.append(("event_impact", target_date)),
    )

    payload = agent_analysis_run_routes.api_run_agent_analysis(date="2026-07-11")

    assert payload == {"status": "dispatched", "agent": "all", "date": "2026-07-11"}
    assert calls == [("market_regime", "2026-07-11"), ("event_impact", "2026-07-11")]
