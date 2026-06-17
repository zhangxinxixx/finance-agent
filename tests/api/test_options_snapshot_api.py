from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.analysis.agents.fact_review import persist_fact_review_agent_output
from apps.analysis.agents.synthesis import persist_synthesis_agent_output
from apps.api import main as api_main
from database.models.analysis import AnalysisBase, AgentOutput
from database.queries.analysis import upsert_agent_output


_PROJECT_ROOT_PATCH = "apps.api.data_service._PROJECT_ROOT"


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _make_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _seed_options_outputs(session: Session) -> None:
    snapshot_id = "options:2026-06-01:run-options-001"
    upsert_agent_output(
        session,
        {
            "snapshot_id": snapshot_id,
            "analysis_snapshot_db_id": None,
            "asset": "XAUUSD",
            "trade_date": "2026-06-01",
            "run_id": "run-options-001",
            "agent_name": "cme_options_agent",
            "module": "options",
            "version": "1.0",
            "status": "success",
            "bias": "bearish",
            "confidence": 0.67,
            "input_snapshot_ids": {"options_analysis_snapshot": snapshot_id},
            "source_refs": [
                {
                    "source_id": "src-cme-001",
                    "source_name": "CME Daily Bulletin",
                    "source_type": "pdf",
                    "status": "available",
                }
            ],
            "key_findings": ["Gamma Zero 位于 3325。"],
            "risk_points": ["初版 bulletin 仍可能修订。"],
            "watchlist": ["3325", "3350"],
            "invalid_conditions": ["重新站回 3350 上方。"],
            "summary": "Gamma Zero 下方仍偏防守，反弹需要先收复 3350。",
            "payload": {
                "generated_by": "hybrid",
                "prompt_version": "cme_options_agent_v1",
                "artifact_refs": ["storage/outputs/cme/2026-06-01/run-options-001/options_analysis_agent_report.md"],
                "claims": [
                    {
                        "claim_id": "claim-options-001",
                        "text": "Gamma Zero 下方仍偏防守。",
                        "source_refs": [],
                        "evidence_refs": [],
                    }
                ],
            },
        },
    )
    session.flush()

    persist_fact_review_agent_output(session, snapshot_id=snapshot_id)
    persist_synthesis_agent_output(session, snapshot_id=snapshot_id)
    session.commit()


def test_api_options_snapshot_returns_analysis_read_model(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        {
            "storage/outputs/cme/2026-06-01/run-options-001/options_analysis.json": json.dumps(
                {
                    "trade_date": "2026-06-01",
                    "data_source": {
                        "product": "OG",
                        "status": "FINAL",
                        "expiries": ["2026-06-26"],
                        "row_count": 128,
                        "source_url": "https://example.test/cme.pdf",
                    },
                    "parameters": {"f_value": 3328.2, "r_value": 0.041},
                    "gex": {
                        "netgex_aggregate": {
                            "net_gex": -1250000,
                            "net_gex_direction": "negative",
                            "gamma_zero": {"price": 3325.0, "method": "interpolated"},
                        }
                    },
                    "wall_scores": [
                        {"strike": 3350, "wall_type": "Call Wall", "side": "CALL", "oi": 1200, "delta_oi": 50, "wall_score": 8.2, "pnt": 1.6},
                        {"strike": 3320, "wall_type": "Put Wall", "side": "PUT", "oi": 1500, "delta_oi": -20, "wall_score": 9.1, "pnt": 1.2},
                    ],
                    "support_resistance": {
                        "resistance": [{"strike": 3350, "wall_score": 8.2, "distance_pct": 0.7}],
                        "support": [{"strike": 3320, "wall_score": 9.1, "distance_pct": 0.2}],
                    },
                    "intent": {"type": "bearish", "confidence": 0.71, "score": 0.71, "evidence": ["Put 墙位仍占优"]},
                    "calibration": {
                        "calculation_method": "hybrid",
                        "calibration_warnings": ["PRELIM delta OI unavailable"],
                    },
                    "source_trace": [],
                    "has_data": True,
                },
                ensure_ascii=False,
            )
        },
    )

    session = _make_session()
    _seed_options_outputs(session)

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = api_main.api_options_snapshot(date="2026-06-01", db=session)

    assert payload["trade_date"] == "2026-06-01"
    assert payload["run_id"] == "run-options-001"
    assert payload["snapshot_id"] == "options:2026-06-01:run-options-001"

    analysis = payload["analysis"]
    assert analysis["snapshot_id"] == "options:2026-06-01:run-options-001"
    assert analysis["run_id"] == "run-options-001"
    assert analysis["fact_review_status"] == "needs_review"
    assert analysis["pending_review_count"] == 1
    assert analysis["cme_options_agent"]["agent_name"] == "cme_options_agent"
    assert analysis["cme_options_agent"]["summary_zh"] == "Gamma Zero 下方仍偏防守，反弹需要先收复 3350。"
    assert analysis["fact_review"]["fact_review_status"] == "needs_review"
    assert analysis["fact_review"]["claim_reviews"][0]["claim_id"] == "claim-options-001"
    assert analysis["synthesis"]["fact_review_status"] == "needs_review"
    assert analysis["synthesis"]["warning_count"] >= 1
    assert analysis["pending_reviews"][0]["claim_id"] == "claim-options-001"
    assert analysis["pending_reviews"][0]["source_module"] == "options"

    rows = session.query(AgentOutput).all()
    assert {row.agent_name for row in rows} == {"cme_options_agent", "fact_review_agent", "synthesis_agent"}
