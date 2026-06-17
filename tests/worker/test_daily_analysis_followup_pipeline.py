from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.pipelines.daily_analysis_followup import (
    DAILY_ANALYSIS_STEP,
    DETAIL_FETCH_STEP,
    VIP_BROWSER_FALLBACK_STEP,
    run_daily_analysis_followup_task,
    run_pending_daily_analysis_followup_tasks,
)
from apps.collectors.news.jin10_detail_fetcher import Jin10DetailFetchResult
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep


def _make_db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


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


def test_run_daily_analysis_followup_task_fetches_readable_detail_page(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    run = _seed_followup_run(session)
    run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path)

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
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/detail.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/detail.json",
            image_assets=[{"path": "raw/news/jin10_detail_pages/2026-06-12/images/01.png"}],
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    status = run_daily_analysis_followup_task(session, run.id, storage_root=tmp_path, detail_fetcher=fake_fetcher)

    assert status == TaskStatus.pending
    session.refresh(run)
    assert run.current_stage == DAILY_ANALYSIS_STEP
    assert run.progress == 0.6
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
    assert steps[VIP_BROWSER_FALLBACK_STEP].status == StepStatus.skipped
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending


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
    source_refs = json.loads(fallback_step.source_refs or "[]")
    assert any(item.get("source_name") == "jin10_vip_browser_fallback" for item in source_refs)
    assert steps[DAILY_ANALYSIS_STEP].status == StepStatus.pending


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


def test_run_pending_daily_analysis_followup_tasks_processes_initial_stage_only(tmp_path: Path) -> None:
    session = _make_db_session(tmp_path)
    eligible = _seed_followup_run(session)
    already_expanded = _seed_followup_run(session, source_url="https://xnews.jin10.com/details/2")
    already_expanded.current_stage = DETAIL_FETCH_STEP
    session.commit()

    payload = run_pending_daily_analysis_followup_tasks(session, storage_root=tmp_path)

    assert payload["status"] == "success"
    assert payload["matched_count"] == 1
    assert payload["processed_count"] == 1
    assert payload["results"][0]["run_id"] == str(eligible.id)
    session.refresh(already_expanded)
    assert already_expanded.current_stage == DETAIL_FETCH_STEP
    assert len(already_expanded.steps) == 1


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
