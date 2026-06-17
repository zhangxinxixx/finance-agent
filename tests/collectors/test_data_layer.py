"""统一数据服务层测试 — 双源兜底逻辑。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from apps.data_layer.models import DualSourceResult
from apps.data_layer.service import MacroDataService, NewsDataService


class FakeOBBResult:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def to_df(self) -> pd.DataFrame:
        return self._df


def _inject_openbb(monkeypatch, mock_obb):
    """注入 fake openbb 模块。"""
    import apps.collectors.openbb.collector as mod
    monkeypatch.setattr(mod, "load_dotenv", lambda *a, **kw: None)
    openbb_mod = MagicMock()
    openbb_mod.obb = mock_obb
    monkeypatch.setitem(sys.modules, "openbb", openbb_mod)
    return openbb_mod


# ── MacroDataService tests ──────────────────────────────────────────────

def test_macro_service_fred_primary_succeeds(tmp_path: Path, monkeypatch) -> None:
    df = pd.DataFrame(
        {"DGS10": [4.30]},
        index=pd.to_datetime(["2026-05-20"]),
    )
    mock_obb = MagicMock()
    mock_obb.economy.fred_series.return_value = FakeOBBResult(df)
    _inject_openbb(monkeypatch, mock_obb)

    svc = MacroDataService(storage_root=tmp_path)
    result = svc.collect_fred_rates(retrieved_date="2026-05-20", symbols=("DGS10",))

    assert result.source_used == "openbb"
    assert result.unavailable_symbols == []
    assert len(result.points) == 1
    assert result.points[0].symbol == "DGS10"
    assert result.points[0].value == 4.30


def test_macro_service_fred_fallback_to_jin10(tmp_path: Path, monkeypatch) -> None:
    mock_obb = MagicMock()
    mock_obb.economy.fred_series.side_effect = RuntimeError("OpenBB failed")
    _inject_openbb(monkeypatch, mock_obb)

    # Jin10 走 mock：直接 patch MacroDataService._try_jin10_rates
    from apps.data_layer.service import DualSourceResult, MacroPoint

    jin10_points = [
        MacroPoint(
            symbol="US10YR", date="2026-05-20", value=4.30,
            source="jin10_mcp", source_url="jin10://quote/US10YR",
            retrieved_at="2026-01-01T00:00:00", raw_path="x",
        )
    ]
    monkeypatch.setattr(
        "apps.data_layer.service.MacroDataService._try_jin10_rates",
        lambda self, *a, **kw: DualSourceResult(
            points=jin10_points,
            source_used="jin10",
            unavailable_symbols=[],
            source_refs=[{"source": "jin10_mcp"}],
            warnings=["fallback"],
        ),
    )

    svc = MacroDataService(storage_root=tmp_path)
    result = svc.collect_fred_rates(retrieved_date="2026-05-20", symbols=("DGS10",))

    assert result.source_used == "jin10"
    assert len(result.points) == 1
    assert "fallback" in result.warnings[0] if result.warnings else False


def test_macro_service_fred_both_fail(tmp_path: Path, monkeypatch) -> None:
    mock_obb = MagicMock()
    mock_obb.economy.fred_series.side_effect = RuntimeError("fail")
    _inject_openbb(monkeypatch, mock_obb)

    monkeypatch.setattr(
        "apps.data_layer.service.MacroDataService._try_jin10_rates",
        lambda self, *a, **kw: None,
    )

    svc = MacroDataService(storage_root=tmp_path)
    result = svc.collect_fred_rates(retrieved_date="2026-05-20", symbols=("DGS10",))

    assert result.source_used is None
    assert "DGS10" in result.unavailable_symbols
    assert len(result.points) == 0
    assert len(result.warnings) > 0


def test_macro_service_price_primary_succeeds(tmp_path: Path, monkeypatch) -> None:
    df = pd.DataFrame({"date": pd.to_datetime(["2026-05-20"]), "close": [100.0]})
    mock_obb = MagicMock()
    mock_obb.index.price.historical.return_value = FakeOBBResult(df)
    _inject_openbb(monkeypatch, mock_obb)

    svc = MacroDataService(storage_root=tmp_path)
    result = svc.collect_market_prices(
        retrieved_date="2026-05-20", symbols={"DX-Y.NYB": "index"}
    )

    assert result.source_used == "openbb"
    assert len(result.points) == 1
    assert result.points[0].value == 100.0


def test_macro_service_price_both_fail(tmp_path: Path, monkeypatch) -> None:
    mock_obb = MagicMock()
    mock_obb.index.price.historical.side_effect = RuntimeError("fail")
    _inject_openbb(monkeypatch, mock_obb)

    monkeypatch.setattr(
        "apps.data_layer.service.MacroDataService._try_jin10_prices",
        lambda self, *a, **kw: None,
    )

    svc = MacroDataService(storage_root=tmp_path)
    result = svc.collect_market_prices(
        retrieved_date="2026-05-20", symbols={"DX-Y.NYB": "index"}
    )

    assert result.source_used is None
    assert "DX-Y.NYB" in result.unavailable_symbols


# ── NewsDataService tests ───────────────────────────────────────────────

def test_news_collect_jin10_succeeds(tmp_path: Path, monkeypatch) -> None:
    """Jin10 可用 → 直接返回。"""
    from apps.parsers.macro.models import CollectorResult, MacroPoint

    points = [
        MacroPoint(
            symbol="NEWS_FLASH", date="2026-05-20", value=0.0,
            source="jin10_mcp", source_url="jin10://flash",
            retrieved_at="2026-05-20T00:00:00", raw_path="r",
        )
    ]
    fake_result = CollectorResult(points=points, unavailable_symbols=[], source_refs=[])

    monkeypatch.setattr(
        "apps.collectors.news.collector.collect_news",
        lambda *a, **kw: fake_result,
    )

    svc = NewsDataService(storage_root=tmp_path)
    result = svc.collect_all(retrieved_date="2026-05-20")

    assert result.source_used == "jin10"
    assert len(result.points) == 1


def test_news_collect_jin10_fails_with_keyerror(tmp_path: Path, monkeypatch) -> None:
    """Jin10 不可用 + OpenBB 也不可用 → 双失败。"""
    monkeypatch.setattr(
        "apps.collectors.news.collector.collect_news",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Jin10 down")),
    )

    # OpenBB 新闻也停用
    import apps.data_layer.service as mod
    monkeypatch.setattr(mod.NewsDataService, "_try_openbb_news", lambda self, *a, **kw: None)

    svc = NewsDataService(storage_root=tmp_path)
    result = svc.collect_all(retrieved_date="2026-05-20")

    assert result.source_used is None
    assert "NEWS_ALL" in result.unavailable_symbols
    assert len(result.warnings) > 0


def test_dual_source_result_structure() -> None:
    """DualSourceResult 结构完整性。"""
    r = DualSourceResult(
        points=[],
        source_used=None,
        unavailable_symbols=["X"],
        source_refs=[{"reason": "test"}],
        warnings=["warning"],
    )
    d = r.to_dict()
    assert d["points"] == []
    assert d["source_used"] is None
    assert d["unavailable_symbols"] == ["X"]
    assert len(d["warnings"]) == 1
