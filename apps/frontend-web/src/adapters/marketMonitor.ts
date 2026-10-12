import { fetchJson, ApiError } from "@/adapters/apiClient";
import type {
  MarketEnvironmentFilter,
  MarketEnvironmentFilterKey,
  MarketMonitorMetric,
  MarketMonitorResponse,
  MarketMonitorSourceTraceItem,
  MarketAgentRegimeSummary,
  MarketRegime,
  MarketRegimeKey,
} from "@/types/market-monitor";
import type { MarketOddsEvidenceViewModel } from "@/types/reports";

const MARKET_MONITOR_OVERVIEW_PATH = "/api/market/monitor";
const MARKET_MONITOR_HISTORY_PATH = "/api/market/monitor/history";
const MARKET_TICKERS_PATH = "/api/market/tickers";
const MACRO_LATEST_PATH = "/api/macro/latest";
export const EXTERNAL_MARKET_ODDS_LATEST_PATH = "/api/market-odds/external/latest";

type RawTickerEntry = {
  price?: unknown;
  value?: unknown;
  unit?: unknown;
  change_pct?: unknown;
  source?: unknown;
  time?: unknown;
  name?: unknown;
};

type RawMarketTickersResponse = {
  generated_at?: unknown;
  sources?: unknown;
  tickers?: Record<string, RawTickerEntry> | unknown;
  market_regime?: {
    regime?: unknown;
    confidence?: unknown;
    available?: unknown;
  } | null;
  primary_driver?: {
    driver?: unknown;
    secondary?: unknown;
    confidence?: unknown;
  } | null;
};

type RawMacroIndicator = {
  daily_change?: unknown;
  date?: unknown;
  direction_note?: unknown;
  label?: unknown;
  monthly_change?: unknown;
  symbol?: unknown;
  unit?: unknown;
  value?: unknown;
  weekly_change?: unknown;
};

type RawMacroLatestResponse = {
  as_of?: unknown;
  indicators?: Record<string, RawMacroIndicator> | unknown;
  source_refs?: Record<string, unknown> | unknown;
  unavailable_symbols?: unknown;
};

type RawMarketAgentRegimeSummary = {
  agent_name?: unknown;
  created_at?: unknown;
  regime?: unknown;
  regime_label?: unknown;
  confidence?: unknown;
  summary?: unknown;
  key_drivers?: unknown;
  llm_model?: unknown;
  llm_elapsed_seconds?: unknown;
  run_id?: unknown;
  snapshot_id?: unknown;
};

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function localizedMetricLabel(value: unknown, fallback: string): string {
  const text = asOptionalString(value);
  return text && /[\u3400-\u9fff]/.test(text) ? text : fallback;
}

function primaryDriverLabel(value: string): string {
  const labels: Record<string, string> = {
    data_insufficient: "数据不足，主因待确认",
    rates: "利率驱动",
    dollar: "美元驱动",
    liquidity: "流动性驱动",
    risk: "风险偏好驱动",
    geopolitics: "地缘驱动",
  };
  return labels[value] ?? (/[\u3400-\u9fff]/.test(value) ? value : "主因待确认");
}

function realtimeRegimeLabel(value: string): string {
  const labels: Record<string, string> = {
    dovish_gold_friendly: "宽松、黄金偏友好",
    hawkish_gold_pressure: "鹰派、黄金承压",
    neutral_soft: "中性偏宽松",
    neutral_firm: "中性偏紧",
    neutral: "中性阶段",
  };
  return labels[value] ?? "阶段待确认";
}

function dateFromTimestamp(value: string): string {
  return value.includes("T") ? value.split("T")[0] : value;
}

function emptyMetric(
  key: string,
  label: string,
  group: MarketMonitorMetric["group"],
  unit: string,
  sourceRefs: string[],
): MarketMonitorMetric {
  return {
    key,
    label,
    group,
    latest_date: null,
    latest_value: null,
    unit,
    one_week_change: null,
    one_month_change: null,
    status: "unavailable",
    interpretation: "",
    source_refs: sourceRefs,
    snapshot_id: null,
  };
}

function createUnavailableRegimes(): Record<MarketRegimeKey, MarketRegime> {
  return {
    rate_pressure: {
      label: "利率压力",
      status: "unavailable",
      confidence: null,
      description: "",
      interpretation: "",
      drivers: [],
    },
    transition_release: {
      label: "过渡释放",
      status: "unavailable",
      confidence: null,
      description: "",
      interpretation: "",
      drivers: [],
    },
    trend_tailwind: {
      label: "趋势顺风",
      status: "unavailable",
      confidence: null,
      description: "",
      interpretation: "",
      drivers: [],
    },
    liquidity_crunch: {
      label: "流动性收缩",
      status: "unavailable",
      confidence: null,
      description: "",
      interpretation: "",
      drivers: [],
    },
    monetary_credit_repricing: {
      label: "货币信用重估",
      status: "unavailable",
      confidence: null,
      description: "",
      interpretation: "",
      drivers: [],
    },
  };
}

function createUnavailableEnvironmentFilters(): Record<MarketEnvironmentFilterKey, MarketEnvironmentFilter> {
  return {
    us10y: {
      label: "US10Y",
      status: "unavailable",
      latest_value: null,
      one_week_change: null,
      one_month_change: null,
      interpretation: "",
      unit: "%",
    },
    dxy: {
      label: "DXY",
      status: "unavailable",
      latest_value: null,
      one_week_change: null,
      one_month_change: null,
      interpretation: "",
      unit: "index",
    },
    us02y: {
      label: "US02Y",
      status: "unavailable",
      latest_value: null,
      one_week_change: null,
      one_month_change: null,
      interpretation: "",
      unit: "%",
    },
    xauusd_price_reaction: {
      label: "XAUUSD Price Reaction",
      status: "unavailable",
      latest_value: null,
      one_week_change: null,
      one_month_change: null,
      interpretation: "",
      unit: "",
    },
  };
}

function buildXAUUSDMetric(
  tickers: Record<string, RawTickerEntry>,
  latestDate: string | null,
): MarketMonitorMetric {
  const xauusd = tickers.xauusd ?? {};
  const price = asNumberOrNull(xauusd.price);
  const changePct = asNumberOrNull(xauusd.change_pct);
  const quoteTime = asString(xauusd.time);
  const source = asString(xauusd.source);
  const name = localizedMetricLabel(xauusd.name, "现货黄金");

  return {
    key: "XAUUSD",
    label: "现货黄金 XAUUSD",
    group: "metals",
    latest_date: quoteTime ? dateFromTimestamp(quoteTime) : latestDate,
    latest_value: price,
    unit: "USD/oz",
    one_week_change: changePct !== null ? `${changePct}%` : null,
    one_month_change: null,
    status: price !== null ? "ok" : "unavailable",
    interpretation: source === "jin10_mcp_realtime" ? `金十 ${name}实时报价` : "",
    source_refs: ["GET /api/market/tickers#xauusd"],
    snapshot_id: null,
  };
}

function buildDXYMetric(
  tickers: Record<string, RawTickerEntry>,
  indicators: Record<string, RawMacroIndicator>,
  fallbackDate: string | null,
): MarketMonitorMetric {
  const macro = indicators.DXY ?? {};
  const ticker = tickers.dxy ?? {};
  const value = asNumberOrNull(macro.value) ?? asNumberOrNull(ticker.value);

  return {
    key: "DXY",
    label: localizedMetricLabel(macro.label, "美元指数 DXY"),
    group: "dollar",
    latest_date: asOptionalString(macro.date) ?? fallbackDate,
    latest_value: value,
    unit: asString(macro.unit, asString(ticker.unit, "index")),
    one_week_change: asNumberOrNull(macro.weekly_change),
    one_month_change: asNumberOrNull(macro.monthly_change),
    status: value !== null ? "ok" : "unavailable",
    interpretation: asString(macro.direction_note),
    source_refs: ["GET /api/macro/latest#DXY", "GET /api/market/tickers#dxy"],
    snapshot_id: null,
  };
}

function buildTGAMetric(
  tickers: Record<string, RawTickerEntry>,
  indicators: Record<string, RawMacroIndicator>,
  fallbackDate: string | null,
): MarketMonitorMetric {
  const macro = indicators.TGA ?? {};
  const ticker = tickers.tga ?? {};
  const value = asNumberOrNull(macro.value) ?? asNumberOrNull(ticker.value);

  return {
    key: "TGA",
    label: localizedMetricLabel(macro.label, "财政账户 TGA"),
    group: "liquidity",
    latest_date: asOptionalString(macro.date) ?? fallbackDate,
    latest_value: value,
    unit: asString(macro.unit, asString(ticker.unit, "B")),
    one_week_change: asNumberOrNull(macro.weekly_change),
    one_month_change: asNumberOrNull(macro.monthly_change),
    status: value !== null ? "ok" : "unavailable",
    interpretation: asString(macro.direction_note),
    source_refs: ["GET /api/macro/latest#TGA", "GET /api/market/tickers#tga"],
    snapshot_id: null,
  };
}

function buildMacroMetric(
  key: string,
  label: string,
  group: MarketMonitorMetric["group"],
  unit: string,
  indicators: Record<string, RawMacroIndicator>,
  fallbackDate: string | null,
  aliases: string[] = [],
): MarketMonitorMetric {
  const resolvedKey = [key, ...aliases].find((candidate) => indicators[candidate]);
  const macro = resolvedKey ? indicators[resolvedKey] ?? {} : {};
  const value = asNumberOrNull(macro.value);

  return {
    key,
    label: localizedMetricLabel(macro.label, label),
    group,
    latest_date: asOptionalString(macro.date) ?? fallbackDate,
    latest_value: value,
    unit: asString(macro.unit, unit),
    one_week_change: asNumberOrNull(macro.weekly_change),
    one_month_change: asNumberOrNull(macro.monthly_change),
    status: value !== null ? "ok" : "unavailable",
    interpretation: asString(macro.direction_note),
    source_refs: [`GET /api/macro/latest#${resolvedKey ?? key}`],
    snapshot_id: null,
  };
}

function buildMetrics(
  tickersPayload: RawMarketTickersResponse,
  macroPayload: RawMacroLatestResponse,
): MarketMonitorMetric[] {
  if (!tickersPayload.tickers || typeof tickersPayload.tickers !== "object") {
    throw new ApiError("行情接口未返回可用价格数据", { url: MARKET_TICKERS_PATH });
  }

  if (!macroPayload.indicators || typeof macroPayload.indicators !== "object") {
    throw new ApiError("宏观接口未返回可用指标数据", { url: MACRO_LATEST_PATH });
  }

  const tickers = tickersPayload.tickers as Record<string, RawTickerEntry>;
  const indicators = macroPayload.indicators as Record<string, RawMacroIndicator>;
  const generatedAt = asString(tickersPayload.generated_at);
  const latestDate = asOptionalString(macroPayload.as_of);

  const metrics = [
    buildXAUUSDMetric(tickers, latestDate),
    buildDXYMetric(tickers, indicators, latestDate),
    buildTGAMetric(tickers, indicators, latestDate),
    buildMacroMetric("US10Y", "10年名义利率 US10Y", "rates", "%", indicators, latestDate),
    buildMacroMetric("US02Y", "2年名义利率 US02Y", "rates", "%", indicators, latestDate),
    buildMacroMetric("T10YIE", "10年通胀预期", "rates", "%", indicators, latestDate, ["BREAKEVEN_10Y"]),
    buildMacroMetric("YIELD_SPREAD_2Y_3M", "2年-3个月利差", "rates", "%", indicators, latestDate),
    buildMacroMetric("REAL_10Y", "10年实际利率", "rates", "%", indicators, latestDate),
    buildMacroMetric("RRP", "隔夜逆回购 RRP", "liquidity", "B", indicators, latestDate, ["ON_RRP_USAGE"]),
    buildMacroMetric("SOFR", "担保隔夜融资利率 SOFR", "funding", "%", indicators, latestDate),
    buildMacroMetric("EFFR", "有效联邦基金利率 EFFR", "funding", "%", indicators, latestDate),
    buildMacroMetric("IORB", "准备金利率 IORB", "funding", "%", indicators, latestDate),
  ];

  const hasAnyValidMetric = metrics.some((metric) => metric.latest_value !== null);
  if (!hasAnyValidMetric) {
    throw new ApiError("市场监控接口未返回有效指标", {
      url: `${MARKET_TICKERS_PATH}, ${MACRO_LATEST_PATH}`,
    });
  }

  return metrics;
}

function buildSourceTrace(
  tickersPayload: RawMarketTickersResponse,
  macroPayload: RawMacroLatestResponse,
): MarketMonitorSourceTraceItem[] {
  const generatedAt = asString(tickersPayload.generated_at);
  const latestDate = asOptionalString(macroPayload.as_of) ?? "—";
  const tickers = tickersPayload.tickers && typeof tickersPayload.tickers === "object" ? tickersPayload.tickers as Record<string, RawTickerEntry> : {};
  const xauusd = tickers.xauusd ?? {};
  const xauusdSource = asString(xauusd.source);

  return [
    {
      name: xauusdSource === "jin10_mcp_realtime" ? "金十 XAUUSD 实时报价" : "市场行情接口",
      trade_date: latestDate,
      file: "api://market/tickers",
      snapshot_id: null,
      source_ref: "GET /api/market/tickers",
      endpoint: "GET /api/market/tickers",
      latest_raw_time: generatedAt || null,
      latest_parsed_time: generatedAt || null,
      model_version: null,
      status: "ok",
    },
    {
      name: "宏观最新数据接口",
      trade_date: latestDate,
      file: "api://macro/latest",
      snapshot_id: null,
      source_ref: "GET /api/macro/latest",
      endpoint: "GET /api/macro/latest",
      latest_raw_time: null,
      latest_parsed_time: null,
      model_version: null,
      status: "ok",
    },
  ];
}

function normalizeApiResponse(
  tickersPayload: RawMarketTickersResponse,
  macroPayload: RawMacroLatestResponse,
): MarketMonitorResponse {
  const generatedAt = asString(tickersPayload.generated_at) || "未提供";
  const latestDate = asOptionalString(macroPayload.as_of);
  const metrics = buildMetrics(tickersPayload, macroPayload);
  const realtimeRegime = tickersPayload.market_regime ?? null;
  const primaryDriver = tickersPayload.primary_driver ?? null;
  const dxyMetric = metrics.find((metric) => metric.key === "DXY");
  const us10yMetric = metrics.find((metric) => metric.key === "US10Y");
  const us02yMetric = metrics.find((metric) => metric.key === "US02Y");
  const xauMetric = metrics.find((metric) => metric.key === "XAUUSD");

  const marketRegimes = createUnavailableRegimes();
  if (realtimeRegime && typeof realtimeRegime === "object") {
    const regimeKey = asString(realtimeRegime.regime);
    const confidence = asNumberOrNull(realtimeRegime.confidence);
    const mappedKey =
      regimeKey === "hawkish_gold_pressure"
        ? "rate_pressure"
        : regimeKey === "dovish_gold_friendly"
          ? "trend_tailwind"
          : "transition_release";
    marketRegimes[mappedKey] = {
      label: mappedKey === "rate_pressure"
        ? "利率压力"
        : mappedKey === "trend_tailwind"
          ? "趋势顺风"
          : "过渡释放",
      status: confidence !== null && confidence > 0 ? "ok" : "info",
      confidence,
      description: realtimeRegimeLabel(regimeKey),
      interpretation: `实时阶段：${realtimeRegimeLabel(regimeKey)}`,
      drivers: primaryDriver && typeof primaryDriver === "object" ? [asString(primaryDriver.driver), asString(primaryDriver.secondary)].filter(Boolean) : [],
    };
  }

  const environmentFilters = createUnavailableEnvironmentFilters();
  environmentFilters.us10y = {
    label: "US10Y",
    status: us10yMetric?.status ?? "unavailable",
    latest_value: us10yMetric?.latest_value ?? null,
    one_week_change: us10yMetric?.one_week_change ?? null,
    one_month_change: us10yMetric?.one_month_change ?? null,
    interpretation: us10yMetric?.interpretation ?? "",
    unit: us10yMetric?.unit ?? "%",
  };
  environmentFilters.dxy = {
    label: "DXY",
    status: dxyMetric?.status ?? "unavailable",
    latest_value: dxyMetric?.latest_value ?? null,
    one_week_change: dxyMetric?.one_week_change ?? null,
    one_month_change: dxyMetric?.one_month_change ?? null,
    interpretation: dxyMetric?.interpretation ?? "",
    unit: dxyMetric?.unit ?? "index",
  };
  environmentFilters.us02y = {
    label: "US02Y",
    status: us02yMetric?.status ?? "unavailable",
    latest_value: us02yMetric?.latest_value ?? null,
    one_week_change: us02yMetric?.one_week_change ?? null,
    one_month_change: us02yMetric?.one_month_change ?? null,
    interpretation: us02yMetric?.interpretation ?? "",
    unit: us02yMetric?.unit ?? "%",
  };
  environmentFilters.xauusd_price_reaction = {
    label: "XAUUSD Price Reaction",
    status: xauMetric?.status ?? "unavailable",
    latest_value: xauMetric?.latest_value ?? null,
    one_week_change: xauMetric?.one_week_change ?? null,
    one_month_change: xauMetric?.one_month_change ?? null,
    interpretation:
      primaryDriver && typeof primaryDriver === "object"
        ? `${primaryDriverLabel(asString(primaryDriver.driver, "data_insufficient"))}${asNumberOrNull(primaryDriver.confidence) === null ? "；把握程度未量化" : `；把握程度 ${asNumberOrNull(primaryDriver.confidence)!.toFixed(2)}`}`
        : xauMetric?.interpretation ?? "",
    unit: xauMetric?.unit ?? "",
  };

  return {
    generated_at: generatedAt,
    latest_date: latestDate,
    has_data: metrics.length > 0,
    source: "api",
    metrics,
    market_regimes: marketRegimes,
    environment_filters: environmentFilters,
    source_trace: buildSourceTrace(tickersPayload, macroPayload),
    realtime_regime: realtimeRegime
      ? {
          regime: asString(realtimeRegime.regime),
          confidence: asNumberOrNull(realtimeRegime.confidence),
          available: Boolean(realtimeRegime.available),
        }
      : null,
    primary_driver: primaryDriver
      ? {
          driver: asString(primaryDriver.driver),
          secondary: asOptionalString(primaryDriver.secondary),
          confidence: asNumberOrNull(primaryDriver.confidence),
        }
      : null,
    agent_market_regime: null,
  };
}

function normalizeAgentMarketRegime(raw: RawMarketAgentRegimeSummary | null | undefined): MarketAgentRegimeSummary | null {
  if (!raw) return null;
  return {
    agentName: asOptionalString(raw.agent_name),
    regime: asString(raw.regime, "unknown"),
    regimeLabel: asString(raw.regime_label, "市场阶段待生成"),
    confidence: asNumberOrNull(raw.confidence),
    summary: asString(raw.summary),
    keyDrivers: asStringList(raw.key_drivers),
    llmModel: asOptionalString(raw.llm_model),
    llmElapsedSeconds: asNumberOrNull(raw.llm_elapsed_seconds),
    createdAt: asOptionalString(raw.created_at),
    runId: asOptionalString(raw.run_id),
    snapshotId: asOptionalString(raw.snapshot_id),
  };
}

function normalizeOverviewResponse(raw: unknown): MarketMonitorResponse {
  if (
    !raw
    || typeof raw !== "object"
    || !Array.isArray((raw as { metrics?: unknown }).metrics)
    || !Array.isArray((raw as { source_trace?: unknown }).source_trace)
    || (raw as { metrics: unknown[] }).metrics.some((metric) => !metric || typeof metric !== "object")
  ) {
    throw new ApiError("市场监控总览数据结构无效", { url: MARKET_MONITOR_OVERVIEW_PATH });
  }

  const payload = raw as MarketMonitorResponse & { agent_market_regime?: RawMarketAgentRegimeSummary | null };
  const realtimeRegime = payload.realtime_regime;
  const primaryDriver = payload.primary_driver;
  return {
    ...payload,
    metrics: payload.metrics.map((metric) => ({
      ...metric,
      // A missing observation date is a real gap. Keep it null so the UI
      // renders an unavailable date instead of inferring it from generated_at.
      latest_date: asOptionalString(metric.latest_date),
    })),
    agent_market_regime: normalizeAgentMarketRegime(payload.agent_market_regime),
    realtime_regime: realtimeRegime
      ? {
          regime: asString(realtimeRegime.regime),
          confidence: asNumberOrNull(realtimeRegime.confidence),
          available: Boolean(realtimeRegime.available),
        }
      : null,
    primary_driver: primaryDriver
      ? {
          driver: asString(primaryDriver.driver),
          secondary: asOptionalString(primaryDriver.secondary),
          confidence: asNumberOrNull(primaryDriver.confidence),
        }
      : null,
  };
}

function isOverviewCompatibilityError(cause: unknown): boolean {
  return cause instanceof ApiError && (cause.status === 404 || cause.status === 501);
}

export async function fetchMarketMonitorData(): Promise<MarketMonitorResponse> {
  try {
    try {
      return normalizeOverviewResponse(await fetchJson<MarketMonitorResponse & { agent_market_regime?: RawMarketAgentRegimeSummary | null }>(MARKET_MONITOR_OVERVIEW_PATH));
    } catch (overviewCause) {
      if (!isOverviewCompatibilityError(overviewCause)) {
        throw overviewCause;
      }
      // Only a missing/unimplemented overview endpoint may use the legacy
      // aggregation path.  5xx, malformed JSON, and network errors must be
      // visible to the hook instead of being silently replaced by partial data.
    }

    const [tickersPayload, macroPayload] = await Promise.all([
      fetchJson<RawMarketTickersResponse>(MARKET_TICKERS_PATH),
      fetchJson<RawMacroLatestResponse>(MACRO_LATEST_PATH),
    ]);

    return normalizeApiResponse(tickersPayload, macroPayload);
  } catch (apiCause) {
    // A failed live read must remain an error. Rendering a bundled snapshot here
    // would make an old market state look current and hide the failed refresh.
    throw apiCause instanceof Error ? apiCause : new Error("Market Monitor API 请求失败");
  }
}

export async function fetchLatestExternalMarketOdds(): Promise<MarketOddsEvidenceViewModel> {
  return await fetchJson<MarketOddsEvidenceViewModel>(EXTERNAL_MARKET_ODDS_LATEST_PATH);
}

export interface MarketMonitorHistoryPoint {
  date: string;
  XAUUSD?: number | null;
  xauusd_ohlc?: {
    open: number;
    high: number;
    low: number;
    close: number;
  } | null;
  DXY?: number | null;
  US10Y?: number | null;
  REAL_10Y?: number | null;
  T10YIE?: number | null;
}

export interface MarketMonitorHistoryResponse {
  generated_at: string;
  timeframe?: string;
  source_timeframe?: string;
  series: MarketMonitorHistoryPoint[];
  available_points: number;
  available_fields: string[];
  degraded: boolean;
  message: string;
  data_gaps?: string[];
  coverage_note?: string | null;
}

export async function fetchMarketMonitorHistory(timeframe = "1M", limit = 30): Promise<MarketMonitorHistoryResponse> {
  return await fetchJson<MarketMonitorHistoryResponse>(
    `${MARKET_MONITOR_HISTORY_PATH}?timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`,
  );
}
