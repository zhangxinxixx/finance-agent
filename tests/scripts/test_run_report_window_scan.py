from __future__ import annotations

import subprocess
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from apps.collectors.jin10.fetcher import Jin10CategoryEntry
from scripts import run_report_window_scan as scanner
from scripts.run_report_window_scan import WINDOWS, due_windows, matching_entries, previous_weekday, publication_date

BEIJING = ZoneInfo("Asia/Shanghai")


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=BEIJING)


def test_due_windows_cover_observed_release_periods() -> None:
    assert {item.key for item in due_windows(_at("2026-07-16T10:00:00"))} == {"jin10_gold", "jin10_oil"}
    assert {item.key for item in due_windows(_at("2026-07-16T12:00:00"))} == {
        "jin10_gold",
        "jin10_oil",
        "cme_metals_options",
    }
    assert {item.key for item in due_windows(_at("2026-07-16T15:00:00"))} == {
        "cme_metals_options",
        "jin10_gold_positioning",
    }
    assert {item.key for item in due_windows(_at("2026-07-16T18:00:00"))} == {
        "cme_metals_options",
        "jin10_market_observation",
    }
    assert {item.key for item in due_windows(_at("2026-07-16T19:00:00"))} == {
        "cme_metals_options",
        "jin10_market_observation",
    }
    assert "cme_metals_options" not in {item.key for item in due_windows(_at("2026-07-16T19:10:00"))}
    assert "gold_daily_macro_close" in {item.key for item in due_windows(_at("2026-07-16T20:00:00"))}
    assert "gold_daily_macro_close" in {item.key for item in due_windows(_at("2026-07-16T20:50:00"))}
    assert "gold_daily_macro_close" not in {item.key for item in due_windows(_at("2026-07-16T21:00:00"))}
    assert due_windows(_at("2026-07-16T08:00:00")) == []


def test_cme_window_is_weekdays_only() -> None:
    assert "cme_metals_options" not in {item.key for item in due_windows(_at("2026-07-18T13:00:00"))}


def test_weekly_window_runs_sunday_noon_through_six_pm() -> None:
    assert "jin10_gold_weekly" not in {item.key for item in due_windows(_at("2026-07-19T11:59:00"))}
    assert "jin10_gold_weekly" in {item.key for item in due_windows(_at("2026-07-19T12:00:00"))}
    assert "jin10_gold_weekly" in {item.key for item in due_windows(_at("2026-07-19T18:00:00"))}
    assert "jin10_gold_weekly" not in {item.key for item in due_windows(_at("2026-07-19T18:10:00"))}
    assert "jin10_gold_weekly" not in {item.key for item in due_windows(_at("2026-07-20T12:00:00"))}


def test_publication_date_understands_live_listing_formats() -> None:
    now = _at("2026-07-16T10:40:00")
    assert publication_date("19分钟前", now=now).isoformat() == "2026-07-16"
    assert publication_date("18小时前", now=now).isoformat() == "2026-07-15"
    assert publication_date("07-15  10:12", now=now).isoformat() == "2026-07-15"
    assert publication_date("2026-07-16 10:12:30", now=now).isoformat() == "2026-07-16"


def test_matching_entries_filters_non_report_headlines_and_old_items() -> None:
    window = next(item for item in WINDOWS if item.key == "jin10_gold")
    now = _at("2026-07-16T10:40:00")
    entries = [
        Jin10CategoryEntry("1", "今日金银主报告", "/1", "19分钟前"),
        Jin10CategoryEntry("2", "黄金头条：盘面异动", "/2", "10分钟前"),
        Jin10CategoryEntry("3", "昨日金银主报告", "/3", "1天前"),
    ]
    assert [item.article_id for item in matching_entries(entries, window=window, now=now)] == ["1"]


def test_weekly_matching_accepts_saturday_publication_on_sunday() -> None:
    window = next(item for item in WINDOWS if item.key == "jin10_gold_weekly")
    now = _at("2026-07-19T12:00:00")
    entries = [
        Jin10CategoryEntry("1", "本周黄金投资者周报", "/1", "1天前"),
        Jin10CategoryEntry("2", "上周黄金投资者周报", "/2", "2天前"),
    ]

    assert [item.article_id for item in matching_entries(entries, window=window, now=now)] == ["1"]


def test_weekly_scan_uses_article_publication_date(tmp_path, monkeypatch) -> None:
    window = next(item for item in WINDOWS if item.key == "jin10_gold_weekly")
    external_root = tmp_path / "external"
    storage_root = tmp_path / "storage"
    meta = external_root / "2026-07-18/weekly/224965/meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(scanner.httpx, "Client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(
        scanner,
        "fetch_category_entries",
        lambda **kwargs: [Jin10CategoryEntry("224965", "黄金投资者周报", "/224965", "1天前")],
    )

    def fake_run_command(command, *, env):
        commands.append(command)
        return {"status": "ok"}

    monkeypatch.setattr(scanner, "run_command", fake_run_command)

    result = scanner.scan_jin10(
        window,
        now=_at("2026-07-19T12:00:00"),
        external_root=external_root,
        storage_root=storage_root,
        dry_run=False,
        env={},
    )

    pipeline_command = next(command for command in commands if "scripts/run_daily_report_pipeline.py" in command)
    assert pipeline_command[pipeline_command.index("--date") + 1] == "2026-07-18"
    assert pipeline_command[pipeline_command.index("--category") + 1] == "536"
    assert result["actions"][0]["article_id"] == "224965"


def test_completed_weekly_scan_triggers_context_revision_with_latest_snapshot_id(tmp_path, monkeypatch) -> None:
    window = next(item for item in WINDOWS if item.key == "jin10_gold_weekly")
    storage_root = tmp_path / "storage"
    output_dir = storage_root / "outputs/jin10/2026-07-18/224965"
    output_dir.mkdir(parents=True)
    (output_dir / "agent_analysis_report.json").write_text("{}", encoding="utf-8")
    (output_dir / "daily_analysis_completion.json").write_text("{}", encoding="utf-8")
    generated: list[dict] = []

    monkeypatch.setattr(scanner.httpx, "Client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(
        scanner,
        "fetch_category_entries",
        lambda **kwargs: [Jin10CategoryEntry("224965", "黄金投资者周报", "/224965", "1天前")],
    )
    monkeypatch.setattr(
        scanner,
        "build_weekly_context_revision_input_snapshot",
        lambda **kwargs: {
            "status": "ready",
            "input_snapshot_ids": {
                "premarket_snapshot": "features/snapshots/XAUUSD/2026-07-19/context-run/premarket_snapshot.json"
            },
        },
    )

    def fake_generate(**kwargs):
        generated.append(kwargs)
        return {"artifact_type": "weekly_context_revision", "paths": ["source.md", "analysis.md", "report.json"]}

    monkeypatch.setattr(scanner, "generate_weekly_context_revision", fake_generate)

    result = scanner.scan_jin10(
        window,
        now=_at("2026-07-19T12:00:00"),
        external_root=tmp_path / "external",
        storage_root=storage_root,
        dry_run=False,
        env={},
    )

    assert result["actions"][0]["status"] == "complete"
    assert result["actions"][0]["revision"]["status"] == "generated"
    assert generated[0]["article_id"] == "224965"
    assert generated[0]["baseline_date"] == "2026-07-18"
    assert generated[0]["trade_date"] == "2026-07-19"
    assert generated[0]["run_id"] == "224965-context-run-v1"


def test_previous_weekday_handles_monday() -> None:
    assert previous_weekday(_at("2026-07-20T12:00:00").date()).isoformat() == "2026-07-17"


def test_scan_cme_passes_parsed_json_to_options_analysis(tmp_path, monkeypatch) -> None:
    window = next(item for item in WINDOWS if item.key == "cme_metals_options")
    raw_root = tmp_path / "repo"
    storage_root = tmp_path / "storage"
    pdf = raw_root / "raw/cme/daily_bulletin/2026-07-15/section64.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    commands: list[list[str]] = []

    def fake_run_command(command, *, env):
        commands.append(command)
        if "scripts/parse_cme_pdf.py" in command:
            return {
                "json_path": str(storage_root / "parsed/cme/2026-07-15/OG_ALL.json"),
                "status": "PRELIM",
            }
        return {"inserted_rows": 1}

    def fake_subprocess_run(command, **kwargs):
        commands.append(command)

    monkeypatch.setattr(scanner, "run_command", fake_run_command)
    monkeypatch.setattr(scanner.subprocess, "run", fake_subprocess_run)

    result = scanner.scan_cme(
        window,
        now=_at("2026-07-16T13:00:00"),
        raw_root=raw_root,
        storage_root=storage_root,
        dry_run=False,
        env={},
    )

    options_command = next(command for command in commands if "scripts/run_options_analysis.py" in command)
    assert options_command[options_command.index("--parsed-json") + 1].endswith("OG_ALL.json")
    assert options_command[options_command.index("--out-dir") + 1].endswith("outputs/cme_options/2026-07-15")
    assert options_command[options_command.index("--data-source-status") + 1] == "PRELIM"
    assert options_command[options_command.index("--data-source-url") + 1].endswith(
        "/Section64_Metals_Option_Products.pdf"
    )
    assert result["status"] == "processed"


def test_run_command_preserves_subprocess_stderr(monkeypatch) -> None:
    monkeypatch.setattr(
        scanner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="XHR network error"),
    )

    with pytest.raises(scanner.CommandExecutionError, match="XHR network error"):
        scanner.run_command(["download-cme"], env={})


def test_scan_cme_keeps_transient_download_failure_as_waiting(tmp_path, monkeypatch) -> None:
    window = next(item for item in WINDOWS if item.key == "cme_metals_options")

    def fail_download(command, *, env):
        raise scanner.CommandExecutionError("CME PDF XHR network error")

    monkeypatch.setattr(scanner, "run_command", fail_download)

    result = scanner.scan_cme(
        window,
        now=_at("2026-07-17T16:00:00"),
        raw_root=tmp_path / "repo",
        storage_root=tmp_path / "storage",
        dry_run=False,
        env={},
    )

    assert result == {
        "window": "cme_metals_options",
        "status": "waiting",
        "reason": "download_failed",
        "expected_report_date": "2026-07-16",
        "error": "CME PDF XHR network error",
    }


def test_systemd_service_pins_api_database_after_environment_file() -> None:
    project_root = Path(__file__).resolve().parents[2]
    service = (project_root / "deploy/systemd/report-window-scanner.service").read_text(encoding="utf-8")

    assert "ExecStart=/usr/bin/env DATABASE_URL=postgresql://finance_agent:finance_agent@127.0.0.1:55432/" in service
