from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.analysis.state.hashing import content_hash
from scripts.bootstrap_analysis_state import _validate_db_bound_overview, main


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fixtures(storage: Path) -> None:
    ref = {"source": "market_snapshot", "snapshot_id": "snap-1"}
    card = {
        "asset": "XAUUSD",
        "run_id": "run-1",
        "bias": "mixed_bullish",
        "scenario_summary": "等待确认",
        "key_levels_from_options": [],
        "invalid_conditions": [],
        "watchlist": [],
        "trigger_conditions": [],
        "confirmation_conditions": [],
        "source_refs": [ref],
        "input_snapshot_ids": {"analysis_snapshot": "snap-1", "coordinator": "snap-1"},
        "created_at": "2026-07-22T08:00:00Z",
    }
    loop = {
        "decision": "passed",
        "review_status": "pass",
        "publish_allowed": True,
        "accepted_output": {
            "source": "primary",
            "agent_name": "coordinator_agent",
            "snapshot_id": "snap-1",
        },
    }
    final = {
        "asset": "XAUUSD",
        "trade_date": "2026-07-22",
        "run_id": "run-1",
        "snapshot_id": "snap-1",
        "final_bias": "mixed_bullish",
        "scenario_summary": "等待确认",
        "input_snapshot_ids": card["input_snapshot_ids"],
        "source_refs": [ref],
        "strategy_card": card,
        "run_summaries": {
            "gold_runtime_summary": {
                "quality_gate_decision": {
                    "action": "pass",
                    "review_status": "pass",
                    "publish_allowed": True,
                },
                "agent_loop_decision": loop,
            }
        },
        "payload_sha256": content_hash(card),
        "strategy_card_sha256": content_hash(card),
    }
    overview = {
        "asset": "XAUUSD",
        "run_id": "run-1",
        "as_of": "2026-07-22T08:00:00Z",
        "phase": "transition_release",
        "net_bias": "mixed_bullish",
        "one_line_conclusion": "等待确认",
        "theme_rankings": [],
        "input_snapshot_ids": {"analysis_snapshot": "snap-1", "coordinator": "snap-1"},
        "source_refs": [ref],
    }
    _write(storage / "input" / "final.json", final)
    _write(storage / "input" / "overview.json", overview)


def test_cli_defaults_to_dry_run_and_writes_nothing(tmp_path: Path, capsys) -> None:
    storage = tmp_path / "storage"
    _fixtures(storage)
    before = sorted(path.relative_to(storage) for path in storage.rglob("*"))

    assert main(
        [
            "--asset", "XAUUSD",
            "--trade-date", "2026-07-22",
            "--run-id", "run-1",
            "--storage-root", str(storage),
            "--final-result-json", "input/final.json",
            "--gold-overview-json", "input/overview.json",
            "--database-url", "sqlite+pysqlite:///:memory:",
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    after = sorted(path.relative_to(storage) for path in storage.rglob("*"))
    assert output["dry_run"] is True
    assert output["state_scope"] == "daily_close"
    assert "/daily_close/" in output["planned_candidate_path"]
    assert output["writes"] == []
    assert before == after
    assert not (storage / output["planned_candidate_path"]).exists()


def test_cli_accepts_explicit_state_scope(tmp_path: Path, capsys) -> None:
    storage = tmp_path / "storage"
    _fixtures(storage)

    assert main(
        [
            "--asset", "XAUUSD",
            "--state-scope", "intraday",
            "--trade-date", "2026-07-22",
            "--run-id", "run-1",
            "--storage-root", str(storage),
            "--final-result-json", "input/final.json",
            "--gold-overview-json", "input/overview.json",
            "--database-url", "sqlite+pysqlite:///:memory:",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["state_scope"] == "intraday"
    assert "/intraday/" in output["planned_candidate_path"]


def test_cli_rejects_input_outside_storage_root(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    _fixtures(storage)
    outside = tmp_path / "outside.json"
    _write(outside, {})

    with pytest.raises(ValueError, match="inside allowed root"):
        main(
            [
                "--asset", "XAUUSD",
                "--trade-date", "2026-07-22",
                "--run-id", "run-1",
                "--storage-root", str(storage),
                "--final-result-json", "input/final.json",
                "--gold-overview-json", str(outside),
                "--database-url", "sqlite+pysqlite:///:memory:",
            ]
        )


def test_commit_overview_must_match_database_analysis_snapshot() -> None:
    expected = {
        "asset": "XAUUSD",
        "run_id": "run-1",
        "one_line_conclusion": "accepted",
    }

    class FakeSession:
        def __init__(self, *, asset: str = "XAUUSD", run_id: str = "run-1") -> None:
            self.asset = asset
            self.run_id = run_id

        def get(self, _model, identity):
            assert identity == "snapshot-db-id"
            return SimpleNamespace(
                asset=self.asset,
                run_id=self.run_id,
                payload={"news": {"data": {"gold_macro_overview": expected}}},
            )

    final = SimpleNamespace(
        analysis_snapshot_db_id="snapshot-db-id",
        asset="XAUUSD",
        run_id="run-1",
    )
    _validate_db_bound_overview(FakeSession(), final_result=final, overview=expected)
    with pytest.raises(ValueError, match="does not match"):
        _validate_db_bound_overview(
            FakeSession(),
            final_result=final,
            overview={**expected, "one_line_conclusion": "tampered"},
        )
    with pytest.raises(ValueError, match="run_id does not match"):
        _validate_db_bound_overview(
            FakeSession(run_id="other-run"),
            final_result=final,
            overview=expected,
        )
