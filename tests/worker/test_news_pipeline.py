from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem
from apps.worker.pipelines.news import NewsPipelineState, run_news_step
from database.models.analysis import MarketCandle, ensure_analysis_tables
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep
from tests.fixtures.news.replay import materialize_news_replay


@pytest.fixture(autouse=True)
def _isolate_source_gating():
    """Keep news worker tests deterministic unless they explicitly opt into source gating."""
    with patch("apps.api.services.source_service.get_data_source_status_index", return_value={}):
        yield


class _FixedNewsDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 6, 10, 12, 31, tzinfo=timezone.utc)
        return value if tz is None else value.astimezone(tz)


def _make_db_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _raw_item(
    *,
    source_key: str,
    source_type: str,
    title: str,
    event_type: str,
    verification_status: str,
) -> RawNewsItem:
    return RawNewsItem(
        source_key=source_key,
        source_name=source_key,
        source_type=source_type,
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
    def official_collector(**kwargs):
        return NewsCollectionResult(
            source_key="fed_rss",
            status="success",
            items=[
                _raw_item(
                    source_key="fed_rss",
                    source_type="official",
                    title="Federal Reserve keeps hawkish rates guidance",
                    event_type="fed_hawkish",
                    verification_status="official_confirmed",
                )
            ],
            source_refs=[{"source": "fed_rss", "source_ref": "fed:test"}],
        )

    def candidate_collector(**kwargs):
        return NewsCollectionResult(
            source_key="gdelt_news",
            status="success",
            items=[
                _raw_item(
                    source_key="gdelt_news",
                    source_type="aggregator",
                    title="Iran Hormuz shipping risk rises",
                    event_type="hormuz_risk",
                    verification_status="single_source",
                )
            ],
            source_refs=[{"source": "gdelt_news", "source_ref": "gdelt:test"}],
        )

    return [("fed_rss", official_collector), ("gdelt_news", candidate_collector)]


def test_news_pipeline_writes_event_and_brief_artifacts(tmp_path: Path) -> None:
    state = NewsPipelineState()

    with (
        patch("apps.worker.pipelines.news._collectors", return_value=_fake_collectors()),
        patch("apps.worker.pipelines.news.datetime", _FixedNewsDatetime),
    ):
        collect_summary = run_news_step("news_collect", state, storage_root=tmp_path, run_id="run-news")
        feature_summary = run_news_step("news_feature", state, storage_root=tmp_path, run_id="run-news")
        brief_summary = run_news_step("news_brief", state, storage_root=tmp_path, run_id="run-news")

    assert collect_summary["status"] == "success"
    assert collect_summary["raw_news_item_count"] == 2
    assert collect_summary["source_ref_count"] == 2
    assert collect_summary["artifact_path"] == f"features/news/{state.retrieved_date}/run-news/collection_diagnostics.json"
    assert feature_summary["event_candidate_count"] == 2
    assert brief_summary["confirmed_event_count"] == 1
    assert brief_summary["candidate_event_count"] == 1
    assert state.snapshot_dict is not None
    assert state.snapshot_dict["daily_market_brief"]["confirmed_events"][0]["verification_status"] == "official_confirmed"
    assert state.snapshot_dict["daily_analysis_triggers"]["trigger_count"] == 0
    assert state.snapshot_dict["daily_brief_input_snapshot"]["report_mode"] == "news_driven"
    assert state.snapshot_dict["daily_brief_output"]["status"] == "available"
    assert state.snapshot_dict["data_quality"]["daily_analysis_trigger_count"] == 0

    feature_dir = tmp_path / "features" / "news" / state.retrieved_date / "run-news"
    output_dir = tmp_path / "outputs" / "daily_brief" / state.retrieved_date / "run-news"
    diagnostics_payload = json.loads((feature_dir / "collection_diagnostics.json").read_text(encoding="utf-8"))
    assert (feature_dir / "event_candidates.json").exists()
    assert (feature_dir / "impact_assessments.json").exists()
    assert (feature_dir / "daily_market_brief.json").exists()
    assert (feature_dir / "daily_brief_input_snapshot.json").exists()
    assert (output_dir / "daily_brief.md").exists()
    assert (output_dir / "daily_brief.json").exists()
    assert brief_summary["daily_brief_input_snapshot_path"] == f"features/news/{state.retrieved_date}/run-news/daily_brief_input_snapshot.json"
    assert brief_summary["daily_brief_markdown_path"] == f"outputs/daily_brief/{state.retrieved_date}/run-news/daily_brief.md"
    assert brief_summary["daily_brief_json_path"] == f"outputs/daily_brief/{state.retrieved_date}/run-news/daily_brief.json"
    assert diagnostics_payload["retrieved_date"] == state.retrieved_date
    assert diagnostics_payload["run_id"] == "run-news"
    assert diagnostics_payload["source_ref_count"] == 2
    assert diagnostics_payload["summary"]["warning_count"] == 0
    assert diagnostics_payload["summary"]["warnings"] == []
    assert diagnostics_payload["collector_statuses"][0]["collector"] == "fed_rss"
    assert diagnostics_payload["latest_collector_status_by_collector"]["gdelt_news"]["status"] == "success"
    assert diagnostics_payload["latest_source_status_by_source_key"]["fed_rss"]["source_ref_count"] == 1
    assert diagnostics_payload["latest_source_status_by_source_key"]["gdelt_news"]["status"] == "unknown"
    assert diagnostics_payload["latest_source_status_by_source_key"]["gdelt_news"]["source_refs"] == [
        {"source_ref": "gdelt:test", "source": "gdelt_news"}
    ]


def test_news_pipeline_collect_checkpoint_skips_seen_items_on_rerun(tmp_path: Path) -> None:
    with (
        patch("apps.worker.pipelines.news._collectors", return_value=_fake_collectors()),
        patch("apps.worker.pipelines.news.datetime", _FixedNewsDatetime),
    ):
        first_state = NewsPipelineState()
        first_summary = run_news_step("news_collect", first_state, storage_root=tmp_path, run_id="run-news-1")

        second_state = NewsPipelineState()
        second_summary = run_news_step("news_collect", second_state, storage_root=tmp_path, run_id="run-news-2")

    checkpoint_path = tmp_path / "state" / "news_collection_checkpoints.json"
    checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    assert first_summary["raw_news_item_count"] == 2
    assert first_summary["collected_raw_news_item_count"] == 2
    assert first_summary["skipped_duplicate_item_count"] == 0
    assert second_summary["raw_news_item_count"] == 0
    assert second_summary["collected_raw_news_item_count"] == 2
    assert second_summary["skipped_duplicate_item_count"] == 2
    assert second_summary["collection_checkpoint_path"] == "state/news_collection_checkpoints.json"
    assert checkpoint_payload["sources"]["fed_rss"]["last_success_at"] == "2026-06-10T12:31:00+00:00"
    assert checkpoint_payload["sources"]["gdelt_news"]["last_accepted_item_count"] == 0
    assert checkpoint_payload["sources"]["gdelt_news"]["last_skipped_duplicate_item_count"] == 1


def test_news_pipeline_collect_checkpoint_survives_later_collector_failure(tmp_path: Path) -> None:
    def broken_collector(**kwargs):
        raise RuntimeError("network disconnected")

    with (
        patch("apps.worker.pipelines.news._collectors", return_value=[*_fake_collectors()[:1], ("broken_news", broken_collector)]),
        patch("apps.worker.pipelines.news.datetime", _FixedNewsDatetime),
    ):
        state = NewsPipelineState()
        summary = run_news_step("news_collect", state, storage_root=tmp_path, run_id="run-news")

    checkpoint_payload = json.loads((tmp_path / "state" / "news_collection_checkpoints.json").read_text(encoding="utf-8"))

    assert summary["status"] == "partial_success"
    assert summary["raw_news_item_count"] == 1
    assert checkpoint_payload["sources"]["fed_rss"]["last_status"] == "success"
    assert checkpoint_payload["sources"]["fed_rss"]["last_success_at"] == "2026-06-10T12:31:00+00:00"
    assert checkpoint_payload["sources"]["broken_news"]["last_status"] == "failed"
    assert checkpoint_payload["sources"]["broken_news"]["error"] == "RuntimeError: network disconnected"


def test_news_pipeline_feature_step_wires_report_events_and_market_reactions(tmp_path: Path) -> None:
    state = NewsPipelineState()
    session = _make_db_session(tmp_path)
    session.add_all(
        [
            MarketCandle(
                asset="WTI",
                timeframe="1m",
                open_time=datetime(2026, 6, 10, 11, 59, tzinfo=timezone.utc),
                open=80.0,
                high=80.0,
                low=80.0,
                close=80.0,
                source="fixture",
            ),
            MarketCandle(
                asset="WTI",
                timeframe="1m",
                open_time=datetime(2026, 6, 10, 12, 30, tzinfo=timezone.utc),
                open=80.7,
                high=80.7,
                low=80.7,
                close=80.7,
                source="fixture",
            ),
            MarketCandle(
                asset="DXY",
                timeframe="1m",
                open_time=datetime(2026, 6, 10, 11, 59, tzinfo=timezone.utc),
                open=104.0,
                high=104.0,
                low=104.0,
                close=104.0,
                source="fixture",
            ),
            MarketCandle(
                asset="DXY",
                timeframe="1m",
                open_time=datetime(2026, 6, 10, 12, 30, tzinfo=timezone.utc),
                open=104.15,
                high=104.15,
                low=104.15,
                close=104.15,
                source="fixture",
            ),
            MarketCandle(
                asset="US10Y",
                timeframe="1m",
                open_time=datetime(2026, 6, 10, 11, 59, tzinfo=timezone.utc),
                open=4.40,
                high=4.40,
                low=4.40,
                close=4.40,
                source="fixture",
            ),
            MarketCandle(
                asset="US10Y",
                timeframe="1m",
                open_time=datetime(2026, 6, 10, 12, 30, tzinfo=timezone.utc),
                open=4.45,
                high=4.45,
                low=4.45,
                close=4.45,
                source="fixture",
            ),
        ]
    )
    session.commit()

    materialize_news_replay(tmp_path, scenario="manual_news_p011_live", include_outputs=True, include_features=False, include_collectors=False)

    with (
        patch("apps.worker.pipelines.news._collectors", return_value=_fake_collectors()),
        patch("apps.worker.pipelines.news.datetime", _FixedNewsDatetime),
    ):
        run_news_step("news_collect", state, storage_root=tmp_path, run_id="run-news")
        feature_summary = run_news_step("news_feature", state, storage_root=tmp_path, run_id="run-news", db_session=session)
        brief_summary = run_news_step("news_brief", state, storage_root=tmp_path, run_id="run-news")

    feature_dir = tmp_path / "features" / "news" / state.retrieved_date / "run-news"
    report_events_payload = json.loads((feature_dir / "report_events.json").read_text(encoding="utf-8"))
    market_reactions_payload = json.loads((feature_dir / "market_reactions.json").read_text(encoding="utf-8"))
    brief_payload = json.loads((feature_dir / "daily_market_brief.json").read_text(encoding="utf-8"))

    assert feature_summary["report_event_count"] >= 2
    assert feature_summary["market_reaction_count"] >= 1
    assert brief_summary["candidate_event_count"] >= 2
    assert report_events_payload["source_key"] == "jin10_report_events"
    assert report_events_payload["items"]
    assert market_reactions_payload["market_reactions"]
    first_reaction = market_reactions_payload["market_reactions"][0]
    assert "5m" in first_reaction["windows"]
    assert first_reaction["market_snapshot"]["requested_assets"][:5] == ["XAUUSD", "DXY", "US10Y", "WTI", "USDJPY"]
    report_event_types = {item["event_type"] for item in report_events_payload["items"]}
    brief_candidate_types = {
        item["event_type"] for item in brief_payload["daily_market_brief"]["candidate_events"]
    }
    assert report_event_types <= brief_candidate_types
    assert brief_payload["daily_market_brief"]["asset_reactions"]
    assert any(
        item.get("market_validation", {}).get("market_snapshot", {}).get("primary_window") == "5m"
        for item in brief_payload["daily_market_brief"]["candidate_events"]
    )
    assert any(item["asset"] == "WTI" for item in brief_payload["daily_market_brief"]["asset_reactions"])


def test_news_pipeline_feature_step_writes_jin10_daily_analysis_triggers(tmp_path: Path) -> None:
    state = NewsPipelineState()

    def jin10_collector(**kwargs):
        return NewsCollectionResult(
            source_key="jin10_feishu",
            status="success",
            items=[
                RawNewsItem(
                    source_key="jin10_feishu",
                    source_name="Jin10 Feishu Chat Pull",
                    source_type="supplemental",
                    feed_key="oc_jin10",
                    title=(
                        "能源推升通胀数据，美联储已难兑现宽松。黄金乐观情绪被清除，短期动量仍为负。"
                        "多头交易仍需等新的催化剂，收复4500是第一道槛。"
                    ),
                    url="https://xnews.jin10.com/details/trigger",
                    domain="xnews.jin10.com",
                    published_at="2026-06-11T12:00:00+00:00",
                    fetched_at="2026-06-11T12:00:01+00:00",
                    summary=(
                        "能源推升通胀数据，美联储已难兑现宽松。黄金乐观情绪被清除，短期动量仍为负。"
                        "多头交易仍需等新的催化剂，收复4500是第一道槛。"
                    ),
                    source_country="CN",
                    source_language="zh-CN",
                    event_type="fed_hawkish",
                    verification_status="single_source",
                    duplicate_key="news:jin10_feishu:daily-trigger",
                    raw_payload={
                        "relevance_decision": {
                            "decision": "high_value",
                            "score": 0.86,
                            "asset_tags": ["XAUUSD", "DXY", "US02Y", "US10Y"],
                            "topic_tags": ["gold", "macro", "rates"],
                        },
                        "source_refs": [
                            {
                                "source": "jin10_feishu",
                                "source_ref": "jin10_feishu:oc_jin10:om_trigger",
                            }
                        ],
                    },
                )
            ],
            source_refs=[{"source": "jin10_feishu", "source_ref": "jin10_feishu:oc_jin10"}],
        )

    with patch("apps.worker.pipelines.news._collectors", return_value=[("jin10_feishu", jin10_collector)]):
        run_news_step("news_collect", state, storage_root=tmp_path, run_id="run-news")
        feature_summary = run_news_step("news_feature", state, storage_root=tmp_path, run_id="run-news")
        run_news_step("news_brief", state, storage_root=tmp_path, run_id="run-news")

    feature_dir = tmp_path / "features" / "news" / state.retrieved_date / "run-news"
    trigger_payload = json.loads((feature_dir / "daily_analysis_triggers.json").read_text(encoding="utf-8"))
    assert feature_summary["daily_analysis_trigger_count"] == 1
    assert feature_summary["daily_analysis_triggers_path"] == f"features/news/{state.retrieved_date}/run-news/daily_analysis_triggers.json"
    assert state.daily_analysis_triggers is not None
    assert state.snapshot_dict is not None
    assert state.snapshot_dict["daily_analysis_triggers"]["trigger_count"] == 1
    assert state.snapshot_dict["daily_analysis_triggers"]["triggers"][0]["trigger_type"] == "jin10_daily_analysis"
    assert trigger_payload["trigger_count"] == 1
    assert trigger_payload["triggers"][0]["priority"] == "high"
    assert trigger_payload["triggers"][0]["suggested_actions"][2] == "run_jin10_daily_analysis"


def test_run_premarket_executes_news_steps_and_snapshot_contains_brief(tmp_path: Path) -> None:
    db = _make_db_session(tmp_path)
    task = TaskRun(name="premarket", status=TaskStatus.pending)
    db.add(task)
    db.flush()
    for name in ["macro_collect", "macro_feature", "report_render", "news_collect", "news_feature", "news_brief"]:
        db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))
    db.commit()

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": "2026-06-10",
                "indicators": {"DGS10": {"value": 4.4, "unit": "percent"}},
                "source_refs": [],
            }
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.pipelines.news._collectors", return_value=_fake_collectors()),
        patch("apps.worker.pipelines.news.datetime", _FixedNewsDatetime),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success
    db.refresh(task)
    steps = {step.name: step for step in task.steps}
    assert steps["news_collect"].status == StepStatus.success
    assert steps["news_feature"].status == StepStatus.success
    assert steps["news_brief"].status == StepStatus.success

    snapshot_candidates = list((tmp_path / "features" / "snapshots" / "XAUUSD").glob("*/" + str(task.id) + "/premarket_snapshot.json"))
    assert len(snapshot_candidates) == 1
    snapshot = json.loads(snapshot_candidates[0].read_text(encoding="utf-8"))
    assert snapshot["news"]["status"] == "available"
    assert snapshot["news"]["data"]["daily_market_brief"]["confirmed_events"][0]["event_id"].startswith("event:fed_hawkish:")
    assert snapshot["news"]["data"]["daily_analysis_triggers"]["trigger_count"] == 0
    assert snapshot["news"]["data"]["daily_brief_input_snapshot"]["report_mode"] == "news_driven"
    assert snapshot["news"]["data"]["daily_brief_output"]["status"] == "available"
