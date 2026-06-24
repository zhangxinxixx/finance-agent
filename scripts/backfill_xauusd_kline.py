"""回填 XAUUSD 1m K 线历史数据（yfinance → market_candles），分批拉取 30 天。"""
# ruff: noqa: E402
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import yfinance as yf
from datetime import datetime, timezone, timedelta
from database.models.engine import SessionLocal
from database.models.analysis import MarketCandle, ensure_analysis_tables
from database.queries.market import upsert_market_candle
from sqlalchemy import func

SYMBOL = "XAUUSD"
YF_TICKERS = ["GC=F", "XAUUSD=X"]  # try gold futures then spot

def main():
    """拉取最近 30 天 1m K 线，每 7 天一批避免 Yahoo 限制。"""
    end = datetime.now(timezone.utc)
    total = 0
    ticker_used = None

    for yf_ticker in YF_TICKERS:
        try:
            t = yf.Ticker(yf_ticker)
            info = t.info
            if info and info.get("regularMarketPrice"):
                ticker_used = yf_ticker
                print(f"Using ticker: {yf_ticker}")
                break
        except Exception:
            continue

    if not ticker_used:
        ticker_used = "GC=F"
        print(f"Fallback to: {ticker_used}")

    ticker = yf.Ticker(ticker_used)

    with SessionLocal() as session:
        ensure_analysis_tables(session)

        # Fetch in 7-day batches (Yahoo limit is 8 days for 1m)
        for day_offset in range(0, 30, 7):
            batch_end = end - timedelta(days=day_offset)
            batch_start = max(end - timedelta(days=30), batch_end - timedelta(days=7))

            print(f"Fetching {batch_start.strftime('%Y-%m-%d')} → {batch_end.strftime('%Y-%m-%d')}...", end=" ")
            try:
                df = ticker.history(interval="1m", start=batch_start, end=batch_end)
                print(f"{len(df)} rows")

                for idx, row in df.iterrows():
                    try:
                        ts = idx.to_pydatetime()
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        open_v = float(row.iloc[0]) if hasattr(row, 'iloc') else float(row["Open"])
                        high_v = float(row.iloc[1]) if hasattr(row, 'iloc') else float(row["High"])
                        low_v = float(row.iloc[2]) if hasattr(row, 'iloc') else float(row["Low"])
                        close_v = float(row.iloc[3]) if hasattr(row, 'iloc') else float(row["Close"])
                        vol_v = row.get("Volume")
                        volume_v = float(vol_v) if vol_v and vol_v > 0 else None

                        upsert_market_candle(
                            session,
                            asset=SYMBOL, timeframe="1m", open_time=ts,
                            open=open_v, high=high_v, low=low_v, close=close_v,
                            volume=volume_v,
                            source="yahoo_finance_1m",
                            source_ref={"symbol": ticker_used, "source": "yahoo_finance",
                                        "source_key": "yahoo", "provider_timeframe": "1m"},
                        )
                        total += 1
                    except Exception:
                        pass  # skip bad rows

                session.commit()
            except Exception as e:
                print(f"FAILED: {e}")

    print(f"\nImported {total} new candles")

    with SessionLocal() as session:
        count = session.query(func.count(MarketCandle.id)).filter(
            MarketCandle.asset == SYMBOL, MarketCandle.timeframe == "1m"
        ).scalar()
        earliest = session.query(func.min(MarketCandle.open_time)).filter(
            MarketCandle.asset == SYMBOL, MarketCandle.timeframe == "1m"
        ).scalar()
        print(f"Total XAUUSD 1m in DB: {count}, earliest: {earliest}")

if __name__ == "__main__":
    main()
