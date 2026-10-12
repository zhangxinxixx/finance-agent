from datetime import UTC, datetime
import pytest
from apps.features.market_data.formal_snapshot_loader import resolve_formal_snapshot_as_of


def test_latest_run_sees_post_21h_data_without_changing_daily_close_replay():
    now = datetime(2026,9,5,16,10,tzinfo=UTC)
    assert resolve_formal_snapshot_as_of(trade_date='2026-09-05',run_time=now,mode='latest_available') == now
    assert resolve_formal_snapshot_as_of(trade_date='2026-09-05',run_time=now) == datetime(2026,9,5,13,tzinfo=UTC)
    with pytest.raises(ValueError, match='current'):
        resolve_formal_snapshot_as_of(trade_date='2026-09-04',run_time=now,mode='latest_available')
