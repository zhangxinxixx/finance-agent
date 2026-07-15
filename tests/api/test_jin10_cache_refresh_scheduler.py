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
        "calendar": object(),
        "flash": object(),
        "web_flash": object(),
        "web_article_analysis": object(),
        "twelvedata": object(),
    }
    monkeypatch.setattr(service, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(service, "Thread", FakeThread)
    monkeypatch.setattr(service, "refresh_jin10_quotes_cache", refreshers["quotes"])
    monkeypatch.setattr(service, "refresh_jin10_kline_cache", refreshers["kline"])
    monkeypatch.setattr(service, "refresh_jin10_calendar_cache", refreshers["calendar"])
    monkeypatch.setattr(service, "refresh_jin10_flash_cache", refreshers["flash"])
    monkeypatch.setattr(service, "refresh_jin10_web_flash_briefs", refreshers["web_flash"])
    monkeypatch.setattr(service, "refresh_jin10_web_article_analysis", refreshers["web_article_analysis"])
    monkeypatch.setattr(service, "refresh_due_twelvedata_xauusd", refreshers["twelvedata"])
    monkeypatch.setattr(
        service,
        "record_jin10_refresh",
        lambda task_type, task_name, refresher: recorded.append((task_type, task_name, refresher)),
    )

    scheduler = service.start_jin10_cache_refresh_scheduler()

    assert scheduler.started is True
    interval_jobs = [job for job in jobs if job["trigger"] == "interval"]
    cron_jobs = [job for job in jobs if job["trigger"] == "cron"]
    assert [(job["id"], job["minutes"]) for job in interval_jobs] == [
        ("jin10_quotes_refresh", 15),
        ("jin10_kline_refresh", 1),
        ("jin10_calendar_refresh", 60),
        ("jin10_flash_refresh", 15),
        ("jin10_web_flash_refresh", 5),
        ("jin10_web_article_analysis_refresh", 30),
    ]
    assert all(job["replace_existing"] is True for job in jobs)
    assert all(
        job["coalesce"] is True and job["max_instances"] == 1 and job["misfire_grace_time"] == 30
        for job in interval_jobs
    )
    assert [job["id"] for job in cron_jobs] == [
        "twelvedata_xauusd_dispatch_refresh",
    ]
    assert [job["minute"] for job in cron_jobs] == [
        "1,6,11,16,21,26,31,36,41,46,51,56",
    ]
    assert cron_jobs[-1]["timezone"] == "UTC"
    assert all(job["second"] == 30 for job in cron_jobs)
    assert all(job["coalesce"] is True and job["max_instances"] == 1 for job in cron_jobs)

    for job in jobs:
        job["func"]()
    assert [item[0] for item in recorded] == [
        "jin10_quotes",
        "jin10_kline",
        "jin10_calendar",
        "jin10_flash",
        "jin10_web_flash",
        "jin10_web_article_analysis",
        "twelvedata_xauusd_dispatch",
    ]
    assert started_threads == [
        ("startup-quotes", refreshers["quotes"]),
        ("startup-kline", refreshers["kline"]),
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


def test_jin10_cache_refresh_scheduler_can_limit_jobs_to_kline(monkeypatch) -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    jobs: list[str] = []
    threads: list[str] = []

    class FakeScheduler:
        def __init__(self, *, daemon: bool) -> None:
            assert daemon is True

        def add_job(self, _func, _trigger, **kwargs) -> None:
            jobs.append(kwargs["id"])

        def start(self) -> None:
            return None

    class FakeThread:
        def __init__(self, *, target, daemon: bool, name: str) -> None:
            assert target is service.refresh_jin10_kline_cache
            assert daemon is True
            self.name = name

        def start(self) -> None:
            threads.append(self.name)

    monkeypatch.setenv("FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS", "jin10_kline")
    monkeypatch.setattr(service, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(service, "Thread", FakeThread)

    service.start_jin10_cache_refresh_scheduler()

    assert jobs == ["jin10_kline_refresh"]
    assert threads == ["startup-kline"]


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
