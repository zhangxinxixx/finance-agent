from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pandas as pd


def test_official_fred_collector_disables_environment_proxies(monkeypatch, tmp_path):
    """FRED official collector must bypass shell proxy env to avoid SSL EOF in WSL."""
    from apps.collectors.fred import collector as fred_collector

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_fetch(client, *, symbol, api_key, retrieved_date, attempts=3):
        assert retrieved_date == "2026-05-21"
        return {"observations": [{"date": "2026-05-20", "value": "4.67"}]}

    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7890")
    monkeypatch.setattr("httpx.Client", DummyClient)
    monkeypatch.setattr(fred_collector, "_fetch_fred_payload_with_retry", fake_fetch)

    result = fred_collector.collect_fred_series(
        retrieved_date="2026-05-21",
        storage_root=tmp_path,
        symbols=("DGS10",),
        api_key="test-key",
    )

    assert len(result.points) == 1
    assert captured["trust_env"] is False


def test_openbb_fred_collector_temporarily_clears_proxy_env(monkeypatch, tmp_path):
    """OpenBB FRED provider should not inherit proxy env that breaks api.stlouisfed.org."""
    from apps.collectors.openbb import collector as openbb_collector

    proxy_keys = (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    )
    for key in proxy_keys:
        monkeypatch.setenv(key, "http://127.0.0.1:7890")

    class DummyFredResult:
        def to_df(self):
            return pd.DataFrame(
                [{"DGS10": 4.67}],
                index=pd.to_datetime(["2026-05-20"]),
            )

    class DummyEconomy:
        @staticmethod
        def fred_series(**kwargs):
            assert kwargs["symbol"] == "DGS10"
            assert all(os.environ.get(key) is None for key in proxy_keys)
            return DummyFredResult()

    fake_openbb = SimpleNamespace(obb=SimpleNamespace(economy=DummyEconomy()))
    monkeypatch.setitem(sys.modules, "openbb", fake_openbb)

    result = openbb_collector.collect_fred_rates_via_openbb(
        retrieved_date="2026-05-21",
        storage_root=tmp_path,
        symbols=("DGS10",),
    )

    assert len(result.points) == 1
    assert result.points[0].symbol == "DGS10"
    assert all(os.environ.get(key) == "http://127.0.0.1:7890" for key in proxy_keys)
