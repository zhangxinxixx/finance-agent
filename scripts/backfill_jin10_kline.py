"""回填 Jin10 现货 XAUUSD 1m K 线 — 拉取近 24 小时数据。"""
# ruff: noqa: E402
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from apps.collectors.jin10.mcp_client import Jin10MCPClient
from database.models.engine import SessionLocal
from database.models.analysis import MarketCandle, ensure_analysis_tables
from database.queries.market import upsert_market_candle
from datetime import datetime, timezone
from sqlalchemy import func

SYMBOL = "XAUUSD"
SOURCE = "jin10_mcp_kline_1m"

def main():
    mcp_key = os.environ.get("JIN10_MCP_KEY", "")
    if not mcp_key:
        print("No JIN10_MCP_KEY")
        return

    now = int(time.time())
    total = 0

    with Jin10MCPClient(mcp_key=mcp_key) as client:
        # 分批拉取：每 100 分钟一批，覆盖 24 小时 = 15 批
        for batch_idx in range(15):
            fetch_time = now - batch_idx * 100 * 60
            payload = client.get_kline(SYMBOL, time_stamp=fetch_time, count=100)
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            rows = data.get("klines", []) if isinstance(data, dict) else []

            if not rows:
                print(f"Batch {batch_idx}: empty, done")
                break

            with SessionLocal() as session:
                ensure_analysis_tables(session)
                for row in rows:
                    try:
                        t = row.get("time", 0)
                        if isinstance(t, (int, float)) and t > 0:
                            open_time = datetime.fromtimestamp(t, tz=timezone.utc)
                            upsert_market_candle(
                                session,
                                asset=SYMBOL, timeframe="1m", open_time=open_time,
                                open=float(row["open"]), high=float(row["high"]),
                                low=float(row["low"]), close=float(row["close"]),
                                volume=float(row.get("volume", 0)) if row.get("volume") else None,
                                source=SOURCE,
                                source_ref={"symbol": SYMBOL, "source": "jin10_mcp",
                                            "source_key": "jin10_mcp_market", "provider_timeframe": "1m"},
                            )
                    except Exception:
                        pass
                session.commit()

            total += len(rows)
            print(f"Batch {batch_idx}: {len(rows)} candles at ts={fetch_time}")
            time.sleep(0.3)

    with SessionLocal() as session:
        count = session.query(func.count(MarketCandle.id)).filter(
            MarketCandle.asset == SYMBOL, MarketCandle.timeframe == "1m", MarketCandle.source == SOURCE
        ).scalar()
        earliest = session.query(func.min(MarketCandle.open_time)).filter(
            MarketCandle.asset == SYMBOL, MarketCandle.timeframe == "1m", MarketCandle.source == SOURCE
        ).scalar()
        print(f"\nJin10 XAUUSD 1m in DB: {count}, earliest: {earliest}")

if __name__ == "__main__":
    main()
