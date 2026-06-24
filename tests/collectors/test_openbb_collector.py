"""OpenBB collector 测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd


class FakeOBBResult:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def to_df(self) -> pd.DataFrame:
        return self._df


def _inject_openbb(monkeypatch, mock_obb) -> MagicMock:
    """将 mock_obb 注入为 openbb 模块，使 `from openbb import obb` 生效。"""
    openbb_mod = MagicMock()
    openbb_mod.obb = mock_obb
    monkeypatch.setitem(sys.modules, "openbb", openbb_mod)

    # 同时抑制 load_dotenv
    import apps.collectors.openbb.collector as mod
    monkeypatch.setattr(mod, "load_dotenv", lambda *a, **kw: None)
    return openbb_mod


# --- FRED rates tests ---

def test_fred_rates_produces_macro_points(tmp_path: Path, monkeypatch) -> None:
    df = pd.DataFrame(
        {"DGS10": [4.25, 4.30, 4.32]},
        index=pd.to_datetime(["2026-05-04", "2026-05-05", "2026-05-06"]),
    )
    mock_obb = MagicMock()
    mock_obb.economy.fred_series.return_value = FakeOBBResult(df)
    _inject_openbb(monkeypatch, mock_obb)

    from apps.collectors.openbb.collector import collect_fred_rates_via_openbb
    result = collect_fred_rates_via_openbb(
        retrieved_date="2026-05-06",
        storage_root=tmp_path,
        symbols=("DGS10",),
    )

    assert result.unavailable_symbols == []
    assert len(result.points) == 1
    p = result.points[0]
    assert p.symbol == "DGS10"
    assert p.date == "2026-05-06"
    assert p.value == 4.32
    assert p.source == "openbb_fred"
    assert p.raw_path.startswith("raw/macro/openbb_fred/2026-05-06/DGS10-")
    assert (tmp_path / p.raw_path).exists()


def test_fred_rates_empty_data_marks_unavailable(tmp_path: Path, monkeypatch) -> None:
    mock_obb = MagicMock()
    mock_obb.economy.fred_series.return_value = FakeOBBResult(pd.DataFrame({"DGS10": []}))
    _inject_openbb(monkeypatch, mock_obb)

    from apps.collectors.openbb.collector import collect_fred_rates_via_openbb
    result = collect_fred_rates_via_openbb(
        retrieved_date="2026-05-06",
        storage_root=tmp_path,
        symbols=("DGS10",),
    )

    assert "DGS10" in result.unavailable_symbols
    assert result.points == []


def test_fred_rates_request_failure_marks_unavailable(tmp_path: Path, monkeypatch) -> None:
    mock_obb = MagicMock()
    mock_obb.economy.fred_series.side_effect = RuntimeError("FRED API 不可用")
    _inject_openbb(monkeypatch, mock_obb)

    from apps.collectors.openbb.collector import collect_fred_rates_via_openbb
    result = collect_fred_rates_via_openbb(
        retrieved_date="2026-05-06",
        storage_root=tmp_path,
        symbols=("DGS10",),
    )

    assert "DGS10" in result.unavailable_symbols
    assert result.points == []
    assert any("FRED API 不可用" in r.get("reason", "") for r in result.source_refs)


# --- Market price tests ---

def test_market_prices_produces_macro_points(tmp_path: Path, monkeypatch) -> None:
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-06"]),
        "close": [102.5],
    })
    mock_obb = MagicMock()
    mock_obb.index.price.historical.return_value = FakeOBBResult(df)
    _inject_openbb(monkeypatch, mock_obb)

    from apps.collectors.openbb.collector import collect_market_prices_via_openbb
    result = collect_market_prices_via_openbb(
        retrieved_date="2026-05-06",
        storage_root=tmp_path,
        symbols={"DX-Y.NYB": "index"},
    )

    assert result.unavailable_symbols == []
    assert len(result.points) == 1
    p = result.points[0]
    assert p.symbol == "DX-Y.NYB"
    assert p.date == "2026-05-06"
    assert p.value == 102.5
    assert p.source == "openbb_yfinance"


def test_market_prices_empty_data_marks_unavailable(tmp_path: Path, monkeypatch) -> None:
    mock_obb = MagicMock()
    mock_obb.index.price.historical.side_effect = Exception("EmptyDataError: No results found.")
    _inject_openbb(monkeypatch, mock_obb)

    from apps.collectors.openbb.collector import collect_market_prices_via_openbb
    result = collect_market_prices_via_openbb(
        retrieved_date="2026-05-06",
        storage_root=tmp_path,
        symbols={"DX-Y.NYB": "index"},
    )

    assert "DX-Y.NYB" in result.unavailable_symbols
    assert result.points == []


def test_collector_result_structure(tmp_path: Path, monkeypatch) -> None:
    mock_obb = MagicMock()
    mock_obb.economy.fred_series.side_effect = RuntimeError("fail")
    _inject_openbb(monkeypatch, mock_obb)

    from apps.collectors.openbb.collector import collect_fred_rates_via_openbb
    result = collect_fred_rates_via_openbb(
        retrieved_date="2026-05-06",
        storage_root=tmp_path,
        symbols=("DGS10", "DGS2"),
    )

    assert isinstance(result.points, list)
    assert isinstance(result.unavailable_symbols, list)
    assert isinstance(result.source_refs, list)
    assert len(result.unavailable_symbols) == 2
    assert len(result.points) == 0
    assert len(result.source_refs) == 2
    for ref in result.source_refs:
        assert "symbol" in ref
        assert "source" in ref
        assert "reason" in ref


def test_market_price_equity_path(tmp_path: Path, monkeypatch) -> None:
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-06"]), "close": [500.0]})
    mock_obb = MagicMock()
    mock_obb.equity.price.historical.return_value = FakeOBBResult(df)
    _inject_openbb(monkeypatch, mock_obb)

    from apps.collectors.openbb.collector import collect_market_prices_via_openbb
    result = collect_market_prices_via_openbb(
        retrieved_date="2026-05-06",
        storage_root=tmp_path,
        symbols={"SPY": "equity"},
    )

    assert result.unavailable_symbols == []
    assert result.points[0].value == 500.0
    mock_obb.equity.price.historical.assert_called_once()
    mock_obb.index.price.historical.assert_not_called()
