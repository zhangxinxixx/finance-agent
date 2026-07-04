import { fetchJson, ApiError } from "@/adapters/apiClient";
import type {
  MarketEnvironmentFilter,
  MarketEnvironmentFilterKey,
  MarketMonitorMetric,
  MarketMonitorMockFile,
  MarketMonitorResponse,
  MarketMonitorSourceTraceItem,
  MarketAgentRegimeSummary,
  MarketRegime,
  MarketRegimeKey,
} from "@/types/market-monitor";

const MARKET_MONITOR_MOCK_URL = new URL("../mocks/market-monitor.json", import.meta.url);
const MARKET_MONITOR_OVERVIEW_PATH = "/api/market/monitor";
const MARKET_MONITOR_HISTORY_PATH = "/api/market/monitor/history";
const MARKET_TICKERS_PATH = "/api/market/tickers";
const MACRO_LATEST_PATH = "/api/macro/latest";

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
  regime?: unknown;
  regime_label?: unknown;
  confidence?: unknown;
  summary?: unknown;
  key_drivers?: unknown;
  llm_model?: unknown;
  llm_elapsed_seconds?: unknown;
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
    latest_date: "unavailable",
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
      label: "Rate Pressure",
      status: "unavailable",
      confidence: 0,
      description: "",
      interpretation: "",
      drivers: [],
    },
    transition_release: {
      label: "Transition Release",
      status: "unavailable",
      confidence: 0,
      description: "",
      interpretation: "",
      drivers: [],
    },
    trend_tailwind: {
      label: "Trend Tailwind",
      status: "unavailable",
      confidence: 0,
      description: "",
      interpretation: "",
      drivers: [],
    },
    liquidity_crunch: {
      label: "Liquidity Crunch",
      status: "unavailable",
      confidence: 0,
      description: "",
      interpretation: "",
      drivers: [],
    },
    monetary_credit_repricing: {
      label: "Monetary Credit Repricing",
      status: "unavailable",
      confidence: 0,
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

function createUnavailableSourceTrace(): MarketMonitorSourceTraceItem[] {
  return [];
}

function createUnavailableResponse(reason: string): MarketMonitorResponse {
  return {
    generated_at: "unavailable",
    latest_date: "unavailable",
    has_data: false,
    source: "unavailable",
    metrics: [],
    market_regimes: createUnavailableRegimes(),
    environment_filters: createUnavailableEnvironmentFilters(),
    source_trace: createUnavailableSourceTrace(),
    error_reason: reason,
    realtime_regime: null,
    primary_driver: null,
    agent_market_regime: null,
  };
}

async function loadMockMarketMonitor(): Promise<MarketMonitorResponse> {
  const response = await fetch(MARKET_MONITOR_MOCK_URL);

  if (!response.ok) {
    throw new Error(`加载 Market Monitor mock 失败：${response.status}`);
  }

  const payload = (await response.json()) as MarketMonitorMockFile;

  return {
    ...payload,
    generated_at: payload.generated_at,
    latest_date: payload.latest_date,
    has_data: payload.has_data ?? payload.metrics.length > 0,
    source: "mock",
  };
}

function buildXAUUSDMetric(
  tickers: Record<string, RawTickerEntry>,
  latestDate: string,
): MarketMonitorMetric {
  const xauusd = tickers.xauusd ?? {};
  const price = asNumberOrNull(xauusd.price);
  const changePct = asNumberOrNull(xauusd.change_pct);
  const quoteTime = asString(xauusd.time);
  const source = asString(xauusd.source);
  const name = asString(xauusd.name, "现货黄金");

  return {
    key: "XAUUSD",
    label: "XAUUSD",
    group: "metals",
    latest_date: quoteTime ? dateFromTimestamp(quoteTime) : latestDate,
    latest_value: price,
    unit: "USD/oz",
    one_week_change: changePct !== null ? `${changePct}%` : null,
    one_month_change: null,
    status: price !== null ? "ok" : "unavailable",
    interpretation: source === "jin10_mcp_realtime" ? `Jin10 ${name}实时报价` : "",
    source_refs: ["GET /api/market/tickers#xauusd"],
    snapshot_id: null,
  };
}

function buildDXYMetric(
  tickers: Record<string, RawTickerEntry>,
  indicators: Record<string, RawMacroIndicator>,
  fallbackDate: string,
): MarketMonitorMetric {
  const macro = indicators.DXY ?? {};
  const ticker = tickers.dxy ?? {};
  const value = asNumberOrNull(macro.value) ?? asNumberOrNull(ticker.value);

  return {
    key: "DXY",
    label: asString(macro.label, "DXY"),
    group: "dollar",
    latest_date: asString(macro.date, fallbackDate),
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
  fallbackDate: string,
): MarketMonitorMetric {
  const macro = indicators.TGA ?? {};
  const ticker = tickers.tga ?? {};
  const value = asNumberOrNull(macro.value) ?? asNumberOrNull(ticker.value);

  return {
    key: "TGA",
    label: asString(macro.label, "TGA"),
    group: "liquidity",
    latest_date: asString(macro.date, fallbackDate),
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
  fallbackDate: string,
  aliases: string[] = [],
): MarketMonitorMetric {
  const resolvedKey = [key, ...aliases].find((candidate) => indicators[candidate]);
  const macro = resolvedKey ? indicators[resolvedKey] ?? {} : {};
  const value = asNumberOrNull(macro.value);

  return {
    key,
    label: asString(macro.label, label),
    group,
    latest_date: asString(macro.date, fallbackDate),
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
    throw new ApiError("Market Tickers API 响应缺少 tickers", { url: MARKET_TICKERS_PATH });
  }

  if (!macroPayload.indicators || typeof macroPayload.indicators !== "object") {
    throw new ApiError("Macro Latest API 响应缺少 indicators", { url: MACRO_LATEST_PATH });
  }

  const tickers = tickersPayload.tickers as Record<string, RawTickerEntry>;
  const indicators = macroPayload.indicators as Record<string, RawMacroIndicator>;
  const generatedAt = asString(tickersPayload.generated_at, "unavailable");
  const latestDate = asString(macroPayload.as_of, generatedAt !== "unavailable" ? dateFromTimestamp(generatedAt) : "unavailable");

  const metrics = [
    buildXAUUSDMetric(tickers, latestDate),
    buildDXYMetric(tickers, indicators, latestDate),
    buildTGAMetric(tickers, indicators, latestDate),
    buildMacroMetric("US10Y", "US10Y", "rates", "%", indicators, latestDate),
    buildMacroMetric("US02Y", "US02Y", "rates", "%", indicators, latestDate),
    buildMacroMetric("T10YIE", "T10YIE", "rates", "%", indicators, latestDate, ["BREAKEVEN_10Y"]),
    buildMacroMetric("REAL_10Y", "10Y Real Rate", "rates", "%", indicators, latestDate),
    buildMacroMetric("RRP", "RRP", "liquidity", "B", indicators, latestDate, ["ON_RRP_USAGE"]),
    buildMacroMetric("SOFR", "SOFR", "funding", "%", indicators, latestDate),
    buildMacroMetric("EFFR", "EFFR", "funding", "%", indicators, latestDate),
    buildMacroMetric("IORB", "IORB", "funding", "%", indicators, latestDate),
  ];

  const hasAnyValidMetric = metrics.some((metric) => metric.latest_value !== null);
  if (!hasAnyValidMetric) {
    throw new ApiError("Market Monitor API 归一化后没有有效 metrics", {
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
  const latestDate = asString(macroPayload.as_of, generatedAt ? dateFromTimestamp(generatedAt) : "unavailable");
  const tickers = tickersPayload.tickers && typeof tickersPayload.tickers === "object" ? tickersPayload.tickers as Record<string, RawTickerEntry> : {};
  const xauusd = tickers.xauusd ?? {};
  const xauusdSource = asString(xauusd.source);

  return [
    {
      name: xauusdSource === "jin10_mcp_realtime" ? "Jin10 XAUUSD 实时报价" : "Market Tickers API",
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
      name: "Macro Latest API",
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
  const generatedAt = asString(tickersPayload.generated_at, "unavailable");
  const latestDate = asString(macroPayload.as_of, generatedAt !== "unavailable" ? dateFromTimestamp(generatedAt) : "unavailable");
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
    const mappedKey =
      regimeKey === "hawkish_gold_pressure"
        ? "rate_pressure"
        : regimeKey === "dovish_gold_friendly"
          ? "trend_tailwind"
          : "transition_release";
    marketRegimes[mappedKey] = {
      label:
        mappedKey === "rate_pressure"
          ? "Rate Pressure"
          : mappedKey === "trend_tailwind"
            ? "Trend Tailwind"
            : "Transition Release",
      status: asNumberOrNull(realtimeRegime.confidence) && asNumberOrNull(realtimeRegime.confidence)! > 0 ? "ok" : "info",
      confidence: asNumberOrNull(realtimeRegime.confidence) ?? 0,
      description: regimeKey || "neutral",
      interpretation: `实时 regime: ${regimeKey || "neutral"}`,
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
        ? `主驱动 ${asString(primaryDriver.driver, "data_insufficient")} / 置信度 ${(asNumberOrNull(primaryDriver.confidence) ?? 0).toFixed(2)}`
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
          confidence: asNumberOrNull(realtimeRegime.confidence) ?? 0,
          available: Boolean(realtimeRegime.available),
        }
      : null,
    primary_driver: primaryDriver
      ? {
          driver: asString(primaryDriver.driver),
          secondary: asOptionalString(primaryDriver.secondary),
          confidence: asNumberOrNull(primaryDriver.confidence) ?? 0,
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
    confidence: asNumberOrNull(raw.confidence) ?? 0,
    summary: asString(raw.summary),
    keyDrivers: asStringList(raw.key_drivers),
    llmModel: asOptionalString(raw.llm_model),
    llmElapsedSeconds: asNumberOrNull(raw.llm_elapsed_seconds),
  };
}

function normalizeOverviewResponse(raw: MarketMonitorResponse & { agent_market_regime?: RawMarketAgentRegimeSummary | null }): MarketMonitorResponse {
  return {
    ...raw,
    agent_market_regime: normalizeAgentMarketRegime(raw.agent_market_regime),
  };
}

export async function fetchMarketMonitorData(): Promise<MarketMonitorResponse> {
  try {
    try {
      return normalizeOverviewResponse(await fetchJson<MarketMonitorResponse & { agent_market_regime?: RawMarketAgentRegimeSummary | null }>(MARKET_MONITOR_OVERVIEW_PATH));
    } catch {
      // fall back to older dual-endpoint aggregation path
    }

    const [tickersPayload, macroPayload] = await Promise.all([
      fetchJson<RawMarketTickersResponse>(MARKET_TICKERS_PATH),
      fetchJson<RawMacroLatestResponse>(MACRO_LATEST_PATH),
    ]);

    return normalizeApiResponse(tickersPayload, macroPayload);
  } catch (apiCause) {
    const apiError = apiCause instanceof Error ? apiCause.message : "Market Monitor API 请求失败";

    try {
      const mockData = await loadMockMarketMonitor();
      return {
        ...mockData,
        source: "mock",
        error_reason: apiError,
      };
    } catch (mockCause) {
      const mockError = mockCause instanceof Error ? mockCause.message : "Market Monitor mock 请求失败";
      return createUnavailableResponse(`${apiError}; ${mockError}`);
    }
  }
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
