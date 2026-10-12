"""Warehouse semantic source oracle, separate from executor tests."""

from datetime import UTC, datetime
import json
import hashlib
import uuid
import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker
from database.models.analysis import ensure_analysis_tables, MarketCandle
from database.models.execution import ensure_execution_tables, RunArtifact
from database.models.task import ensure_task_tables, TaskRun, TaskStatus
from database.models import warehouse as model
from scripts import backfill_data_warehouse as cli

DATE = "2026-10-05"
RUN = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def fixture(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'news.sqlite'}")
    event.listen(engine, "connect", lambda c, r: c.execute("PRAGMA foreign_keys=ON"))
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    ensure_analysis_tables(engine)
    model.ensure_warehouse_tables(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(TaskRun(id=uuid.UUID(RUN), name="news", status=TaskStatus.degraded, trade_date=DATE))
        db.commit()
    yield engine, factory, tmp_path
    engine.dispose()


def registered(fixture, filename, body, artifactid=None, sha=None, prefix=""):
    engine, factory, root = fixture
    path = root / f"storage/features/news/{DATE}/{RUN}/{filename}"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(body, ensure_ascii=False).encode()
    path.write_bytes(data)
    with factory() as db:
        db.add(
            RunArtifact(
                artifact_id=uuid.UUID(artifactid) if artifactid else uuid.uuid4(),
                run_id=uuid.UUID(RUN),
                artifact_type="feature_json",
                file_path=prefix + f"features/news/{DATE}/{RUN}/{filename}",
                storage_backend="local_fs",
                sha256=sha or hashlib.sha256(data).hexdigest(),
                generated_at=datetime(2026, 10, 5, 6, tzinfo=UTC),
                created_at=datetime(2026, 10, 5, 7, tzinfo=UTC),
            )
        )
        db.commit()


def call(fixture, capsys, dataset):
    code = cli.main(
        ["--dataset", dataset, "--apply", "--limit", "100", "--storage-root", str(fixture[2] / "storage")],
        session_factory=fixture[1],
        project_root=fixture[2],
    )
    out = capsys.readouterr().out
    assert code in (0, 1, 2), out
    return json.loads(out.strip().splitlines()[-1])


def test_real_source_ref_source_and_source_url_are_fields_not_lost(fixture, capsys):
    registered(
        fixture,
        "event_candidates.json",
        {
            "as_of": "2026-10-05T06:00:00Z",
            "event_candidates": [
                {
                    "event_id": "fed-event",
                    "event_type": "fed_hawkish",
                    "event_status": "developing",
                    "event_time": "2026-10-02T06:00:00Z",
                    "verification_status": "single_source",
                    "need_verification": True,
                    "confidence": 0.4,
                    "source_count": 1,
                    "asset_tags": ["XAUUSD"],
                    "source_refs": [
                        {
                            "source": "fed_rss",
                            "source_ref": "fed:release",
                            "source_url": "https://example.test/fed",
                            "raw_path": "raw/fed/known.json",
                            "retrieved_at": "2026-10-05T05:00:00Z",
                        }
                    ],
                }
            ],
        },
    )
    result = call(fixture, capsys, "news-events")
    assert result.get("inserted") == 1
    with fixture[0].connect() as c:
        row = c.execute(
            text(
                "SELECT s.source_key,r.url,f.verification_status,f.need_verification,f.event_time FROM dwh_event_source_ref r JOIN dwh_dim_source s ON s.id=r.source_id JOIN dwh_fact_news_event f ON f.id=r.event_id"
            )
        ).one()
        assert row[:2] == ("fed_rss", "https://example.test/fed")
        assert row[2] == "single_source" and row[3] in (True, 1)
        assert str(row[4]).startswith("2026-10-02")


def test_empty_trigger_is_loaded_with_original_asof_and_zero_facts(fixture, capsys):
    registered(
        fixture,
        "daily_analysis_triggers.json",
        {
            "as_of": "2026-10-02T06:00:00Z",
            "triggers": [],
            "trigger_count": 0,
            "data_quality": {"rejected_event_count": 9},
        },
    )
    result = call(fixture, capsys, "news-triggers")
    assert result.get("inserted") == 0 and result.get("rejected") == 0
    with fixture[0].connect() as c:
        assert c.execute(text("SELECT count(*) FROM dwh_fact_news_trigger")).scalar() == 0
        row = c.execute(
            text(
                "SELECT status,as_of,source_trigger_count,source_rejected_count FROM dwh_load_batch WHERE dataset='news-triggers'"
            )
        ).one()
        assert row[0] == "loaded" and str(row[1]).startswith("2026-10-02") and row[2:] == (0, 9)


def test_known_gc_future_mislabeled_as_spot_is_quarantined(fixture, capsys):
    with fixture[1]() as db:
        db.add(
            MarketCandle(
                id="11111111-1111-4111-8111-111111111111",
                asset="XAUUSD",
                source="yahoo_finance_gc_f",
                timeframe="1d",
                open_time=datetime(2026, 10, 2, 6, tzinfo=UTC),
                open=3000,
                high=3001,
                low=2999,
                close=3000,
            )
        )
        db.commit()
    result = call(fixture, capsys, "candles")
    assert result.get("rejected", 0) == 1
    with fixture[0].connect() as c:
        assert c.execute(text("SELECT count(*) FROM dwh_fact_candle")).scalar() == 0
        assert c.execute(text("SELECT asset FROM market_candles")).scalar() == "XAUUSD"
