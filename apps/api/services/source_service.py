from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT, _latest_date_dir, _try_db_session

_KNOWN_SOURCE_DEFS: list[dict[str, Any]] = [
    {"source_key": "fred", "source_name": "FRED", "source_group": "macro", "source_type": "api", "access_method": "fred_api", "metadata": {"provider_role": "official_primary", "fallback_for": [], "fallback_sources": ["openbb_macro", "jin10_news"], "frontend_label": "FRED 官方宏观主源", "notes": "官方宏观时间序列主源；异常时由 OpenBB 补充，并由 Jin10 提供事件/快讯上下文。"}},
    {"source_key": "openbb_macro", "source_name": "OpenBB Macro/Market", "source_group": "macro", "source_type": "api", "access_method": "openbb_data_layer", "metadata": {"provider_role": "fallback", "fallback_for": ["fred", "fed", "treasury", "dxy"], "fallback_sources": [], "frontend_label": "OpenBB 宏观/市场补充源", "notes": "补充或回退宏观/市场数据；未写入原始/解析工件时不得视为已入库。"}},
    {"source_key": "fed", "source_name": "Federal Reserve", "source_group": "macro", "source_type": "api", "access_method": "fred_api", "metadata": {"provider_role": "official_primary", "fallback_for": [], "fallback_sources": ["openbb_macro", "jin10_news"], "frontend_label": "Federal Reserve 官方源"}},
    {"source_key": "treasury", "source_name": "US Treasury", "source_group": "macro", "source_type": "api", "access_method": "fred_api", "metadata": {"provider_role": "official_primary", "fallback_for": [], "fallback_sources": ["openbb_macro", "jin10_news"], "frontend_label": "US Treasury 官方源"}},
    {"source_key": "dxy", "source_name": "DXY Index", "source_group": "macro", "source_type": "api", "access_method": "tradingview+cnbc", "metadata": {"provider_role": "official_primary", "fallback_for": [], "fallback_sources": ["openbb_macro", "jin10_news"], "frontend_label": "DXY 主行情源"}},
    {"source_key": "cme_daily_bulletin", "source_name": "CME Daily Bulletin", "source_group": "cme", "source_type": "pdf", "access_method": "cme_ftp", "metadata": {"provider_role": "official_primary", "fallback_for": [], "fallback_sources": [], "frontend_label": "CME 官方公告"}},
    {"source_key": "cme_options", "source_name": "CME Options Data", "source_group": "cme", "source_type": "structured", "access_method": "cme_ftp+parser", "metadata": {"provider_role": "derived", "fallback_for": [], "fallback_sources": ["cme_daily_bulletin"], "frontend_label": "CME 解析后期权数据"}},
    {"source_key": "technical_yahoo", "source_name": "Jin10 XAUUSD Technical", "source_group": "technical", "source_type": "api", "access_method": "jin10_mcp", "metadata": {"provider_role": "supplemental", "fallback_for": ["openbb_macro"], "fallback_sources": ["jin10_news"], "frontend_label": "Jin10 黄金实时/技术补充源"}},
    {"source_key": "positioning_cot", "source_name": "COT Positioning", "source_group": "positioning", "source_type": "api", "access_method": "cftc_api", "metadata": {"provider_role": "official_primary", "fallback_for": [], "fallback_sources": [], "frontend_label": "COT 官方持仓源"}},
    {"source_key": "jin10_news", "source_name": "Jin10 News", "source_group": "news", "source_type": "scraper", "access_method": "jin10_rss", "metadata": {"provider_role": "supplemental", "fallback_for": ["fred", "fed", "treasury", "dxy", "openbb_macro"], "fallback_sources": [], "frontend_label": "Jin10 新闻/日历补充源", "notes": "提供快讯、日历、事件上下文；不应被前端当作官方宏观时间序列主源。"}},
    {"source_key": "jin10_flash", "source_name": "Jin10 Flash", "source_group": "news", "source_type": "api", "access_method": "jin10_mcp_list_flash", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "event_layer": "realtime_flash", "fallback_for": [], "fallback_sources": ["jin10_news"], "frontend_label": "Jin10 实时快讯", "notes": "Jin10 MCP list_flash 高频缓存源；实时重点事件播报在采集缓存阶段用 MiMo 语义打标。"}},
    {"source_key": "jin10_mcp_flash", "source_name": "Jin10 MCP Flash", "source_group": "news", "source_type": "mcp", "access_method": "mcp", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "event_layer": "realtime_flash", "fallback_for": [], "fallback_sources": ["jin10_news"], "frontend_label": "Jin10 MCP 快讯", "notes": "Jin10 MCP list_flash/search_flash 分 lane 可观测源；用于实时事件雷达和关键词快讯。"}},
    {"source_key": "jin10_mcp_calendar", "source_name": "Jin10 MCP Calendar", "source_group": "news", "source_type": "calendar", "access_method": "mcp", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "event_layer": "calendar_candidate", "fallback_for": [], "fallback_sources": ["bls_calendar", "bea_calendar", "eia_energy"], "frontend_label": "Jin10 MCP 财经日历", "notes": "Jin10 MCP list_calendar 周内财经日历候选；宏观事实仍以官方源确认。"}},
    {"source_key": "jin10_mcp_market", "source_name": "Jin10 MCP Market", "source_group": "technical", "source_type": "mcp", "access_method": "mcp", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "fallback_for": ["technical_yahoo"], "fallback_sources": [], "frontend_label": "Jin10 MCP 行情/K线", "notes": "Jin10 MCP get_quote/get_kline 近端行情源；历史不足时显式降级。"}},
    {"source_key": "twelvedata_xauusd", "source_name": "Twelve Data XAU/USD", "source_group": "technical", "source_type": "api", "access_method": "twelvedata_rest", "metadata": {"provider_role": "validation_and_fallback", "priority_level": "P0", "fallback_for": ["jin10_mcp_market"], "fallback_sources": [], "frontend_label": "Twelve Data 黄金校验/备用", "provider_symbol": "XAU/USD", "instrument_type": "composite_otc_spot_proxy", "entitlement": "trial", "production_guaranteed": False, "notes": "原生 5m/15m/1h/4h 只做独立校验和整根 K 线故障接管；免费 trial entitlement 变化时必须显式降级。"}},
    {"source_key": "jin10_xnews_public", "source_name": "Jin10 xnews Public", "source_group": "news", "source_type": "scraper", "access_method": "http_document", "metadata": {"provider_role": "supplemental", "priority_level": "P1", "event_layer": "article_context", "fallback_for": [], "fallback_sources": ["jin10_mcp_flash"], "frontend_label": "Jin10 公开文章", "notes": "公开 xnews 详情页正文和图片；只作为 single_source/article context。"}},
    {"source_key": "jin10_datacenter_reports", "source_name": "Jin10 Datacenter Reports", "source_group": "macro", "source_type": "structured", "access_method": "js_data_script", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "fallback_for": [], "fallback_sources": ["fred", "positioning_cot", "cme_options"], "frontend_label": "Jin10 数据中心报表", "notes": "数据中心 JS/API 结构化报表；只做补充展示和交叉验证，不覆盖官方事实。"}},
    {"source_key": "jin10_minipro_etf_reports", "source_name": "Jin10 Mini Program ETF Reports", "source_group": "positioning", "source_type": "structured", "access_method": "minipro_rest", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "required_for": [], "fallback_policy": "degraded_allowed", "fallback_for": [], "fallback_sources": [], "frontend_label": "Jin10 黄金/白银 ETF 持仓", "notes": "小程序黄金 SPDR 与白银 iShares ETF 日持仓；作为 single_source 补充事实进入审查链，不替代基金官方披露。"}},
    {"source_key": "jin10_svip_reports", "source_name": "Jin10 SVIP Reports", "source_group": "reports", "source_type": "scraper", "access_method": "vip_browser_profile", "metadata": {"provider_role": "supplemental", "priority_level": "P1", "fallback_for": [], "fallback_sources": ["jin10_xnews_public"], "frontend_label": "Jin10 SVIP 授权报告", "notes": "已授权浏览器 profile 下的报告图文资产；缺登录或预览页必须显式标记。"}},
    {"source_key": "jin10_web_important_flash", "source_name": "Jin10 Web Important Flash", "source_group": "news", "source_type": "web_flash", "access_method": "vip_browser_profile", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "event_layer": "realtime_flash", "fallback_for": [], "fallback_sources": ["jin10_mcp_flash", "jin10_news"], "frontend_label": "Jin10 首页重要快讯", "notes": "首页重要市场快讯和重要新闻头条采集；单源 supplemental 上下文。"}},
    {"source_key": "jin10_web_vip_flash", "source_name": "Jin10 Web VIP Flash", "source_group": "news", "source_type": "vip_flash", "access_method": "vip_browser_profile", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "event_layer": "vip_analysis_flash", "fallback_for": [], "fallback_sources": ["jin10_mcp_flash", "jin10_news"], "frontend_label": "Jin10 VIP 快讯", "notes": "首页 VIP 快讯分析采集；必须显式标记登录/VIP 限制。"}},
    {"source_key": "jin10_feishu", "source_name": "Jin10 Feishu Chat Pull", "source_group": "news", "source_type": "webhook", "access_method": "feishu_openapi_chat_pull", "metadata": {"provider_role": "supplemental", "priority_level": "P0", "event_layer": "supplemental_trade_signal", "fallback_for": [], "fallback_sources": ["jin10_news"], "frontend_label": "飞书金十群消息", "notes": "主动拉取飞书群内金十机器人消息，作为交易线索和日报触发来源；单源内容保持 supplemental/single_source。"}},
    {"source_key": "fed_rss", "source_name": "Federal Reserve RSS", "source_group": "news", "source_type": "rss", "access_method": "feedparser+httpx", "metadata": {"provider_role": "official_primary", "priority_level": "P0", "event_layer": "official_calendar", "fallback_for": [], "fallback_sources": ["jin10_news"], "frontend_label": "Fed 官方 RSS 事件源", "notes": "只采集 Fed 官方发布/讲话/纪要事件；不替代 FRED/Fed 宏观时间序列。"}},
    {"source_key": "bls_calendar", "source_name": "BLS Release Calendar", "source_group": "news", "source_type": "calendar", "access_method": "official_calendar", "metadata": {"provider_role": "official_primary", "priority_level": "P0", "event_layer": "official_calendar", "fallback_for": [], "fallback_sources": ["jin10_news"], "frontend_label": "BLS 官方发布日历", "notes": "CPI/PPI/非农/JOLTS 等发布时间事件层；数据值仍由宏观链处理。"}},
    {"source_key": "bea_calendar", "source_name": "BEA Release Schedule", "source_group": "news", "source_type": "calendar", "access_method": "official_calendar", "metadata": {"provider_role": "official_primary", "priority_level": "P0", "event_layer": "official_calendar", "fallback_for": [], "fallback_sources": ["jin10_news"], "frontend_label": "BEA 官方发布日历", "notes": "PCE/GDP/Personal Income 发布时间事件层；数据值仍由宏观链处理。"}},
    {"source_key": "eia_energy", "source_name": "EIA Energy Events", "source_group": "news", "source_type": "api", "access_method": "eia_api", "metadata": {"provider_role": "official_primary", "priority_level": "P0", "event_layer": "official_energy", "fallback_for": [], "fallback_sources": ["jin10_news", "gdelt_news"], "frontend_label": "EIA 能源事件源", "notes": "EIA 周报/库存/能源发布事件层；用于油价和通胀传导。"}},
    {"source_key": "gdelt_news", "source_name": "GDELT DOC News Radar", "source_group": "news", "source_type": "api", "access_method": "gdelt_doc_api", "metadata": {"provider_role": "aggregator", "priority_level": "P0", "event_layer": "candidate_event_radar", "fallback_for": [], "fallback_sources": ["google_news_rss", "jin10_news"], "frontend_label": "GDELT 全球新闻雷达", "notes": "候选事件池，不作为最终事实确认源。"}},
    {"source_key": "google_news_rss", "source_name": "Google News RSS", "source_group": "news", "source_type": "rss", "access_method": "feedparser+httpx", "metadata": {"provider_role": "aggregator", "priority_level": "P0", "event_layer": "candidate_event_radar", "fallback_for": [], "fallback_sources": ["gdelt_news", "jin10_news"], "frontend_label": "Google News RSS 候选扫描", "notes": "免费关键词备用扫描，默认只进入 candidate events。"}},
    {"source_key": "reuters_public_news", "source_name": "Reuters Public Metadata", "source_group": "news", "source_type": "rss", "access_method": "public_metadata", "metadata": {"provider_role": "wire_public_candidate", "priority_level": "P0.5", "event_layer": "candidate_event_radar", "authorized_wire": False, "fallback_for": [], "fallback_sources": ["gdelt_news", "google_news_rss", "jin10_news"], "frontend_label": "Reuters 公开元数据候选源", "notes": "只采公开可访问 metadata；不保存全文，不绕登录，不等同 LSEG/Reuters Connect 授权 wire。"}},
    {"source_key": "llm_web_search", "source_name": "LLM Web Search Fallback", "source_group": "news", "source_type": "api", "access_method": "responses_web_search", "metadata": {"provider_role": "online_research_fallback", "priority_level": "P1", "event_layer": "candidate_event_radar", "fallback_for": ["gdelt_news", "google_news_rss", "reuters_public_news"], "fallback_sources": [], "frontend_label": "LLM 联网新闻兜底", "notes": "仅在常规发现源没有达到 freshness 目标时触发；必须存在真实 web_search_call URL，结果保持 supplemental/single_source。"}},
]

_KNOWN_SOURCE_INDEX: dict[str, dict[str, Any]] = {src["source_key"]: src for src in _KNOWN_SOURCE_DEFS}
_NEWS_SOURCE_STORAGE_DIRS: dict[str, str] = {
    "fed_rss": "fed_rss",
    "bls_calendar": "bls",
    "bea_calendar": "bea",
    "eia_energy": "eia",
    "gdelt_news": "gdelt",
    "google_news_rss": "google_news_rss",
    "jin10_feishu": "jin10_feishu",
    "jin10_minipro_etf_reports": "jin10_minipro_etf_reports",
    "reuters_public_news": "reuters_public",
    "llm_web_search": "llm_web_search",
}
_NEWS_FEATURE_FILENAMES: dict[str, str] = {
    "brief_artifact_path": "daily_market_brief.json",
    "daily_analysis_triggers_artifact_path": "daily_analysis_triggers.json",
    "article_briefs_artifact_path": "jin10_article_briefs.json",
    "event_candidates_artifact_path": "event_candidates.json",
    "impact_assessments_artifact_path": "impact_assessments.json",
    "market_reactions_artifact_path": "market_reactions.json",
    "report_events_artifact_path": "report_events.json",
    "collection_diagnostics_artifact_path": "collection_diagnostics.json",
}

_FRESHNESS_MODE_TTLS: dict[str, timedelta] = {
    "server_side_cache": timedelta(minutes=15),
    "cached_market_poll": timedelta(minutes=15),
    "cursor_poll": timedelta(minutes=15),
    "rss_poll": timedelta(hours=6),
    "scheduled_batch": timedelta(hours=36),
    "fallback_batch": timedelta(hours=36),
    "official_file_check": timedelta(hours=36),
    "derived_after_cme_pdf": timedelta(hours=36),
    "calendar_poll": timedelta(hours=36),
    "official_api_poll": timedelta(hours=36),
    "structured_report_probe": timedelta(hours=48),
    "article_discovery_then_detail": timedelta(hours=48),
    "public_metadata_poll": timedelta(hours=24),
    "weekly_batch": timedelta(days=8),
    "rate_limited_query_groups": timedelta(hours=24),
}
_MANUAL_FRESHNESS_MODES = frozenset({"manual_or_authorized_browser_profile"})

_SOURCE_OBSERVABILITY: dict[str, dict[str, Any]] = {
    "fred": {
        "database_tables": ["data_source_status", "analysis_snapshots.macro"],
        "artifact_layers": ["storage/features/macro"],
        "polling_strategy": {"mode": "scheduled_batch", "cadence": "daily / premarket", "query": "macro collector -> FRED series ids"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "保持批处理缓存；无需高频轮询。"},
    },
    "fed": {
        "database_tables": ["data_source_status", "analysis_snapshots.macro"],
        "artifact_layers": ["storage/features/macro"],
        "polling_strategy": {"mode": "scheduled_batch", "cadence": "daily / official release window", "query": "FRED/Fed macro collector"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "官方发布时间低频，按发布窗口刷新。"},
    },
    "treasury": {
        "database_tables": ["data_source_status", "analysis_snapshots.macro"],
        "artifact_layers": ["storage/features/macro"],
        "polling_strategy": {"mode": "scheduled_batch", "cadence": "daily", "query": "Treasury/FRED macro collector"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "日频批处理足够。"},
    },
    "dxy": {
        "database_tables": ["data_source_status", "market_candles", "analysis_snapshots.technical"],
        "artifact_layers": ["storage/features/technical"],
        "polling_strategy": {"mode": "cached_market_poll", "cadence": "1m-5m during active session", "query": "market candle latest by asset/timeframe"},
        "pressure_profile": {"level": "medium", "upgrade_required": True, "recommendation": "行情类读多写少，建议统一 server-side cache + last-write-wins upsert，前端只轮询聚合快照。"},
    },
    "openbb_macro": {
        "database_tables": ["data_source_status", "analysis_snapshots.macro"],
        "artifact_layers": ["storage/features/macro"],
        "polling_strategy": {"mode": "fallback_batch", "cadence": "on macro refresh failure / daily", "query": "OpenBB fallback collector"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "作为 fallback，不应被高频轮询。"},
    },
    "cme_daily_bulletin": {
        "database_tables": ["data_source_status"],
        "artifact_layers": ["raw/cme/daily_bulletin", "storage/raw/cme", "storage/parsed/cme"],
        "polling_strategy": {
            "mode": "official_file_check",
            "cadence": "daily afternoon bulletin window / latest available previous bulletin",
            "query": "CME Daily Bulletin PDF discovery",
        },
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "下午检查官方 PDF；盘前报告允许使用最新可用的上一份公告。"},
    },
    "cme_options": {
        "database_tables": ["data_source_status", "analysis_snapshots.options"],
        "artifact_layers": ["storage/outputs/cme", "storage/outputs/cme_options", "storage/features/cme", "storage/features/options"],
        "polling_strategy": {"mode": "derived_after_cme_pdf", "cadence": "after latest available bulletin parse", "query": "latest options snapshot by trade date/run"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "衍生数据跟随最新可用 CME PDF 解析完成，不需要独立高频采集。"},
    },
    "technical_yahoo": {
        "database_tables": ["data_source_status", "market_candles", "analysis_snapshots.technical"],
        "artifact_layers": ["storage/features/technical"],
        "polling_strategy": {"mode": "cached_market_poll", "cadence": "1m-5m", "query": "latest quote/candle per symbol"},
        "pressure_profile": {"level": "medium", "upgrade_required": True, "recommendation": "技术行情应进入共享行情缓存，避免多个页面分别打外部源。"},
    },
    "positioning_cot": {
        "database_tables": ["data_source_status", "analysis_snapshots.positioning"],
        "artifact_layers": ["storage/features/positioning"],
        "polling_strategy": {"mode": "weekly_batch", "cadence": "weekly after CFTC release", "query": "COT positioning collector"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "周频数据不需要高频组件。"},
    },
    "jin10_news": {
        "database_tables": ["data_source_status", "analysis_snapshots.news", "task_runs", "task_steps"],
        "artifact_layers": ["storage/raw/news", "storage/parsed/news", "storage/features/news"],
        "polling_strategy": {"mode": "server_side_cache", "cadence": "60s UI refresh / collector controlled", "query": "Jin10 flash cache + news feature artifacts"},
        "pressure_profile": {"level": "high", "upgrade_required": True, "recommendation": "实时新闻应由后端单点采集并缓存，前端只读缓存；后续可升级为 Redis TTL + SSE/WebSocket 推送。"},
    },
    "jin10_flash": {
        "database_tables": ["data_source_status"],
        "artifact_layers": ["storage/outputs/jin10/flash_cache.json"],
        "polling_strategy": {"mode": "server_side_cache", "cadence": "60s cache TTL / scheduler refresh", "query": "Jin10 MCP list_flash -> MiMo semantic filter -> flash_cache.json"},
        "pressure_profile": {"level": "high", "upgrade_required": True, "recommendation": "保持后端单点采集与缓存；后续高频场景建议加 Redis TTL、按 flash id 增量 LLM 打标和 SSE/WebSocket 推送，避免多页面轮询放大压力。"},
    },
    "jin10_mcp_flash": {
        "database_tables": ["data_source_status", "task_runs", "task_steps"],
        "artifact_layers": ["storage/outputs/jin10/flash_cache.json", "storage/raw/news"],
        "polling_strategy": {"mode": "server_side_cache", "cadence": "60s cache TTL / scheduler refresh", "query": "Jin10 MCP list_flash/search_flash"},
        "pressure_profile": {"level": "high", "upgrade_required": True, "recommendation": "实时快讯保持后端单点采集和缓存；前端只读缓存，不直接打 MCP。"},
    },
    "jin10_mcp_calendar": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/outputs/jin10/calendar_cache.json", "storage/raw/news"],
        "polling_strategy": {"mode": "scheduled_batch", "cadence": "daily / release window / manual refresh", "query": "Jin10 MCP list_calendar"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "财经日历低频刷新即可，重要事实由官方日历或官方数据源确认。"},
    },
    "jin10_mcp_market": {
        "database_tables": ["data_source_status", "market_candles"],
        "artifact_layers": ["storage/outputs/jin10/quotes_cache.json"],
        "polling_strategy": {"mode": "cached_market_poll", "cadence": "1m-5m during active session", "query": "Jin10 MCP get_quote/get_kline"},
        "pressure_profile": {"level": "medium", "upgrade_required": True, "recommendation": "行情进入共享缓存和 market_candles，历史不足显式标记 insufficient_history。"},
    },
    "twelvedata_xauusd": {
        "database_tables": ["data_source_status", "market_candles"],
        "artifact_layers": ["storage/raw/market/twelvedata", "storage/monitoring/market_data"],
        "polling_strategy": {
            "mode": "cached_market_poll",
            "cadence": "on closed 5m/15m/1h/4h buckets",
            "query": "Twelve Data XAU/USD native time_series validation/fallback",
        },
        "pressure_profile": {
            "level": "medium",
            "upgrade_required": False,
            "recommendation": "正常日保持约 414 次请求并监控 credit headers；trial entitlement 或 quota 异常时显式降级。",
        },
    },
    "jin10_xnews_public": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/jin10_detail_pages", "storage/parsed/news/jin10_detail_pages", "storage/features/news"],
        "polling_strategy": {"mode": "article_discovery_then_detail", "cadence": "manual / scheduled article queue", "query": "xnews category/topic discovery -> public detail HTML"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "公开详情页只在需要正文图片或 HTML provenance 时抓取，避免重复拉同一文章。"},
    },
    "jin10_datacenter_reports": {
        "database_tables": ["data_source_status"],
        "artifact_layers": ["storage/raw/jin10/datacenter", "storage/parsed/jin10/datacenter"],
        "polling_strategy": {"mode": "structured_report_probe", "cadence": "daily / manual for pilot slugs", "query": "datacenter reportType HTML -> latest JS data script"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "按 slug 低频刷新并做 schema_changed 降级；不作为官方事实主源。"},
    },
    "jin10_minipro_etf_reports": {
        "database_tables": ["data_source_status", "analysis_snapshots.news", "task_runs", "task_steps"],
        "artifact_layers": [
            "storage/raw/news/jin10_minipro_etf_reports",
            "storage/parsed/news/jin10_minipro_etf_reports",
            "storage/features/market",
        ],
        "polling_strategy": {
            "mode": "structured_report_probe",
            "cadence": "daily / premarket",
            "query": "Jin10 Mini Program ETF reports for SPDR Gold Trust and iShares Silver Trust",
        },
        "pressure_profile": {
            "level": "low",
            "upgrade_required": False,
            "recommendation": "日频拉取并归档原始响应；保持 supplemental/single_source 标签。",
        },
    },
    "jin10_svip_reports": {
        "database_tables": ["data_source_status"],
        "artifact_layers": ["~/jin10-reports", "storage/outputs/jin10"],
        "polling_strategy": {"mode": "manual_or_authorized_browser_profile", "cadence": "manual / configured report job only", "query": "SVIP category/detail through authorized browser profile"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "不要自动全量抓取；登录态失效时标记 login_required，图片可得但正文不足时标记 image_only。"},
    },
    "jin10_web_important_flash": {
        "database_tables": ["data_source_status", "analysis_snapshots.news", "task_runs", "task_steps"],
        "artifact_layers": ["storage/raw/jin10/web_flash", "storage/parsed/jin10/web_flash", "storage/features/news"],
        "polling_strategy": {"mode": "server_side_cache", "cadence": "60s-5m collector controlled / manual refresh", "query": "Jin10 homepage important flash + important news top list"},
        "pressure_profile": {"level": "high", "upgrade_required": True, "recommendation": "首页重要快讯压力高，需要后端缓存；前端只读缓存，避免直接高频轮询。"},
    },
    "jin10_web_vip_flash": {
        "database_tables": ["data_source_status", "analysis_snapshots.news", "task_runs", "task_steps"],
        "artifact_layers": ["storage/raw/jin10/web_flash", "storage/parsed/jin10/web_flash", "storage/features/news"],
        "polling_strategy": {"mode": "manual_or_authorized_browser_profile", "cadence": "manual / configured authorized browser refresh", "query": "Jin10 homepage VIP flash analysis through authorized browser profile"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "VIP 快讯中等压力，不要自动全量抓取；登录/VIP 限制必须显式标记。"},
    },
    "jin10_feishu": {
        "database_tables": ["data_source_status", "analysis_snapshots.news", "task_runs", "task_steps"],
        "artifact_layers": ["storage/raw/news/jin10_feishu", "storage/parsed/news/jin10_feishu", "storage/features/news"],
        "polling_strategy": {"mode": "cursor_poll", "cadence": "1m-5m with cursor / manual trigger", "query": "Feishu chat message cursor by chat id"},
        "pressure_profile": {"level": "high", "upgrade_required": True, "recommendation": "飞书消息应使用 cursor 增量、去重和冷却；不建议前端直接驱动频繁刷新。"},
    },
    "fed_rss": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/fed_rss", "storage/parsed/news/fed_rss", "storage/features/news"],
        "polling_strategy": {"mode": "rss_poll", "cadence": "15m-60m", "query": "Fed RSS feed URLs"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "RSS 可低频轮询并做 ETag/Last-Modified 缓存。"},
    },
    "bls_calendar": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/bls", "storage/parsed/news/bls", "storage/features/news"],
        "polling_strategy": {"mode": "calendar_poll", "cadence": "daily / release calendar window", "query": "BLS official release calendar"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "日历源低频更新，缓存即可。"},
    },
    "bea_calendar": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/bea", "storage/parsed/news/bea", "storage/features/news"],
        "polling_strategy": {"mode": "calendar_poll", "cadence": "daily / release calendar window", "query": "BEA release schedule"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "日历源低频更新，缓存即可。"},
    },
    "eia_energy": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/eia", "storage/parsed/news/eia", "storage/features/news"],
        "polling_strategy": {"mode": "official_api_poll", "cadence": "daily / weekly release window", "query": "EIA release endpoints"},
        "pressure_profile": {"level": "low", "upgrade_required": False, "recommendation": "跟随 EIA 发布窗口轮询，不需要常驻高频。"},
    },
    "gdelt_news": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/gdelt", "storage/parsed/news/gdelt", "storage/features/news"],
        "polling_strategy": {"mode": "rate_limited_query_groups", "cadence": "15m+ with local cooldown", "query": "GDELT DOC query groups"},
        "pressure_profile": {"level": "high", "upgrade_required": True, "recommendation": "必须保留 query group 冷却和缓存；后续可加队列限速器，避免多关键词并发打爆上游。"},
    },
    "google_news_rss": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/google_news_rss", "storage/parsed/news/google_news_rss", "storage/features/news"],
        "polling_strategy": {"mode": "rss_poll", "cadence": "15m-60m", "query": "Google News RSS keyword feeds"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "RSS 备用扫描应低频批量轮询，避免按页面访问触发。"},
    },
    "reuters_public_news": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/reuters_public", "storage/parsed/news/reuters_public", "storage/features/news"],
        "polling_strategy": {"mode": "public_metadata_poll", "cadence": "30m+ / manual", "query": "authorized public metadata only"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "保持公开 metadata 边界；不要为了频率绕过授权。"},
    },
    "llm_web_search": {
        "database_tables": ["data_source_status", "analysis_snapshots.news"],
        "artifact_layers": ["storage/raw/news/llm_web_search", "storage/parsed/news/llm_web_search", "storage/features/news"],
        "polling_strategy": {"mode": "fallback_batch", "cadence": "only when freshness gate requires fallback", "query": "bounded financial-news query groups through an actual Responses web_search_call"},
        "pressure_profile": {"level": "medium", "upgrade_required": False, "recommendation": "仅条件触发；检查 provider capability 与调用成本，不能把模型摘要当官方确认。"},
    },
}

_SOURCE_REQUIRED_FOR_BY_GROUP: dict[str, list[str]] = {
    "macro": ["macro_snapshot", "premarket"],
    "cme": ["options_snapshot", "premarket"],
    "technical": ["market_monitor", "premarket"],
    "positioning": ["positioning_snapshot", "premarket"],
    "news": ["event_flow", "news_monitor", "premarket"],
    "reports": ["daily_analysis_followup"],
}


def _check_fs_artifact(path_rel: str) -> bool:
    return (_PROJECT_ROOT / path_rel).exists()


def _check_fs_date_dirs(base_rel: str) -> bool:
    base = _PROJECT_ROOT / base_rel
    return base.exists() and any(d.is_dir() for d in base.iterdir())


def _relative_project_path(path: Any) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(_PROJECT_ROOT).as_posix()
    except Exception:
        return None


def _path_mtime_iso(path: Any) -> str | None:
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
    except Exception:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _max_iso_datetime(*values: Any) -> str | None:
    latest_value: str | None = None
    latest_dt: datetime | None = None
    for value in values:
        parsed = _parse_datetime(value)
        if parsed is not None and (latest_dt is None or parsed > latest_dt):
            latest_dt = parsed
            latest_value = str(value)
    return latest_value


def _latest_update_time(source: dict[str, Any]) -> str | None:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    latest_raw_ref = metadata.get("latest_raw_ref") if isinstance(metadata.get("latest_raw_ref"), dict) else {}
    return _max_iso_datetime(
        source.get("latest_parsed_time"),
        source.get("latest_raw_time"),
        metadata.get("as_of"),
        metadata.get("latest_as_of"),
        metadata.get("written_at"),
        metadata.get("latest_artifact_mtime"),
        latest_raw_ref.get("published_at"),
    )


def _source_observability_contract(source_key: str) -> dict[str, Any]:
    contract = dict(_SOURCE_OBSERVABILITY.get(source_key, {}))
    contract.setdefault("database_tables", ["data_source_status"])
    contract.setdefault("artifact_layers", [])
    contract.setdefault(
        "polling_strategy",
        {"mode": "unknown", "cadence": "manual / task scheduler", "query": f"source_key={source_key}"},
    )
    contract.setdefault(
        "pressure_profile",
        {"level": "unknown", "upgrade_required": False, "recommendation": "暂无专门压力策略；按任务调度链路观察。"},
    )
    return contract


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _source_url_from_metadata(metadata: dict[str, Any]) -> str | None:
    return _first_non_empty(
        metadata.get("latest_raw_url"),
        metadata.get("source_url"),
        metadata.get("url"),
        metadata.get("endpoint"),
    )


def _latest_raw_ref_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    url = _source_url_from_metadata(metadata)
    raw_path = _first_non_empty(
        metadata.get("collector_raw_artifact_path"),
        metadata.get("raw_artifact_path"),
        metadata.get("raw_path"),
    )
    parsed_path = _first_non_empty(metadata.get("collector_parsed_artifact_path"), metadata.get("parsed_path"))
    if not url and not raw_path and not parsed_path:
        return None
    return {
        "label": "latest raw",
        "url": url,
        "raw_path": raw_path,
        "parsed_path": parsed_path,
        "source_ref": _first_non_empty(metadata.get("source_ref"), metadata.get("latest_source_ref")),
        "published_at": _first_non_empty(metadata.get("published_at"), metadata.get("created_at"), metadata.get("as_of")),
    }


def _latest_file_in_dir(base: Any) -> Any | None:
    if base is None or not base.exists() or not base.is_dir():
        return None
    files = [path for path in base.iterdir() if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _latest_news_layer_file(storage_dir: str, *, layer: str) -> Any | None:
    base = _PROJECT_ROOT / "storage" / layer / "news" / storage_dir
    date_dir = _latest_date_dir(base)
    if date_dir is None:
        return None
    return _latest_file_in_dir(date_dir)


def _load_news_feature_brief_summary(path: Any) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    brief = payload.get("daily_market_brief")
    if not isinstance(brief, dict):
        return {}
    market_mainline = brief.get("market_mainline") if isinstance(brief.get("market_mainline"), dict) else {}
    data_quality = brief.get("data_quality") if isinstance(brief.get("data_quality"), dict) else {}
    return {
        "market_mainline": market_mainline,
        "data_quality": data_quality,
        "confirmed_event_count": len(brief.get("confirmed_events") or []),
        "candidate_event_count": len(brief.get("candidate_events") or []),
        "unconfirmed_risk_count": len(brief.get("unconfirmed_risks") or []),
        "calendar_event_count": len(brief.get("next_7d_calendar") or []),
    }


def _load_news_collection_diagnostics(path: Any) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    collector_map = payload.get("latest_collector_status_by_collector")
    source_map = payload.get("latest_source_status_by_source_key")
    summary = payload.get("summary")
    return {
        "collection_summary": dict(summary) if isinstance(summary, dict) else {},
        "latest_collector_status_by_collector": dict(collector_map) if isinstance(collector_map, dict) else {},
        "latest_source_status_by_source_key": dict(source_map) if isinstance(source_map, dict) else {},
    }


def _latest_news_feature_artifacts() -> dict[str, Any]:
    base = _PROJECT_ROOT / "storage" / "features" / "news"
    date_dir = _latest_date_dir(base)
    if date_dir is None:
        return {}
    run_dirs = sorted((path for path in date_dir.iterdir() if path.is_dir()), key=lambda path: path.name, reverse=True)
    for run_dir in run_dirs:
        artifact_paths: dict[str, Any] = {}
        for meta_key, filename in _NEWS_FEATURE_FILENAMES.items():
            candidate = run_dir / filename
            if candidate.exists():
                artifact_paths[meta_key] = _relative_project_path(candidate)
        if not artifact_paths:
            continue
        brief_path = run_dir / _NEWS_FEATURE_FILENAMES["brief_artifact_path"]
        summary = _load_news_feature_brief_summary(brief_path) if brief_path.exists() else {}
        diagnostics_path = run_dir / _NEWS_FEATURE_FILENAMES["collection_diagnostics_artifact_path"]
        diagnostics = _load_news_collection_diagnostics(diagnostics_path) if diagnostics_path.exists() else {}
        return {
            "latest_feature_date": date_dir.name,
            "latest_feature_run_id": run_dir.name,
            "artifact_path": artifact_paths.get("brief_artifact_path")
            or artifact_paths.get("impact_assessments_artifact_path")
            or artifact_paths.get("event_candidates_artifact_path"),
            "collection_diagnostics_artifact_mtime": _path_mtime_iso(diagnostics_path) if diagnostics_path.exists() else None,
            **artifact_paths,
            **summary,
            **diagnostics,
        }
    return {}


def _normalize_source_metadata(source_key: str, metadata: Any, *, source_name: str | None = None) -> dict[str, Any]:
    source_def = _KNOWN_SOURCE_INDEX.get(source_key, {})
    contract = source_def.get("metadata") or {}
    normalized = dict(metadata) if isinstance(metadata, dict) else {}
    if source_name and "frontend_label" not in normalized and not contract.get("frontend_label"):
        normalized["frontend_label"] = source_name
    normalized = {**normalized, **contract}
    normalized["provider_role"] = normalized.get("provider_role") or "derived"
    normalized["fallback_for"] = normalized.get("fallback_for") if isinstance(normalized.get("fallback_for"), list) else []
    normalized["fallback_sources"] = normalized.get("fallback_sources") if isinstance(normalized.get("fallback_sources"), list) else []
    if source_name and "frontend_label" not in normalized:
        normalized["frontend_label"] = source_name
    return normalized


def _build_fs_fallback_source(source_def: dict[str, Any]) -> dict[str, Any]:
    source_key = source_def["source_key"]
    result: dict[str, Any] = {
        "source_key": source_key,
        "source_name": source_def["source_name"],
        "source_group": source_def["source_group"],
        "source_type": source_def["source_type"],
        "access_method": source_def["access_method"],
        "configured": False,
        "raw_ingested": False,
        "parsed": False,
        "analysis_ready": False,
        "latest_raw_time": None,
        "latest_parsed_time": None,
        "latest_snapshot_id": None,
        "row_count": None,
        "status": "not_connected",
        "error_message": None,
        "last_run_id": None,
        "next_run_time": None,
        "metadata": _normalize_source_metadata(source_key, source_def.get("metadata"), source_name=source_def["source_name"]),
    }
    if source_key in ("fred", "fed", "treasury", "dxy"):
        if _check_fs_date_dirs("storage/features/macro") or _check_fs_date_dirs("storage/outputs/macro"):
            result.update({"configured": True, "raw_ingested": True, "parsed": True, "analysis_ready": True, "status": "ok"})
    elif source_key == "cme_daily_bulletin":
        raw_present = (
            _check_fs_date_dirs("raw/cme/daily_bulletin")
            or _check_fs_date_dirs("storage/raw/cme/daily_bulletin")
            or _check_fs_date_dirs("storage/raw/cme")
        )
        parsed_present = _check_fs_date_dirs("storage/parsed/cme")
        if raw_present:
            result.update({"configured": True, "raw_ingested": True, "status": "partial"})
            raw_ref = _latest_artifact_ref_from_layers(["raw/cme/daily_bulletin", "storage/raw/cme/daily_bulletin", "storage/raw/cme"])
            if raw_ref and raw_ref.get("raw_path"):
                result["metadata"]["collector_raw_artifact_path"] = raw_ref["raw_path"]
                result["latest_raw_time"] = raw_ref.get("published_at")
        if parsed_present:
            result.update({"configured": True, "raw_ingested": True, "parsed": True, "status": "ok"})
            parsed_ref = _latest_artifact_ref_from_layers(["storage/parsed/cme"])
            if parsed_ref and parsed_ref.get("raw_path"):
                result["metadata"]["collector_parsed_artifact_path"] = parsed_ref["raw_path"]
                result["latest_parsed_time"] = parsed_ref.get("published_at")
    elif source_key == "cme_options" and (
        _check_fs_date_dirs("storage/outputs/cme")
        or _check_fs_date_dirs("storage/outputs/cme_options")
        or _check_fs_date_dirs("storage/features/cme")
        or _check_fs_date_dirs("storage/features/options")
    ):
        result.update({"configured": True, "raw_ingested": True, "parsed": True, "analysis_ready": True, "status": "ok"})
        options_ref = _latest_artifact_ref_from_layers(["storage/outputs/cme", "storage/outputs/cme_options", "storage/features/cme", "storage/features/options"])
        if options_ref and options_ref.get("raw_path"):
            result["metadata"]["artifact_path"] = options_ref["raw_path"]
            result["latest_parsed_time"] = options_ref.get("published_at")
    elif source_key == "technical_yahoo" and _check_fs_date_dirs("storage/features/technical"):
        result.update({"configured": True, "raw_ingested": True, "parsed": True, "analysis_ready": True, "status": "ok"})
    elif source_key == "positioning_cot" and _check_fs_date_dirs("storage/features/positioning"):
        result.update({"configured": True, "raw_ingested": True, "parsed": True, "analysis_ready": True, "status": "ok"})
    elif source_key == "jin10_news" and _check_fs_date_dirs("storage/features/news"):
        result.update({"configured": True, "raw_ingested": True, "parsed": True, "analysis_ready": True, "status": "ok"})
    elif source_key in _NEWS_SOURCE_STORAGE_DIRS:
        storage_dir = _NEWS_SOURCE_STORAGE_DIRS[source_key]
        raw_present = _check_fs_date_dirs(f"storage/raw/news/{storage_dir}")
        parsed_present = _check_fs_date_dirs(f"storage/parsed/news/{storage_dir}")
        if raw_present:
            result.update({"configured": True, "raw_ingested": True, "status": "partial"})
        if parsed_present:
            result.update({"configured": True, "raw_ingested": True, "parsed": True, "status": "ok"})

    if _check_fs_date_dirs("storage/outputs/final_report") or _check_fs_date_dirs("storage/outputs/strategy_card"):
        if source_key in ("fred", "fed", "treasury", "dxy", "cme_options", "technical_yahoo", "positioning_cot", "jin10_news"):
            result.update({"analysis_ready": True, "status": "ok"})
    return result


def _promote_news_status(current_status: str, *, raw_present: bool, parsed_present: bool, analysis_ready: bool) -> str:
    if current_status in {"error", "failed"}:
        return current_status
    if analysis_ready:
        return "ok"
    if parsed_present or raw_present:
        return "partial" if current_status in {"not_connected", "unavailable"} else current_status or "partial"
    return current_status or "not_connected"


def _augment_news_source_status(source: dict[str, Any]) -> dict[str, Any]:
    source_key = source.get("source_key")
    if source_key not in _NEWS_SOURCE_STORAGE_DIRS and source_key != "jin10_news":
        return source

    result = dict(source)
    metadata = dict(result.get("metadata") or {})
    feature_meta = _latest_news_feature_artifacts()

    raw_file = None
    parsed_file = None
    if source_key in _NEWS_SOURCE_STORAGE_DIRS:
        storage_dir = _NEWS_SOURCE_STORAGE_DIRS[source_key]
        raw_file = _latest_news_layer_file(storage_dir, layer="raw")
        parsed_file = _latest_news_layer_file(storage_dir, layer="parsed")
        if raw_file is not None:
            result["configured"] = True
            result["raw_ingested"] = True
            result["latest_raw_time"] = result.get("latest_raw_time") or _path_mtime_iso(raw_file)
            metadata["collector_raw_artifact_path"] = _relative_project_path(raw_file)
        if parsed_file is not None:
            result["configured"] = True
            result["raw_ingested"] = True
            result["parsed"] = True
            result["latest_parsed_time"] = result.get("latest_parsed_time") or _path_mtime_iso(parsed_file)
            metadata["collector_parsed_artifact_path"] = _relative_project_path(parsed_file)

    if source_key == "jin10_news" and feature_meta:
        result["configured"] = True
        result["raw_ingested"] = True
        result["parsed"] = True

    if feature_meta and (result.get("parsed") or source_key == "jin10_news"):
        result["analysis_ready"] = True
        metadata.update(feature_meta)
        best_artifact_path = feature_meta.get("artifact_path") or metadata.get("collector_parsed_artifact_path") or metadata.get("collector_raw_artifact_path")
        if best_artifact_path:
            metadata["artifact_path"] = best_artifact_path
        result["last_run_id"] = result.get("last_run_id") or feature_meta.get("latest_feature_run_id")
    elif not metadata.get("artifact_path"):
        best_artifact_path = metadata.get("collector_parsed_artifact_path") or metadata.get("collector_raw_artifact_path")
        if best_artifact_path:
            metadata["artifact_path"] = best_artifact_path

    source_runtime = None
    if source_key == "jin10_news":
        source_runtime = feature_meta.get("collection_summary")
    else:
        latest_source_statuses = feature_meta.get("latest_source_status_by_source_key")
        if isinstance(latest_source_statuses, dict):
            candidate = latest_source_statuses.get(source_key)
            if isinstance(candidate, dict):
                source_runtime = candidate
    if feature_meta.get("collection_diagnostics_artifact_path"):
        metadata["collection_diagnostics_artifact_path"] = feature_meta.get("collection_diagnostics_artifact_path")
    if source_runtime:
        if source_key == "jin10_news":
            metadata["latest_collection_summary"] = source_runtime
        else:
            metadata["latest_collection_status"] = source_runtime.get("status")
            metadata["latest_source_ref_count"] = source_runtime.get("source_ref_count")
            metadata["latest_source_ref_statuses"] = list(source_runtime.get("source_ref_statuses") or [])
            metadata["latest_reason_codes"] = list(source_runtime.get("reason_codes") or [])
            metadata["latest_collection_warnings"] = list(source_runtime.get("warnings") or [])
            cooldown = _latest_cooldown_metadata(source_runtime)
            if cooldown:
                metadata["latest_cooldown"] = cooldown

    latest_collectors = feature_meta.get("latest_collector_status_by_collector")
    if isinstance(latest_collectors, dict):
        collector_runtime = latest_collectors.get(source_key)
        if isinstance(collector_runtime, dict):
            metadata["latest_collector_runtime"] = collector_runtime

    result["status"] = _promote_news_status(
        str(result.get("status") or "not_connected"),
        raw_present=bool(result.get("raw_ingested")),
        parsed_present=bool(result.get("parsed")),
        analysis_ready=bool(result.get("analysis_ready")),
    )
    result["metadata"] = metadata
    return result


def _latest_cooldown_metadata(source_runtime: dict[str, Any]) -> dict[str, Any]:
    refs = source_runtime.get("source_refs")
    source_refs = [dict(ref) for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []
    reason_codes = [str(code) for code in (source_runtime.get("reason_codes") or []) if code]
    warnings = [str(warning) for warning in (source_runtime.get("warnings") or []) if warning]
    cooldown_refs = [
        ref for ref in source_refs
        if str(ref.get("status") or "") == "rate_limited"
        or str(ref.get("reason_code") or "") in {"cooldown_active", "rate_limited"}
    ]
    if not cooldown_refs and not ({"cooldown_active", "rate_limited"} & set(reason_codes)):
        return {}

    ref = cooldown_refs[0] if cooldown_refs else {}
    parsed_path = str(ref.get("parsed_path") or "").strip()
    payload = _load_json_artifact(parsed_path) if parsed_path else {}
    reason_code = str(ref.get("reason_code") or (reason_codes[0] if reason_codes else "")).strip()
    cooldown: dict[str, Any] = {
        "active": reason_code == "cooldown_active",
        "status": str(ref.get("status") or source_runtime.get("status") or "").strip() or None,
        "reason_code": reason_code or None,
        "source_ref": ref.get("source_ref"),
        "query_group": ref.get("query_group"),
        "warning": ref.get("warning") or (warnings[0] if warnings else None),
        "parsed_path": parsed_path or None,
    }
    if isinstance(payload, dict):
        for key in ("cooldown_until", "cooldown_seconds", "written_at", "reason"):
            if payload.get(key) not in (None, ""):
                cooldown[key] = payload.get(key)
    return {key: value for key, value in cooldown.items() if value not in (None, "", [])}


def _source_health_state(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    cooldown = metadata.get("latest_cooldown") if isinstance(metadata.get("latest_cooldown"), dict) else {}
    if cooldown.get("active"):
        return "cooldown"

    status = str(source.get("status") or "").strip().lower()
    if status == "ok" and (source.get("analysis_ready") or source.get("parsed") or source.get("raw_ingested")):
        return "healthy"
    if status in {"partial", "stale", "warn", "rate_limited"}:
        return "degraded"
    if status in {"not_connected", "unavailable", "error", "failed"}:
        return "unavailable"
    if source.get("configured") or source.get("raw_ingested") or source.get("parsed"):
        return "degraded"
    return "unavailable"


def _source_readiness_state(source: dict[str, Any]) -> dict[str, str]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    status = str(source.get("status") or "").strip().lower()
    health_state = str(source.get("health_state") or metadata.get("health_state") or "").strip().lower()
    freshness_status = str(source.get("freshness_status") or metadata.get("freshness_status") or "").strip().lower()
    configured = bool(source.get("configured"))
    raw_ingested = bool(source.get("raw_ingested"))
    parsed = bool(source.get("parsed"))
    analysis_ready = bool(source.get("analysis_ready"))
    error_message = str(source.get("error_message") or "").strip()

    if not configured:
        return {
            "readiness_state": "not_configured",
            "gate_state": "closed",
            "gating_reason": "not_configured",
        }

    if error_message:
        return {
            "readiness_state": "blocked",
            "gate_state": "closed",
            "gating_reason": "error_message",
        }

    if status in {"error", "failed"}:
        return {
            "readiness_state": "blocked",
            "gate_state": "closed",
            "gating_reason": f"status_{status}",
        }

    if health_state in {"unavailable", "error", "failed"}:
        return {
            "readiness_state": "blocked",
            "gate_state": "closed",
            "gating_reason": f"health_{health_state}",
        }

    if freshness_status == "stale":
        return {
            "readiness_state": "degraded",
            "gate_state": "degraded",
            "gating_reason": "freshness_stale",
        }

    if freshness_status == "manual":
        return {
            "readiness_state": "degraded",
            "gate_state": "degraded",
            "gating_reason": "freshness_manual",
        }

    if analysis_ready and status == "ok" and health_state in {"", "healthy"}:
        return {
            "readiness_state": "ready",
            "gate_state": "open",
            "gating_reason": "analysis_ready",
        }

    if status in {"partial", "stale", "warn", "rate_limited"} or health_state in {"degraded", "cooldown"} or raw_ingested or parsed or analysis_ready:
        if health_state == "cooldown":
            reason = "health_cooldown"
        elif status in {"partial", "stale", "warn", "rate_limited"}:
            reason = f"status_{status}"
        elif analysis_ready:
            reason = "analysis_ready_partial"
        elif parsed:
            reason = "parsed_only"
        elif raw_ingested:
            reason = "raw_only"
        else:
            reason = "pipeline_incomplete"
        return {
            "readiness_state": "degraded",
            "gate_state": "degraded",
            "gating_reason": reason,
        }

    return {
        "readiness_state": "blocked",
        "gate_state": "closed",
        "gating_reason": "pipeline_incomplete",
    }


def _stage_health(
    status: str,
    *,
    message: str | None = None,
    updated_at: str | None = None,
    input_ref: str | None = None,
    output_ref: str | None = None,
) -> dict[str, Any]:
    stage: dict[str, Any] = {"status": status}
    if message:
        stage["message"] = message
    if updated_at:
        stage["updated_at"] = updated_at
    if input_ref:
        stage["input_ref"] = input_ref
    if output_ref:
        stage["output_ref"] = output_ref
    return stage


def _artifact_item(key: str, label: str, layer: str, path: str | None) -> dict[str, str] | None:
    if not isinstance(path, str) or not path.strip():
        return None
    return {"key": key, "label": label, "layer": layer, "path": path.strip()}


def _dedupe_artifact_items(items: list[dict[str, str] | None]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not item:
            continue
        key = (item["layer"], item["path"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _source_artifact_evidence(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    latest_raw_ref = metadata.get("latest_raw_ref") if isinstance(metadata.get("latest_raw_ref"), dict) else {}
    collector_raw = _first_non_empty(
        metadata.get("collector_raw_artifact_path"),
        metadata.get("raw_artifact_path"),
        metadata.get("raw_path"),
        latest_raw_ref.get("raw_path"),
    )
    collector_parsed = _first_non_empty(
        metadata.get("collector_parsed_artifact_path"),
        metadata.get("parsed_artifact_path"),
        metadata.get("parsed_path"),
        latest_raw_ref.get("parsed_path"),
    )
    preferred = _first_non_empty(
        metadata.get("artifact_path"),
        metadata.get("brief_artifact_path"),
        metadata.get("daily_analysis_triggers_artifact_path"),
        metadata.get("article_briefs_artifact_path"),
        metadata.get("event_candidates_artifact_path"),
        metadata.get("impact_assessments_artifact_path"),
        metadata.get("report_events_artifact_path"),
        collector_parsed,
        collector_raw,
    )
    raw_artifacts = _dedupe_artifact_items(
        [
            _artifact_item("collector_raw", "Collector raw", "raw", collector_raw),
            _artifact_item("latest_raw_ref", "Latest raw ref", "raw", latest_raw_ref.get("raw_path")),
        ]
    )
    parsed_artifacts = _dedupe_artifact_items(
        [
            _artifact_item("collector_parsed", "Collector parsed", "parsed", collector_parsed),
            _artifact_item("latest_raw_ref_parsed", "Latest parsed ref", "parsed", latest_raw_ref.get("parsed_path")),
        ]
    )
    feature_artifacts = _dedupe_artifact_items(
        [
            _artifact_item("brief", "Daily market brief", "features", metadata.get("brief_artifact_path")),
            _artifact_item("daily_analysis_triggers", "Daily analysis triggers", "features", metadata.get("daily_analysis_triggers_artifact_path")),
            _artifact_item("article_briefs", "Jin10 article briefs", "features", metadata.get("article_briefs_artifact_path")),
            _artifact_item("event_candidates", "Event candidates", "features", metadata.get("event_candidates_artifact_path")),
            _artifact_item("impact_assessments", "Impact assessments", "features", metadata.get("impact_assessments_artifact_path")),
            _artifact_item("market_reactions", "Market reactions", "features", metadata.get("market_reactions_artifact_path")),
            _artifact_item("report_events", "Report events", "features", metadata.get("report_events_artifact_path")),
            _artifact_item("collection_diagnostics", "Collection diagnostics", "features", metadata.get("collection_diagnostics_artifact_path")),
            _artifact_item("preferred", "Preferred artifact", "features", preferred if str(preferred or "").startswith("storage/features/") else None),
        ]
    )
    analysis_artifacts = _dedupe_artifact_items(
        [
            _artifact_item("analysis", "Analysis artifact", "analysis", metadata.get("analysis_artifact_path")),
            _artifact_item("snapshot", "Analysis snapshot", "analysis", metadata.get("snapshot_artifact_path")),
        ]
    )
    return {
        "preferred_artifact_path": preferred,
        "collector_raw_artifact_path": collector_raw,
        "collector_parsed_artifact_path": collector_parsed,
        "latest_raw_url": metadata.get("latest_raw_url"),
        "raw_artifacts": raw_artifacts,
        "parsed_artifacts": parsed_artifacts,
        "feature_artifacts": feature_artifacts,
        "analysis_artifacts": analysis_artifacts,
    }


def _latest_data_date(source: dict[str, Any]) -> str | None:
    latest = _max_iso_datetime(source.get("latest_update_time"), source.get("latest_parsed_time"), source.get("latest_raw_time"))
    return latest[:10] if isinstance(latest, str) and len(latest) >= 10 else None


def _staleness_days(latest_data_date: str | None) -> int | None:
    if not latest_data_date:
        return None
    try:
        latest_dt = datetime.fromisoformat(latest_data_date).date()
    except ValueError:
        return None
    return (_utc_now().date() - latest_dt).days


def _affected_modules_for_source(source: dict[str, Any]) -> list[str]:
    source_group = str(source.get("source_group") or "")
    return list(_SOURCE_REQUIRED_FOR_BY_GROUP.get(source_group, [source_group or "unknown"]))


def _source_pipeline_health(source: dict[str, Any], artifact_evidence: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    source_key = str(source.get("source_key") or "")
    source_group = str(source.get("source_group") or "unknown")
    source_name = str(metadata.get("frontend_label") or source.get("source_name") or source_key)
    configured = bool(source.get("configured"))
    raw_ingested = bool(source.get("raw_ingested"))
    parsed = bool(source.get("parsed"))
    analysis_ready = bool(source.get("analysis_ready"))
    status = str(source.get("status") or "").strip().lower()
    error_message = str(source.get("error_message") or "").strip()
    snapshot_id = source.get("latest_snapshot_id")
    raw_ref = artifact_evidence.get("collector_raw_artifact_path")
    parsed_ref = artifact_evidence.get("collector_parsed_artifact_path")
    preferred_ref = artifact_evidence.get("preferred_artifact_path")
    latest_raw_time = source.get("latest_raw_time")
    latest_parsed_time = source.get("latest_parsed_time")
    latest_update_time = source.get("latest_update_time")

    has_raw_evidence = raw_ingested or bool(raw_ref) or bool(latest_raw_time)
    has_parsed_evidence = parsed or bool(parsed_ref) or bool(latest_parsed_time)
    failed = status in {"error", "failed", "not_connected", "unavailable"}

    connection = _stage_health("OK" if configured else "ERROR", message=None if configured else "not configured")
    if not configured:
        collect = _stage_health("BLOCKED", message="upstream not configured")
        raw_landing = _stage_health("BLOCKED")
        parse = _stage_health("BLOCKED")
        validate = _stage_health("BLOCKED")
        snapshot = _stage_health("BLOCKED")
        consumer_ready = _stage_health("BLOCKED")
    else:
        if has_raw_evidence:
            collect = _stage_health("OK", updated_at=latest_raw_time, output_ref=raw_ref)
            raw_landing = _stage_health("OK", updated_at=latest_raw_time, output_ref=raw_ref)
        elif failed:
            collect = _stage_health("ERROR", message=error_message or "collection failed")
            raw_landing = _stage_health("NO_DATA")
        else:
            collect = _stage_health("NO_DATA", message="no data collected")
            raw_landing = _stage_health("NO_DATA")

        if has_parsed_evidence:
            parse = _stage_health("OK", updated_at=latest_parsed_time, input_ref=raw_ref, output_ref=parsed_ref)
        elif has_raw_evidence:
            parse = _stage_health("WARN" if status in {"partial", "stale", "warn", "rate_limited"} else "ERROR", message="raw ingested but parse incomplete", input_ref=raw_ref)
        else:
            parse = _stage_health("BLOCKED", message="no raw data")

        if has_parsed_evidence:
            validate = _stage_health("OK" if status == "ok" else "WARN", message=None if status == "ok" else "degraded quality", input_ref=parsed_ref)
        else:
            validate = _stage_health("BLOCKED", message="parse not ready")

        if analysis_ready:
            snapshot = _stage_health("READY", message="analysis ready", input_ref=preferred_ref, output_ref=snapshot_id)
            consumer_ready = _stage_health("READY", input_ref=snapshot_id or preferred_ref)
        elif snapshot_id:
            snapshot = _stage_health("READY", message="snapshot available", input_ref=preferred_ref, output_ref=snapshot_id)
            consumer_ready = _stage_health("WARN", message="using snapshot without analysis_ready", input_ref=snapshot_id)
        elif has_parsed_evidence:
            snapshot = _stage_health("NO_SNAPSHOT", message="parsed but no snapshot yet", input_ref=parsed_ref)
            consumer_ready = _stage_health("WARN", message="partial availability", input_ref=parsed_ref)
        else:
            snapshot = _stage_health("BLOCKED", message="upstream incomplete")
            consumer_ready = _stage_health("BLOCKED", message="upstream incomplete")

    gate_state = str(source.get("gate_state") or metadata.get("gate_state") or "").lower()
    if analysis_ready and gate_state in {"", "open"}:
        downstream_status = "READY"
    elif gate_state == "closed" and not has_parsed_evidence:
        downstream_status = "BLOCKED"
    elif has_parsed_evidence or snapshot_id or analysis_ready:
        downstream_status = "DEGRADED"
    else:
        downstream_status = "BLOCKED"

    latest_data_date = _latest_data_date(source)
    return {
        "source_id": source_key,
        "source_name": source_name,
        "source_type": str(source.get("source_type") or "unknown"),
        "domain": source_group,
        "priority": str(metadata.get("provider_role") or "derived"),
        "stages": {
            "connection": connection,
            "collect": collect,
            "raw_landing": raw_landing,
            "parse": parse,
            "validate": validate,
            "snapshot": snapshot,
            "consumer_ready": consumer_ready,
        },
        "latest_run_id": source.get("last_run_id"),
        "snapshot_id": snapshot_id,
        "raw_artifact_ref": raw_ref,
        "fact_table": next(iter(metadata.get("database_tables") or []), None),
        "affected_modules": _affected_modules_for_source(source),
        "downstream_status": downstream_status,
        "latest_data_date": latest_data_date,
        "staleness_days": _staleness_days(latest_data_date),
        "latest_update_time": latest_update_time,
    }


def _source_latest_health_at(source: dict[str, Any]) -> str | None:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    cooldown = metadata.get("latest_cooldown") if isinstance(metadata.get("latest_cooldown"), dict) else {}
    return _max_iso_datetime(
        source.get("latest_update_time"),
        metadata.get("latest_artifact_mtime"),
        metadata.get("collection_diagnostics_artifact_mtime"),
        cooldown.get("written_at"),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _source_freshness(source: dict[str, Any]) -> dict[str, str]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    if not bool(source.get("configured")):
        return {
            "freshness_status": "not_applicable",
            "freshness_reason": "not_configured",
        }

    polling = metadata.get("polling_strategy") if isinstance(metadata.get("polling_strategy"), dict) else {}
    mode = str(polling.get("mode") or "").strip().lower()
    if mode in _MANUAL_FRESHNESS_MODES:
        return {
            "freshness_status": "manual",
            "freshness_reason": "manual_refresh",
        }

    latest_update_time = source.get("latest_update_time")
    latest_dt = _parse_datetime(latest_update_time)
    if latest_dt is None:
        return {
            "freshness_status": "unknown",
            "freshness_reason": "missing_timestamp",
        }

    ttl = _FRESHNESS_MODE_TTLS.get(mode)
    if ttl is None:
        return {
            "freshness_status": "unknown",
            "freshness_reason": "unknown_mode",
        }

    if _utc_now() - latest_dt <= ttl:
        return {
            "freshness_status": "fresh",
            "freshness_reason": "within_sla",
        }
    return {
        "freshness_status": "stale",
        "freshness_reason": "ttl_exceeded",
    }


def _load_json_artifact(path_rel: str) -> dict[str, Any]:
    path = _resolve_project_or_storage_path(path_rel)
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_project_or_storage_path(path_rel: str) -> Any | None:
    if not path_rel:
        return None
    candidates = [_PROJECT_ROOT / path_rel]
    if not path_rel.startswith("storage/"):
        candidates.append(_PROJECT_ROOT / "storage" / path_rel)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _raw_ref_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    refs = item.get("source_refs")
    first_ref = next((ref for ref in refs if isinstance(ref, dict)), {}) if isinstance(refs, list) else {}
    url = _first_non_empty(item.get("source_url"), item.get("url"), item.get("final_url"), first_ref.get("url"))
    raw_path = _first_non_empty(item.get("raw_path"), first_ref.get("raw_path"))
    parsed_path = _first_non_empty(item.get("parsed_path"), first_ref.get("parsed_path"))
    source_ref = _first_non_empty(item.get("source_ref"), first_ref.get("source_ref"))
    if not url and not raw_path and not parsed_path:
        return None
    return {
        "label": _first_non_empty(item.get("headline"), item.get("source_title"), item.get("title"), item.get("event_type")) or "latest raw",
        "url": url,
        "raw_path": raw_path,
        "parsed_path": parsed_path,
        "source_ref": source_ref,
        "published_at": _first_non_empty(
            item.get("created_at"),
            item.get("published_at"),
            item.get("event_time"),
            item.get("time"),
        ),
        "summary": _first_non_empty(
            item.get("summary_zh"),
            item.get("summary"),
            item.get("analysis_summary"),
            item.get("original_excerpt"),
            item.get("evidence_text"),
            item.get("filter_reason"),
        ),
        "importance": _first_non_empty(item.get("importance"), item.get("priority"), item.get("risk_level")),
        "classification_confidence": item.get("classification_confidence"),
    }


def _latest_raw_ref_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for key in ("triggers", "briefs", "events", "items", "source_refs"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            ref = _raw_ref_from_item(item)
            if ref:
                candidates.append(ref)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda ref: (
            (_parse_datetime(ref.get("published_at")).timestamp() if _parse_datetime(ref.get("published_at")) else 0),
            str(ref.get("source_ref") or ref.get("url") or ref.get("raw_path") or ""),
        ),
    )


def _latest_raw_ref_from_artifact(path_rel: Any) -> dict[str, Any] | None:
    if not isinstance(path_rel, str) or not path_rel.strip():
        return None
    payload = _load_json_artifact(path_rel)
    if not payload:
        return None
    return _latest_raw_ref_from_payload(payload)


def _latest_news_raw_ref(metadata: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("daily_analysis_triggers_artifact_path", "article_briefs_artifact_path", "brief_artifact_path", "event_candidates_artifact_path"):
        ref = _latest_raw_ref_from_artifact(metadata.get(key))
        if ref:
            return ref
    return _latest_raw_ref_from_metadata(metadata)


def _latest_artifact_ref_from_layers(layers: list[str]) -> dict[str, Any] | None:
    latest_path = None
    latest_mtime = None
    for layer in layers:
        if not isinstance(layer, str) or not layer.strip():
            continue
        root = _PROJECT_ROOT / layer
        if not root.exists():
            continue
        candidates = (root,) if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = path
    if latest_path is None:
        return None
    return {
        "label": latest_path.name,
        "url": None,
        "raw_path": _relative_project_path(latest_path),
        "parsed_path": None,
        "source_ref": _relative_project_path(latest_path),
        "published_at": _path_mtime_iso(latest_path),
    }


def _augment_source_observability(source: dict[str, Any]) -> dict[str, Any]:
    result = dict(source)
    source_key = str(result.get("source_key") or "")
    metadata = dict(result.get("metadata") or {})
    contract = _source_observability_contract(source_key)

    latest_raw_ref = _latest_news_raw_ref(metadata) if result.get("source_group") == "news" else _latest_raw_ref_from_metadata(metadata)
    if not latest_raw_ref:
        latest_raw_ref = _latest_artifact_ref_from_layers(list(contract.get("artifact_layers") or []))
    if latest_raw_ref:
        metadata["latest_raw_ref"] = latest_raw_ref
        if latest_raw_ref.get("url"):
            metadata["latest_raw_url"] = latest_raw_ref["url"]
        if latest_raw_ref.get("published_at"):
            metadata["latest_artifact_mtime"] = latest_raw_ref["published_at"]

    metadata.update(contract)
    result["metadata"] = metadata
    result["latest_update_time"] = _latest_update_time(result)
    latest_health_at = _source_latest_health_at(result)
    if latest_health_at:
        metadata["latest_health_at"] = latest_health_at
        result["latest_health_at"] = latest_health_at
    health_state = _source_health_state(result)
    metadata["health_state"] = health_state
    result["health_state"] = health_state
    freshness = _source_freshness(result)
    metadata.update(freshness)
    result.update(freshness)
    readiness = _source_readiness_state(result)
    metadata.update(readiness)
    result.update(readiness)
    artifact_evidence = _source_artifact_evidence(result)
    result["artifact_evidence"] = artifact_evidence
    result["affected_modules"] = _affected_modules_for_source(result)
    result["pipeline_health"] = _source_pipeline_health(result, artifact_evidence)
    return result


def _row_to_source_status(row: Any) -> dict[str, Any]:
    return {
        "source_key": row.source_key,
        "source_name": row.source_name,
        "source_group": row.source_group,
        "source_type": row.source_type,
        "access_method": row.access_method,
        "configured": bool(row.configured),
        "raw_ingested": bool(row.raw_ingested),
        "parsed": bool(row.parsed),
        "analysis_ready": bool(row.analysis_ready),
        "latest_raw_time": row.latest_raw_time.isoformat() if row.latest_raw_time else None,
        "latest_parsed_time": row.latest_parsed_time.isoformat() if row.latest_parsed_time else None,
        "latest_snapshot_id": row.latest_snapshot_id,
        "row_count": row.row_count,
        "status": row.status,
        "error_message": row.error_message,
        "last_run_id": row.last_run_id,
        "next_run_time": row.next_run_time.isoformat() if row.next_run_time else None,
        "metadata": _normalize_source_metadata(row.source_key, row.source_metadata, source_name=row.source_name),
    }


def _merge_known_source_contract(existing_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {src["source_key"]: src for src in existing_sources}
    merged: list[dict[str, Any]] = []
    for source_def in _KNOWN_SOURCE_DEFS:
        source_key = source_def["source_key"]
        if source_key in by_key:
            src = dict(by_key[source_key])
            src["metadata"] = _normalize_source_metadata(source_key, src.get("metadata"), source_name=src.get("source_name"))
            merged.append(src)
        else:
            merged.append(_build_fs_fallback_source(source_def))
    for source_key in sorted(by_key.keys()):
        if source_key not in _KNOWN_SOURCE_INDEX:
            src = dict(by_key[source_key])
            src["metadata"] = _normalize_source_metadata(source_key, src.get("metadata"), source_name=src.get("source_name"))
            merged.append(src)
    return [_augment_source_observability(_augment_news_source_status(src)) for src in merged]


def get_data_source_statuses() -> dict[str, Any]:
    db = _try_db_session()
    if db is not None:
        try:
            from database.queries.data_source_status import list_data_source_statuses

            rows = list_data_source_statuses(db)
            if rows:
                return {"sources": _merge_known_source_contract([_row_to_source_status(row) for row in rows])}
        except Exception:
            pass
        finally:
            db.close()
    return {"sources": _merge_known_source_contract([])}


def get_data_source_status_index() -> dict[str, dict[str, Any]]:
    statuses = get_data_source_statuses()
    index: dict[str, dict[str, Any]] = {}
    for source in statuses.get("sources", []):
        source_key = source.get("source_key")
        if isinstance(source_key, str) and source_key not in index:
            index[source_key] = source
    return index


def get_data_sources_registry() -> dict[str, Any]:
    """Return the configured source registry contract used by health/readiness views."""
    sources = [_source_registry_entry(source_def) for source_def in _KNOWN_SOURCE_DEFS]
    return {"total": len(sources), "sources": sources}


def get_data_source_history(source_key: str, *, db: Any, limit: int = 30) -> dict[str, Any]:
    """Return persisted daily source-health rows for one source."""
    from database.queries.data_source_health import list_data_source_health_history

    return list_data_source_health_history(db, source_key, limit=limit)


def _source_registry_entry(source_def: dict[str, Any]) -> dict[str, Any]:
    source_key = str(source_def.get("source_key") or "")
    source_group = str(source_def.get("source_group") or "unknown")
    observability = _SOURCE_OBSERVABILITY.get(source_key, {})
    polling_strategy = observability.get("polling_strategy") if isinstance(observability, dict) else {}
    if not isinstance(polling_strategy, dict):
        polling_strategy = {}
    mode = str(polling_strategy.get("mode") or "")
    ttl = _FRESHNESS_MODE_TTLS.get(mode)
    metadata = source_def.get("metadata") if isinstance(source_def.get("metadata"), dict) else {}
    required_for = metadata.get("required_for")
    if not isinstance(required_for, list):
        required_for = _SOURCE_REQUIRED_FOR_BY_GROUP.get(source_group, [source_group])
    return {
        "source_key": source_key,
        "source_name": source_def.get("source_name") or source_key,
        "domain": source_group,
        "provider": source_def.get("source_name") or source_key,
        "source_type": source_def.get("source_type"),
        "access_method": source_def.get("access_method"),
        "expected_frequency": _expected_frequency_from_polling_mode(mode),
        "expected_arrival_time": None,
        "freshness_sla_minutes": None if ttl is None else int(ttl.total_seconds() // 60),
        "required_for": list(required_for),
        "fallback_policy": _fallback_policy_from_metadata(metadata),
        "owner_module": _owner_module_for_source(source_group),
        "enabled": True,
        "metadata": metadata,
        "polling_strategy": polling_strategy,
    }


def _expected_frequency_from_polling_mode(mode: str) -> str:
    if mode in {"server_side_cache", "cached_market_poll", "cursor_poll", "rss_poll", "rate_limited_query_groups"}:
        return "intraday"
    if mode == "weekly_batch":
        return "weekly"
    if mode == "manual_or_authorized_browser_profile":
        return "manual"
    return "daily"


def _fallback_policy_from_metadata(metadata: dict[str, Any]) -> str:
    explicit_policy = metadata.get("fallback_policy")
    if isinstance(explicit_policy, str) and explicit_policy.strip():
        return explicit_policy.strip()
    fallback_sources = metadata.get("fallback_sources")
    fallback_for = metadata.get("fallback_for")
    if isinstance(fallback_sources, list) and fallback_sources:
        return "fallback_available"
    if isinstance(fallback_for, list) and fallback_for:
        return "fallback_provider"
    return "block_if_unavailable"


def _owner_module_for_source(source_group: str) -> str:
    return {
        "macro": "collectors.macro",
        "cme": "collectors.cme",
        "technical": "collectors.market",
        "positioning": "collectors.positioning",
        "news": "collectors.news",
        "reports": "collectors.reports",
    }.get(source_group, "collectors")


def _source_layer_status(*, done: bool, configured: bool, status: str) -> str:
    if done:
        return "success"
    if not configured:
        return "unavailable"
    if status in {"failed", "error"}:
        return "failed"
    if status in {"not_connected", "unavailable"}:
        return "unavailable"
    if status in {"stale", "rate_limited"}:
        return "stale"
    return "pending"


def _source_health_data_status(source: dict[str, Any]) -> str:
    status = str(source.get("status") or "not_connected").lower()
    freshness_status = str(source.get("freshness_status") or source.get("metadata", {}).get("freshness_status") or "").lower()
    gate_state = str(source.get("gate_state") or source.get("metadata", {}).get("gate_state") or "").lower()
    if status == "ok" and freshness_status == "fresh" and gate_state in {"", "open"}:
        return "live"
    if status == "ok" or status in {"partial", "stale", "warn", "rate_limited"} or gate_state == "degraded":
        return "partial"
    return "unavailable"


def get_data_source_health_latest(date: str | None = None, db: Any | None = None) -> dict[str, Any]:
    """Return a derived latest source-health snapshot from the current status read model."""
    if date is not None and db is not None:
        from database.queries.data_source_health import get_data_source_health_snapshot

        persisted = get_data_source_health_snapshot(db, date)
        if persisted is not None:
            return persisted

    as_of_dt = _utc_now()
    as_of = as_of_dt.isoformat()
    snapshot_date = date or as_of_dt.date().isoformat()
    sources = get_data_source_statuses().get("sources", [])

    items: list[dict[str, Any]] = []
    live_count = 0
    partial_count = 0
    unavailable_count = 0
    stale_sources: list[str] = []

    for source in sources:
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        source_key = str(source.get("source_key") or "")
        source_name = str(source.get("source_name") or source_key)
        label = str(metadata.get("frontend_label") or source_name)
        status = str(source.get("status") or "not_connected").lower()
        configured = bool(source.get("configured"))
        raw_ingested = bool(source.get("raw_ingested"))
        parsed = bool(source.get("parsed"))
        feature_ready = bool(source.get("latest_snapshot_id") or source.get("analysis_ready"))
        analysis_ready = bool(source.get("analysis_ready"))
        freshness_status = str(source.get("freshness_status") or metadata.get("freshness_status") or "unknown")
        freshness_reason = str(source.get("freshness_reason") or metadata.get("freshness_reason") or "unknown")
        data_status = _source_health_data_status(source)

        if data_status == "live":
            live_count += 1
        elif data_status == "partial":
            partial_count += 1
        else:
            unavailable_count += 1
        if freshness_status == "stale":
            stale_sources.append(label)

        items.append(
            {
                "source_key": source_key,
                "source_name": source_name,
                "source_group": source.get("source_group"),
                "provider_role": metadata.get("provider_role"),
                "latest_data_date": source.get("latest_update_time"),
                "latest_health_at": source.get("latest_health_at") or metadata.get("latest_health_at"),
                "health_state": source.get("health_state") or metadata.get("health_state") or "unavailable",
                "freshness_status": freshness_status,
                "freshness_reason": freshness_reason,
                "raw_status": _source_layer_status(done=raw_ingested, configured=configured, status=status),
                "parsed_status": _source_layer_status(done=parsed, configured=configured, status=status),
                "feature_status": _source_layer_status(done=feature_ready, configured=configured, status=status),
                "analysis_status": _source_layer_status(done=analysis_ready, configured=configured, status=status),
                "data_status": data_status,
                "readiness_state": source.get("readiness_state") or metadata.get("readiness_state"),
                "gate_state": source.get("gate_state") or metadata.get("gate_state"),
                "gating_reason": source.get("gating_reason") or metadata.get("gating_reason"),
                "last_run_id": source.get("last_run_id"),
                "latest_snapshot_id": source.get("latest_snapshot_id"),
            }
        )

    if unavailable_count == 0 and partial_count == 0 and live_count > 0:
        overall_status = "LIVE"
    elif live_count > 0 or partial_count > 0:
        overall_status = "PARTIAL"
    else:
        overall_status = "UNAVAILABLE"

    return {
        "snapshot_date": snapshot_date,
        "as_of": as_of,
        "overall_status": overall_status,
        "counts": {
            "total": len(items),
            "live": live_count,
            "partial": partial_count,
            "unavailable": unavailable_count,
            "stale": len(stale_sources),
        },
        "stale_sources": stale_sources,
        "items": items,
    }


def persist_data_source_health_snapshot(
    db: Any,
    *,
    date: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a source-health snapshot and return the persisted payload."""
    from database.queries.data_source_health import get_data_source_health_snapshot, upsert_data_source_health_snapshot

    snapshot_payload = payload or get_data_source_health_latest(date=date)
    snapshot = upsert_data_source_health_snapshot(db, snapshot_payload)
    persisted = get_data_source_health_snapshot(db, snapshot.snapshot_date)
    if persisted is None:
        return snapshot_payload
    return persisted


def get_data_status_summary() -> dict[str, Any]:
    """Aggregate global data status for the frontend DataStatusBar.

    Combines DataSourceStatus + latest TaskRun + latest AnalysisSnapshot
    into a single summary with overall_status: LIVE | PARTIAL | MOCK | UNAVAILABLE.
    """
    from database.models.task import TaskRun

    sources_data = get_data_source_statuses()
    sources = sources_data.get("sources", [])

    # Classify each source
    live_count = 0
    partial_count = 0
    unavailable_count = 0
    source_list: list[dict[str, Any]] = []
    missing_sources: list[str] = []
    stale_sources: list[str] = []

    for src in sources:
        status = src.get("status", "not_connected")
        source_key = src.get("source_key", "")
        label = src.get("metadata", {}).get("frontend_label") or src.get("source_name", source_key)
        latest_health_at = src.get("latest_health_at") or src.get("metadata", {}).get("latest_health_at")
        health_state = src.get("health_state") or src.get("metadata", {}).get("health_state") or "unavailable"
        raw_freshness_status = src.get("freshness_status") or src.get("metadata", {}).get("freshness_status")
        raw_freshness_reason = src.get("freshness_reason") or src.get("metadata", {}).get("freshness_reason")
        freshness_status = str(raw_freshness_status) if raw_freshness_status else ("fresh" if status == "ok" else "unknown")
        freshness_reason = str(raw_freshness_reason) if raw_freshness_reason else ("status_only" if status == "ok" else "unknown")

        if status == "ok" and freshness_status == "fresh":
            source_list.append({
                "name": source_key,
                "status": "LIVE",
                "source": "api",
                "label": label,
                "latest_health_at": latest_health_at,
                "health_state": health_state,
                "freshness_status": freshness_status,
                "freshness_reason": freshness_reason,
            })
            live_count += 1
        elif status == "ok" and freshness_status in {"stale", "manual", "unknown"}:
            source_list.append({
                "name": source_key,
                "status": "PARTIAL",
                "source": "api",
                "label": label,
                "latest_health_at": latest_health_at,
                "health_state": health_state,
                "freshness_status": freshness_status,
                "freshness_reason": freshness_reason,
            })
            partial_count += 1
            if freshness_status == "stale":
                stale_sources.append(label)
        elif status in ("partial", "stale", "warn", "rate_limited"):
            source_list.append({
                "name": source_key,
                "status": "PARTIAL",
                "source": "api",
                "label": label,
                "latest_health_at": latest_health_at,
                "health_state": health_state,
                "freshness_status": freshness_status,
                "freshness_reason": freshness_reason,
            })
            partial_count += 1
        else:
            source_list.append({
                "name": source_key,
                "status": "UNAVAILABLE",
                "source": "unavailable",
                "label": label,
                "latest_health_at": latest_health_at,
                "health_state": health_state,
                "freshness_status": freshness_status,
                "freshness_reason": freshness_reason,
            })
            unavailable_count += 1
            missing_sources.append(label)

    # Determine overall status
    if live_count > 0 and unavailable_count == 0 and partial_count == 0:
        overall_status = "LIVE"
    elif live_count > 0:
        overall_status = "PARTIAL"
    elif partial_count > 0:
        overall_status = "PARTIAL"
    else:
        overall_status = "UNAVAILABLE"

    latest_run: dict[str, Any] | None = None
    snapshot_id: str | None = None
    data_date: str | None = None
    db = _try_db_session()
    if db is not None:
        try:
            task = db.query(TaskRun).order_by(TaskRun.created_at.desc()).limit(1).first()
            if task:
                latest_run = {
                    "run_id": str(task.id),
                    "status": task.status.value,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "trade_date": task.trade_date,
                }

            from database.models.analysis import AnalysisSnapshot

            snap = db.query(AnalysisSnapshot).order_by(AnalysisSnapshot.created_at.desc()).limit(1).first()
            if snap:
                snapshot_id = snap.snapshot_id
                data_date = snap.trade_date.isoformat() if snap.trade_date else None
        except Exception:
            pass
        finally:
            db.close()

    return {
        "overall_status": overall_status,
        "latest_run": latest_run,
        "snapshot_id": snapshot_id,
        "data_date": data_date,
        "sources": source_list,
        "missing_sources": missing_sources,
        "stale_sources": stale_sources,
    }
