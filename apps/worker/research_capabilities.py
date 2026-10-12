"""Allowlisted evidence capabilities for hypothesis-driven gold research.

The deterministic baseline is collected before this catalog is exposed to the
model.  The model may choose only supplemental reads from this catalog; it
cannot suppress baseline collection or invent a collector.
"""

from apps.collectors.fred.collector import FRED_SERIES
from apps.parsers.market.tradingview import ALL_INSTRUMENTS
from apps.collectors.research.public_evidence import BOOKMARKS, ALLOWED_HOSTS


OPTIONAL_FRED_SERIES = {
    "DDFUELUSGULF": "美国湾区超低硫柴油现货；检验成品油二阶通胀",
    "DGASUSGULF": "美国湾区普通汽油现货；检验居民能源价格传导",
}

FRED_PURPOSES = {
    "RRPONTSYD": "ON RRP用量；流动性缓冲背景",
    "RRPONTSYAWARD": "ON RRP利率；短端工具背景",
    "WRESBAL": "银行准备金；数量型流动性",
    "WTREGEN": "TGA周均余额；财政抽水",
    "WALCL": "Fed总资产；资产负债表背景",
    "SOFR": "担保隔夜融资利率；融资压力",
    "EFFR": "有效联邦基金利率；政策执行",
    "IORB": "准备金利率；融资利差基准",
    "DGS2": "2年期国债；近端政策路径",
    "DGS3MO": "3个月国债；当前政策锚与2Y-3M",
    "DGS5": "5年期国债；中段政策和增长",
    "DGS10": "10年期名义收益率",
    "DGS30": "30年期名义收益率；期限与财政压力",
    "DFII5": "5年期TIPS实际利率",
    "DFII10": "10年期TIPS实际利率；黄金机会成本",
    "DFII30": "30年期TIPS实际利率",
    "T5YIE": "5年期盈亏平衡通胀率",
    "T5YIFR": "5年后5年远期通胀预期",
    "T10YIE": "10年期盈亏平衡通胀率",
    "DTWEXBGS": "广义美元指数；正式宏观美元口径",
    "BAMLH0A0HYM2": "高收益债OAS；信用压力",
    "DCOILWTICO": "WTI现货日度序列；非盘中期货",
    "DCOILBRENTEU": "Brent现货日度序列；非盘中期货",
    "VIXCLS": "VIX官方日度收盘；非盘中值",
    "CPIAUCSL": "季调CPI总指数；通胀动能",
    "CPILFESL": "季调核心CPI；底层通胀动能",
    "CPIAUCNS": "未季调CPI总指数；同比口径",
    "CPILFENS": "未季调核心CPI；同比口径",
    "PCEPILFE": "核心PCE价格指数；Fed目标相关",
    "CPIENGSL": "CPI能源分项",
    "CPIUFDSL": "CPI食品分项",
    "CUSR0000SAH1": "CPI住房分项",
    "CUSR0000SEHA": "CPI租金分项",
    "CUSR0000SEHC": "CPI业主等价租金分项",
    "CUSR0000SACL1E": "CPI核心商品分项",
    "CUSR0000SASLE": "CPI能源服务分项",
    "PPIFIS": "PPI最终需求；上游通胀管道",
    "PPIACO": "PPI全部商品；商品成本压力",
    "PCEPI": "PCE总价格指数",
    "JTSJOL": "JOLTS职位空缺；劳动力需求",
    "ICSA": "初请失业金；高频就业压力",
    "NAPM": "已停用的历史ISM镜像；不得当作当前ISM",
}


def capability_catalog() -> dict:
    """Return a compact, serializable catalog for one research decision."""
    fred = {
        symbol: {
            "description": OPTIONAL_FRED_SERIES.get(symbol, FRED_PURPOSES.get(symbol, symbol)),
            "source_tier": "official_or_primary_mirror",
            "freshness": "release_frequency; not an intraday quote",
        }
        for symbol in (*FRED_SERIES, *OPTIONAL_FRED_SERIES)
    }
    market = {
        ticker: {
            "symbol": spec[0],
            "description": spec[3],
            "instrument_type": spec[1],
            "unit": spec[2],
            "source_tier": "secondary_market_data",
            "freshness": "15-minute completed-bar windows are the normal research view; 1-minute is only for a specific event-window question; 60-minute is a broader context view",
        }
        for ticker, spec in ALL_INSTRUMENTS.items()
    }
    return {
        "collection_policy": {
            "mandatory_baseline": "deterministic and outside model control",
            "supplemental_collection": "selected by the research Agent for a stated hypothesis",
            "selection_rule": "request only evidence that can distinguish competing explanations, change a state/scenario conclusion, or materially reduce uncertainty",
        },
        "providers": {
            "web_search": {
                "request_key": "English question with dates and preferred official/publisher sources",
                "capabilities": "Existing configured Responses web_search collector, falling back to public news RSS across allowed official/publisher/syndication hosts. Hosted path requires actual web_search_call source URLs; no invented URL accepted. Find alternative sources when direct access fails. At most one hosted attempt (30s) plus one RSS query.",
                "limitations": "Tool-grounded model summary is secondary evidence, not a publisher quotation or an official probability distribution. Retain publication time and independently assess attribution. Prefer direct body when available; do not keep retrying denied URLs.",
            },
            "public_document": {
                "request_key": "bookmark or HTTPS URL",
                "capabilities": {k: v for k, v in BOOKMARKS.items()},
                "allowed_hosts": sorted(ALLOWED_HOSTS),
                "limitations": "Publisher article/table evidence, no access bypass. WGC is monthly context; IAU levels are not flows. FEDWATCH requires entitled CME_FEDWATCH_ACCESS_TOKEN; unavailable is explicit.",
            },
            "evidence_detail": {"request_key": "document_id:part_index", "capabilities": "Read another complete part of a document already collected in this investigation; no new network read."},
            "snapshot_detail": {"request_key": "cme:<selected option expiry> or cme:gamma_grid", "capabilities": "Expand an existing CME expiry calculation or model grid from this snapshot; dates and proxy semantics remain unchanged. No new collection."},
            "news_search": {"request_key": "English query", "capabilities": "AP/Reuters discovery with direct publisher links; request public_document for body verification", "limitations": "search metadata is not body evidence; no assumed two-day lookback"},
            "fred": {"request_key": "series_id", "capabilities": fred},
            "tradingview": {
                "request_key": "ticker",
                "optional_request_fields": {
                    "resolution": "1, 15, or 60; defaults to 15. Choose explicitly from the research horizon, never infer it from freshness_need."
                },
                "capabilities": market,
                "limitations": (
                    "scanner observation plus bounded common completed-bar windows anchored to XAUUSD; "
                    "600-second delayed series can support an explicitly timestamped common historical window, "
                    "but are not real-time and price co-movement is not causal attribution. "
                    "Use 1-minute only for event follow-up; no 5-minute strategy signal is produced. "
                    "Futures are not spot or official settlement."
                ),
            },
            "reuters_metadata": {
                "request_key": "English search query",
                "capabilities": "public Reuters headline/snippet discovery",
                "limitations": "no guaranteed full text; headline/snippet cannot alone confirm the event",
            },
        },
    }


def allowed_fred_series() -> frozenset[str]:
    return frozenset(FRED_SERIES) | frozenset(OPTIONAL_FRED_SERIES)


def allowed_market_symbols() -> frozenset[str]:
    return frozenset(ALL_INSTRUMENTS)
