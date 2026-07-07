from __future__ import annotations

import pytest


def test_jin10_cache_refresh_scheduler_preserves_registered_jobs_and_startup_refreshes(monkeypatch) -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    jobs: list[dict[str, object]] = []
    started_threads: list[tuple[str, object]] = []
    recorded: list[tuple[str, str, object]] = []

    class FakeScheduler:
        def __init__(self, *, daemon: bool) -> None:
            assert daemon is True
            self.started = False

        def add_job(self, func, trigger, **kwargs) -> None:
            jobs.append({"func": func, "trigger": trigger, **kwargs})

        def start(self) -> None:
            self.started = True

    class FakeThread:
        def __init__(self, *, target, daemon: bool, name: str) -> None:
            assert daemon is True
            self.target = target
            self.name = name

        def start(self) -> None:
            started_threads.append((self.name, self.target))

    refreshers = {
        "quotes": object(),
        "kline": object(),
        "market_candles_daily": object(),
        "calendar": object(),
        "flash": object(),
        "web_flash": object(),
        "web_article_analysis": object(),
    }
    monkeypatch.setattr(service, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(service, "Thread", FakeThread)
    monkeypatch.setattr(service, "refresh_jin10_quotes_cache", refreshers["quotes"])
    monkeypatch.setattr(service, "refresh_jin10_kline_cache", refreshers["kline"])
    monkeypatch.setattr(service, "refresh_market_candle_daily_cache", refreshers["market_candles_daily"])
    monkeypatch.setattr(service, "refresh_jin10_calendar_cache", refreshers["calendar"])
    monkeypatch.setattr(service, "refresh_jin10_flash_cache", refreshers["flash"])
    monkeypatch.setattr(service, "refresh_jin10_web_flash_briefs", refreshers["web_flash"])
    monkeypatch.setattr(service, "refresh_jin10_web_article_analysis", refreshers["web_article_analysis"])
    monkeypatch.setattr(
        service,
        "record_jin10_refresh",
        lambda task_type, task_name, refresher: recorded.append((task_type, task_name, refresher)),
    )

    scheduler = service.start_jin10_cache_refresh_scheduler()

    assert scheduler.started is True
    assert [(job["id"], job["minutes"]) for job in jobs] == [
        ("jin10_quotes_refresh", 15),
        ("jin10_kline_refresh", 1),
        ("market_candles_daily_refresh", 60),
        ("jin10_calendar_refresh", 60),
        ("jin10_flash_refresh", 15),
        ("jin10_web_flash_refresh", 5),
        ("jin10_web_article_analysis_refresh", 30),
    ]
    assert all(job["trigger"] == "interval" and job["replace_existing"] is True for job in jobs)

    for job in jobs:
        job["func"]()
    assert [item[0] for item in recorded] == [
        "jin10_quotes",
        "jin10_kline",
        "market_candles_daily",
        "jin10_calendar",
        "jin10_flash",
        "jin10_web_flash",
        "jin10_web_article_analysis",
    ]
    assert started_threads == [
        ("startup-quotes", refreshers["quotes"]),
        ("startup-kline", refreshers["kline"]),
        ("startup-market-candles", refreshers["market_candles_daily"]),
        ("startup-flash", refreshers["flash"]),
        ("startup-web-flash", refreshers["web_flash"]),
        ("startup-web-article-analysis", refreshers["web_article_analysis"]),
    ]


def test_stop_jin10_cache_refresh_scheduler_uses_non_blocking_shutdown() -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    calls: list[bool] = []

    class FakeScheduler:
        def shutdown(self, *, wait: bool) -> None:
            calls.append(wait)

    service.stop_jin10_cache_refresh_scheduler(FakeScheduler())

    assert calls == [False]


@pytest.mark.anyio
async def test_api_lifespan_delegates_cache_refresh_lifecycle_to_service(monkeypatch) -> None:
    from apps.api import main as api_main

    scheduler = object()
    started: list[object] = []
    stopped: list[object] = []
    monkeypatch.setattr(api_main, "_database_reachable", lambda: False)
    monkeypatch.setattr(api_main, "_should_skip_background_jobs", lambda: False)
    monkeypatch.setattr(api_main, "start_jin10_cache_refresh_scheduler", lambda: started.append(scheduler) or scheduler)
    monkeypatch.setattr(api_main, "stop_jin10_cache_refresh_scheduler", lambda value: stopped.append(value))

    async with api_main.lifespan(api_main.app):
        assert started == [scheduler]

    assert stopped == [scheduler]
    assert getattr(api_main.app.state, "jin10_scheduler", None) is None
