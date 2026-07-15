"""逐个测试数据源采集器，报告成功/失败。"""
# ruff: noqa: E402
from __future__ import annotations
from pathlib import Path
from datetime import date

STORAGE = Path(__file__).resolve().parents[1] / "storage"
TODAY = date.today().isoformat()

def test_collector(name: str, fn, **kwargs) -> dict:
    try:
        result = fn(**kwargs)
        return {
            "source": name,
            "status": "ok",
            "points": len(result.points) if hasattr(result, "points") else "N/A",
            "unavailable": getattr(result, "unavailable_symbols", []),
            "sample": str(result.points[0])[:200] if hasattr(result, "points") and result.points else "无数据",
            "error": None,
        }
    except Exception as e:
        return {
            "source": name,
            "status": "failed",
            "points": 0,
            "unavailable": [],
            "sample": None,
            "error": f"{type(e).__name__}: {e}",
        }

results = []

# 1. FRED
from apps.collectors.fred.collector import collect_fred_series
results.append(test_collector("FRED", collect_fred_series, retrieved_date=TODAY, storage_root=STORAGE))

# 2. Fed
from apps.collectors.fed.collector import collect_fed_series
results.append(test_collector("Fed", collect_fed_series, retrieved_date=TODAY, storage_root=STORAGE))

# 3. Treasury
from apps.collectors.treasury.collector import collect_treasury_series
results.append(test_collector("Treasury", collect_treasury_series, retrieved_date=TODAY, storage_root=STORAGE))

# 4. DXY
from apps.collectors.dxy.collector import collect_dxy_series
results.append(test_collector("DXY", collect_dxy_series, retrieved_date=TODAY, storage_root=STORAGE))

# 5. Positioning (COT)
from apps.collectors.positioning.collector import collect_positioning_cot
results.append(test_collector("COT Positioning", collect_positioning_cot, retrieved_date=TODAY, storage_root=STORAGE))

# 6. Technical (Yahoo/Jin10)
from apps.collectors.technical.collector import collect_technical
results.append(test_collector("Technical (Yahoo/Jin10)", collect_technical, retrieved_date=TODAY, storage_root=STORAGE))

# 7. CME Bulletin (PDF)
print("\n📡 CME Daily Bulletin — 跳过（需真实 PDF 下载）")

# 输出报告
print("\n" + "=" * 80)
print(f"数据源采集器测试报告 — {TODAY}")
print("=" * 80)
for r in results:
    status = "✅ 正常" if r["status"] == "ok" else "❌ 失败"
    print(f"\n📡 {r['source']} — {status}")
    if r["status"] == "ok":
        print(f"   采集点数: {r['points']}")
        if r["unavailable"]:
            print(f"   缺失指标: {r['unavailable']}")
        sample = r["sample"]
        if sample and sample != "无数据":
            print(f"   样本数据: {sample[:150]}")
    else:
        print(f"   错误: {r['error'][:200]}")

total = len(results)
ok = sum(1 for r in results if r["status"] == "ok")
failed = total - ok
print(f"\n{'='*80}")
print(f"合计: {ok}/{total} 通过, {failed}/{total} 失败")
print(f"{'='*80}")
