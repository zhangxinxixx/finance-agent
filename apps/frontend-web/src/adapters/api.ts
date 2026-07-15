import type { DashboardAgentCompactSummary, DashboardDataResponse, DashboardMetric, DashboardSummary, DashboardStrategyCardViewModel, DashboardViewModel, SignalDirection, StrategyCardData, UnifiedDate } from "@/types/dashboard";
import type { DataStatus, ModuleStatus, ReportMeta, SourceRef } from "@/types/common";
import { fetchJson } from "@/adapters/apiClient";
import { mergeDataStatus, normalizeDataStatus } from "@/lib/status";
import { dedupeSourceRefs, normalizeSourceRefs, sourceRefFromEndpoint } from "@/lib/sourceRefs";

const DASHBOARD_SUMMARY_PATH = "/api/dashboard/summary";
const DASHBOARD_TIMEOUT_MS = 8000;
const ENABLE_DASHBOARD_MOCK_FALLBACK = import.meta.env.VITE_ENABLE_DASHBOARD_MOCK_FALLBACK === "true";

type RawDashboardSummaryResponse = {
  generated_at?: string;
  realtime_status?: {
    source?: string;
    generated_at?: string | null;
    available_symbols?: string[];
    message?: string;
  };
  realtime_quotes?: Record<string, {
    price?: number | null;
    value?: number | null;
    change?: number | null;
    change_pct?: number | null;
    unit?: string | null;
    time?: string | null;
    source?: string | null;
    name?: string | null;
  }>;
  options?: {
    trade_date?: string;
    product?: string;
    expiries?: string[];
    summary_text?: string;
    intent?: string;
    intent_score?: number;
    gamma_zero?: number | null;
    forward_price?: number | null;
    walls?: {
      resistance?: Array<{ strike?: number; score?: number; distance_pct?: number }>;
      support?: Array<{ strike?: number; score?: number; distance_pct?: number }>;
    };
    data_status?: string;
    confidence?: {
      score?: number;
      level?: string;
      trade_date?: string;
      age_days?: number | null;
      data_status?: string;
      reasons?: string[];
    };
  };
  macro?: {
    as_of?: string;
    available_count?: number;
    unavailable_count?: number;
    indicators?: Record<string, {
      daily_change?: number | null;
      date?: string;
      direction_note?: string;
      label?: string;
      monthly_change?: number | null;
      symbol?: string;
      unit?: string;
      value?: number | string | null;
      weekly_change?: number | null;
    }>;
  };
  pipeline?: DashboardSummary["pipeline"];
  warnings?: string[];
  risk_alerts?: string[];
  integrated_macro?: {
    report_type?: string;
    trade_date?: string;
    run_id?: string | null;
    source?: string;
    overall_bias?: string;
    direction?: unknown;
    macro_regime?: string;
    dominant_driver?: unknown;
    liquidity_state?: string;
    rates_state?: string;
    dollar_state?: string;
    options_alignment?: string;
    confidence?: number | null;
    reasoning?: string;
    trade_implication?: string;
    quick_supports?: Array<{
      level?: number;
      label?: string;
      source?: string;
      source_label?: string;
      trade_date?: string | null;
      timeframe?: string | null;
      basis?: string;
      status?: string;
      source_ref?: string;
    }>;
    trigger_upgrade?: unknown;
    trigger_downgrade?: unknown;
    invalidation?: unknown;
    risks?: unknown;
    missing_inputs?: unknown;
    composite_status?: string | null;
    composite_trade_date?: string | null;
    source_refs?: DashboardSummary["source_trace"];
  } | null;
  agent_summary?: {
    coordinator?: RawDashboardAgentCompactSummary | null;
    synthesis?: RawDashboardAgentCompactSummary | null;
  } | null;
  composite_analysis?: DashboardSummary["composite_analysis"];
  gold_macro_overview?: DashboardSummary["gold_macro_overview"];
  latest_supplemental_report?: DashboardSummary["latest_supplemental_report"];
  latest_reports?: DashboardSummary["latest_reports"];
  data_source_status?: Record<string, {
    name?: string;
    status?: string;
    configured?: boolean;
    analysis_ready?: boolean;
  }>;
  recent_tasks?: DashboardSummary["recent_tasks"];
  source_trace?: DashboardSummary["source_trace"];
  strategy?: {
    bias?: string;
    direction?: unknown;
    confidence?: number | null;
    macro_phase?: string;
    key_levels?: {
      resistance?: number[];
      support?: number[];
    };
    triggers?: unknown;
    invalid_conditions?: unknown;
    risk_points?: unknown;
    run_id?: string | null;
    snapshot_id?: string | null;
    evidence_refs?: StrategyCardData["evidence_refs"];
    data_quality?: unknown;
    data_category_summary?: StrategyCardData["data_category_summary"];
  };
};

type RawDashboardAgentCompactSummary = {
  agent_name?: string | null;
  status?: string | null;
  bias?: string | null;
  confidence?: number | null;
  summary?: string | null;
  summary_raw?: string | null;
  fact_review_status?: string | null;
  key_findings?: unknown;
  risk_points?: unknown;
  invalid_conditions?: unknown;
  watchlist?: unknown;
  claim_count?: number | null;
  created_at?: string | null;
};

type DashboardMockPayload = {
  default_date: string;
  dates: UnifiedDate[];
  summaries: Record<string, DashboardSummary>;
};


function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function normalizeSignalDirection(value: unknown, fallback: SignalDirection): SignalDirection {
  if (value === "bullish" || value === "bearish" || value === "neutral") {
    return value;
  }
  return fallback;
}

function trendFromChange(value: number | null | undefined): DashboardMetric["trend"] {
  if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

function metricFromIndicator(
  raw: RawDashboardSummaryResponse["macro"] extends infer M
    ? M extends { indicators?: Record<string, infer I> }
      ? I | undefined
      : never
    : never,
  fallbackLabel: string,
  fallbackUnit = "",
): DashboardMetric {
  const weekly = typeof raw?.weekly_change === "number" ? raw.weekly_change : null;
  const value = raw?.value ?? null;
  return {
    label: asString(raw?.label, fallbackLabel),
    value,
    unit: asString(raw?.unit, fallbackUnit),
    change: weekly === null ? null : `${weekly >= 0 ? "+" : ""}${weekly.toFixed(2)}`,
    trend: trendFromChange(weekly),
    status: value === null || value === undefined || value === "" ? "unavailable" : "ok",
    note: asString(raw?.direction_note),
  };
}

function xauusdMetric(options: RawDashboardSummaryResponse["options"]): DashboardMetric {
  return {
    label: "XAUUSD",
    value: options?.forward_price ?? null,
    unit: "USD/oz",
    change: null,
    trend: "flat",
    status: options?.forward_price ? "ok" : "unavailable",
    note: "CME GC forward / latest available",
  };
}

function overlayRealtimeMetric(
  metric: DashboardMetric,
  realtime: { price?: number | null; value?: number | null; change_pct?: number | null; source?: string | null; name?: string | null } | null | undefined,
  fallbackUnit = "",
): DashboardMetric {
  if (!realtime) return metric;
  const liveValue = typeof realtime.price === "number" ? realtime.price : typeof realtime.value === "number" ? realtime.value : null;
  const liveChange = typeof realtime.change_pct === "number" ? realtime.change_pct : null;
  if (liveValue === null) return metric;
  return {
    ...metric,
    value: liveValue,
    unit: metric.unit || fallbackUnit,
    change: liveChange === null ? metric.change : `${liveChange >= 0 ? "+" : ""}${liveChange.toFixed(2)}%`,
    trend: liveChange === null ? metric.trend : trendFromChange(liveChange),
    status: "ok",
    note: realtime.source ?? metric.note ?? "",
  };
}

function normalizeWallLevels(levels: Array<{ strike?: number; score?: number; distance_pct?: number }> | undefined) {
  return (levels ?? [])
    .filter((item) => typeof item.strike === "number")
    .map((item) => ({
      strike: item.strike as number,
      score: asNumber(item.score),
      distance_pct: asNumber(item.distance_pct),
    }));
}

function normalizeDataSourceStatus(input: RawDashboardSummaryResponse["data_source_status"]): DashboardSummary["data_source_status"] {
  const entries = Object.entries(input ?? {});
  return Object.fromEntries(entries.map(([key, value]) => [
    key,
    {
      label: value.name ?? key,
      status: value.status === "ok" || value.status === "warn" || value.status === "error" || value.status === "unavailable" ? value.status : "unavailable",
      updated_at: value.analysis_ready ? "analysis_ready" : null,
    },
  ]));
}

function normalizeDashboardAgent(item: RawDashboardAgentCompactSummary | null | undefined): DashboardAgentCompactSummary | null {
  if (!item) return null;
  return {
    agentName: asOptionalString(item.agent_name),
    status: asOptionalString(item.status),
    bias: asString(item.bias, "neutral"),
    confidence: typeof item.confidence === "number" ? item.confidence : 0,
    summary: asString(item.summary),
    summaryRaw: asString(item.summary_raw, asString(item.summary)),
    factReviewStatus: asOptionalString(item.fact_review_status),
    keyFindings: asStringList(item.key_findings),
    riskPoints: asStringList(item.risk_points),
    invalidConditions: asStringList(item.invalid_conditions),
    watchlist: asStringList(item.watchlist),
    claimCount: typeof item.claim_count === "number" ? item.claim_count : 0,
    createdAt: asOptionalString(item.created_at),
  };
}

function normalizeIntegratedMacro(
  item: RawDashboardSummaryResponse["integrated_macro"],
): DashboardSummary["integrated_macro"] {
  if (!item) return null;
  return {
    report_type: asString(item.report_type, "integrated_macro_summary"),
    trade_date: asString(item.trade_date),
    run_id: asOptionalString(item.run_id),
    source: asString(item.source, "macro_conclusion"),
    overall_bias: asString(item.overall_bias, "宏观结论待确认"),
    direction: normalizeSignalDirection(item.direction, "neutral"),
    macro_regime: asString(item.macro_regime, "宏观阶段待确认"),
    dominant_driver: asStringList(item.dominant_driver),
    liquidity_state: asString(item.liquidity_state, "流动性状态待确认"),
    rates_state: asString(item.rates_state, "利率状态待确认"),
    dollar_state: asString(item.dollar_state, "美元状态待确认"),
    options_alignment: asString(item.options_alignment, "期权结构待确认"),
    confidence: typeof item.confidence === "number" ? item.confidence : null,
    reasoning: asString(item.reasoning),
    trade_implication: asString(item.trade_implication),
    quick_supports: (item.quick_supports ?? [])
      .filter((support) => typeof support.level === "number" && Number.isFinite(support.level))
      .map((support) => ({
        level: support.level as number,
        label: asString(support.label, "快支撑"),
        source: asString(support.source, "unknown"),
        source_label: asString(support.source_label, "来源待确认"),
        trade_date: asOptionalString(support.trade_date),
        timeframe: asOptionalString(support.timeframe),
        basis: asString(support.basis),
        status: support.status === "active" || support.status === "broken" ? support.status : "unknown",
        source_ref: asString(support.source_ref),
      })),
    trigger_upgrade: asStringList(item.trigger_upgrade),
    trigger_downgrade: asStringList(item.trigger_downgrade),
    invalidation: asStringList(item.invalidation),
    risks: asStringList(item.risks),
    missing_inputs: asStringList(item.missing_inputs),
    composite_status: asOptionalString(item.composite_status),
    composite_trade_date: asOptionalString(item.composite_trade_date),
    source_refs: item.source_refs ?? [],
  };
}

function normalizeGoldMacroOverview(value: unknown): DashboardSummary["gold_macro_overview"] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return Object.keys(value).length > 0 ? value as DashboardSummary["gold_macro_overview"] : null;
}

function normalizeReportStatus(value: unknown): DashboardSummary["latest_reports"][number]["status"] {
  if (value === "ready" || value === "pending" || value === "missing" || value === "degraded") {
    return value;
  }
  return "ready";
}

function normalizeDashboardSummary(raw: RawDashboardSummaryResponse): DashboardSummary {
  const options = raw.options ?? {};
  const rawStrategy = raw.strategy ?? {};
  const indicators = raw.macro?.indicators ?? {};
  const realtimeQuotes = (raw.realtime_quotes ?? {}) as Record<string, { price?: number | null; value?: number | null; change_pct?: number | null; source?: string | null; name?: string | null }>;
  const xauRealtime = realtimeQuotes.XAUUSD ?? realtimeQuotes.xauusd;
  const dxyRealtime = realtimeQuotes.DXY ?? realtimeQuotes.dxy;
  // Map API indicator names to frontend expected names
  const mappedIndicators: typeof indicators = { ...indicators };
  if (!mappedIndicators.RRP && indicators.ON_RRP_USAGE) mappedIndicators.RRP = indicators.ON_RRP_USAGE;
  if (!mappedIndicators.BANK_RESERVES && indicators.RESERVES) mappedIndicators.BANK_RESERVES = indicators.RESERVES;
  if (!mappedIndicators.T10YIE && indicators.BREAKEVEN_10Y) mappedIndicators.T10YIE = indicators.BREAKEVEN_10Y;
  const resistance = normalizeWallLevels(options.walls?.resistance);
  const support = normalizeWallLevels(options.walls?.support);
  const intentScore = asNumber(options.intent_score);
  const optionDirection = intentScore >= 0.6 ? "bullish" : intentScore <= 0.35 ? "bearish" : "neutral";
  const warnings = raw.warnings ?? [];
  const riskAlerts = raw.risk_alerts ?? [];
  const rawTriggers = asStringList(rawStrategy.triggers);
  const rawInvalidConditions = asStringList(rawStrategy.invalid_conditions);
  const rawRiskPoints = asStringList(rawStrategy.risk_points);
  const rawDataQuality = asStringList(rawStrategy.data_quality);
  const rawEvidenceRefs = Array.isArray(rawStrategy.evidence_refs) ? rawStrategy.evidence_refs : [];
  const rawResistance = Array.isArray(rawStrategy.key_levels?.resistance)
    ? rawStrategy.key_levels.resistance.filter((value): value is number => typeof value === "number")
    : [];
  const rawSupport = Array.isArray(rawStrategy.key_levels?.support)
    ? rawStrategy.key_levels.support.filter((value): value is number => typeof value === "number")
    : [];

  return {
    generated_at: asString(raw.generated_at, new Date().toISOString()),
    realtime_status: {
      source: asString(raw.realtime_status?.source, "unavailable"),
      generated_at: asOptionalString(raw.realtime_status?.generated_at),
      available_symbols: Array.isArray(raw.realtime_status?.available_symbols) ? raw.realtime_status?.available_symbols.filter((item): item is string => typeof item === "string") : [],
      message: asString(raw.realtime_status?.message, ""),
    },
    realtime_quotes: raw.realtime_quotes ?? {},
    conclusion: {
      bias: `期权结构：${asString(options.intent, "unavailable")}`,
      direction: optionDirection,
      confidence: intentScore,
      macro_phase: raw.macro ? `macro: ${raw.macro.available_count ?? 0} available` : "macro unavailable",
      options_summary: `Gamma Zero ${options.gamma_zero?.toFixed?.(1) ?? "—"}，Forward ${options.forward_price?.toFixed?.(1) ?? "—"}，到期月 ${(options.expiries ?? []).slice(0, 4).join(" / ")}`,
      pin_level: derivePinLevel({
        pin_level: null,
        gamma_zero: options.gamma_zero ?? null,
        upper_resistance_walls: resistance,
        lower_support_walls: support,
      }),
      resistance_levels: resistance.map((item) => item.strike).slice(0, 3),
      support_levels: support.map((item) => item.strike).slice(0, 3),
      wall_score: resistance.length > 0 || support.length > 0 ? Math.max(...[...resistance, ...support].map((item) => item.score), 0) : null,
      net_gex: null,
    },
    market_summary: {
      XAUUSD: overlayRealtimeMetric(xauusdMetric(options), xauRealtime, "USD/oz"),
      DXY: overlayRealtimeMetric(metricFromIndicator(mappedIndicators.DXY, "DXY", "index"), dxyRealtime, "index"),
      US10Y: metricFromIndicator(mappedIndicators.US10Y, "US10Y", "%"),
      US02Y: metricFromIndicator(mappedIndicators.US02Y, "US02Y", "%"),
      T10YIE: metricFromIndicator(mappedIndicators.T10YIE, "T10YIE", "%"),
      REAL_10Y: metricFromIndicator(mappedIndicators.REAL_10Y, "10Y Real", "%"),
      YIELD_SPREAD_2Y_3M: metricFromIndicator(mappedIndicators.YIELD_SPREAD_2Y_3M, "2Y-3M Spread", "%"),
    },
    macro_liquidity: {
      RRP: metricFromIndicator(mappedIndicators.RRP, "RRP", "B"),
      TGA: metricFromIndicator(mappedIndicators.TGA, "TGA", "B"),
      BANK_RESERVES: metricFromIndicator(mappedIndicators.BANK_RESERVES, "Bank Reserves", "B"),
      SOFR: metricFromIndicator(mappedIndicators.SOFR, "SOFR", "%"),
      IORB: metricFromIndicator(mappedIndicators.IORB, "IORB", "%"),
    },
    cme_options: {
      trade_date: asString(options.trade_date),
      product: asString(options.product, "OG"),
      expiries: options.expiries ?? [],
      summary_text: asString(options.summary_text, ""),
      intent: asString(options.intent, "unavailable"),
      intent_score: intentScore,
      gamma_zero: options.gamma_zero ?? null,
      pin_level: derivePinLevel({
        pin_level: null,
        gamma_zero: options.gamma_zero ?? null,
        upper_resistance_walls: resistance,
        lower_support_walls: support,
      }),
      net_gex: null,
      wall_score: resistance.length > 0 || support.length > 0 ? Math.max(...[...resistance, ...support].map((item) => item.score), 0) : null,
      market_regime: asString(options.intent, "unavailable"),
      upper_resistance_walls: resistance,
      lower_support_walls: support,
      data_status: asString(options.data_status, "UNAVAILABLE"),
      confidence: {
        score: typeof options.confidence?.score === "number" ? options.confidence.score : intentScore,
        level: asString(options.confidence?.level, "low"),
        trade_date: asOptionalString(options.confidence?.trade_date) ?? asOptionalString(options.trade_date),
        age_days: typeof options.confidence?.age_days === "number" ? options.confidence.age_days : null,
        data_status: asString(options.confidence?.data_status, asString(options.data_status, "UNAVAILABLE")),
        reasons: Array.isArray(options.confidence?.reasons)
          ? options.confidence?.reasons.filter((item): item is string => typeof item === "string")
          : [],
      },
    },
    strategy: {
      bias: asString(rawStrategy.bias, "综合报告待生成"),
      direction: normalizeSignalDirection(rawStrategy.direction, "neutral"),
      confidence: typeof rawStrategy.confidence === "number" ? rawStrategy.confidence : 0,
      macro_phase: asString(rawStrategy.macro_phase, raw.macro ? `macro as_of ${raw.macro.as_of ?? "—"}` : "macro unavailable"),
      key_levels: {
        resistance: rawResistance.length > 0 ? rawResistance : resistance.map((item) => item.strike),
        support: rawSupport.length > 0 ? rawSupport : support.map((item) => item.strike),
      },
      triggers: rawTriggers.length > 0 ? rawTriggers : warnings,
      invalid_conditions: rawInvalidConditions.length > 0 ? rawInvalidConditions : riskAlerts,
      risk_points: rawRiskPoints.length > 0 ? rawRiskPoints : [...warnings, ...riskAlerts],
      run_id: asOptionalString(rawStrategy.run_id) ?? undefined,
      snapshot_id: asOptionalString(rawStrategy.snapshot_id) ?? undefined,
      evidence_refs: rawEvidenceRefs,
      data_quality: rawDataQuality,
      data_category_summary: rawStrategy.data_category_summary,
    },
    risk: {
      items: riskAlerts.map((alert) => ({ label: "Risk", value: alert, status: "warn" as const })),
      alerts: riskAlerts,
    },
    pipeline: raw.pipeline ?? { raw: "unavailable", parsed: "unavailable", features: "unavailable", agent: "unavailable", report: "unavailable", knowledge: "unavailable" },
    warnings,
    risk_alerts: riskAlerts,
    integrated_macro: normalizeIntegratedMacro(raw.integrated_macro),
    gold_macro_overview: normalizeGoldMacroOverview(raw.gold_macro_overview),
    agent_summary: {
      coordinator: normalizeDashboardAgent(raw.agent_summary?.coordinator),
      synthesis: normalizeDashboardAgent(raw.agent_summary?.synthesis),
    },
    composite_analysis: raw.composite_analysis,
    latest_supplemental_report: raw.latest_supplemental_report
      ? {
          ...raw.latest_supplemental_report,
          status: normalizeReportStatus(raw.latest_supplemental_report.status),
        }
      : null,
    latest_reports: (raw.latest_reports ?? []).map((report) => ({
      ...report,
      status: normalizeReportStatus(report.status),
    })),
    recent_tasks: raw.recent_tasks ?? [],
    data_source_status: normalizeDataSourceStatus(raw.data_source_status),
    source_trace: raw.source_trace ?? [],
  };
}

function sortDatesDesc(dates: UnifiedDate[]): UnifiedDate[] {
  return [...dates].sort((left, right) => right.trade_date.localeCompare(left.trade_date));
}

function latestTradeDate(dates: UnifiedDate[]): string | null {
  return sortDatesDesc(dates)[0]?.trade_date ?? null;
}

function normalizeDateString(value: unknown): string | null {
  return asOptionalString(value);
}

function hasDashboardStrategyEvidence(summary: DashboardSummary, selectedDate?: string | null): boolean {
  const strategy = summary.strategy;
  if (
    asOptionalString(strategy.run_id) ||
    asOptionalString(strategy.snapshot_id) ||
    (Array.isArray(strategy.evidence_refs) && strategy.evidence_refs.length > 0) ||
    (Array.isArray(strategy.data_quality) && strategy.data_quality.length > 0) ||
    strategy.data_category_summary
  ) {
    return true;
  }

  if (selectedDate && summary.composite_analysis?.trade_date === selectedDate) {
    const compositeStatus = normalizeDataStatus(summary.composite_analysis.status);
    return compositeStatus !== "unavailable";
  }

  return false;
}

function dashboardStrategyStatus(summary: DashboardSummary, selectedDate?: string | null): DataStatus {
  if (summary.composite_analysis) {
    return normalizeDataStatus(summary.composite_analysis.status);
  }
  if (hasDashboardStrategyEvidence(summary, selectedDate)) {
    return "available";
  }
  if (summary.strategy.bias || summary.strategy.triggers.length > 0 || summary.strategy.risk_points.length > 0) {
    return "partial";
  }
  return "unavailable";
}

function derivePinLevel(options: Pick<DashboardSummary["cme_options"], "pin_level" | "gamma_zero" | "upper_resistance_walls" | "lower_support_walls">): number | null {
  return options.pin_level ?? options.gamma_zero ?? options.upper_resistance_walls[0]?.strike ?? options.lower_support_walls[0]?.strike ?? null;
}

function metricHasValue(metric: DashboardMetric | undefined): boolean {
  if (!metric) return false;
  return metric.value !== null && metric.value !== undefined && metric.value !== "";
}

function isRenderableDashboardSummary(summary: DashboardSummary, source: "api" | "mock"): boolean {
  // If data came from a successful API call, trust it — don't discard real data
  // just because the conclusion text looks "technical". Only fall back to mock
  // when the API response is genuinely empty (no signals at all).
  if (source === "api") {
    const hasAnySignal =
      summary.conclusion.pin_level !== null ||
      summary.conclusion.wall_score !== null ||
      summary.conclusion.net_gex !== null ||
      summary.cme_options.pin_level !== null ||
      summary.cme_options.wall_score !== null ||
      summary.cme_options.net_gex !== null ||
      [
        summary.market_summary.XAUUSD,
        summary.market_summary.DXY,
        summary.market_summary.US10Y,
        summary.market_summary.US02Y,
        summary.market_summary.T10YIE,
        summary.market_summary.REAL_10Y,
        summary.market_summary.YIELD_SPREAD_2Y_3M,
      ].filter(metricHasValue).length >= 1 ||
      [
        summary.macro_liquidity.RRP,
        summary.macro_liquidity.TGA,
        summary.macro_liquidity.BANK_RESERVES,
        summary.macro_liquidity.SOFR,
        summary.macro_liquidity.IORB,
      ].filter(metricHasValue).length >= 1 ||
      summary.latest_reports.length > 0 ||
      summary.recent_tasks.length > 0 ||
      summary.warnings.length > 0 ||
      summary.risk_alerts.length > 0;
    return hasAnySignal;
  }

  // For mock data, keep the original strict check
  const headlineSignals = [
    summary.conclusion.pin_level,
    summary.conclusion.wall_score,
    summary.conclusion.net_gex,
    summary.cme_options.pin_level,
    summary.cme_options.wall_score,
    summary.cme_options.net_gex,
  ].filter((value) => value !== null && value !== undefined);

  const marketSignalCount = [
    summary.market_summary.XAUUSD,
    summary.market_summary.DXY,
    summary.market_summary.US10Y,
    summary.market_summary.US02Y,
    summary.market_summary.T10YIE,
    summary.market_summary.REAL_10Y,
    summary.market_summary.YIELD_SPREAD_2Y_3M,
  ].filter(metricHasValue).length;

  const macroSignalCount = [
    summary.macro_liquidity.RRP,
    summary.macro_liquidity.TGA,
    summary.macro_liquidity.BANK_RESERVES,
    summary.macro_liquidity.SOFR,
    summary.macro_liquidity.IORB,
  ].filter(metricHasValue).length;

  const hasOperationalContext =
    summary.latest_reports.length > 0 ||
    summary.recent_tasks.length > 0 ||
    summary.warnings.length > 0 ||
    summary.risk_alerts.length > 0;

  return headlineSignals.length > 0 || marketSignalCount >= 3 || macroSignalCount >= 3 || hasOperationalContext;
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new Error(`${label} timeout`));
    }, timeoutMs);

    promise
      .then((value) => {
        window.clearTimeout(timer);
        resolve(value);
      })
      .catch((error) => {
        window.clearTimeout(timer);
        reject(error);
      });
    });
}

function dashboardTradeDate(summary: DashboardSummary | null): string | null {
  return summary?.composite_analysis?.trade_date ?? summary?.cme_options.trade_date ?? normalizeDateString(summary?.generated_at.slice(0, 10)) ?? null;
}

function buildDashboardDateSnapshot(summary: DashboardSummary, selectedDate: string | null): UnifiedDate[] {
  if (!selectedDate) return [];

  const matchingReports = summary.latest_reports.filter((report) => report.trade_date === selectedDate);
  const hasStrategyEvidence = hasDashboardStrategyEvidence(summary, selectedDate);
  const modules = [
    summary.cme_options.trade_date === selectedDate ? "cme_options" : null,
    summary.composite_analysis?.trade_date === selectedDate ? "composite_analysis" : null,
    matchingReports.length > 0 ? "latest_reports" : null,
    hasStrategyEvidence ? "strategy" : null,
  ].filter((item): item is string => item !== null);

  return [
    {
      trade_date: selectedDate,
      modules,
      latest_run_id: hasStrategyEvidence ? asOptionalString(summary.strategy.run_id) ?? matchingReports[0]?.run_id ?? null : matchingReports[0]?.run_id ?? null,
      has_final_report: matchingReports.some((report) => report.status === "ready"),
      has_strategy_card: hasStrategyEvidence,
    },
  ];
}

function sourceRefsFromStrategyEvidence(evidenceRefs: StrategyCardData["evidence_refs"] | undefined): SourceRef[] {
  return (evidenceRefs ?? []).map((ref, index) => {
    const sourceRef = asOptionalString(ref?.ref) ?? asOptionalString(ref?.source) ?? `strategy_evidence_${index + 1}`;
    return {
      source_ref: sourceRef,
      label: asOptionalString(ref?.description) ?? asOptionalString(ref?.source) ?? "策略证据",
      artifact_path: asOptionalString(ref?.ref),
      status: "partial" as const,
    };
  });
}

function buildDashboardSourceRefs(
  summary: DashboardSummary | null,
  source: "api" | "mock" | "unavailable",
): SourceRef[] {
  const refs = normalizeSourceRefs(summary?.source_trace ?? []);
  const endpointRef = source === "api" ? sourceRefFromEndpoint(DASHBOARD_SUMMARY_PATH, { trade_date: dashboardTradeDate(summary) }) : null;
  const mockRef = source === "mock" ? { source_ref: "mock/dashboard.json", artifact_path: "apps/frontend-web/src/mocks/dashboard.json", status: "partial" as const } : null;
  return dedupeSourceRefs([...refs, endpointRef, mockRef].filter((item): item is SourceRef => item !== null));
}

function metricStatus(metric: DashboardMetric | undefined): DataStatus {
  return metricHasValue(metric) ? "available" : "unavailable";
}

function buildDashboardModules(
  summary: DashboardSummary | null,
  sourceRefs: SourceRef[],
): ModuleStatus[] {
  if (!summary) {
    return [{ id: "dashboard", label: "Dashboard", status: "unavailable", message: "暂无 Dashboard summary", source_refs: sourceRefs }];
  }

  const marketStatus = mergeDataStatus(Object.values(summary.market_summary).map(metricStatus));
  const macroStatus = mergeDataStatus(Object.values(summary.macro_liquidity).map(metricStatus));
  const optionsStatus = summary.cme_options.trade_date || summary.cme_options.gamma_zero !== null ? "available" : "unavailable";
  const strategyStatus = dashboardStrategyStatus(summary);
  const reportsStatus = summary.latest_reports.length > 0 ? "available" : "unavailable";
  const riskStatus = summary.risk_alerts.length > 0 || summary.risk.items.length > 0 ? "partial" : "available";
  const realtimeStatus = summary.realtime_status?.available_symbols?.length ? "available" : "partial";

  return [
    { id: "market", label: "市场指标", status: marketStatus, source_refs: sourceRefs },
    { id: "macro", label: "宏观流动性", status: macroStatus, source_refs: sourceRefs },
    { id: "options", label: "CME 期权", status: optionsStatus, source_refs: sourceRefs },
    { id: "realtime", label: "实时行情", status: realtimeStatus, source_refs: sourceRefs },
    { id: "strategy", label: "策略卡片", status: strategyStatus, source_refs: sourceRefs },
    { id: "reports", label: "最新报告", status: reportsStatus, source_refs: sourceRefs },
    { id: "risk", label: "风险提示", status: riskStatus, source_refs: sourceRefs },
  ];
}

function buildDashboardStrategyCard(
  summary: DashboardSummary,
  sourceRefs: SourceRef[],
): DashboardStrategyCardViewModel {
  const strategy = summary.strategy;
  const strategyStatus = dashboardStrategyStatus(summary);
  const compositeWarnings = summary.composite_analysis?.warnings ?? [];
  const strategySourceRefs = dedupeSourceRefs([...sourceRefs, ...sourceRefsFromStrategyEvidence(strategy.evidence_refs)]);

  return {
    status: strategyStatus,
    bias: strategy.bias || summary.conclusion.bias || "策略卡片不可用",
    direction: strategy.direction,
    confidence: strategy.confidence,
    scenario_summary: strategy.bias || summary.conclusion.bias || undefined,
    trigger_conditions: strategy.triggers,
    invalid_conditions: strategy.invalid_conditions,
    risk_points: [...strategy.risk_points, ...compositeWarnings],
    watchlist: [],
    is_trade_instruction: false,
    run_id: strategy.run_id ?? null,
    snapshot_id: strategy.snapshot_id ?? null,
    source_refs: strategySourceRefs,
    evidence_refs: strategy.evidence_refs,
    data_quality: strategy.data_quality,
    data_category_summary: strategy.data_category_summary,
  };
}

function buildDashboardViewModel(
  summary: DashboardSummary | null,
  source: "api" | "mock" | "unavailable",
  selectedDate: string | null,
): DashboardViewModel | null {
  const sourceRefs = buildDashboardSourceRefs(summary, source);
  const modules = buildDashboardModules(summary, sourceRefs);

  if (!summary) return null;

  const status = mergeDataStatus(modules.map((module) => module.status));
  const strategyCardView = buildDashboardStrategyCard(summary, sourceRefs);
  const latestReports: ReportMeta[] = summary.latest_reports.map((report) => ({
    type: report.type ?? "dashboard_latest_report",
    ...(report.family ? { family: report.family } : {}),
    title: report.title,
    trade_date: report.trade_date,
    run_id: report.run_id ?? undefined,
    format: "markdown",
    status: normalizeDataStatus(report.status),
    source_refs: sourceRefs,
  }));

  return {
    status,
    trade_date: selectedDate ?? null,
    run_id: strategyCardView.run_id ?? null,
    generated_at: summary.generated_at,
    market_state: {
      label: strategyCardView.scenario_summary || strategyCardView.bias || "等待后端综合结论",
      bias: strategyCardView.direction,
      confidence: strategyCardView.confidence,
      status: strategyCardView.status,
      summary: summary.agent_summary?.synthesis?.summary || summary.agent_summary?.coordinator?.summary || strategyCardView.scenario_summary || "暂无综合摘要",
      updated_at: summary.generated_at,
      source_refs: strategyCardView.source_refs,
    },
    key_drivers: [
      { id: "macro", label: "宏观阶段", summary: summary.conclusion.macro_phase, status: modules.find((item) => item.id === "macro")?.status ?? "unavailable", source_refs: sourceRefs },
      { id: "rates", label: "利率与美元", summary: "美元指数、名义利率、实际利率共同决定宏观方向", status: modules.find((item) => item.id === "market")?.status ?? "unavailable", source_refs: sourceRefs },
      { id: "liquidity", label: "流动性", summary: "TGA / RRP / 银行准备金用于判断流动性背景", status: modules.find((item) => item.id === "macro")?.status ?? "unavailable", source_refs: sourceRefs },
      { id: "options", label: "期权结构", summary: summary.conclusion.options_summary, status: normalizeDataStatus(summary.cme_options.intent ? "available" : "unavailable"), source_refs: sourceRefs },
    ],
    strategy_card: strategyCardView,
    cme_summary: {
      status: modules.find((item) => item.id === "options")?.status ?? "unavailable",
      trade_date: summary.cme_options.trade_date || null,
      product: summary.cme_options.product,
      intent: summary.cme_options.intent,
      confidence: summary.cme_options.intent_score,
      gamma_zero: summary.cme_options.gamma_zero,
      pin_level: summary.cme_options.pin_level,
      resistance_levels: summary.conclusion.resistance_levels,
      support_levels: summary.conclusion.support_levels,
      source_refs: sourceRefs,
    },
    macro_summary: {
      status: modules.find((item) => item.id === "macro")?.status ?? "unavailable",
      phase: summary.conclusion.macro_phase,
      metrics: Object.values(summary.macro_liquidity),
      source_refs: sourceRefs,
    },
    gold_macro_overview: summary.gold_macro_overview ?? null,
    risk_alerts: summary.risk_alerts.map((alert, index) => ({
      id: `risk-${index}`,
      label: "风险提示",
      detail: alert,
      severity: "warning",
      status: "partial",
      source_refs: sourceRefs,
    })),
    data_status: Object.entries(summary.data_source_status).map(([id, item]) => ({
      id,
      label: item.label,
      status: normalizeDataStatus(item.status),
      updated_at: item.updated_at ?? undefined,
      source_refs: sourceRefs,
    })),
    latest_reports: latestReports,
    modules,
    source_refs: sourceRefs,
  };
}

function buildDashboardDataResponse(
  summary: DashboardSummary | null,
  selectedDate: string | null,
  source: "api" | "mock" | "unavailable",
  dates?: UnifiedDate[],
): DashboardDataResponse {
  const sourceRefs = buildDashboardSourceRefs(summary, source);
  const modules = buildDashboardModules(summary, sourceRefs);
  const resolvedDates = dates ?? (summary && selectedDate ? buildDashboardDateSnapshot(summary, selectedDate) : []);
  return {
    dates: resolvedDates,
    selected_date: selectedDate,
    summary,
    has_data: summary !== null,
    source,
    status: summary ? mergeDataStatus(modules.map((module) => module.status)) : "unavailable",
    source_refs: sourceRefs,
    modules,
    view_model: buildDashboardViewModel(summary, source, selectedDate),
  };
}

async function loadDashboardFromMock(preferredDate?: string | null): Promise<DashboardDataResponse> {
  const { default: dashboardMock } = await import("@/mocks/dashboard.json");
  const mock = dashboardMock as DashboardMockPayload;
  const dates = sortDatesDesc(Array.isArray(mock.dates) ? mock.dates : []);
  const selectedDate =
    (preferredDate && dates.some((item) => item.trade_date === preferredDate) ? preferredDate : null) ??
    latestTradeDate(dates) ??
    mock.default_date ??
    null;
  const summary = selectedDate ? mock.summaries[selectedDate] ?? null : null;
  return buildDashboardDataResponse(summary, selectedDate, "mock", dates);
}

export async function fetchDashboardData(preferredDate?: string | null): Promise<DashboardDataResponse> {
  try {
    const summaryRaw = await withTimeout(
      fetchJson<RawDashboardSummaryResponse>(DASHBOARD_SUMMARY_PATH),
      DASHBOARD_TIMEOUT_MS,
      "dashboard",
    );
    const summary = normalizeDashboardSummary(summaryRaw);
    const selectedDate = dashboardTradeDate(summary);
    if (!isRenderableDashboardSummary(summary, "api") && ENABLE_DASHBOARD_MOCK_FALLBACK) {
      return loadDashboardFromMock(preferredDate);
    }
    return buildDashboardDataResponse(summary, selectedDate, "api");
  } catch (error) {
    if (ENABLE_DASHBOARD_MOCK_FALLBACK) {
      return loadDashboardFromMock(preferredDate);
    }
    throw error;
  }
}
