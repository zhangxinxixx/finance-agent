"""启动时初始化数据源状态 -> data_source_status 表。

从 source_service 读取 _KNOWN_SOURCE_DEFS，幂等 upsert 到 DB。
确保调度中心 / 数据接入页面能看到全部 25 个数据源。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from database.models.engine import SessionLocal
from database.queries.data_source_status import upsert_data_source_status

logger = logging.getLogger(__name__)

_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "storage"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_source_configured(source_key: str, access_method: str | None) -> bool:
    """判断指定数据源在当前环境中是否已配置。"""
    from apps.runtime.secret_resolver import resolve_runtime_secret

    # 需要 API key 的数据源
    key_map = {
        "fred": "FRED_API_KEY",
        "fed": "FRED_API_KEY",
        "treasury": "FRED_API_KEY",
        "dxy": None,  # 无需 key
        "cme_daily_bulletin": None,  # 公开 PDF
        "cme_options": None,  # 派生自 CME PDF
        "technical_yahoo": "JIN10_MCP_KEY",  # Jin10 → Yahoo fallback
        "positioning_cot": None,  # 公开 CFTC
        "jin10_news": "JIN10_MCP_KEY",
        "jin10_flash": "JIN10_MCP_KEY",
        "jin10_mcp_flash": "JIN10_MCP_KEY",
        "jin10_mcp_calendar": "JIN10_MCP_KEY",
        "jin10_mcp_market": "JIN10_MCP_KEY",
        "jin10_xnews_public": None,  # 公开页面
        "jin10_datacenter_reports": "JIN10_MCP_KEY",
        "jin10_svip_reports": None,  # 需要浏览器登录
        "jin10_feishu": None,  # 走飞书用户授权，非 env key
        "fed_rss": None,
        "bls_calendar": None,
        "bea_calendar": None,
        "eia_energy": None,  # 公开 EIA 发布日历
        "gdelt_news": None,
        "google_news_rss": None,
        "reuters_public_news": None,
    }

    env_key = key_map.get(source_key)
    if env_key is None:
        return True  # 无需 key 的默认视为已配置

    try:
        key = resolve_runtime_secret(env_key)
        return bool(key)
    except Exception:
        return False


def init_data_source_status() -> int:
    """幂等初始化所有已知数据源状态到 data_source_status 表。

    Returns:
        写入的记录数。
    """
    from apps.api.services.source_service import _KNOWN_SOURCE_DEFS

    count = 0
    try:
        with SessionLocal() as session:
            for src_def in _KNOWN_SOURCE_DEFS:
                source_key = src_def["source_key"]
                configured = _resolve_source_configured(
                    source_key, src_def.get("access_method")
                )
                metadata = dict(src_def.get("metadata", {}))

                # 补充最新产物路径
                latest_raw_path = _find_latest_artifact(source_key, "raw")
                latest_parsed_path = _find_latest_artifact(source_key, "parsed")
                latest_feature_path = _find_latest_artifact(source_key, "features")

                metadata["latest_raw_ref"] = (
                    {"label": f"{source_key}_raw", "raw_path": latest_raw_path, "published_at": _utc_now_iso()}
                    if latest_raw_path
                    else None
                )

                status = "ok" if configured else "not_connected"

                # 如果已有记录且之前状态更好，不降级覆盖
                from database.queries.data_source_status import get_data_source_status
                existing = get_data_source_status(session, source_key)
                if existing and existing.status == "ok" and status == "not_connected":
                    status = "ok"
                    configured = True  # 保持之前的配置状态

                # 已有数据不覆盖为 False
                if existing:
                    if existing.raw_ingested:
                        latest_raw_path = existing.latest_raw_time  # 保留已有
                    if existing.parsed:
                        latest_parsed_path = True
                    if existing.analysis_ready:
                        latest_feature_path = True

                upsert_data_source_status(
                    session,
                    {
                        "source_key": source_key,
                        "source_name": src_def["source_name"],
                        "source_group": src_def["source_group"],
                        "source_type": src_def["source_type"],
                        "access_method": src_def.get("access_method"),
                        "configured": configured,
                        "raw_ingested": latest_raw_path is not None,
                        "parsed": latest_parsed_path is not None,
                        "analysis_ready": latest_feature_path is not None,
                        "status": status,
                        "source_metadata": metadata,
                    },
                )
                count += 1

            session.commit()
            logger.info("Initialized %d data source status records", count)
    except Exception as exc:
        logger.exception("Failed to initialize data source status: %s", exc)

    return count


def _find_latest_artifact(source_key: str, layer: str) -> str | None:
    """查找指定 source 最新产物路径（相对于 storage）。"""
    import glob

    patterns = {
        "raw": [
            f"storage/raw/{source_key}/**/*.*",
            f"storage/raw/*/{source_key}/**/*.*",
        ],
        "parsed": [
            f"storage/parsed/{source_key}/**/*.*",
        ],
        "features": [
            f"storage/features/*/{source_key}/**/*.*",
            f"storage/features/{source_key}/**/*.*",
        ],
        "outputs": [
            f"storage/outputs/{source_key}/**/*.md",
            f"storage/outputs/{source_key}/**/*.json",
        ],
    }

    for pattern in patterns.get(layer, []):
        files = sorted(glob.glob(str(_STORAGE_ROOT.parent / pattern), recursive=True), reverse=True)
        for f in files:
            p = Path(f)
            try:
                return str(p.relative_to(_STORAGE_ROOT.parent))
            except ValueError:
                return str(p)

    return None
