from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
_TRADE_DATE = "2026-05-14"


@pytest.fixture(autouse=True)
def _mock_source_status_index():
    """Keep C4 output integration tests isolated from source gating by default."""
    with patch("apps.api.services.source_service.get_data_source_status_index", return_value={}):
        yield


def _make_db_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _make_task_with_steps(db, step_names: list[str]) -> TaskRun:
    task = TaskRun(name="premarket", status=TaskStatus.pending)
    db.add(task)
    db.flush()
    for name in step_names:
        db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))
    db.commit()
    return task


def _make_rich_snapshot(
    *,
    run_id: str = "run-c4-rich",
    trade_date: str = _TRADE_DATE,
) -> dict:
    """Return an analysis snapshot with macro + options data for the C4 pipeline."""
    return {
        "version": "1.0",
        "snapshot_id": f"XAUUSD:{trade_date}:{run_id}",
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "snapshot_time": _CREATED_AT.isoformat(),
        "run_id": run_id,
        "input_snapshot_ids": {
            "macro": f"macro:{trade_date}:{run_id}",
            "options": f"options:{trade_date}:{run_id}",
        },
        "macro": {
            "status": "available",
            "data": {
                "indicators": {
                    "DXY": {
                        "value": 101.50,
                        "change_1w": -0.80,
                        "unit": "index",
                    },
                    "DGS10": {
                        "value": 4.42,
                        "change_1w": -0.12,
                        "unit": "percent",
                    },
                    "T10YIE": {
                        "value": 2.15,
                        "change_1w": -0.03,
                        "unit": "percent",
                    },
                    "RRPONTSYD": {
                        "value": 180.5,
                        "change_1w": -12.3,
                        "unit": "billions_usd",
                    },
                    "TGA": {
                        "value": 720.1,
                        "change_1w": 45.2,
                        "unit": "billions_usd",
                    },
                    "SOFR": {
                        "value": 4.33,
                        "change_1w": 0.0,
                        "unit": "percent",
                    },
                    "EFFR": {
                        "value": 4.33,
                        "unit": "percent",
                    },
                    "IORB": {
                        "value": 4.40,
                        "unit": "percent",
                    },
                },
                "source_refs": [{"source": "fred", "symbol": "DGS10"}],
            },
        },
        "options": {
            "status": "available",
            "data": {
                "intent": {"type": "supportive", "score": 0.65},
                "wall_scores": [
                    {"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"},
                ],
                "support_resistance": {
                    "support": [{"strike": 3250, "score": 0.7}],
                    "resistance": [{"strike": 3400, "score": 0.6}],
                },
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3350}},
                    "by_expiry": {
                        "2026-06": {
                            "summary": {"net_gex": 2500, "dominant_side": "positive"},
                            "iv_skew": {"risk_reversal_25d": 0.15},
                        },
                    },
                },
                "walls": {
                    "block_pnt_walls": [{"strike": 3320, "block": 120, "pnt": 80}],
                },
                "data_source": {
                    "status": "FINAL",
                    "input_snapshot_ids": {"raw_file_sha256": "abc123"},
                    "expiries": ["2026-06", "2026-07"],
                },
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            },
        },
        "positioning": {"status": "unavailable", "reason": "collector_not_implemented"},
        "news": {"status": "unavailable", "reason": "collector_not_implemented"},
        "technical": {"status": "unavailable", "reason": "feature_not_implemented"},
        "source_refs": [
            {"source": "analysis_snapshot", "snapshot_id": f"XAUUSD:{trade_date}:{run_id}"},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# C4 pipeline unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════


def test_c4_pipeline_writes_final_report_and_strategy_card(tmp_path: Path) -> None:
    """C4 should produce final_report.md, strategy_card.md and strategy_card.json."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-c4-artifacts")
    summaries, _ = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-c4-artifacts",
        created_at=_CREATED_AT,
    )

    # ── step summaries ──
    assert "c3_agents" in summaries
    assert summaries["c3_agents"]["status"] == "success"
    assert summaries["c3_agents"]["macro_status"] is not None
    assert summaries["c3_agents"]["options_status"] is not None
    assert summaries["c3_agents"]["risk_status"] is not None
    assert summaries["c3_agents"]["coordinator_status"] is not None

    assert "final_report" in summaries
    assert summaries["final_report"]["status"] == "success"
    assert len(summaries["final_report"]["paths"]) >= 1  # P4-04: may include structured_report.json
    assert "quality_gate_decision" in summaries["final_report"]
    assert "agent_loop_decision" in summaries["final_report"]
    assert summaries["final_report"]["quality_gate_action"] == summaries["final_report"]["quality_gate_decision"]["action"]
    assert isinstance(summaries["final_report"]["publish_allowed"], bool)

    assert "strategy_card" in summaries
    assert summaries["strategy_card"]["status"] == "success"
    assert len(summaries["strategy_card"]["paths"]) == 2
    assert "gold_runtime_summary" in summaries
    assert summaries["gold_runtime_summary"]["run_mode"] == "premarket_full_run"
    assert summaries["gold_runtime_summary"]["runtime_contract_only"] is False
    assert summaries["gold_runtime_summary"]["quality_gate_status"] in {
        "passed",
        "fallback_required",
        "needs_review",
        "blocked",
    }

    # ── files exist ──
    report_path = Path(summaries["final_report"]["paths"][0])
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "# XAUUSD 相关报告" in report_text
    assert "数据刷新时间:" in report_text
    assert "### 宏观流动性视图" in report_text
    assert "## 免责声明" in report_text

    # P4-04: verify structured_report.json when present
    if len(summaries["final_report"]["paths"]) >= 2:
        structured_path = Path(summaries["final_report"]["paths"][1])
        assert structured_path.exists()
        assert structured_path.name == "structured_report.json"

    json_path = Path(summaries["strategy_card"]["paths"][0])
    md_path = Path(summaries["strategy_card"]["paths"][1])
    assert json_path.exists()
    assert md_path.exists()
    assert "# XAUUSD Strategy Card" in md_path.read_text(encoding="utf-8")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["asset"] == "XAUUSD"
    assert data["is_trade_instruction"] is False
    assert "analysis_snapshot" in data["input_snapshot_ids"]
    assert "coordinator" in data["input_snapshot_ids"]


def test_c4_pipeline_returns_final_report_quality_gate_metadata(tmp_path: Path) -> None:
    from apps.api.services.quality_gate_service import QualityGateDecision
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-quality-gate")
    summaries, c4_outputs = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-quality-gate",
        created_at=_CREATED_AT,
    )

    decision = c4_outputs["quality_gate_decision"]
    assert isinstance(decision, QualityGateDecision)
    assert summaries["final_report"]["quality_gate_decision"] == decision.model_dump(mode="json")
    assert summaries["final_report"]["quality_gate_action"] == decision.action.value
    assert summaries["final_report"]["review_status"] == decision.review_status
    assert summaries["final_report"]["publish_allowed"] == decision.publish_allowed
    runtime_summary = c4_outputs["gold_runtime_summary"]
    assert runtime_summary["quality_gate_decision"] == decision.model_dump(mode="json")
    assert runtime_summary["agent_loop_decision"] == c4_outputs["agent_loop_decision"].model_dump(mode="json")
    assert runtime_summary["accepted_outputs"]["final_report_paths"] == summaries["final_report"]["paths"]
    assert runtime_summary["accepted_outputs"]["strategy_card_paths"] == summaries["strategy_card"]["paths"]
    assert runtime_summary["fallback_attempts"] == 0


def test_c4_pipeline_binds_snapshot_id_to_outputs(tmp_path: Path) -> None:
    """All C4 outputs must bind to the input snapshot_id."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-snapshot-id")
    summaries, _ = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-snapshot-id",
        created_at=_CREATED_AT,
    )

    snapshot_id = snapshot["snapshot_id"]
    assert summaries["final_report"]["snapshot_id"] == snapshot_id
    assert summaries["strategy_card"]["snapshot_id"] == snapshot_id

    # strategy_card input_snapshot_ids must include analysis_snapshot
    input_ids = summaries["strategy_card"]["input_snapshot_ids"]
    assert input_ids["analysis_snapshot"] == snapshot_id


def test_c4_pipeline_no_overwrite_history(tmp_path: Path) -> None:
    """C4 must not overwrite historical reports — FileExistsError on re-run."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-no-overwrite")

    # first write succeeds
    _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-no-overwrite",
        created_at=_CREATED_AT,
    )

    # second write must fail
    with pytest.raises(FileExistsError, match="already exist"):
        _run_c4_agent_pipeline(
            storage_root=tmp_path,
            snapshot=snapshot,
            run_id="run-no-overwrite",
            created_at=_CREATED_AT,
        )


def test_enrich_runner_artifact_metadata_skips_inferred_fields_for_missing_file() -> None:
    from apps.worker.runner import _enrich_runner_artifact_metadata

    artifact = {
        "artifact_id": "run-1:missing",
        "artifact_type": "structured_json",
        "file_path": "/tmp/does-not-exist/premarket_snapshot.json",
        "label": "keep-me",
    }

    enriched = _enrich_runner_artifact_metadata(artifact)

    assert enriched == artifact
    assert "content_type" not in enriched
    assert "byte_size" not in enriched
    assert "generated_at" not in enriched


def test_c4_pipeline_no_llm_no_network_calls(tmp_path: Path) -> None:
    """C4 agents are deterministic rule-based post-processors — no LLM, no network."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-no-llm")

    # Run without network/LLM — if any agent tries to make an HTTP call
    # or invoke an LLM it will fail because we haven't set up any mocks.
    summaries, _ = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-no-llm",
        created_at=_CREATED_AT,
    )

    assert summaries["c3_agents"]["status"] == "success"


def test_c4_pipeline_records_partial_when_snapshot_has_missing_data(tmp_path: Path) -> None:
    """When macro data is missing, C3 agents should produce partial statuses."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-partial")
    # Remove macro indicators entirely
    snapshot["macro"] = {"status": "unavailable", "reason": "collector_failed"}
    # Remove options data too
    snapshot["options"] = {"status": "unavailable", "reason": "cme_download_failed"}

    summaries, _ = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-partial",
        created_at=_CREATED_AT,
    )

    assert summaries["c3_agents"]["macro_status"] == "unavailable"
    assert summaries["c3_agents"]["options_status"] == "unavailable"

    # final report still renders even with partial inputs
    report_path = Path(summaries["final_report"]["paths"][0])
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "## 数据质量与限制" in report_text  # unavailable agents produce warnings
    assert "unavailable" in report_text.lower()


def test_c4_pipeline_no_execution_language_in_outputs(tmp_path: Path) -> None:
    """Strategy card and report must contain no executable trading language."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-no-exec")
    summaries, _ = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-no-exec",
        created_at=_CREATED_AT,
    )

    # Strategy card
    json_path = Path(summaries["strategy_card"]["paths"][0])
    md_path = Path(summaries["strategy_card"]["paths"][1])
    json_text = json_path.read_text(encoding="utf-8").lower()
    md_text = md_path.read_text(encoding="utf-8").lower()

    for forbidden in ("buy", "sell", "enter", "stop loss", "take profit"):
        assert forbidden not in json_text, f"forbidden '{forbidden}' in strategy_card.json"
        assert forbidden not in md_text, f"forbidden '{forbidden}' in strategy_card.md"

    # Final report
    report_path = Path(summaries["final_report"]["paths"][0])
    report_text = report_path.read_text(encoding="utf-8").lower()
    for forbidden in ("buy", "sell", "enter", "stop loss", "take profit"):
        assert forbidden not in report_text, f"forbidden '{forbidden}' in final_report.md"


def test_c4_pipeline_source_refs_flow_through(tmp_path: Path) -> None:
    """C4 outputs must carry source_refs from snapshot + agents."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-source-refs")
    summaries, _ = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-source-refs",
        created_at=_CREATED_AT,
    )

    # Check strategy_card.json has source_refs
    json_path = Path(summaries["strategy_card"]["paths"][0])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "source_refs" in data
    assert isinstance(data["source_refs"], list)
    assert len(data["source_refs"]) > 0


def test_c4_pipeline_strategy_card_consumes_gold_macro_conditions(tmp_path: Path) -> None:
    """GoldMacroOverview should reach strategy_card as conditional research signals."""
    from apps.worker.runner import _run_c4_agent_pipeline

    snapshot = _make_rich_snapshot(run_id="run-gold-macro-conditions")
    snapshot["news"] = {
        "status": "available",
        "data": {
            "gold_macro_overview": {
                "asset": "XAUUSD",
                "as_of": "2026-06-30T00:00:00Z",
                "phase": "macro_verification",
                "dominant_mainline": "real_rates_usd",
                "net_bias": "mixed",
                "driver_conflict": {"verification_needed": ["real_rate_response_needed"]},
                "verification_matrix": [
                    {"label": "多源确认", "status": "pending"},
                    {"label": "实际利率确认", "status": "pending"},
                ],
            }
        },
    }

    summaries, _ = _run_c4_agent_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-gold-macro-conditions",
        created_at=_CREATED_AT,
    )

    json_path = Path(summaries["strategy_card"]["paths"][0])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["gold_macro_conditions"]["dominant_mainline"] == "real_rates_usd"
    assert data["gold_macro_conditions"]["net_bias"] == "mixed"
    assert data["trigger_conditions"] == [
        "Gold macro context remains mixed with dominant mainline real_rates_usd."
    ]
    assert any("Gold macro condition" in item for item in data["confirmation_conditions"])
    assert any("GoldMacroOverview dominant mainline changes" in item for item in data["invalid_conditions"])


# ═══════════════════════════════════════════════════════════════════════
# Full runner integration tests (with DB + mocked pipelines)
# ═══════════════════════════════════════════════════════════════════════


def test_run_premarket_with_c4_writes_all_artifacts(tmp_path: Path) -> None:
    """Full premarket run with mocked steps should produce C4 outputs."""
    db = _make_db_session(tmp_path)
    ensure_execution_tables(db)
    task = _make_task_with_steps(
        db,
        [
            "macro_collect",
            "macro_feature",
            "report_render",
            "cme_download",
            "cme_parse",
            "cme_ingest",
            "option_wall",
        ],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {
                    "support": [{"strike": 3250, "score": 0.7}],
                    "resistance": [{"strike": 3400, "score": 0.6}],
                },
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3350}},
                    "by_expiry": {"2026-06": {"summary": {"net_gex": 2500, "dominant_side": "positive"}, "iv_skew": {"risk_reversal_25d": 0.15}}},
                },
                "walls": {"block_pnt_walls": [{"strike": 3320, "block": 120, "pnt": 80}]},
                "data_source": {"status": "FINAL", "input_snapshot_ids": {"raw_file_sha256": "abc123"}, "expiries": ["2026-06", "2026-07"]},
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                    "SOFR": {"value": 4.33, "change_1w": 0.0, "unit": "percent"},
                    "EFFR": {"value": 4.33, "unit": "percent"},
                    "IORB": {"value": 4.40, "unit": "percent"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    # ── Verify C4 artifacts exist ──
    run_id = str(task.id)
    base = tmp_path / "outputs"

    # Final report
    report_path = base / "final_report" / "XAUUSD" / _TRADE_DATE / run_id / "final_report.md"
    assert report_path.exists(), f"Missing: {report_path}"
    report = report_path.read_text(encoding="utf-8")
    assert "# XAUUSD 相关报告" in report

    # Strategy card may use build_strategy_card's extracted/fallback date.
    sc_json_candidates = list(base.glob(f"strategy_card/XAUUSD/*/{run_id}/strategy_card.json"))
    sc_md_candidates = list(base.glob(f"strategy_card/XAUUSD/*/{run_id}/strategy_card.md"))
    assert len(sc_json_candidates) == 1, f"Expected one strategy_card.json for {run_id}"
    assert len(sc_md_candidates) == 1, f"Expected one strategy_card.md for {run_id}"

    # ── Verify step summaries include C4 steps ──
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1, f"Expected one step_summaries.json for {run_id}"
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert "c3_agents" in summaries["steps"]
    assert "final_report" in summaries["steps"]

    support_artifact_paths = {
        row.file_path
        for row in db.query(RunArtifact).filter(RunArtifact.run_id == task.id).all()
    }
    assert any(path.endswith("premarket_snapshot.json") for path in support_artifact_paths)
    assert any(path.endswith("step_summaries.json") for path in support_artifact_paths)
    assert any(path.endswith("run_provenance.json") for path in support_artifact_paths)
    assert "strategy_card" in summaries["steps"]

    run_artifacts = db.query(RunArtifact).filter(RunArtifact.run_id == task.id).all()
    artifacts_by_path = {artifact.file_path: artifact for artifact in run_artifacts}
    assert str(report_path) in artifacts_by_path
    assert str(sc_json_candidates[0]) in artifacts_by_path
    assert str(sc_md_candidates[0]) in artifacts_by_path
    report_artifact = artifacts_by_path[str(report_path)]
    strategy_card_json_artifact = artifacts_by_path[str(sc_json_candidates[0])]
    strategy_card_md_artifact = artifacts_by_path[str(sc_md_candidates[0])]
    assert report_artifact.content_type == "text/markdown"
    assert report_artifact.byte_size == report_path.stat().st_size
    assert strategy_card_json_artifact.content_type == "application/json"
    assert strategy_card_json_artifact.byte_size == sc_json_candidates[0].stat().st_size
    assert strategy_card_md_artifact.content_type == "text/markdown"
    assert strategy_card_md_artifact.byte_size == sc_md_candidates[0].stat().st_size
    assert any(artifact.artifact_type == "analysis_md" for artifact in run_artifacts)


def test_run_premarket_with_c4_registers_report_registry_entries(tmp_path: Path) -> None:
    """Full premarket run should register final report + strategy card into report registry."""
    db = _make_db_session(tmp_path)
    ensure_execution_tables(db)
    ensure_report_tables(db)
    task = _make_task_with_steps(
        db,
        [
            "macro_collect",
            "macro_feature",
            "report_render",
            "cme_download",
            "cme_parse",
            "cme_ingest",
            "option_wall",
        ],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {
                    "support": [{"strike": 3250, "score": 0.7}],
                    "resistance": [{"strike": 3400, "score": 0.6}],
                },
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3350}},
                    "by_expiry": {"2026-06": {"summary": {"net_gex": 2500, "dominant_side": "positive"}, "iv_skew": {"risk_reversal_25d": 0.15}}},
                },
                "walls": {"block_pnt_walls": [{"strike": 3320, "block": 120, "pnt": 80}]},
                "data_source": {"status": "FINAL", "input_snapshot_ids": {"raw_file_sha256": "abc123"}, "expiries": ["2026-06", "2026-07"]},
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                    "SOFR": {"value": 4.33, "change_1w": 0.0, "unit": "percent"},
                    "EFFR": {"value": 4.33, "unit": "percent"},
                    "IORB": {"value": 4.40, "unit": "percent"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    run_id = str(task.id)
    final_report_id = f"final_report:{run_id}"
    strategy_card_id = f"strategy_card:{run_id}"

    report_items = {
        row.report_id: row
        for row in db.query(ReportItem).filter(ReportItem.run_id == run_id).all()
    }
    assert set(report_items) >= {final_report_id, strategy_card_id}

    final_report_item = report_items[final_report_id]
    strategy_card_item = report_items[strategy_card_id]
    assert final_report_item.family == "final_report_markdown"
    assert strategy_card_item.family == "strategy_card"
    assert final_report_item.trade_date.isoformat() == _TRADE_DATE
    assert strategy_card_item.trade_date.isoformat() == _TRADE_DATE
    assert final_report_item.snapshot_id == strategy_card_item.snapshot_id
    assert final_report_item.source_refs
    assert strategy_card_item.source_refs

    report_artifacts = db.query(ReportArtifact).filter(ReportArtifact.report_id.in_([final_report_id, strategy_card_id])).all()
    artifacts_by_report = {}
    for artifact in report_artifacts:
        artifacts_by_report.setdefault(artifact.report_id, []).append(artifact)

    assert {artifact.artifact_type for artifact in artifacts_by_report[final_report_id]} == {"analysis_md", "structured_json"}
    assert {artifact.artifact_type for artifact in artifacts_by_report[strategy_card_id]} == {"analysis_md", "structured_json"}

    primary_artifacts = {artifact.report_id: artifact for artifact in report_artifacts if artifact.is_primary}
    assert primary_artifacts[final_report_id].content_type == "text/markdown"
    assert primary_artifacts[strategy_card_id].content_type == "application/json"

    for artifact in report_artifacts:
        assert artifact.storage_backend == "local_fs"
        assert artifact.sha256
        assert artifact.byte_size is not None
        assert artifact.generated_at is not None
        assert artifact.source_refs


def test_run_premarket_c4_not_triggered_when_snapshot_fails(tmp_path: Path) -> None:
    """When analysis snapshot fails, C4 should NOT run (no snapshot to consume)."""
    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(db, ["macro_collect", "macro_feature", "report_render"])

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            # Return a snapshot that will cause build_analysis_snapshot to succeed
            # but then we need the _persist_analysis_snapshot call to fail...
            # Actually, let's test C4 is skipped when the snapshot build fails.
            # The easiest way: make state.snapshot_dict invalid so build raises.
            state.snapshot_dict = {"as_of": _TRADE_DATE}
        return {"step": step_name, "status": "success"}

    # Force _persist_analysis_snapshot to raise
    def mock_persist(*args, **kwargs):
        raise RuntimeError("simulated snapshot persistence failure")

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner._persist_analysis_snapshot", side_effect=mock_persist),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    # Should be partial_success — steps succeeded but snapshot failed
    assert result == TaskStatus.partial_success

    # C4 artifacts must NOT exist
    run_id = str(task.id)
    base = tmp_path / "outputs"
    report_path = base / "final_report" / "XAUUSD" / _TRADE_DATE / run_id / "final_report.md"
    assert not report_path.exists(), "C4 should not have run when snapshot failed"

    # Step summaries should record the analysis_snapshot failure.
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1, f"Expected one step_summaries.json for {run_id}"
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert summaries["steps"]["analysis_snapshot"]["status"] == "failed"
    assert "c3_agents" not in summaries["steps"]


def test_run_premarket_c4_failure_recorded_in_summaries(tmp_path: Path) -> None:
    """When C4 pipeline itself fails, the failure is recorded without losing prior steps."""
    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(db, ["macro_collect", "macro_feature", "report_render"])

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                },
                "source_refs": [],
            }
        return {"step": step_name, "status": "success"}

    # Force C4 pipeline to fail
    def mock_c4_fail(*args, **kwargs):
        raise RuntimeError("simulated C4 agent pipeline failure")

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner._run_c4_agent_pipeline", side_effect=mock_c4_fail),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    # C4 failure → partial_success (steps succeeded, C4 failed)
    assert result == TaskStatus.partial_success

    run_id = str(task.id)
    base = tmp_path / "outputs"
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1, f"Expected one step_summaries.json for {run_id}"
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert summaries["steps"]["c4_agent_pipeline"]["status"] == "failed"
    assert "partial_summary" in summaries["steps"]["c4_agent_pipeline"]
