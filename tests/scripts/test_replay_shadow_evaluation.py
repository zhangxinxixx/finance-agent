from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import replay_shadow_evaluation as cli


AS_OF = datetime(2026, 7, 18, 10, 39, tzinfo=UTC)


def _snapshot() -> dict[str, object]:
    return {
        "evaluation_id": "eval-legacy",
        "account_id": "codex-xauusd-shadow",
        "asset": "XAUUSD",
        "trade_date": "2026-07-18",
        "run_id": "run-legacy",
        "strategy_id": "strategy-legacy",
        "strategy_version": "rules.v1",
        "as_of": AS_OF.isoformat(),
        "reference_price": 4000.0,
        "bias": "neutral",
        "mode": "shadow",
        "publish_allowed": True,
        "quality_gate": {"status": "approved"},
        "key_levels": [],
        "entry_conditions": [],
        "invalidation": {},
        "risk": {},
        "source_refs": [],
        "artifact_refs": [],
    }


def _rows() -> list[dict[str, object]]:
    return [
        {
            "asset": "XAUUSD",
            "timeframe": "5m",
            "open_time": AS_OF.replace(second=0) + timedelta(minutes=1 + index * 5),
            "open": 4000.0,
            "high": 4001.0,
            "low": 3999.0,
            "close": 4000.0,
            "source": "twelvedata_xauusd_5m",
            "source_ref": {"provider_symbol": "XAU/USD", "instrument_type": "otc_spot_quote_proxy"},
        }
        for index in range(13)
    ]


def test_programmatic_replay_is_dry_run_by_default(tmp_path: Path) -> None:
    summary = cli.replay_shadow_evaluation(
        trade_date="2026-07-18",
        evaluation_id="eval-legacy",
        horizon="1h",
        storage_root=tmp_path,
        snapshot_payload=_snapshot(),
        market_rows=_rows(),
    )
    assert summary["dry_run"] is True
    assert summary["supersedes_evaluation_id"] == "eval-legacy"
    assert not (tmp_path / "evaluation").exists()


def test_programmatic_replay_rejects_mismatched_snapshot_context(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not match"):
        cli.replay_shadow_evaluation(
            trade_date="2026-07-18",
            evaluation_id="eval-other",
            horizon="1h",
            storage_root=tmp_path,
            snapshot_payload=_snapshot(),
            market_rows=_rows(),
        )


def test_cli_rejects_unsafe_evaluation_id() -> None:
    with pytest.raises(SystemExit, match="safe path component"):
        cli.main(["--date", "2026-07-18", "--evaluation-id", "../escape", "--horizon", "1h"])
