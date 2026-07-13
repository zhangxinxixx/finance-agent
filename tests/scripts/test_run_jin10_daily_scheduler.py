from __future__ import annotations

from pathlib import Path

from scripts import run_jin10_daily_scheduler as scheduler


def test_attempt_once_uses_existing_local_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        scheduler,
        "_has_local_report",
        lambda **_: {"article_id": "221250", "external_report_dir": str(tmp_path / "2026-06-05" / "daily" / "221250")},
    )
    seen: dict[str, str] = {}

    def fake_run_pipeline(
        *,
        trade_date: str,
        article_id: str,
        category: str,
        vision_provider: str,
        vision_model: str,
        external_root: Path,
        storage_root: Path,
        image_retention_days: int,
        env,
    ):
        seen.update(
            {
                "trade_date": trade_date,
                "article_id": article_id,
                "category": category,
                "vision_provider": vision_provider,
                "vision_model": vision_model,
                "external_root": str(external_root),
                "storage_root": str(storage_root),
                "image_retention_days": str(image_retention_days),
            }
        )
        return {"date": trade_date, "daily_reports": [{"run_id": article_id}]}

    monkeypatch.setattr(scheduler, "_run_pipeline", fake_run_pipeline)
    class _Args:
        external_root = str(tmp_path)
        storage_root = str(tmp_path)
        category = "270"
        report_type = "daily"
        browser_profile = None
        vision_provider = "mimo"
        vision_model = "gpt-5.6-luna"
        image_retention_days = 30
        dry_run = False
        force_rerun = False

    result = scheduler._attempt_once(trade_date="2026-06-05", args=_Args(), env={})
    assert result.status == "success"
    assert result.article_id == "221250"
    assert seen == {
        "trade_date": "2026-06-05",
        "article_id": "221250",
        "category": "270",
        "vision_provider": "mimo",
        "vision_model": "gpt-5.6-luna",
        "external_root": str(tmp_path),
        "storage_root": str(tmp_path),
        "image_retention_days": "30",
    }


def test_attempt_once_returns_retry_when_article_id_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler, "_has_local_report", lambda **_: None)
    monkeypatch.setattr(scheduler, "_discover_article_id", lambda **_: None)

    class _Args:
        external_root = str(tmp_path)
        storage_root = str(tmp_path)
        category = "270"
        report_type = "daily"
        browser_profile = None
        vision_model = "gpt-5.6-luna"
        image_retention_days = 30
        dry_run = False
        force_rerun = False

    result = scheduler._attempt_once(trade_date="2026-06-06", args=_Args(), env={})
    assert result.status == "retry"
    assert "未发现可用日报 article_id" in result.message


def test_attempt_once_dry_run_reports_ready_after_discovery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler, "_has_local_report", lambda **_: None)
    monkeypatch.setattr(
        scheduler,
        "_discover_article_id",
        lambda **_: {"article_id": "221300", "title": "示例日报"},
    )

    class _Args:
        external_root = str(tmp_path)
        storage_root = str(tmp_path)
        category = "270"
        report_type = "daily"
        browser_profile = None
        vision_model = "gpt-5.6-luna"
        image_retention_days = 30
        dry_run = True
        force_rerun = False

    result = scheduler._attempt_once(trade_date="2026-06-06", args=_Args(), env={})
    assert result.status == "ready"
    assert result.article_id == "221300"


def test_attempt_once_skips_pipeline_when_agent_artifact_already_exists(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        scheduler,
        "_has_local_report",
        lambda **_: {"article_id": "221250", "external_report_dir": str(tmp_path / "2026-06-05" / "daily" / "221250")},
    )

    artifact = tmp_path / "outputs" / "jin10" / "2026-06-05" / "221250" / "agent_analysis_report.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"ok":true}\n', encoding="utf-8")

    def fail_pipeline(**kwargs):  # pragma: no cover
        raise AssertionError(f"pipeline should not run: {kwargs}")

    monkeypatch.setattr(scheduler, "_run_pipeline", fail_pipeline)

    class _Args:
        external_root = str(tmp_path)
        storage_root = str(tmp_path)
        category = "270"
        report_type = "daily"
        browser_profile = None
        vision_model = "gpt-5.6-luna"
        image_retention_days = 30
        dry_run = False
        force_rerun = False

    result = scheduler._attempt_once(trade_date="2026-06-05", args=_Args(), env={})
    assert result.status == "success"
    assert result.pipeline_summary["skipped"] is True
