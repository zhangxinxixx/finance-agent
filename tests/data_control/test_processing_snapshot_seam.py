from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.data_control.data_control_agent import run_data_control_agent
from apps.data_control.gold_processing_context import GoldProcessingContext
from apps.data_control.processing_planner import build_processing_plan
from apps.runtime.premarket_snapshot_authority import stage_premarket_snapshot_authority
from database.models.analysis import AnalysisBase
from database.models.execution import ExecutionBase
from database.models.task import Base, TaskRun, TaskStatus


TRADE_DATE = "2026-08-11"
OBSERVED_AT = datetime(2026, 8, 11, 8, 30, tzinfo=UTC)
SNAPSHOT_TIME = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)


def _factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ExecutionBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _payload(
    run_id: str,
    *,
    snapshot_time: datetime | None = SNAPSHOT_TIME,
    core: bool = True,
    jin10_technical: bool = False,
) -> dict:
    payload = {
        "asset": "XAUUSD",
        "trade_date": TRADE_DATE,
        "run_id": run_id,
        "snapshot_id": f"XAUUSD:{TRADE_DATE}:{run_id}",
        "input_snapshot_ids": {"macro": f"macro:{TRADE_DATE}:{run_id}"},
        "source_refs": [],
    }
    if snapshot_time is not None:
        payload["snapshot_time"] = snapshot_time.isoformat()
    if core:
        timestamp = snapshot_time.isoformat() if snapshot_time is not None else TRADE_DATE
        payload["macro"] = {
            "status": "available",
            "data": {
                "indicators": {
                    "US02Y": {"value": 3.9, "date": timestamp},
                    "US10Y": {"value": 4.2, "date": timestamp},
                    "US30Y": {"value": 4.5, "date": timestamp},
                    "T10YIE": {"value": 2.1, "date": timestamp},
                    "BROAD_DOLLAR": {"value": 120.0, "date": timestamp},
                }
            },
        }
        payload["technical"] = {
            "status": "available",
            "data": {"xauusd": {"price": 2400.0, "as_of": timestamp}},
        }
        payload["futures"] = {"status": "available", "data": {"gc_futures": {"value": 2401.0, "date": timestamp}}}
        payload["oil"] = {
            "status": "available",
            "data": {"schema_version": "oil_snapshot.v1"},
        }
        for symbol, value in (("wti", 75.0), ("brent", 78.0)):
            payload["oil"]["data"][symbol] = {
                "asset": symbol.upper(),
                "series_id": symbol.upper(),
                "market_role": "oil",
                "timeframe": "1d",
                "value": value,
                "close": value,
                "bar_open_time": (SNAPSHOT_TIME - timedelta(days=1)).isoformat(),
                "bar_close_time": timestamp,
                "freshness_status": "fresh",
                "quality_status": "accepted",
                "alignment_status": "aligned",
                "source_refs": [
                    {
                        "source": "oil_provider",
                        "reference": f"{symbol}:{TRADE_DATE}",
                        "retrieved_at": timestamp,
                    }
                ],
            }
        payload["etf_flow"] = {"status": "available", "data": {"etf_flow": {"value": 1.0, "date": timestamp}}}
        payload["positioning"] = {"status": "available", "data": {"cot": {"value": 10.0, "date": timestamp}}}
    if jin10_technical:
        payload["technical"] = {
            "status": "available",
            "data": {
                "xauusd": {
                    "price": 2400.0,
                    "as_of": SNAPSHOT_TIME.isoformat(),
                    "source_refs": [
                        {
                            "source": "jin10_mcp_derived_5m",
                            "reference": "jin10:spot",
                            "retrieved_at": SNAPSHOT_TIME.isoformat(),
                        }
                    ],
                }
            },
        }
    return payload


def _stage(
    factory: sessionmaker[Session],
    storage_root: Path,
    *,
    payload: dict,
) -> None:
    run = TaskRun(
        id=uuid.UUID(payload["run_id"]),
        name="premarket",
        task_type="premarket",
        status=TaskStatus.running,
    )
    path = storage_root / "features" / "snapshots" / "XAUUSD" / TRADE_DATE / payload["run_id"] / "premarket_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with factory() as session:
        session.add(run)
        session.flush()
        stage_premarket_snapshot_authority(
            session,
            run_id=payload["run_id"],
            snapshot=payload,
            snapshot_path=path,
            storage_root=storage_root,
        )
        run.status = TaskStatus.success
        session.commit()


def test_agent_uses_db_authority_and_keeps_authority_and_feature_ids(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    run_id = str(uuid.uuid4())
    payload = _payload(run_id)
    _stage(factory, storage_root, payload=payload)

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )

    gold = result["gold_processing"]
    assert gold["authority"]["status"] == "found"
    assert gold["authority"]["snapshot_id"] == payload["snapshot_id"]
    assert gold["feature"]["snapshot_id"].startswith("feature_snapshot.v2:")
    assert gold["authority"]["snapshot_id"] != gold["feature"]["snapshot_id"]
    assert gold["cutoff"] == SNAPSHOT_TIME.isoformat()
    assert gold["source_refs"][0]["source"] == "analysis_snapshot"

    artifact = json.loads(
        (storage_root / result["artifacts"]["processing_plan"]).read_text(encoding="utf-8")
    )
    assert artifact["quality_gate_evaluation"]["status"] == "current"
    assert artifact["quality_gate_evaluation"]["cutoff"] == SNAPSHOT_TIME.isoformat()
    assert artifact["quality_gate"]["capabilities"]["full_daily_analysis"] == "allowed"
    assert artifact["quality_gate"]["capabilities"]["options_structure_analysis"] == "blocked"
    assert artifact["quality_gate"]["knowledge_distillation_source"] == "unknown"


def test_core_missing_blocks_direction_but_cme_missing_does_not_block_macro(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    run_id = str(uuid.uuid4())
    _stage(factory, storage_root, payload=_payload(run_id))
    ready_result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert ready_result["main_analysis_readiness"] == "ready"
    assert ready_result["gold_limits"]["options"] == "blocked"

    missing_root = tmp_path / "missing-storage"
    missing_factory = _factory(tmp_path)
    missing_run_id = str(uuid.uuid4())
    _stage(missing_factory, missing_root, payload=_payload(missing_run_id, core=False))
    missing_result = run_data_control_agent(
        storage_root=missing_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=missing_factory,
    )
    assert missing_result["main_analysis_readiness"] == "blocked"
    assert "DIRECTIONAL_ANALYSIS" in missing_result["gold_limits"]["blocked_outputs"]


def test_future_snapshot_is_rejected_without_midnight_fallback(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    run_id = str(uuid.uuid4())
    _stage(
        factory,
        storage_root,
        payload=_payload(run_id, snapshot_time=OBSERVED_AT + timedelta(minutes=1)),
    )

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert result["gold_authority"]["status"] == "invalid"
    assert result["gold_authority"]["reason_code"] == "authority_snapshot_time_future"
    assert result["main_analysis_readiness"] == "blocked"


def test_snapshot_cutoff_date_must_match_requested_trade_date(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    run_id = str(uuid.uuid4())
    _stage(
        factory,
        storage_root,
        payload=_payload(run_id, snapshot_time=SNAPSHOT_TIME - timedelta(days=1)),
    )

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert result["gold_authority"]["status"] == "invalid"
    assert result["gold_authority"]["reason_code"] == "authority_snapshot_trade_date_mismatch"
    assert result["main_analysis_readiness"] == "blocked"


def test_hash_tamper_and_ambiguous_authority_are_rejected(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    first_id = str(uuid.uuid4())
    first_payload = _payload(first_id)
    _stage(factory, storage_root, payload=first_payload)
    path = storage_root / "features" / "snapshots" / "XAUUSD" / TRADE_DATE / first_id / "premarket_snapshot.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    tampered = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert tampered["gold_authority"]["reason_code"] == "authority_integrity_invalid"

    second_id = str(uuid.uuid4())
    _stage(factory, storage_root, payload=_payload(second_id))
    ambiguous = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert ambiguous["gold_authority"]["status"] == "ambiguous"
    assert ambiguous["gold_authority"]["reason_code"] == "multiple_successful_premarket_runs"


def test_all_source_no_jin10_skips_legacy_inputs_and_collection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    run_id = str(uuid.uuid4())
    _stage(factory, storage_root, payload=_payload(run_id, jin10_technical=True))
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert result["gold_authority"]["reason_code"] == "jin10_input_disabled"
    assert result["disabled_sources"]
    collection = json.loads(
        (storage_root / result["artifacts"]["collection_plan"]).read_text(encoding="utf-8")
    )
    dispatch = json.loads(
        (storage_root / result["artifacts"]["dispatch_plan"]).read_text(encoding="utf-8")
    )
    assert all(not str(item["source_key"]).startswith("jin10_") for item in collection["actions"])
    assert all(not str(item["source_key"]).startswith("jin10_") for item in dispatch["requests"])


def test_no_jin10_ignores_unconsumed_legacy_technical_when_formal_market_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    run_id = str(uuid.uuid4())
    payload = _payload(run_id, jin10_technical=True)
    timestamp = SNAPSHOT_TIME.isoformat()
    payload["market_prices"] = {"status": "available", "data": {"schema_version": "market_price_snapshot.v1"}}
    for field, series_id, role, asset, value in (
        ("xauusd_spot", "XAUUSD_SPOT", "spot", "XAUUSD", 2400.0),
        ("gc_futures", "GC_FUTURES", "futures", "GC", 2401.0),
    ):
        payload["market_prices"]["data"][field] = {
            "asset": asset,
            "series_id": series_id,
            "market_role": role,
            "timeframe": "5m" if field == "xauusd_spot" else "1d",
            "value": value,
            "close": value,
            "bar_open_time": (SNAPSHOT_TIME - timedelta(minutes=5)).isoformat(),
            "bar_close_time": timestamp,
            "freshness_status": "fresh",
            "quality_status": "accepted",
            "alignment_status": "aligned",
            "source_refs": [
                {"source": "market_provider", "reference": field, "retrieved_at": timestamp}
            ],
        }
    _stage(factory, storage_root, payload=payload)
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert result["gold_authority"]["status"] == "found"
    assert result["gold_authority"]["reason_code"] == "authoritative_premarket_snapshot_found"


@pytest.mark.parametrize(
    "jin10_reference",
    ["storage/raw/jin10/spot.json", "https://www.jin10.com/spot/1"],
)
def test_no_jin10_blocks_nested_formal_market_jin10_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jin10_reference: str
) -> None:
    storage_root = tmp_path / "storage"
    factory = _factory(tmp_path)
    run_id = str(uuid.uuid4())
    payload = _payload(run_id)
    payload["market_prices"] = {
        "status": "available",
        "data": {
            "schema_version": "market_price_snapshot.v1",
            "xauusd_spot": {
                "source_refs": [
                    {
                        "source": "jin10_mcp_derived_5m",
                        "reference": jin10_reference,
                        "retrieved_at": SNAPSHOT_TIME.isoformat(),
                    }
                ]
            },
        },
    }
    _stage(factory, storage_root, payload=payload)
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")

    result = run_data_control_agent(
        storage_root=storage_root,
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT,
        record_task_run=False,
        session_factory=factory,
    )
    assert result["gold_authority"]["status"] == "invalid"
    assert result["gold_authority"]["reason_code"] == "jin10_input_disabled"
    assert result["main_analysis_readiness"] == "blocked"


def test_planner_projects_gold_strategy_and_options_without_event_capability_alias(tmp_path: Path) -> None:
    context = GoldProcessingContext(
        authority_status="found",
        authority_reason_code="authoritative_premarket_snapshot_found",
        authority_snapshot_id="XAUUSD:2026-08-11:run",
        feature_snapshot_id="feature_snapshot.v2:feature",
        readiness={
            "analysis_readiness": "ready",
            "strategy_readiness": "observe",
            "options_readiness": "blocked",
            "event_attribution_readiness": "observe",
            "missing_required_inputs": [],
            "missing_confirmatory_inputs": [],
            "prohibited_outputs": ["OPTIONS_CONFIRMATION", "TRIGGERED_STRATEGY", "CONFIRMED_EVENT_ATTRIBUTION"],
            "reason_codes": [],
        },
        gold_source_ref={"source": "analysis_snapshot", "source_ref": "snapshot"},
    )
    plan = build_processing_plan(
        storage_root=tmp_path / "storage",
        trade_date=TRADE_DATE,
        observed_at=OBSERVED_AT.isoformat(),
        gold_context=context,
    )

    assert plan["quality_gate"]["capabilities"]["full_daily_analysis"] == "allowed"
    assert plan["quality_gate"]["capabilities"]["technical_trigger_confirmation"] == "degraded"
    assert plan["quality_gate"]["capabilities"]["options_structure_analysis"] == "blocked"
    event_limits = [item for item in plan["blocked_steps"] if item.get("step") == "run_confirmed_event_attribution"]
    assert event_limits and event_limits[0]["capability"] is None
    assert not any(item.get("capability") == "research_report_interpretation" for item in event_limits)
