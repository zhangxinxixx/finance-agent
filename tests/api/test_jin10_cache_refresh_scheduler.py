from __future__ import annotations

import pytest


def test_jin10_cache_refresh_scheduler_preserves_registered_jobs_and_startup_refreshes(monkeypatch) -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    monkeypatch.delenv("FINANCE_AGENT_DISABLE_JIN10", raising=False)
    monkeypatch.delenv("FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS", raising=False)
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
        "calendar": object(),
        "flash": object(),
        "web_flash": object(),
        "web_article_analysis": object(),
        "twelvedata": object(),
    }
    monkeypatch.setattr(service, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(service, "Thread", FakeThread)
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
    assert cron_jobs == []

    for job in jobs:
        job["func"]()
    assert [item[0] for item in recorded] == [
        "jin10_calendar",
        "jin10_flash",
        "jin10_web_flash",
        "jin10_web_article_analysis",
    ]
    assert [name for name, _ in started_threads] == ["startup-flash", "startup-web-flash", "startup-web-article-analysis"]
    for _, target in started_threads:
        target()
    assert [item[0] for item in recorded[4:]] == ["jin10_flash", "jin10_web_flash", "jin10_web_article_analysis"]
    assert [item[2] for item in recorded[4:]] == [refreshers[key] for key in ("flash", "web_flash", "web_article_analysis")]


def test_stop_jin10_cache_refresh_scheduler_uses_non_blocking_shutdown() -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    calls: list[bool] = []

    class FakeScheduler:
        def shutdown(self, *, wait: bool) -> None:
            calls.append(wait)

    service.stop_jin10_cache_refresh_scheduler(FakeScheduler())

    assert calls == [False]


@pytest.mark.parametrize("configured", [None, "", "*", "market_candles_daily"])
def test_default_or_wildcard_does_not_schedule_local_candle_collection(monkeypatch, configured):
    from apps.api.services import jin10_cache_refresh_scheduler as service

    jobs = []
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")
    if configured is None:
        monkeypatch.delenv("FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS", raising=False)
    else:
        monkeypatch.setenv("FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS", configured)

    class Scheduler:
        def __init__(self, **kwargs):
            pass

        def add_job(self, func, trigger, **kwargs):
            jobs.append(kwargs["id"])

        def start(self):
            pass

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(service, "BackgroundScheduler", Scheduler)
    monkeypatch.setattr(service, "Thread", Thread)
    service.start_jin10_cache_refresh_scheduler()
    assert jobs == []


def test_retired_daily_refresh_is_ignored_with_clear_log(monkeypatch, caplog) -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")
    monkeypatch.setenv("FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS", "market_candles_daily")

    class Scheduler:
        def __init__(self, **kwargs):
            pass

        def add_job(self, *args, **kwargs):
            raise AssertionError("retired market-candle refresh must not be registered")

        def start(self):
            pass

    monkeypatch.setattr(service, "BackgroundScheduler", Scheduler)
    service.start_jin10_cache_refresh_scheduler()

    assert "Ignoring retired API background refresh jobs market_candles_daily" in caplog.text
    assert "TradingView" in caplog.text


@pytest.mark.parametrize("configured", ["twelvedata_xauusd_dispatch", "twelvedata_xauusd_5m"])
def test_explicit_intraday_validation_keeps_audited_serial_dispatch(monkeypatch, configured):
    from apps.api.services import jin10_cache_refresh_scheduler as service

    jobs, calls = [], []
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")
    monkeypatch.setenv("FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS", configured)

    class Scheduler:
        def __init__(self, **kwargs):
            pass

        def add_job(self, func, trigger, **kwargs):
            jobs.append({"func": func, "trigger": trigger, **kwargs})

        def start(self):
            pass

    def audited(task_type, task_name, refresher):
        calls.append((task_type, refresher))

    monkeypatch.setattr(service, "BackgroundScheduler", Scheduler)
    monkeypatch.setattr(service, "record_jin10_refresh", audited)
    service.start_jin10_cache_refresh_scheduler()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["id"] == "twelvedata_xauusd_dispatch_refresh"
    assert job["minute"] == "1,6,11,16,21,26,31,36,41,46,51,56"
    assert job["second"] == 30 and job["timezone"] == "UTC"
    assert job["max_instances"] == 1 and job["coalesce"] is True
    job["func"]()
    assert calls == [("twelvedata_xauusd_dispatch", service.refresh_due_twelvedata_xauusd)]


def test_jin10_cache_refresh_scheduler_cannot_reenable_retired_numeric_jobs(monkeypatch) -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    monkeypatch.delenv("FINANCE_AGENT_DISABLE_JIN10", raising=False)
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
            raise AssertionError("retired numeric job must not start")
            assert daemon is True
            self.name = name

        def start(self) -> None:
            threads.append(self.name)

    monkeypatch.setenv("FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS", "jin10_kline")
    monkeypatch.setattr(service, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(service, "Thread", FakeThread)

    service.start_jin10_cache_refresh_scheduler()

    assert jobs == []
    assert threads == []


def test_jin10_cache_refresh_scheduler_keeps_explicit_intraday_validation_when_jin10_is_disabled(monkeypatch) -> None:
    from apps.api.services import jin10_cache_refresh_scheduler as service

    jobs: list[str] = []
    started_threads: list[tuple[str, object]] = []

    class FakeScheduler:
        def __init__(self, *, daemon: bool) -> None:
            assert daemon is True

        def add_job(self, _func, _trigger, **kwargs) -> None:
            jobs.append(kwargs["id"])

        def start(self) -> None:
            return None

    class FakeThread:
        def __init__(self, *, target, daemon: bool, name: str) -> None:
            assert daemon is True
            started_threads.append((name, target))

        def start(self) -> None:
            return None

    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", " yes ")
    monkeypatch.setenv(
        "FINANCE_AGENT_API_BACKGROUND_REFRESH_JOBS",
        "jin10_kline,twelvedata_xauusd_dispatch,market_candles_daily",
    )
    monkeypatch.setattr(service, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(service, "Thread", FakeThread)

    service.start_jin10_cache_refresh_scheduler()

    assert jobs == ["twelvedata_xauusd_dispatch_refresh"]
    assert started_threads == []


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
