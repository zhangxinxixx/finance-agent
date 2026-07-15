from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.analysis.evaluation.replay import ReplayCoverageError, run_shadow_replay
from apps.analysis.evaluation.strategy_snapshot import build_strategy_snapshot


AS_OF = datetime(2026, 7, 18, 10, 39, tzinfo=UTC)


def _legacy_payload() -> dict[str, object]:
    snapshot = build_strategy_snapshot(
        account_id="codex-xauusd-shadow",
        asset="XAUUSD",
        trade_date="2026-07-18",
        run_id="run-legacy",
        strategy_id="strategy-legacy",
        strategy_version="live_strategy.rules.v1",
        as_of=AS_OF,
        reference_price=4000.0,
        bias="neutral",
        publish_allowed=True,
        quality_gate={"status": "approved"},
        entry_conditions=[
            {"setup_id": "long", "direction": "long", "status": "watching", "entry_zone": [4001.0, 4002.0]},
            {"setup_id": "short", "direction": "short", "status": "watching", "entry_zone": [3998.0, 3999.0]},
        ],
        invalidation={
            "setups": [
                {"setup_id": "long", "level": 3995.0},
                {"setup_id": "short", "level": 4005.0},
            ]
        },
        evaluation_id="eval-legacy",
    ).to_dict()
    snapshot.pop("evaluation_setups")
    snapshot.pop("supersedes_evaluation_id")
    return snapshot


def _rows(*, gap: bool = False) -> list[dict[str, object]]:
    rows = []
    for index in range(13):
        at = AS_OF.replace(second=0, microsecond=0) + timedelta(minutes=1 + 5 * index)
        if gap and index == 5:
            continue
        rows.append(
            {
                "asset": "XAUUSD",
                "timeframe": "5m",
                "open_time": at,
                "open": 4000.0,
                "high": 4001.0,
                "low": 3999.0,
                "close": 4000.0,
                "source": "twelvedata_xauusd_5m",
                "source_ref": {"provider_symbol": "XAU/USD", "instrument_type": "otc_spot_quote_proxy"},
            }
        )
    return rows


def test_replay_creates_superseding_unscorable_revision_without_overwrite(tmp_path: Path) -> None:
    dry = run_shadow_replay(
        snapshot_payload=_legacy_payload(),
        market_rows=_rows(),
        horizon="1h",
        storage_root=tmp_path,
    )

    assert dry["dry_run"] is True
    assert dry["evaluation_id"] != "eval-legacy"
    assert dry["supersedes_evaluation_id"] == "eval-legacy"
    assert dry["coverage"]["status"] == "complete"
    assert dry["outcome"] == {
        "status": "unscorable",
        "classification": "unscorable",
        "lifecycle_status": "insufficient_strategy_contract",
        "reason_codes": ["evaluation_setup_missing"],
        "scoreable": False,
    }
    assert not (tmp_path / "evaluation").exists()

    written = run_shadow_replay(
        snapshot_payload=_legacy_payload(),
        market_rows=_rows(),
        horizon="1h",
        storage_root=tmp_path,
        write=True,
    )
    replayed = run_shadow_replay(
        snapshot_payload=_legacy_payload(),
        market_rows=_rows(),
        horizon="1h",
        storage_root=tmp_path,
        write=True,
    )
    assert written["snapshot"]["created"] is True
    assert written["outcome_artifact"]["created"] is True
    assert replayed["snapshot"]["created"] is False
    assert replayed["outcome_artifact"]["created"] is False
    snapshot_path = Path(written["snapshot"]["path"])
    assert '"supersedes_evaluation_id":"eval-legacy"' in snapshot_path.read_text(encoding="utf-8")


def test_replay_refuses_gapped_market_path(tmp_path: Path) -> None:
    with pytest.raises(ReplayCoverageError, match="contains gaps"):
        run_shadow_replay(
            snapshot_payload=_legacy_payload(),
            market_rows=_rows(gap=True),
            horizon="1h",
            storage_root=tmp_path,
            write=True,
        )
    assert not (tmp_path / "evaluation").exists()
