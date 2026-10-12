from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from dagster import build_op_context
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.collectors.news.jin10_detail_fetcher import Jin10DetailFetchResult
from database.models.execution import ensure_execution_tables
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep
from dagster_finance.definitions import defs
from dagster_finance.jobs.daily_analysis_followup_job import daily_analysis_followup_job
from dagster_finance.ops.daily_analysis_followup import (
    DailyAnalysisFollowupConfig,
    daily_analysis_followup_op,
)


def _seed_offline_followup(session) -> TaskRun:
    run = TaskRun(
        name="daily_analysis_followup:job-test",
        task_type="daily_analysis_followup",
        status=TaskStatus.pending,
        current_stage="news_followup",
        trade_date="2026-06-12",
    )
    session.add(run)
    session.flush()
    payload = {
        "date": "2026-06-12",
        "run_id": "job-test",
        "queue_source_artifact": "daily_analysis_triggers",
        "followup": {
            "followup_id": "job-test",
            "queue_type": "jin10_daily_analysis",
            "action": "run_jin10_daily_analysis",
            "source_url": "https://xnews.jin10.com/details/job-test",
            "source_artifact": "daily_analysis_triggers",
            "source_title": "离线测试新闻",
            "source_refs": [{"source": "jin10_feishu", "source_ref": "job-test"}],
            "evidence_text": "离线测试证据",
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
            input_json=json.dumps(payload, ensure_ascii=True),
            input_refs=json.dumps([], ensure_ascii=True),
            output_refs=json.dumps([], ensure_ascii=True),
            source_refs=json.dumps(payload["followup"]["source_refs"], ensure_ascii=True),
        )
    )
    session.commit()
    return run


def test_daily_analysis_followup_job_is_registered_without_a_schedule() -> None:
    job = defs.get_job_def("daily_analysis_followup_job")

    assert job.tags["pipeline"] == "daily_analysis_followup"
    assert job.tags["task_scope"] == "explicit_ids"
    assert all(schedule.job_name != job.name for schedule in defs.schedules)


def test_daily_analysis_followup_op_passes_only_explicit_ids_to_worker(monkeypatch) -> None:
    db_session = object()
    calls: list[dict] = []

    def _fake_worker(db, task_ids, **kwargs):
        calls.append({"db": db, "task_ids": list(task_ids), **kwargs})
        return {"status": "success", "requested_count": 1, "processed_count": 1, "results": []}

    monkeypatch.setattr(
        "dagster_finance.ops.daily_analysis_followup.run_selected_daily_analysis_followup_tasks",
        _fake_worker,
    )
    context = build_op_context(resources={"db_session": db_session})

    result = daily_analysis_followup_op(
        context,
        DailyAnalysisFollowupConfig(
            task_ids=["task-001"],
            storage_root="/tmp/followup-test-storage",
            max_stage_steps=3,
        ),
    )

    assert result["status"] == "success"
    assert calls == [
        {
            "db": db_session,
            "task_ids": ["task-001"],
            "storage_root": Path("/tmp/followup-test-storage"),
            "max_stage_steps": 3,
        }
    ]


def test_daily_analysis_followup_op_empty_ids_does_not_scan_or_call_worker(monkeypatch) -> None:
    worker = Mock(side_effect=AssertionError("empty config must not execute a worker"))
    monkeypatch.setattr(
        "dagster_finance.ops.daily_analysis_followup.run_selected_daily_analysis_followup_tasks",
        worker,
    )

    result = daily_analysis_followup_op(
        build_op_context(resources={"db_session": object()}),
        DailyAnalysisFollowupConfig(task_ids=[]),
    )

    assert result["status"] == "empty"
    assert result["results"] == []
    worker.assert_not_called()


def test_daily_analysis_followup_job_runs_real_worker_with_offline_detail_fetch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'job.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    ensure_execution_tables(session)
    run = _seed_offline_followup(session)
    monkeypatch.delenv("FINANCE_AGENT_DISABLE_JIN10", raising=False)

    def fake_detail_fetcher(**kwargs):
        assert kwargs["storage_root"] == tmp_path
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="readable",
            title="离线测试新闻",
            raw_text="离线详情文本",
            fetched_at="2026-06-12T00:00:00+00:00",
        )

    monkeypatch.setattr(
        "apps.worker.pipelines.daily_analysis_followup._default_detail_fetcher",
        lambda: fake_detail_fetcher,
    )
    monkeypatch.setattr(
        "apps.worker.pipelines.daily_analysis_followup._default_vip_browser_fetcher",
        lambda: (_ for _ in ()).throw(AssertionError("readable detail must not open browser")),
    )

    execution = daily_analysis_followup_job.execute_in_process(
        run_config={
            "ops": {
                "daily_analysis_followup_op": {
                    "config": {
                        "task_ids": [str(run.id)],
                        "storage_root": str(tmp_path),
                        "max_stage_steps": 4,
                    }
                }
            }
        },
        resources={"db_session": session},
    )

    assert execution.success is True
    session.expire_all()
    persisted = session.get(TaskRun, run.id)
    assert persisted is not None
    assert persisted.status == TaskStatus.success
    assert persisted.current_stage == "daily_analysis"
    assert execution.output_for_node("daily_analysis_followup_op")["results"][0]["status"] == "completed"
