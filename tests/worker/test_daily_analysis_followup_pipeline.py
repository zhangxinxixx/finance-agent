from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.pipelines.daily_analysis_followup import (
    DAILY_ANALYSIS_STEP,
    DETAIL_FETCH_STEP,
    MAX_SELECTED_FOLLOWUP_TASKS,
    VIP_BROWSER_FALLBACK_STEP,
    run_daily_analysis_followup_task,
    run_pending_daily_analysis_followup_tasks,
    run_selected_daily_analysis_followup_tasks,
)
from apps.collectors.news.jin10_detail_fetcher import Jin10DetailFetchResult
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep


def _make_db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _write_artifact_file(base: Path, relative_path: str, content: str | bytes) -> str:
    target = base / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target.as_posix()


def _seed_followup_run(
    session: Session,
    *,
    source_url: str | None = "https://xnews.jin10.com/details/1",
    input_json: str | None = None,
) -> TaskRun:
    run = TaskRun(
        name="daily_analysis_followup:trigger:test",
        task_type="daily_analysis_followup",
        status=TaskStatus.pending,
        current_stage="news_followup",
        progress=0.0,
        trade_date="2026-06-12",
    )
    session.add(run)
    session.flush()
    payload = {
        "date": "2026-06-12",
        "run_id": "run-news",
        "queue_source_artifact": "daily_analysis_triggers",
        "artifact_paths": {
            "daily_analysis_triggers": "features/news/2026-06-12/run-news/daily_analysis_triggers.json"
        },
        "followup": {
            "followup_id": "trigger:test",
            "queue_type": "jin10_daily_analysis",
            "action": "run_jin10_daily_analysis",
            "source_url": source_url,
            "source_artifact": "daily_analysis_triggers",
            "source_title": "黄金日报触发器",
            "source_event_id": "event:test",
            "event_type": "gold_market_narrative",
            "evidence_text": "黄金和美联储路径需要进入日报跟踪。",
            "impact_path": "macro_to_gold",
            "gold_impact": "bullish",
            "asset_tags": ["XAUUSD", "DXY"],
            "topic_tags": ["Fed", "gold"],
            "source_refs": [{"source": "jin10_feishu", "source_ref": "msg:test"}],
        },
    }
    session.add(
        TaskStep(
            task_run_id=run.id,
            name="run_jin10_daily_analysis",
            stage="news_followup",
            task_kind="jin10_daily_analysis",
            status=StepStatus.pending,
            step_order=0,
            input_json=input_json if input_json is not None else json.dumps(payload, ensure_ascii=True, sort_keys=True),
            input_refs=json.dumps(
                [
                    {
                        "artifact_id": "daily_analysis_triggers",
                        "artifact_type": "feature_json",
                        "file_path": "features/news/2026-06-12/run-news/daily_analysis_triggers.json",
                    }
                ],
                ensure_ascii=True,
            ),
            output_refs=json.dumps([], ensure_ascii=True),
            source_refs=json.dumps([{"source": "jin10_feishu", "source_ref": "msg:test"}], ensure_ascii=True),
            retry_count=0,
        )
    )
    session.commit()
    session.refresh(run)
    return run


def test_run_daily_analysis_followup_task_expands_auditable_steps(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    ensure_execution_tables(session)
    run = _seed_followup_run(session)

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.status == TaskStatus.pending
    assert run.current_stage == DETAIL_FETCH_STEP
    assert run.progress == 0.25

    steps = {step.name: step for step in run.steps}
    assert steps["run_jin10_daily_analysis"].status == StepStatus.success
    plan = json.loads(steps["run_jin10_daily_analysis"].output_json or "{}")
    assert plan["status"] == "planned"
    assert plan["execution_policy"]["network_calls"] == "deferred"

    assert steps[DETAIL_FETCH_STEP].status == StepStatus.pending
    assert steps[DETAIL_FETCH_STEP].task_kind == DETAIL_FETCH_STEP
    detail_input = json.loads(steps[DETAIL_FETCH_STEP].input_json or "{}")
    assert detail_input["source_url"] == "https://xnews.jin10.com/details/1"
    assert steps[VIP_BROWSER_FALLBACK_STEP].status == StepStatus.blocked
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.blocked

    execution_events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()
    initial_step_events = [
        json.loads(event.payload or "{}")
        for event in execution_events
        if event.event_type == "TASK_STATUS_CHANGED" and json.loads(event.payload or "{}").get("step_name") == "run_jin10_daily_analysis"
    ]
    assert any(item.get("from_status") == "pending" and item.get("to_status") == "success" for item in initial_step_events)


def test_run_daily_analysis_followup_task_fetches_readable_detail_page(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    ensure_execution_tables(session)
    run = _seed_followup_run(session)
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    raw_html_path = _write_artifact_file(
        tmp_path,
        "raw/news/jin10_detail_pages/2026-06-12/detail.html",
        "<html><body>黄金日报</body></html>",
    )
    parsed_path = _write_artifact_file(
        tmp_path,
        "parsed/news/jin10_detail_pages/2026-06-12/detail.json",
        json.dumps({"title": "黄金日报"}, ensure_ascii=False),
    )
    image_path = _write_artifact_file(
        tmp_path,
        "raw/news/jin10_detail_pages/2026-06-12/images/01.png",
        b"\x89PNG\r\n\x1a\nfakepng",
    )

    def fake_fetcher(**kwargs):
        assert kwargs["url"] == "https://xnews.jin10.com/details/1"
        assert kwargs["storage_root"] == tmp_path
        assert kwargs["retrieved_date"] == "2026-06-12"
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="readable",
            title="黄金日报",
            raw_text="黄金和美联储主线仍需重点跟进。",
            raw_html_path=raw_html_path,
            parsed_path=parsed_path,
            image_assets=[{"path": image_path}],
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.current_stage == DAILY_ANALYSIS_STEP
    assert run.progress == 0.6
    assert run.ended_at is None
    steps = {step.name: step for step in run.steps}
    detail_step = steps[DETAIL_FETCH_STEP]
    assert detail_step.status == StepStatus.success
    output = json.loads(detail_step.output_json or "{}")
    assert output["detail_fetch"]["access_status"] == "readable"
    assert output["data_quality"]["used_detail_text"] is True
    refs = json.loads(detail_step.output_refs or "[]")
    assert {item["artifact_type"] for item in refs} >= {"raw_file", "parsed_file", "chart_snapshot"}
    source_refs = json.loads(detail_step.source_refs or "[]")
    assert any(item.get("source_name") == "jin10_detail_pages" for item in source_refs)
    run_artifacts = session.query(RunArtifact).filter(RunArtifact.run_id == run.id).all()
    assert {artifact.artifact_type for artifact in run_artifacts} >= {"raw_file", "parsed_file", "chart_snapshot"}
    artifact_by_type = {artifact.artifact_type: artifact for artifact in run_artifacts}
    assert artifact_by_type["raw_file"].content_type == "text/html"
    assert artifact_by_type["raw_file"].byte_size == len("<html><body>黄金日报</body></html>".encode("utf-8"))
    assert artifact_by_type["parsed_file"].content_type == "application/json"
    assert artifact_by_type["parsed_file"].byte_size == len(json.dumps({"title": "黄金日报"}, ensure_ascii=False).encode("utf-8"))
    assert artifact_by_type["chart_snapshot"].content_type == "image/png"
    assert artifact_by_type["chart_snapshot"].byte_size == len(b"\x89PNG\r\n\x1a\nfakepng")
    assert steps[VIP_BROWSER_FALLBACK_STEP].status == StepStatus.skipped
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending

    event_types = [event.event_type for event in session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc())]
    assert "RUN_STARTED" in event_types
    assert "TASK_STARTED" in event_types
    assert "TASK_FINISHED" in event_types


def test_run_daily_analysis_followup_task_daily_analysis_archives_snapshot_from_readable_detail(
    tmp_path: Path,
) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    def fake_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="readable",
            title="黄金日报",
            raw_text="黄金和美联储主线仍需重点跟进，美元和收益率反应是关键。",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/detail.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/detail.json",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    session.refresh(run)
    assert run.status == TaskStatus.success
    assert run.current_stage == DAILY_ANALYSIS_STEP
    steps = {step.name: step for step in run.steps}
    analysis_step = steps[DAILY_ANALYSIS_STEP]
    assert analysis_step.status == StepStatus.success
    output = json.loads(analysis_step.output_json or "{}")
    snapshot_ref = output["daily_analysis"]["snapshot_path"]
    assert snapshot_ref == "features/news/2026-06-12/run-news/daily_brief_input_snapshot.json"
    assert output["data_quality"]["partial"] is False
    snapshot = json.loads((tmp_path / snapshot_ref).read_text(encoding="utf-8"))
    assert snapshot["report_mode"] == "jin10_daily_brief"
    assert snapshot["status"] == "complete"
    assert snapshot["key_articles"][0]["text_source"] == "detail_fetch"
    assert "黄金和美联储主线" in snapshot["key_articles"][0]["body_text"]
    assert "vip_preview_only" not in snapshot["quality_flags"]
    refs = json.loads(analysis_step.output_refs or "[]")
    assert refs == [
        {
            "artifact_id": "daily_brief_input_snapshot",
            "artifact_type": "feature_json",
            "file_path": snapshot_ref,
        }
    ]


def test_run_daily_analysis_followup_task_routes_vip_detail_to_browser_fallback(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    def fake_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="vip_locked",
            title="VIP专享文章",
            raw_text="VIP专享文章",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/vip.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/vip.json",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.current_stage == VIP_BROWSER_FALLBACK_STEP
    steps = {step.name: step for step in run.steps}
    assert steps[DETAIL_FETCH_STEP].status == StepStatus.success
    assert steps[VIP_BROWSER_FALLBACK_STEP].status == StepStatus.pending
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.blocked
    assert steps[DAILY_ANALYSIS_STEP].blocked_reason == "waiting for VIP/browser fallback artifact"


def test_run_daily_analysis_followup_task_daily_analysis_archives_partial_snapshot_when_vip_locked(
    tmp_path: Path,
) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    def fake_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="vip_locked",
            title="VIP专享文章",
            raw_text="VIP专享文章",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/vip.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/vip.json",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)
    session.refresh(run)
    steps = {step.name: step for step in run.steps}
    steps[VIP_BROWSER_FALLBACK_STEP].status = StepStatus.blocked
    steps[VIP_BROWSER_FALLBACK_STEP].blocked_reason = "profile missing in test"
    steps[DAILY_ANALYSIS_STEP].status = StepStatus.pending
    steps[DAILY_ANALYSIS_STEP].blocked_reason = None
    run.current_stage = DAILY_ANALYSIS_STEP
    run.status = TaskStatus.pending
    session.commit()

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    session.refresh(run)
    steps = {step.name: step for step in run.steps}
    analysis_step = steps[DAILY_ANALYSIS_STEP]
    snapshot_ref = json.loads(analysis_step.output_json or "{}")["daily_analysis"]["snapshot_path"]
    snapshot = json.loads((tmp_path / snapshot_ref).read_text(encoding="utf-8"))
    assert snapshot["status"] == "partial"
    assert "vip_preview_only" in snapshot["quality_flags"]
    assert "vip_preview_only" in snapshot["risk_flags"]
    assert snapshot["key_articles"][0]["text_source"] == "preview"
    assert "黄金日报触发器" in snapshot["key_articles"][0]["body_text"]
    assert "黄金和美联储路径" in snapshot["core_events"][0]["evidence_text"]


def test_run_daily_analysis_followup_task_partial_snapshot_uses_title_preview(
    tmp_path: Path,
) -> None:
    session = _make_db_session(tmp_path)
    payload = {
        "date": "2026-06-12",
        "run_id": "run-news",
        "queue_source_artifact": "daily_analysis_triggers",
        "artifact_paths": {
            "daily_analysis_triggers": "features/news/2026-06-12/run-news/daily_analysis_triggers.json"
        },
        "followup": {
            "followup_id": "trigger:title-only",
            "queue_type": "jin10_daily_analysis",
            "action": "run_jin10_daily_analysis",
            "source_url": "https://xnews.jin10.com/details/1",
            "source_artifact": "daily_analysis_triggers",
            "title": "只有 title 的黄金日报触发器",
            "source_refs": [{"source": "jin10_feishu", "source_ref": "msg:title-only"}],
        },
    }
    run = _seed_followup_run(session, input_json=json.dumps(payload, ensure_ascii=True, sort_keys=True))
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    def fake_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="vip_locked",
            title="VIP专享文章",
            raw_text="VIP专享文章",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/vip.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/vip.json",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)
    session.refresh(run)
    steps = {step.name: step for step in run.steps}
    steps[VIP_BROWSER_FALLBACK_STEP].status = StepStatus.blocked
    steps[VIP_BROWSER_FALLBACK_STEP].blocked_reason = "profile missing in test"
    steps[DAILY_ANALYSIS_STEP].status = StepStatus.pending
    steps[DAILY_ANALYSIS_STEP].blocked_reason = None
    run.current_stage = DAILY_ANALYSIS_STEP
    run.status = TaskStatus.pending
    session.commit()

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    session.refresh(run)
    analysis_step = {step.name: step for step in run.steps}[DAILY_ANALYSIS_STEP]
    snapshot_ref = json.loads(analysis_step.output_json or "{}")["daily_analysis"]["snapshot_path"]
    snapshot = json.loads((tmp_path / snapshot_ref).read_text(encoding="utf-8"))
    assert snapshot["status"] == "partial"
    assert snapshot["key_articles"][0]["body_text"] != "preview unavailable"
    assert "只有 title 的黄金日报触发器" in snapshot["key_articles"][0]["body_text"]
    assert snapshot["core_events"][0]["title"] == "只有 title 的黄金日报触发器"


def test_run_daily_analysis_followup_task_vip_browser_fallback_routes_to_daily_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    ensure_execution_tables(session)
    profile_dir = tmp_path / "jin10-browser-profile"
    profile_dir.mkdir()
    monkeypatch.setenv("JIN10_BROWSER_PROFILE", str(profile_dir))
    run = _seed_followup_run(session)
    _route_run_to_vip_browser_fallback(session, run, storage_root=tmp_path)

    def fake_vip_fetcher(**kwargs):
        assert kwargs["article_id"] == "1"
        assert kwargs["source_url"] == "https://xnews.jin10.com/details/1"
        assert kwargs["storage_root"] == tmp_path
        assert kwargs["retrieved_date"] == "2026-06-12"
        assert kwargs["user_data_dir"] == profile_dir
        return {
            "status": "fetched",
            "access_status": "readable",
            "article_id": "1",
            "title": "VIP黄金日报",
            "raw_text": "金十VIP全文内容，黄金和美联储主线仍需进入日报分析。",
            "raw_html": "<html><title>VIP黄金日报</title><p>金十VIP全文内容</p></html>",
            "source_url": "https://svip.jin10.com/news/1",
            "image_assets": [{"seq": 1, "url": "https://img.jin10.com/news/1.png"}],
            "fetched_at": "2026-06-12T00:00:00+00:00",
        }

    status = run_daily_analysis_followup_task(
        session,
        run.id,
        storage_root=tmp_path,
        vip_browser_fetcher=fake_vip_fetcher,
    )

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.status == TaskStatus.pending
    assert run.current_stage == DAILY_ANALYSIS_STEP
    assert run.progress == 0.7
    assert run.ended_at is None
    steps = {step.name: step for step in run.steps}
    fallback_step = steps[VIP_BROWSER_FALLBACK_STEP]
    assert fallback_step.status == StepStatus.success
    output = json.loads(fallback_step.output_json or "{}")
    assert output["vip_browser_fallback"]["access_status"] == "readable"
    assert output["vip_browser_fallback"]["article_id"] == "1"
    assert output["data_quality"]["raw_text_chars"] > 0
    assert (tmp_path / output["vip_browser_fallback"]["raw_html_path"]).is_file()
    parsed_payload = json.loads((tmp_path / output["vip_browser_fallback"]["parsed_path"]).read_text(encoding="utf-8"))
    assert parsed_payload["title"] == "VIP黄金日报"
    assert parsed_payload["raw_text"] == "金十VIP全文内容，黄金和美联储主线仍需进入日报分析。"
    refs = json.loads(fallback_step.output_refs or "[]")
    assert {item["artifact_type"] for item in refs} >= {"raw_file", "parsed_file", "chart_snapshot"}
    assert fallback_step.artifact_refs == fallback_step.output_refs
    run_artifacts = session.query(RunArtifact).filter(RunArtifact.run_id == run.id).all()
    assert {artifact.file_path for artifact in run_artifacts} >= {
        output["vip_browser_fallback"]["raw_html_path"],
        output["vip_browser_fallback"]["parsed_path"],
    }
    source_refs = json.loads(fallback_step.source_refs or "[]")
    assert any(item.get("source_name") == "jin10_vip_browser_fallback" for item in source_refs)
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending


def test_run_daily_analysis_followup_task_daily_analysis_registers_snapshot_artifact(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    ensure_execution_tables(session)
    run = _seed_followup_run(session)
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    def fake_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="readable",
            title="黄金日报",
            raw_text="黄金和美联储主线仍需重点跟进，美元和收益率反应是关键。",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/detail.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/detail.json",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)
    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    run_artifacts = session.query(RunArtifact).filter(RunArtifact.run_id == run.id).all()
    snapshot_artifact = next(
        artifact
        for artifact in run_artifacts
        if artifact.artifact_type == "feature_json"
        and artifact.file_path == "features/news/2026-06-12/run-news/daily_brief_input_snapshot.json"
    )
    assert snapshot_artifact.content_type == "application/json"
    assert snapshot_artifact.byte_size == (
        tmp_path / "features/news/2026-06-12/run-news/daily_brief_input_snapshot.json"
    ).stat().st_size


def test_run_daily_analysis_followup_task_vip_browser_fallback_keeps_logged_in_vip_text_readable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    profile_dir = tmp_path / "jin10-browser-profile"
    profile_dir.mkdir()
    monkeypatch.setenv("JIN10_BROWSER_PROFILE", str(profile_dir))
    run = _seed_followup_run(session)
    _route_run_to_vip_browser_fallback(session, run, storage_root=tmp_path)

    full_text = (
        "金十VIP专享每日金银报告\n"
        "行情回顾：黄金昨日震荡上行，美元指数回落。\n"
        "关键指标：实际利率、美债收益率和ETF持仓均需跟踪。\n"
        "观点分享：短线关注回调后的多头延续。（仅VIP查看）"
    )

    def fake_vip_fetcher(**kwargs):
        return {
            "status": "fetched",
            "article_id": "1",
            "title": "钻石VIP专享文章",
            "raw_text": full_text,
            "raw_html": "<html><body><h1>金十VIP专享每日金银报告</h1><p>行情回顾</p></body></html>",
            "source_url": "https://svip.jin10.com/news/1",
            "fetched_at": "2026-06-12T00:00:00+00:00",
        }

    status = run_daily_analysis_followup_task(
        session,
        run.id,
        storage_root=tmp_path,
        vip_browser_fetcher=fake_vip_fetcher,
    )

    assert status == TaskStatus.pending
    session.refresh(run)
    steps = {step.name: step for step in run.steps}
    fallback_step = steps[VIP_BROWSER_FALLBACK_STEP]
    assert fallback_step.status == StepStatus.success
    output = json.loads(fallback_step.output_json or "{}")
    assert output["vip_browser_fallback"]["access_status"] == "readable"
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending
    assert run.current_stage == DAILY_ANALYSIS_STEP


def test_run_daily_analysis_followup_task_vip_browser_fallback_keeps_paywall_login_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    profile_dir = tmp_path / "jin10-browser-profile"
    profile_dir.mkdir()
    monkeypatch.setenv("JIN10_BROWSER_PROFILE", str(profile_dir))
    run = _seed_followup_run(session)
    _route_run_to_vip_browser_fallback(session, run, storage_root=tmp_path)

    def fake_vip_fetcher(**kwargs):
        return {
            "status": "fetched",
            "article_id": "1",
            "title": "VIP黄金日报",
            "raw_text": "付费内容，开通VIP阅读全文\n已是VIP？登录查看全文\n解锁文章\n登录后查看",
            "raw_html": "<html><body>付费内容，开通VIP阅读全文</body></html>",
            "source_url": "https://svip.jin10.com/news/1",
            "fetched_at": "2026-06-12T00:00:00+00:00",
        }

    status = run_daily_analysis_followup_task(
        session,
        run.id,
        storage_root=tmp_path,
        vip_browser_fetcher=fake_vip_fetcher,
    )

    assert status == TaskStatus.pending
    session.refresh(run)
    steps = {step.name: step for step in run.steps}
    fallback_step = steps[VIP_BROWSER_FALLBACK_STEP]
    assert fallback_step.status == StepStatus.blocked
    assert fallback_step.error_type == "login_required"
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending
    assert run.current_stage == DAILY_ANALYSIS_STEP

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    session.refresh(run)
    analysis_step = {step.name: step for step in run.steps}[DAILY_ANALYSIS_STEP]
    snapshot_ref = json.loads(analysis_step.output_json or "{}")["daily_analysis"]["snapshot_path"]
    snapshot = json.loads((tmp_path / snapshot_ref).read_text(encoding="utf-8"))
    assert snapshot["status"] == "partial"
    assert "vip_preview_only" in snapshot["quality_flags"]
    assert snapshot["key_articles"][0]["text_source"] == "preview"


def test_run_daily_analysis_followup_task_daily_analysis_prefers_vip_browser_fallback_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    profile_dir = tmp_path / "jin10-browser-profile"
    profile_dir.mkdir()
    monkeypatch.setenv("JIN10_BROWSER_PROFILE", str(profile_dir))
    run = _seed_followup_run(session)
    _route_run_to_vip_browser_fallback(session, run, storage_root=tmp_path)

    def fake_vip_fetcher(**kwargs):
        return {
            "status": "fetched",
            "access_status": "readable",
            "article_id": "1",
            "title": "VIP黄金日报",
            "raw_text": "金十VIP全文优先用于日报输入快照，覆盖普通详情页预览。",
            "raw_html": "<html><title>VIP黄金日报</title></html>",
            "source_url": "https://svip.jin10.com/news/1",
            "fetched_at": "2026-06-12T00:00:00+00:00",
        }

    run_daily_analysis_followup_task(
        session,
        run.id,
        storage_root=tmp_path,
        vip_browser_fetcher=fake_vip_fetcher,
    )

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    session.refresh(run)
    steps = {step.name: step for step in run.steps}
    analysis_step = steps[DAILY_ANALYSIS_STEP]
    snapshot_ref = json.loads(analysis_step.output_json or "{}")["daily_analysis"]["snapshot_path"]
    snapshot = json.loads((tmp_path / snapshot_ref).read_text(encoding="utf-8"))
    assert snapshot["status"] == "complete"
    assert snapshot["key_articles"][0]["text_source"] == "vip_browser_fallback"
    assert snapshot["key_articles"][0]["body_text"] == "金十VIP全文优先用于日报输入快照，覆盖普通详情页预览。"
    assert any(item.get("source_name") == "jin10_vip_browser_fallback" for item in snapshot["source_refs"])


def test_run_daily_analysis_followup_task_vip_browser_fallback_blocks_when_profile_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    ensure_execution_tables(session)
    missing_profile = tmp_path / "missing-profile"
    monkeypatch.setenv("JIN10_BROWSER_PROFILE", str(missing_profile))
    run = _seed_followup_run(session)
    _route_run_to_vip_browser_fallback(session, run, storage_root=tmp_path)

    def fake_vip_fetcher(**kwargs):
        raise AssertionError("fetcher should not be called when browser profile is missing")

    status = run_daily_analysis_followup_task(
        session,
        run.id,
        storage_root=tmp_path,
        vip_browser_fetcher=fake_vip_fetcher,
    )

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.status == TaskStatus.pending
    assert run.current_stage == DAILY_ANALYSIS_STEP
    assert "partial snapshot" in (run.error_summary or "")
    steps = {step.name: step for step in run.steps}
    fallback_step = steps[VIP_BROWSER_FALLBACK_STEP]
    assert fallback_step.status == StepStatus.blocked
    assert fallback_step.error_type == "profile_missing"
    assert fallback_step.retryable is False
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending
    assert steps[DAILY_ANALYSIS_STEP].blocked_reason is None

    execution_events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()
    run_transitions = [
        json.loads(event.payload or "{}")
        for event in execution_events
        if event.event_type == "RUN_STATUS_CHANGED"
    ]
    assert any(item.get("from_status") == "pending" and item.get("to_status") == "pending" and item.get("reason") == "vip_fallback_partial_snapshot" for item in run_transitions)
    daily_analysis_transitions = [
        json.loads(event.payload or "{}")
        for event in execution_events
        if event.event_type == "TASK_STATUS_CHANGED" and json.loads(event.payload or "{}").get("step_name") == DAILY_ANALYSIS_STEP
    ]
    assert any(item.get("from_status") == "blocked" and item.get("to_status") == "pending" and item.get("reason") == "step_requeued" for item in daily_analysis_transitions)

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    session.refresh(run)
    analysis_step = {step.name: step for step in run.steps}[DAILY_ANALYSIS_STEP]
    snapshot_ref = json.loads(analysis_step.output_json or "{}")["daily_analysis"]["snapshot_path"]
    snapshot = json.loads((tmp_path / snapshot_ref).read_text(encoding="utf-8"))
    assert snapshot["status"] == "partial"
    assert "vip_preview_only" in snapshot["quality_flags"]
    assert "vip_preview_only" in snapshot["risk_flags"]
    assert snapshot["key_articles"][0]["text_source"] == "preview"


def test_run_daily_analysis_followup_task_requeues_blocked_analysis_step_via_state_machine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    ensure_execution_tables(session)
    missing_profile = tmp_path / "missing-profile"
    monkeypatch.setenv("JIN10_BROWSER_PROFILE", str(missing_profile))
    run = _seed_followup_run(session)
    _route_run_to_vip_browser_fallback(session, run, storage_root=tmp_path)

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.status == TaskStatus.pending
    assert run.current_stage == DAILY_ANALYSIS_STEP
    steps = {step.name: step for step in run.steps}
    analysis_step = steps[DAILY_ANALYSIS_STEP]
    assert analysis_step.status == StepStatus.pending
    assert analysis_step.started_at is None
    assert analysis_step.finished_at is None
    assert analysis_step.blocked_reason is None

    execution_events = session.query(ExecutionEvent).order_by(ExecutionEvent.created_at.asc()).all()
    analysis_transitions = [
        json.loads(event.payload or "{}")
        for event in execution_events
        if event.event_type == "TASK_STATUS_CHANGED"
        and json.loads(event.payload or "{}").get("step_name") == DAILY_ANALYSIS_STEP
    ]
    assert any(
        item.get("from_status") == "blocked"
        and item.get("to_status") == "pending"
        and item.get("reason") == "step_requeued"
        for item in analysis_transitions
    )


def test_run_daily_analysis_followup_task_vip_browser_fallback_maps_fetcher_exception(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    profile_dir = tmp_path / "jin10-browser-profile"
    profile_dir.mkdir()
    monkeypatch.setenv("JIN10_BROWSER_PROFILE", str(profile_dir))
    run = _seed_followup_run(session)
    _route_run_to_vip_browser_fallback(session, run, storage_root=tmp_path)

    def fake_vip_fetcher(**kwargs):
        raise RuntimeError("Playwright is required for browser-profile Jin10 fetch.")

    status = run_daily_analysis_followup_task(
        session,
        run.id,
        storage_root=tmp_path,
        vip_browser_fetcher=fake_vip_fetcher,
    )

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.status == TaskStatus.pending
    assert run.current_stage == DAILY_ANALYSIS_STEP
    assert "partial snapshot" in (run.error_summary or "")
    steps = {step.name: step for step in run.steps}
    fallback_step = steps[VIP_BROWSER_FALLBACK_STEP]
    assert fallback_step.status == StepStatus.failed
    assert fallback_step.error_type == "browser_unavailable"
    assert fallback_step.retryable is False
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.success
    session.refresh(run)
    analysis_step = {step.name: step for step in run.steps}[DAILY_ANALYSIS_STEP]
    snapshot_ref = json.loads(analysis_step.output_json or "{}")["daily_analysis"]["snapshot_path"]
    snapshot = json.loads((tmp_path / snapshot_ref).read_text(encoding="utf-8"))
    assert snapshot["status"] == "partial"
    assert "vip_preview_only" in snapshot["quality_flags"]
    assert "vip_preview_only" in snapshot["risk_flags"]
    assert snapshot["key_articles"][0]["text_source"] == "preview"


def test_run_daily_analysis_followup_task_records_detail_fetch_failure(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    def fake_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=None,
            status="fetch_failed",
            access_status="unavailable",
            error_reason="TimeoutError: timed out",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)

    assert status == TaskStatus.failed
    session.refresh(run)
    assert run.status == TaskStatus.failed
    assert run.error_summary == "detail_fetch failed"
    steps = {step.name: step for step in run.steps}
    assert steps[DETAIL_FETCH_STEP].status == StepStatus.failed
    assert steps[DETAIL_FETCH_STEP].error_type == "network_timeout"
    assert steps[DETAIL_FETCH_STEP].retryable is True


def test_run_daily_analysis_followup_task_blocks_when_source_url_missing(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session, source_url=None)

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.blocked
    session.refresh(run)
    assert run.status == TaskStatus.blocked
    assert run.error_summary == "detail_fetch blocked: source_url is missing"
    steps = {step.name: step for step in run.steps}
    assert steps[DETAIL_FETCH_STEP].status == StepStatus.blocked
    assert steps[DETAIL_FETCH_STEP].blocked_reason == "follow-up has no source_url for detail fetch"
    assert steps[DETAIL_FETCH_STEP].error_type == "data_unavailable"


def test_run_daily_analysis_followup_task_fails_invalid_input_json(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session, input_json="{bad json")

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

    assert status == TaskStatus.failed
    session.refresh(run)
    assert run.status == TaskStatus.failed
    step = run.steps[0]
    assert step.status == StepStatus.failed
    assert step.error_type == "invalid_input_json"


def test_run_pending_daily_analysis_followup_tasks_refuses_implicit_pending_scan(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    eligible = _seed_followup_run(session)
    already_expanded = _seed_followup_run(session, source_url="https://xnews.jin10.com/details/2")
    already_expanded.current_stage = DETAIL_FETCH_STEP
    session.commit()

    payload = run_pending_daily_analysis_followup_tasks(session, storage_root=tmp_path)

    assert payload["status"] == "disabled"
    assert payload["reason"] == "explicit_task_ids_required"
    assert payload["matched_count"] == 0
    assert payload["processed_count"] == 0
    session.refresh(eligible)
    assert eligible.status == TaskStatus.pending
    assert eligible.current_stage == "news_followup"
    session.refresh(already_expanded)
    assert already_expanded.current_stage == DETAIL_FETCH_STEP
    assert len(already_expanded.steps) == 1


def test_run_selected_daily_analysis_followup_tasks_advances_all_stages_and_audits_them(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    ensure_execution_tables(session)
    run = _seed_followup_run(session)

    def fake_detail_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="readable",
            title="黄金日报",
            raw_text="黄金和美联储主线仍需重点跟进。",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/detail.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/detail.json",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    result = run_selected_daily_analysis_followup_tasks(
        session,
        [str(run.id)],
        storage_root=tmp_path,
        detail_fetcher=fake_detail_fetcher,
    )

    assert result["status"] == "success"
    assert result["processed_count"] == 1
    assert result["results"] == [
        {
            "task_id": str(run.id),
            "status": "completed",
            "task_status": "success",
            "current_stage": DAILY_ANALYSIS_STEP,
            "stages_processed": 3,
        }
    ]
    session.refresh(run)
    assert run.status == TaskStatus.success
    assert [step.status for step in sorted(run.steps, key=lambda item: item.step_order or 0)] == [
        StepStatus.success,
        StepStatus.success,
        StepStatus.skipped,
        StepStatus.success,
    ]
    events = session.query(ExecutionEvent).filter(ExecutionEvent.run_id == run.id).all()
    assert any(event.event_type == "RUN_STATUS_CHANGED" for event in events)


def test_run_selected_daily_analysis_followup_tasks_reports_waiting_at_stage_bound(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)

    result = run_selected_daily_analysis_followup_tasks(
        session,
        [run.id],
        storage_root=tmp_path,
        max_stage_steps=1,
    )

    assert result["results"][0] == {
        "task_id": str(run.id),
        "status": "waiting",
        "task_status": "pending",
        "current_stage": DETAIL_FETCH_STEP,
        "reason": "stage_step_limit_reached",
        "stages_processed": 1,
    }
    session.refresh(run)
    assert run.status == TaskStatus.pending
    assert run.current_stage == DETAIL_FETCH_STEP


def test_run_selected_daily_analysis_followup_tasks_returns_terminal_and_blocked_without_reexecution(
    tmp_path: Path,
) -> None:
    session = _make_db_session(tmp_path)
    terminal = _seed_followup_run(session)
    terminal.status = TaskStatus.success
    terminal.current_stage = DAILY_ANALYSIS_STEP
    session.commit()
    blocked = _seed_followup_run(session, source_url=None)

    result = run_selected_daily_analysis_followup_tasks(
        session,
        [str(terminal.id), str(blocked.id), str(blocked.id)],
        storage_root=tmp_path,
    )

    by_id = {item["task_id"]: item for item in result["results"]}
    assert result["unique_task_count"] == 2
    assert by_id[str(terminal.id)]["status"] == "terminal"
    assert by_id[str(terminal.id)]["stages_processed"] == 0
    assert by_id[str(blocked.id)]["status"] == "blocked"
    session.refresh(blocked)
    assert blocked.status == TaskStatus.blocked
    assert blocked.current_stage == DETAIL_FETCH_STEP


def test_run_selected_daily_analysis_followup_tasks_respects_no_jin10_switch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)

    def fetcher(**_kwargs):
        raise AssertionError("disabled Jin10 must not fetch")

    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")

    result = run_selected_daily_analysis_followup_tasks(
        session,
        [run.id],
        storage_root=tmp_path,
        detail_fetcher=fetcher,
    )

    assert result["results"][0]["status"] == "blocked"
    session.refresh(run)
    assert run.status == TaskStatus.blocked
    assert run.error_summary == "detail_fetch blocked: Jin10 is disabled"
    detail_step = next(step for step in run.steps if step.name == DETAIL_FETCH_STEP)
    assert detail_step.error_type == "source_disabled"
    assert detail_step.retryable is False


def test_run_selected_daily_analysis_followup_tasks_marks_worker_exception_and_step_audit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)

    def _raise(*_args, **_kwargs):
        raise RuntimeError("worker exploded")

    monkeypatch.setattr("apps.worker.pipelines.daily_analysis_followup.run_daily_analysis_followup_task", _raise)
    result = run_selected_daily_analysis_followup_tasks(session, [run.id], storage_root=tmp_path)

    assert result["results"][0]["status"] == "failed"
    assert result["results"][0]["reason"] == "worker_exception"
    session.refresh(run)
    assert run.status == TaskStatus.failed
    assert run.error_summary == "RuntimeError: worker exploded"
    assert run.steps[0].status == StepStatus.failed
    assert run.steps[0].error_type == "execution_error"
    assert run.steps[0].retryable is True


def test_run_selected_daily_analysis_followup_tasks_concurrent_starts_claim_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed_session = factory()
    run = _seed_followup_run(seed_session)
    task_id = run.id
    seed_session.close()

    worker_entered = threading.Event()
    release_worker = threading.Event()
    calls: list[str] = []
    calls_lock = threading.Lock()

    def _slow_worker(_db, selected_id, **_kwargs):
        with calls_lock:
            calls.append(str(selected_id))
        worker_entered.set()
        assert release_worker.wait(timeout=5)
        return TaskStatus.running

    monkeypatch.setattr("apps.worker.pipelines.daily_analysis_followup.run_daily_analysis_followup_task", _slow_worker)

    def _run_once():
        session = factory()
        try:
            return run_selected_daily_analysis_followup_tasks(session, [task_id], storage_root=tmp_path)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(_run_once)
        assert worker_entered.wait(timeout=5)
        second_future = executor.submit(_run_once)
        second = second_future.result(timeout=5)
        release_worker.set()
        first = first_future.result(timeout=5)

    assert calls == [str(task_id)]
    assert second["results"][0]["status"] == "already_running"
    assert first["results"][0]["status"] == "waiting"
    check_session = factory()
    try:
        persisted = check_session.get(TaskRun, task_id)
        assert persisted is not None
        assert persisted.status == TaskStatus.running
    finally:
        check_session.close()


def test_run_selected_daily_analysis_followup_tasks_rejects_unbounded_batch(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    task_ids = [str(uuid.uuid4()) for _ in range(MAX_SELECTED_FOLLOWUP_TASKS + 1)]

    result = run_selected_daily_analysis_followup_tasks(session, task_ids, storage_root=tmp_path)

    assert result == {
        "status": "rejected",
        "reason": "task_batch_too_large",
        "requested_count": MAX_SELECTED_FOLLOWUP_TASKS + 1,
        "unique_task_count": 0,
        "processed_count": 0,
        "results": [],
    }


def _route_run_to_vip_browser_fallback(session: Session, run: TaskRun, *, storage_root: Path) -> None:
    run_daily_analysis_followup_task(session, run.id, storage_root=storage_root)

    def fake_detail_fetcher(**kwargs):
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="vip_locked",
            title="VIP专享文章",
            raw_text="VIP专享文章",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/vip.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/vip.json",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    run_daily_analysis_followup_task(session, run.id, storage_root=storage_root, detail_fetcher=fake_detail_fetcher)
    session.refresh(run)
    assert run.current_stage == VIP_BROWSER_FALLBACK_STEP
