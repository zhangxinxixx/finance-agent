"""OpenBB 数据采集器 — FRED 利率 + yfinance 市场价格代理。

设计原则：
1. 遵循项目现有 CollectorResult / MacroPoint 契约。
2. 原始 API 响应必须通过 archive_raw_payload 归档。
3. 缺失数据显式标记为 unavailable，不补造。
4. 错误不阻断 — 单个采集失败不影响其他 symbol。
5. OpenBB / provider 异常统一记录到 source_refs.reason。
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from apps.runtime.secret_resolver import resolve_runtime_secret
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)


@contextmanager
def _without_proxy_env():
    """Temporarily remove proxy env for providers broken by WSL proxy TLS."""
    saved = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    try:
        for key in _PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _temporary_env_var(key: str, value: str | None):
    if not value:
        yield
        return
    previous = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous

# 默认 FRED 宏观利率符号
FRED_RATE_SYMBOLS: tuple[str, ...] = (
    "DGS10",
    "DGS2",
    "DGS30",
    "DFII10",
    "DFII5",
    "FEDFUNDS",
    "SOFR",
    "T10Y2Y",
    "T10YIE",
)

# 默认市场价格代理符号
MARKET_PRICE_SYMBOLS: dict[str, str] = {
    # symbol → OpenBB asset type
    "DX-Y.NYB": "index",  # 美元指数
    "^VIX": "index",      # VIX 波动率
    "SPY": "equity",      # S&P500 代理
    "TLT": "equity",      # 长债 ETF
    "GDX": "equity",      # 金矿股 ETF
    "SLV": "equity",      # 白银 ETF
}


def _load_env(env_file: Path | None = None) -> None:
    """从指定 .env 文件加载环境变量（不覆盖已有值）。"""
    if env_file is None:
        env_file = Path(__file__).resolve().parents[3] / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


def collect_fred_rates_via_openbb(
    *,
    retrieved_date: str,
    storage_root: Path,
    symbols: tuple[str, ...] = FRED_RATE_SYMBOLS,
    env_file: Path | None = None,
) -> CollectorResult:
    """通过 OpenBB 采集 FRED 宏观利率。

    依赖：FRED_API_KEY 环境变量（从 .env 或 os.environ 读取）。
    无 key 时全部标记为 unavailable。
    """
    _load_env(env_file)
    api_key = resolve_runtime_secret("FRED_API_KEY")

    all_points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, str]] = []
    retrieved_at = utc_now_iso()

    rd = date.fromisoformat(retrieved_date) if len(retrieved_date) >= 10 else date.today()
    macro_start = (rd - timedelta(days=365)).isoformat() if rd > date.today() else "2020-01-01"

    with _temporary_env_var("FRED_API_KEY", api_key):
        from openbb import obb

        for symbol in symbols:
            source_url = f"https://fred.stlouisfed.org/series/{symbol}"
            raw_path = ""
            try:
                with _without_proxy_env():
                    result = obb.economy.fred_series(
                        symbol=symbol,
                        provider="fred",
                        start_date=macro_start,
                        end_date=retrieved_date,
                    )
                df = result.to_df()
            except Exception as exc:
                unavailable.append(symbol)
                refs.append({
                    "symbol": symbol,
                    "source": "openbb_fred",
                    "source_url": source_url,
                    "reason": f"OpenBB FRED 失败: {type(exc).__name__}: {exc}",
                })
                continue

            if df is None or df.empty:
                unavailable.append(symbol)
                refs.append({
                    "symbol": symbol,
                    "source": "openbb_fred",
                    "source_url": source_url,
                    "reason": "OpenBB FRED 返回空数据",
                })
                continue

            # 归档原始数据
            payload = {
                "symbol": symbol,
                "source": "openbb_fred",
                "retrieved_date": retrieved_date,
                "columns": list(df.columns),
                "row_count": len(df),
                "latest": df.tail(3).to_dict("records") if len(df) >= 3 else df.to_dict("records"),
            }
            raw_path = archive_raw_payload(
                storage_root=storage_root,
                source="openbb_fred",
                retrieved_date=retrieved_date,
                symbol=symbol,
                payload=payload,
            )

            # 转换为 MacroPoint（取最新值）
            # OpenBB FRED 返回的 DataFrame：index=date，column=series_symbol
            try:
                last_date = str(df.index[-1])[:10]
                sym_col = df.columns[0]  # FRED 用 symbol 作为列名
                last_value = float(df.iloc[-1][sym_col])
            except Exception as exc:
                unavailable.append(symbol)
                refs.append({
                    "symbol": symbol,
                    "source": "openbb_fred",
                    "source_url": source_url,
                    "raw_path": raw_path,
                    "reason": f"MacroPoint 转换失败: {type(exc).__name__}: {exc}",
                })
                continue

            all_points.append(
                MacroPoint(
                    symbol=symbol,
                    date=last_date,
                    value=last_value,
                    source="openbb_fred",
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                )
            )
            refs.append({
                "symbol": symbol,
                "source": "openbb_fred",
                "source_url": source_url,
                "raw_path": raw_path,
            })

    return CollectorResult(
        points=all_points,
        unavailable_symbols=unavailable,
        source_refs=refs,
    )


def _jsonify_records(records: list[dict]) -> list[dict]:
    """将 DataFrame.to_dict('records') 产生的 Timestamp 转为 ISO 字符串。"""
    import pandas as pd

    result: list[dict] = []
    for row in records:
        clean: dict[str, object] = {}
        for k, v in row.items():
            if isinstance(v, pd.Timestamp):
                clean[k] = v.isoformat()
            else:
                clean[k] = v
        result.append(clean)
    return result


def collect_market_prices_via_openbb(
    *,
    retrieved_date: str,
    storage_root: Path,
    symbols: dict[str, str] | None = None,
    env_file: Path | None = None,
    lookback_days: int = 180,
) -> CollectorResult:
    """通过 OpenBB/yfinance 采集市场价格代理。

    symbols: {symbol: asset_type}，asset_type 为 "equity" 或 "index"。
    默认使用 MARKET_PRICE_SYMBOLS。
    """
    if symbols is None:
        symbols = MARKET_PRICE_SYMBOLS

    _load_env(env_file)
    from openbb import obb

    all_points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, str]] = []
    retrieved_at = utc_now_iso()
    # 使用简单的回看窗口
    rd = date.fromisoformat(retrieved_date) if retrieved_date else date.today()
    start = (rd - timedelta(days=lookback_days)).isoformat()

    for symbol, asset_type in symbols.items():
        source_url = f"https://finance.yahoo.com/quote/{symbol}"
        raw_path = ""
        try:
            if asset_type == "index":
                result = obb.index.price.historical(
                    symbol=symbol,
                    provider="yfinance",
                    start_date=start,
                    end_date=retrieved_date,
                )
            else:
                result = obb.equity.price.historical(
                    symbol=symbol,
                    provider="yfinance",
                    start_date=start,
                    end_date=retrieved_date,
                )
            df = result.to_df()
        except Exception as exc:
            # 分类处理：空数据 vs 真错误
            err_str = str(exc)
            if "Empty" in err_str or "No results" in err_str or "delisted" in err_str.lower():
                unavailable.append(symbol)
                refs.append({
                    "symbol": symbol,
                    "source": "openbb_yfinance",
                    "source_url": source_url,
                    "reason": f"yfinance 无数据: {err_str[:200]}",
                })
            else:
                unavailable.append(symbol)
                refs.append({
                    "symbol": symbol,
                    "source": "openbb_yfinance",
                    "source_url": source_url,
                    "reason": f"OpenBB yfinance 失败: {type(exc).__name__}: {err_str[:200]}",
                })
            continue

        if df is None or df.empty:
            unavailable.append(symbol)
            refs.append({
                "symbol": symbol,
                "source": "openbb_yfinance",
                "source_url": source_url,
                "reason": "OpenBB yfinance 返回空数据",
            })
            continue

        # 归档原始数据（只保存最近几行，避免过大）
        # to_dict 产生的 Timestamp 需要转字符串才能 JSON 序列化
        records = df.tail(3).to_dict("records") if len(df) >= 3 else df.to_dict("records")
        clean_records = _jsonify_records(records)
        payload = {
            "symbol": symbol,
            "asset_type": asset_type,
            "source": "openbb_yfinance",
            "retrieved_date": retrieved_date,
            "columns": list(df.columns),
            "row_count": len(df),
            "latest": clean_records,
        }
        raw_path = archive_raw_payload(
            storage_root=storage_root,
            source="openbb_yfinance",
            retrieved_date=retrieved_date,
            symbol=symbol.replace("^", "").replace("=", "_"),
            payload=payload,
        )

        # 转换为 MacroPoint（取最新收盘价）
        try:
            last_row = df.iloc[-1]
            date_col = "date" if "date" in df.columns else df.columns[0]
            close_col = "close" if "close" in df.columns else df.columns[-1]
            point_date = str(last_row[date_col])[:10]
            point_value = float(last_row[close_col])
        except Exception as exc:
            unavailable.append(symbol)
            refs.append({
                "symbol": symbol,
                "source": "openbb_yfinance",
                "source_url": source_url,
                "raw_path": raw_path,
                "reason": f"MacroPoint 转换失败: {type(exc).__name__}: {exc}",
            })
            continue

        all_points.append(
            MacroPoint(
                symbol=symbol,
                date=point_date,
                value=point_value,
                source="openbb_yfinance",
                source_url=source_url,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
        refs.append({
            "symbol": symbol,
            "source": "openbb_yfinance",
            "source_url": source_url,
            "raw_path": raw_path,
        })

    return CollectorResult(
        points=all_points,
        unavailable_symbols=unavailable,
        source_refs=refs,
    )
