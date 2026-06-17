"""手动触发全部数据采集器，每个采集器记录到 task_runs。

GET/POST /api/scheduler/run-all-collectors
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from pathlib import Path

from apps.runtime.task_recorder import TaskRecorder

logger = logging.getLogger(__name__)

_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "storage"

COLLECTOR_TASKS = [
    ("fred", "FRED 宏观数据采集", "apps.collectors.fred.collector", "collect_fred_series"),
    ("fed", "Fed 政策利率采集", "apps.collectors.fed.collector", "collect_fed_series"),
    ("treasury", "Treasury 财政数据采集", "apps.collectors.treasury.collector", "collect_treasury_series"),
    ("dxy", "DXY 美元指数采集", "apps.collectors.dxy.collector", "collect_dxy_series"),
    ("positioning", "COT 持仓数据采集", "apps.collectors.positioning.collector", "collect_positioning_cot"),
    ("technical", "XAUUSD 技术数据采集", "apps.collectors.technical.collector", "collect_technical"),
]


def run_all_collectors_sync(trade_date: str | None = None) -> dict:
    """同步运行全部采集器，每个包装在 TaskRecorder 中。"""
    today = trade_date or date.today().isoformat()
    results = []

    for task_type, task_name, module_path, func_name in COLLECTOR_TASKS:
        try:
            with TaskRecorder(
                task_type=task_type,
                task_name=task_name,
                trade_date=today,
            ) as rec:
                mod = __import__(module_path, fromlist=[func_name])
                fn = getattr(mod, func_name)
                result = fn(retrieved_date=today, storage_root=_STORAGE_ROOT)

                points_count = len(result.points) if hasattr(result, "points") else 0
                source_refs = getattr(result, "source_refs", []) or []
                raw_dir = _STORAGE_ROOT / "raw" / task_type / today
                output_refs = [
                    {
                        "artifact_id": f"{task_type}:{today}",
                        "artifact_type": "raw_data",
                        "file_path": str(raw_dir),
                        "points": points_count,
                    }
                ]
                rec.step(
                    f"collect_{task_type}",
                    status="success",
                    source_refs=source_refs,
                    output_refs=output_refs,
                )
                results.append({
                    "source": task_type,
                    "status": "ok",
                    "points": points_count,
                    "run_id": rec.run_id(),
                })
                logger.info("Collector %s done: %d points, run=%s", task_type, points_count, rec.run_id())
        except Exception as exc:
            logger.exception("Collector %s failed: %s", task_type, exc)
            results.append({
                "source": task_type,
                "status": "failed",
                "error": str(exc),
            })

    ok = sum(1 for r in results if r["status"] == "ok")
    return {
        "total": len(results),
        "ok": ok,
        "failed": len(results) - ok,
        "results": results,
    }


def run_all_collectors_async(trade_date: str | None = None):
    """在后台线程异步运行全部采集器。"""
    def _run():
        try:
            result = run_all_collectors_sync(trade_date=trade_date)
            logger.info("Async collector run complete: %d/%d ok", result["ok"], result["total"])
        except Exception:
            logger.exception("Async collector run failed")

    thread = threading.Thread(target=_run, daemon=True, name="collect-all")
    thread.start()
    return {"status": "dispatched", "message": "全部采集器已在后台启动"}
