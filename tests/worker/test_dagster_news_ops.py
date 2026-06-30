from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem
from apps.worker.pipelines.news import NewsPipelineState
from dagster_finance.ops.news import NewsConfig, news_brief_op, news_collect_op, news_feature_op
from database.models.analysis import ensure_analysis_tables
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import TaskRun, TaskStatus, ensure_task_tables


class _FixedNewsDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 6, 10, 12, 31, tzinfo=timezone.utc)
        return value if tz is None else value.astimezone(tz)


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    ensure_analysis_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _raw_item(
    *,
    source_key: str,
    title: str,
    event_type: str,
    verification_status: str,
) -> RawNewsItem:
    return RawNewsItem(
        source_key=source_key,
        source_name=source_key,
        source_type="official",
        feed_key="test",
        title=title,
        url=f"https://example.test/{source_key}/{event_type}",
        domain="example.test",
        published_at="2026-06-10T12:00:00+00:00",
        fetched_at="2026-06-10T12:00:01+00:00",
        event_type=event_type,
        verification_status=verification_status,
        duplicate_key=f"news:{source_key}:{event_type}",
        raw_payload={"source_refs": [{"source": source_key, "source_ref": f"{source_key}:test"}]},
    )


def _fake_collectors():
    def official_collector(**_kwargs):
        return NewsCollectionResult(
            source_key="fed_rss",
            status="success",
            items=[
                _raw_item(
                    source_key="fed_rss",
                    title="Federal Reserve keeps hawkish rates guidance",
                    event_type="fed_hawkish",
                    verification_status="official_confirmed",
                )
            ],
            source_refs=[{"source": "fed_rss", "source_ref": "fed:test"}],
        )

    return [("fed_rss", official_collector)]


def test_news_dagster_ops_register_written_artifacts_in_run_artifact_registry(tmp_path: Path) -> None:
    session = _make_session()
    run_id = uuid.uuid4()
    session.add(
        TaskRun(
            id=run_id,
            name="premarket_job",
            task_type="premarket",
            status=TaskStatus.running,
            snapshot_id="news:2026-06-10",
            trade_date="2026-06-10",
        )
    )
    session.commit()
    context = SimpleNamespace(
        run_id=str(run_id),
        resources=SimpleNamespace(db_session=session),
        log=SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None),
    )

    with (
        patch("apps.worker.pipelines.news._collectors", return_value=_fake_collectors()),
        patch("apps.worker.pipelines.news.datetime", _FixedNewsDatetime),
    ):
        state = news_collect_op.compute_fn.decorated_fn(context, NewsPipelineState(), NewsConfig(storage_root=str(tmp_path)))
        state = news_feature_op.compute_fn.decorated_fn(context, state, NewsConfig(storage_root=str(tmp_path)))
        news_brief_op.compute_fn.decorated_fn(context, state, NewsConfig(storage_root=str(tmp_path)))

    artifacts = session.query(RunArtifact).order_by(RunArtifact.file_path.asc()).all()
    artifact_names = {Path(artifact.file_path).name for artifact in artifacts}
    assert artifact_names == {
        "collection_diagnostics.json",
        "daily_analysis_triggers.json",
        "daily_brief.json",
        "daily_brief.md",
        "daily_brief_input_snapshot.json",
        "daily_market_brief.json",
        "event_candidates.json",
        "impact_assessments.json",
        "market_reactions.json",
    }
    assert {artifact.run_id for artifact in artifacts} == {run_id}
    assert {artifact.artifact_type for artifact in artifacts} == {"analysis_md", "feature_json"}
    assert all(artifact.source_refs_data for artifact in artifacts)
    assert all(artifact.artifact_metadata["input_snapshot_ids"]["news"] == f"news:2026-06-10:{run_id}" for artifact in artifacts)
