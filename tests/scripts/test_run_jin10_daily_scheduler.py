from __future__ import annotations

import json
from pathlib import Path

from scripts import run_jin10_daily_scheduler as scheduler


def _args(tmp_path: Path, **overrides):
    values = {
        "external_root": str(tmp_path),
        "storage_root": str(tmp_path),
        "category": "270",
        "report_type": "daily",
        "browser_profile": None,
        "vision_provider": "mimo",
        "vision_model": "gpt-5.6-luna",
        "image_retention_days": 30,
        "analysis_provider": "cockpit",
        "analysis_model": "gpt-5.6-terra",
        "analysis_reasoning_effort": "medium",
        "analysis_timeout": 180.0,
        "analysis_max_images": 12,
        "model": "compat-model",
        "dry_run": False,
        "force_rerun": False,
    }
    values.update(overrides)
    return type("Args", (), values)()


def _write_complete_artifacts(root: Path, *, quality_status: str = "accepted") -> None:
    base = root / "outputs" / "jin10" / "2026-06-05" / "221250"
    base.mkdir(parents=True, exist_ok=True)
    (base / "agent_analysis_report.json").write_text(
        json.dumps(
            {
                "article_id": "221250",
                "run_id": "221250",
                "family": "jin10_agent_analysis",
                "one_line_conclusion": "黄金维持条件性观察。",
                "source_refs": [{"source_ref": "jin10:221250"}],
                "quality_audit": {"status": quality_status},
            }
        ),
        encoding="utf-8",
    )
    (base / "agent_analysis_report.md").write_text("# 分析\n\n黄金维持条件性观察。\n", encoding="utf-8")


def _pipeline_summary(*, quality_status: str = "accepted") -> dict:
    return {
        "date": "2026-06-05",
        "reports": 1,
        "daily_reports": [{"run_id": "221250", "trade_date": "2026-06-05"}],
        "persisted_agent_outputs": [{"run_id": "221250", "agent_output_id": 7}],
        "quality_status": quality_status,
    }


def test_attempt_once_uses_existing_local_report_and_passes_analysis_options(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        scheduler,
        "_has_local_report",
        lambda **_: {"article_id": "221250", "external_report_dir": str(tmp_path / "report")},
    )
    seen: dict[str, object] = {}

    def fake_run_pipeline(**kwargs):
        seen.update(kwargs)
        _write_complete_artifacts(tmp_path)
        return _pipeline_summary()

    monkeypatch.setattr(scheduler, "_run_pipeline", fake_run_pipeline)
    result = scheduler._attempt_once(trade_date="2026-06-05", args=_args(tmp_path), env={})

    assert result.status == "success"
    assert result.article_id == "221250"
    assert seen["analysis_provider"] == "cockpit"
    assert seen["analysis_model"] == "gpt-5.6-terra"
    assert seen["analysis_reasoning_effort"] == "medium"
    assert seen["analysis_timeout"] == 180.0
    assert seen["analysis_max_images"] == 12


def test_attempt_once_returns_retry_when_article_id_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler, "_has_local_report", lambda **_: None)
    monkeypatch.setattr(scheduler, "_discover_article_id", lambda **_: None)

    result = scheduler._attempt_once(trade_date="2026-06-06", args=_args(tmp_path), env={})

    assert result.status == "retry"
    assert "未发现可用日报 article_id" in result.message


def test_attempt_once_dry_run_reports_ready_after_discovery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler, "_has_local_report", lambda **_: None)
    monkeypatch.setattr(scheduler, "_discover_article_id", lambda **_: {"article_id": "221300", "title": "示例日报"})

    result = scheduler._attempt_once(
        trade_date="2026-06-06",
        args=_args(tmp_path, dry_run=True),
        env={},
    )

    assert result.status == "ready"
    assert result.article_id == "221300"


def test_invalid_existing_json_does_not_claim_success_and_reruns(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler, "_has_local_report", lambda **_: {"article_id": "221250"})
    base = tmp_path / "outputs" / "jin10" / "2026-06-05" / "221250"
    base.mkdir(parents=True)
    (base / "agent_analysis_report.json").write_text('{"ok": true}\n', encoding="utf-8")
    calls = 0

    def fake_run_pipeline(**_):
        nonlocal calls
        calls += 1
        return {"reports": 0, "daily_reports": [], "persisted_agent_outputs": []}

    monkeypatch.setattr(scheduler, "_run_pipeline", fake_run_pipeline)
    result = scheduler._attempt_once(trade_date="2026-06-05", args=_args(tmp_path), env={})

    assert calls == 1
    assert result.status == "retry"
    assert "target_daily_report_missing" in result.message


def test_validated_existing_marker_can_skip_pipeline(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler, "_has_local_report", lambda **_: {"article_id": "221250"})
    _write_complete_artifacts(tmp_path)
    base = tmp_path / "outputs" / "jin10" / "2026-06-05" / "221250"
    (base / scheduler.COMPLETION_MARKER_NAME).write_text(json.dumps(_pipeline_summary()), encoding="utf-8")
    monkeypatch.setattr(
        scheduler,
        "_run_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError(f"pipeline should not run: {kwargs}")),
    )

    result = scheduler._attempt_once(trade_date="2026-06-05", args=_args(tmp_path), env={})

    assert result.status == "success"
    assert result.pipeline_summary["skipped"] is True


def test_needs_review_is_limited_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scheduler, "_has_local_report", lambda **_: {"article_id": "221250"})

    def fake_run_pipeline(**_):
        _write_complete_artifacts(tmp_path, quality_status="needs_review")
        return _pipeline_summary(quality_status="needs_review")

    monkeypatch.setattr(scheduler, "_run_pipeline", fake_run_pipeline)
    result = scheduler._attempt_once(trade_date="2026-06-05", args=_args(tmp_path), env={})

    assert result.status == "limited_success"
    assert "需要复核" in result.message


def test_run_pipeline_explicitly_passes_all_analysis_cli_options(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_json_command(cmd, *, env):
        captured["cmd"] = cmd
        captured["env"] = env
        return {}

    monkeypatch.setattr(scheduler, "_run_json_command", fake_run_json_command)
    scheduler._run_pipeline(
        env={"no_proxy": "localhost"},
        trade_date="2026-06-05",
        article_id="221250",
        category="270",
        vision_provider="cockpit",
        vision_model="vision-model",
        external_root=tmp_path / "external",
        storage_root=tmp_path / "storage",
        image_retention_days=30,
        analysis_provider="cockpit",
        analysis_model="analysis-model",
        analysis_reasoning_effort="medium",
        analysis_timeout=123.0,
        analysis_max_images=9,
    )

    cmd = captured["cmd"]
    assert cmd[cmd.index("--analysis-provider") + 1] == "cockpit"
    assert cmd[cmd.index("--analysis-model") + 1] == "analysis-model"
    assert cmd[cmd.index("--analysis-reasoning-effort") + 1] == "medium"
    assert cmd[cmd.index("--analysis-timeout") + 1] == "123.0"
    assert cmd[cmd.index("--analysis-max-images") + 1] == "9"
