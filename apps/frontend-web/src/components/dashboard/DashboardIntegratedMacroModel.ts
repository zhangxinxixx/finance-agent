import type { DashboardMetric, DashboardQuickSupportLevel, DashboardSummary, DashboardViewModel, SignalDirection, SourceTraceItem } from "@/types/dashboard";
import { translateText } from "./judgmentFormat";
import { formatOptionalNumber, getWallStrength, translateIntent } from "./CMEOptionsSummaryFormat";

export interface DashboardIntegratedMacroSummary {
  overallBias: string;
  direction: SignalDirection | "unknown";
  macroRegime: string;
  dominantDrivers: string[];
  liquidityState: string;
  ratesState: string;
  dollarState: string;
  optionsAlignment: string;
  confidence: number | null;
  invalidation: string[];
  macroExplanation: string;
  researchMemo: string;
  liquidityExplanation: string;
  optionsExplanation: string;
  optionsMemo: string;
  decisionSummary: string;
  riskNote: string;
  tradeImplication: string;
  quickSupports: DashboardQuickSupportLevel[];
  macroLevels: {
    resistance: number[];
    support: number[];
    resistanceCoordinate: "spot" | "gc_futures" | "unknown";
    supportCoordinate: "spot" | "gc_futures" | "unknown";
  };
  dataCompleteness: {
    label: string;
    ok: number;
    total: number;
    pct: number | null;
  };
}

export interface DashboardOptionsEvidenceSummary {
  reportType: string;
  dataStatus: string;
  optionBias: string;
  wallBias: string;
  confidencePct: string;
  gammaZero: string;
  pin: string;
  callWall: string;
  putWall: string;
  sourceRefs: SourceTraceItem[];
  analysisSummary: string | null;
  upgradeCondition: string | null;
  failureCondition: string | null;
  revisionNote: string | null;
  usageNote: string;
}

/** Time of the selected research result, never the most recent unrelated report or UI read. */
export function dashboardResearchDate(summary: DashboardSummary, _viewModel?: DashboardViewModel | null): string {
  return summary.integrated_macro ? summary.integrated_macro.trade_date || "未提供"
    : summary.composite_analysis?.trade_date || "未提供";
}

export function dashboardResearchAsOf(summary: DashboardSummary, _viewModel?: DashboardViewModel | null): string | null {
  if (summary.integrated_macro) return summary.integrated_macro.as_of || summary.integrated_macro.trade_date || null;
  return summary.agent_summary?.synthesis?.createdAt || summary.agent_summary?.coordinator?.createdAt
    || summary.composite_analysis?.trade_date || null;
}

function directionLabel(direction: SignalDirection | "unknown" | string | null | undefined): string {
  const value = String(direction ?? "").toLowerCase();
  if (value === "bullish" || value === "偏多" || value === "看多") return "偏多";
  if (value === "bearish" || value === "偏空" || value === "看空") return "偏空";
  if (value === "neutral-bullish") return "中性偏多";
  if (value === "neutral-bearish") return "中性偏空";
  if (value === "mixed") return "混合";
  return value === "neutral" ? "中性" : "方向未提供";
}

function directionOf(direction: SignalDirection | "unknown" | string | null | undefined): SignalDirection | "unknown" {
  const value = String(direction ?? "").toLowerCase();
  if (value === "bullish" || value === "偏多" || value === "看多") return "bullish";
  if (value === "bearish" || value === "偏空" || value === "看空") return "bearish";
  return value === "neutral" ? "neutral" : "unknown";
}

function cleanText(value: string | null | undefined): string | null {
  const text = translateText(value ?? "").trim();
  if (!text || text === "—") return null;
  if (/^期权(意图|结构)：?/.test(text)) return null;
  if (/Gamma Zero|Forward|到期月/i.test(text)) return null;
  if (/^期权数据[:：]/.test(text)) return null;
  return text;
}

function metricState(metric: DashboardMetric | undefined, label: string): string {
  if (!metric || metric.value === null || metric.value === undefined || metric.value === ""
    || typeof metric.value === "number" && !Number.isFinite(metric.value)) {
    return `${label}暂无有效读数`;
  }
  const value = typeof metric.value === "number"
    ? metric.value.toLocaleString("en-US", { maximumFractionDigits: 2 })
    : String(metric.value);
  const unit = metric.unit && metric.unit !== "index" ? metric.unit : "";
  const trend =
    metric.trend === "up" ? "上行"
      : metric.trend === "down" ? "回落"
        : "横向";
  return `${label}${trend}至 ${value}${unit}（源数据 ${metric.data_date || "时间未提供"}）`;
}

function mergeRateStructureState(readModelState: string | null, fallbackState: string, shortCurveState: string): string {
  if (!readModelState) return fallbackState;
  if (/2Y-3M|利差|短端/.test(readModelState)) return readModelState;
  return `${readModelState}；${shortCurveState}`;
}

function strongestWall(walls: DashboardSummary["cme_options"]["upper_resistance_walls"]): number | null {
  if (walls.length === 0) return null;
  return [...walls].sort((a, b) => b.score - a.score)[0]?.strike ?? null;
}

function uniqueItems(items: Array<string | null | undefined>, fallback: string): string[] {
  const seen = new Set<string>();
  const values = items
    .map((item) => cleanText(item))
    .filter((item): item is string => {
      if (!item || seen.has(item)) return false;
      seen.add(item);
      return true;
    });
  return values.length ? values : [fallback];
}

function firstReadModelItem(items: string[] | undefined, pattern: RegExp): string | null {
  const item = items?.find((value) => pattern.test(value));
  return item ? translateText(item).trim() || null : null;
}

function sourceDataCompleteness(sourceTrace: DashboardSummary["source_trace"]): DashboardIntegratedMacroSummary["dataCompleteness"] {
  const total = sourceTrace.length;
  const ok = sourceTrace.filter((trace) => trace.status === "ok").length;
  const pct = total > 0 ? Math.round((ok / total) * 100) : null;
  if (total === 0) return { label: "数据状态待确认", ok, total, pct };
  if (ok === total) return { label: "已列来源状态正常", ok, total, pct };
  if (ok > 0) return { label: "已列来源部分可用", ok, total, pct };
  return { label: "已列来源待核验", ok, total, pct };
}

function firstSentence(value: string | null): string | null {
  if (!value) return null;
  const match = value.match(/^.*?[。！？.!?]/);
  return (match?.[0] ?? value).trim() || null;
}

export function buildIntegratedMacroSummary(
  summary: DashboardSummary,
  viewModel?: DashboardViewModel | null,
): DashboardIntegratedMacroSummary {
  const readModel = summary.integrated_macro ?? null;
  // A selected research result owns its missing fields. Other snapshots cannot fill them.
  const agent = readModel ? null : summary.agent_summary?.synthesis ?? summary.agent_summary?.coordinator ?? null;
  const strategyView = readModel ? null : viewModel?.strategy_card ?? null;
  const direction = directionOf(readModel ? readModel.direction : agent?.bias ?? strategyView?.direction ?? summary.strategy.direction);
  const rawConfidence = readModel
    ? readModel.confidence
    : agent?.confidence ?? strategyView?.confidence ?? summary.strategy.confidence ?? null;
  const confidence = typeof rawConfidence === "number" && Number.isFinite(rawConfidence) ? rawConfidence : null;
  const overallBias =
    cleanText(readModel?.overall_bias) ??
    cleanText(agent?.bias) ??
    cleanText(strategyView?.bias) ??
    (readModel ? null : cleanText(summary.strategy.bias)) ??
    directionLabel(direction);
  const rawMacroRegime = readModel ? cleanText(readModel.macro_regime)
    : cleanText(summary.strategy.macro_phase) ?? cleanText(viewModel?.macro_summary?.phase);
  const macroRegime = rawMacroRegime && !/^\d{4}-\d{2}-\d{2}$/.test(rawMacroRegime)
    ? rawMacroRegime
    : "宏观阶段待综合报告确认";
  const dollarState = metricState(summary.market_summary.DXY, "美元指数");
  const shortCurveState = metricState(summary.market_summary.YIELD_SPREAD_2Y_3M, "2Y-3M利差");
  const ratesState = [
    metricState(summary.market_summary.REAL_10Y, "10Y实际利率"),
    metricState(summary.market_summary.US10Y, "10Y美债收益率"),
    shortCurveState,
  ].join("，");
  const liquidityState = [
    metricState(summary.macro_liquidity.TGA, "TGA"),
    metricState(summary.macro_liquidity.RRP, "RRP"),
    metricState(summary.macro_liquidity.BANK_RESERVES, "银行准备金"),
  ].join("；");
  const wallBias = getWallStrength(summary.cme_options.wall_score);
  const readModelOptionsAlignment = readModel?.options_alignment
    ? translateText(readModel.options_alignment).trim() || null
    : null;
  const optionsAlignment =
    readModelOptionsAlignment ??
    (readModel ? "本次研究未提供期权配合度；独立结构证据请查看期权摘要。"
      : `${translateIntent(summary.cme_options.intent)}，${wallBias.label}；仅作为价格结构约束与短线反应证据`);
  const invalidation = uniqueItems(
    readModel ? readModel.invalidation ?? [] : [
      ...(agent?.invalidConditions ?? []),
      ...(strategyView?.invalid_conditions ?? []),
      ...summary.strategy.invalid_conditions,
    ],
    "后端尚未提供失效条件；当前结果不能作为完整策略条件参考。",
  );
  const dominantDrivers = readModel?.dominant_driver?.length
    ? readModel.dominant_driver
    : ["主导驱动未提供"];
  const agentSummary = cleanText(agent?.summary ?? strategyView?.scenario_summary);
  const macroExplanation = readModel
    ? cleanText(readModel.reasoning) ?? "本次研究未提供宏观影响解释；独立的当前观测请查看市场数据。"
    : agentSummary ?? `${dollarState}；${ratesState}。后端尚未提供影响解释。`;
  const researchMemo =
    cleanText(readModel?.reasoning) ??
    agentSummary ?? "后端尚未提供研究解释。";
  const optionsMemo =
    readModelOptionsAlignment ??
    "后端尚未提供期权配合度分析；请进入结构详情查看已有数据与限制。";
  const riskNote = uniqueItems(readModel ? readModel.risks ?? [] : summary.risk_alerts, "后端尚未提供风险说明。")[0];
  const decisionSummary =
    firstSentence(cleanText(readModel?.trade_implication)) ??
    firstSentence(cleanText(readModel?.reasoning)) ??
    agentSummary ??
    "后端尚未提供综合结论。";
  const strategyResistance = readModel ? [] : summary.strategy.key_levels.resistance;
  const strategySupport = readModel ? [] : summary.strategy.key_levels.support;
  const resistance = readModel ? [] : strategyResistance.length ? strategyResistance : summary.conclusion.resistance_levels;
  const support = readModel ? [] : strategySupport.length ? strategySupport : summary.conclusion.support_levels;
  const resistanceCoordinate = strategyResistance.length
    ? summary.strategy.key_level_coordinates?.resistance ?? "unknown"
    : resistance.length ? "gc_futures" : "unknown";
  const supportCoordinate = strategySupport.length
    ? summary.strategy.key_level_coordinates?.support ?? "unknown"
    : support.length ? "gc_futures" : "unknown";

  return {
    overallBias,
    direction,
    macroRegime,
    dominantDrivers,
    liquidityState: readModel ? cleanText(readModel.liquidity_state) ?? "本次研究未提供流动性状态；当前观测请查看市场数据。" : liquidityState,
    ratesState: readModel ? cleanText(readModel.rates_state) ?? "本次研究未提供利率状态；当前观测请查看市场数据。"
      : mergeRateStructureState(null, ratesState, shortCurveState),
    dollarState: readModel ? cleanText(readModel.dollar_state) ?? "本次研究未提供美元状态；当前观测请查看市场数据。" : dollarState,
    optionsAlignment,
    confidence,
    invalidation,
    macroExplanation,
    researchMemo,
    liquidityExplanation: readModel ? cleanText(readModel.liquidity_state) ?? "本次研究未提供流动性解释。请在市场数据中查看独立的当前观测。"
      : `${liquidityState}。当前流动性变量用于判断宏观背景强弱，不单独给出趋势方向。`,
    optionsExplanation: `${optionsAlignment}。Proxy Gamma Flip 与显式 OI-Gamma Concentration（Pin）不直接替代综合宏观方向。`,
    optionsMemo,
    decisionSummary,
    riskNote,
    tradeImplication: cleanText(readModel?.trade_implication) ?? "后端尚未提供触发或等待条件，请查看策略状态。",
    quickSupports: readModel?.quick_supports ?? [],
    macroLevels: {
      resistance,
      support,
      resistanceCoordinate,
      supportCoordinate,
    },
    dataCompleteness: sourceDataCompleteness(summary.source_trace),
  };
}

export function buildOptionsEvidenceSummary(summary: DashboardSummary): DashboardOptionsEvidenceSummary {
  const options = summary.cme_options;
  const readModel = summary.integrated_macro ?? null;
  const rawConfidence = options.confidence?.score;
  const confidence = typeof rawConfidence === "number" && Number.isFinite(rawConfidence)
    ? Math.max(0, Math.min(1, rawConfidence)) : null;
  const callWall = strongestWall(options.upper_resistance_walls);
  const putWall = strongestWall(options.lower_support_walls);
  const sourceRefs = summary.source_trace
    .filter((trace) => /cme|option|options|期权/i.test(`${trace.name} ${trace.source_ref}`))
    .slice(0, 3);
  const analysisSummary = readModel?.options_alignment
    ? translateText(readModel.options_alignment).trim() || null
    : null;
  const upgradeCondition = firstReadModelItem(
    readModel?.trigger_upgrade,
    /XAUUSD.*(?:站上|确认区|期权结构)|(?:站上|确认区).*XAUUSD/i,
  );
  const failureCondition = firstReadModelItem(
    [...(readModel?.trigger_downgrade ?? []), ...(readModel?.invalidation ?? [])],
    /XAUUSD.*(?:跌破|支撑)|(?:跌破|失效).*支撑|价格有效跌破/i,
  );
  const rawRevisionNote = firstReadModelItem(readModel?.risks, /CME.*PRELIM|PRELIM.*(?:墙位|修订|版本)/i)
    ?? ((options.data_status || options.confidence?.data_status || "").toUpperCase().startsWith("PRELIM")
      ? "CME 公告为初步版；研究可用性以返回的质量门禁为准，后续修订可能调整 OI 与 Proxy Gamma 结构。"
      : null);
  const revisionNote = analysisSummary && /PRELIM.*(?:修订|调整)|(?:修订|调整).*PRELIM/i.test(analysisSummary)
    ? null
    : rawRevisionNote;

  return {
    reportType: "CME 期权结构报告",
    dataStatus: options.data_status || options.confidence?.data_status || "UNAVAILABLE",
    optionBias: translateIntent(options.intent),
    wallBias: getWallStrength(options.wall_score).label,
    confidencePct: confidence === null ? "未量化" : options.confidence?.is_probability
      ? `${Math.round(confidence * 100)}%` : `${Math.round(confidence * 100)}/100（非概率）`,
    gammaZero: formatOptionalNumber(options.gamma_zero, 1),
    pin: formatOptionalNumber(options.pin_level, 1),
    callWall: formatOptionalNumber(callWall, 0),
    putWall: formatOptionalNumber(putWall, 0),
    sourceRefs,
    analysisSummary,
    upgradeCondition,
    failureCondition,
    revisionNote,
    usageNote: "用于观察短线价格吸附、墙位反应和结构风险，不单独作为黄金宏观方向判断。",
  };
}
