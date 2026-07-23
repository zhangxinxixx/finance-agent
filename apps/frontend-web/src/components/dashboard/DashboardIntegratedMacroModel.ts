import type { DashboardMetric, DashboardQuickSupportLevel, DashboardSummary, DashboardViewModel, SignalDirection, SourceTraceItem } from "@/types/dashboard";
import { translateText } from "./judgmentFormat";
import { formatOptionalNumber, getWallBias, translateIntent } from "./CMEOptionsSummaryFormat";

export interface DashboardIntegratedMacroSummary {
  overallBias: string;
  direction: SignalDirection;
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

function directionLabel(direction: SignalDirection | "unknown" | string | null | undefined): string {
  const value = String(direction ?? "").toLowerCase();
  if (value === "bullish" || value === "偏多" || value === "看多") return "偏多";
  if (value === "bearish" || value === "偏空" || value === "看空") return "偏空";
  if (value === "neutral-bullish") return "中性偏多";
  if (value === "neutral-bearish") return "中性偏空";
  if (value === "mixed") return "混合";
  return "中性";
}

function directionOf(direction: SignalDirection | "unknown" | string | null | undefined): SignalDirection {
  const value = String(direction ?? "").toLowerCase();
  if (value === "bullish" || value === "偏多" || value === "看多") return "bullish";
  if (value === "bearish" || value === "偏空" || value === "看空") return "bearish";
  return "neutral";
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
  if (!metric || metric.value === null || metric.value === undefined || metric.value === "") {
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
  return `${label}${trend}至 ${value}${unit}`;
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
  if (ok === total) return { label: "数据完整", ok, total, pct };
  if (ok > 0) return { label: "数据部分可用", ok, total, pct };
  return { label: "数据待修复", ok, total, pct };
}

function tradeImplicationFor(direction: SignalDirection): string {
  if (direction === "bullish") {
    return "等待美元或实际利率继续转弱确认；不按期权墙位单独追涨。";
  }
  if (direction === "bearish") {
    return "优先防守和观察；美元或实际利率转弱后再评估修复。";
  }
  return "维持区间观察；等待美元或实际利率给出方向。";
}

function decisionSummaryFor(direction: SignalDirection): string {
  if (direction === "bullish") {
    return "偏修复，但确认信号仍来自美元和实际利率；期权结构只作为关键位反应证据。";
  }
  if (direction === "bearish") {
    return "偏防守，黄金修复需要美元或实际利率转弱配合；期权支撑不等于宏观转向。";
  }
  return "当前以观察为主，宏观方向未形成强共振；先看美元、实际利率和关键价位反应。";
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
  const agent = summary.agent_summary?.synthesis ?? summary.agent_summary?.coordinator ?? null;
  const strategyView = viewModel?.strategy_card ?? null;
  const direction = directionOf(readModel?.direction ?? agent?.bias ?? strategyView?.direction ?? summary.strategy.direction);
  const confidence = readModel
    ? readModel.confidence
    : agent?.confidence ?? strategyView?.confidence ?? summary.strategy.confidence ?? null;
  const overallBias =
    cleanText(readModel?.overall_bias) ??
    cleanText(agent?.bias) ??
    cleanText(strategyView?.bias) ??
    cleanText(summary.strategy.bias) ??
    directionLabel(direction);
  const rawMacroRegime = cleanText(readModel?.macro_regime) ?? cleanText(summary.strategy.macro_phase) ?? cleanText(viewModel?.macro_summary?.phase);
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
  const wallBias = getWallBias(summary.cme_options.wall_score);
  const readModelOptionsAlignment = readModel?.options_alignment
    ? translateText(readModel.options_alignment).trim() || null
    : null;
  const optionsAlignment =
    readModelOptionsAlignment ??
    `${translateIntent(summary.cme_options.intent)}，${wallBias.label}；仅作为价格结构约束与短线反应证据`;
  const invalidation = uniqueItems(
    [
      ...(readModel?.invalidation ?? []),
      ...(readModel?.risks ?? []),
      ...(agent?.invalidConditions ?? []),
      ...(agent?.riskPoints ?? []),
      ...(strategyView?.invalid_conditions ?? []),
      ...(strategyView?.risk_points ?? []),
      ...summary.strategy.invalid_conditions,
      ...summary.risk_alerts,
    ],
    "美元重新走强、实际利率反弹或价格跌破关键支撑时，当前综合判断需要复核。",
  );
  const dominantDrivers = readModel?.dominant_driver?.length
    ? readModel.dominant_driver
    : ["美元指数", "实际利率", "流动性条件", "期权结构"];
  const agentSummary = cleanText(agent?.summary ?? strategyView?.scenario_summary);
  const macroExplanation =
    cleanText(readModel?.reasoning) ??
    agentSummary ??
    `${dollarState}，${ratesState}。综合判断优先由美元、名义/实际利率和宏观阶段共同决定。`;
  const researchMemo =
    cleanText(readModel?.reasoning) ??
    `${directionLabel(direction)}判断仍由${dominantDrivers.slice(0, 2).join("与")}主导。${dollarState}，${ratesState}；流动性侧${liquidityState}，当前更适合作为宏观背景强弱观察，不单独构成趋势信号。`;
  const optionsMemo =
    readModelOptionsAlignment ??
    `CME 期权结构显示${translateIntent(summary.cme_options.intent)}、${wallBias.label}，更适合作为短线价格吸附、墙位反应和结构约束证据，不应单独推导宏观方向。`;
  const riskNote = invalidation[0];
  const decisionSummary =
    firstSentence(cleanText(readModel?.trade_implication)) ??
    firstSentence(cleanText(readModel?.reasoning)) ??
    agentSummary ??
    decisionSummaryFor(direction);

  return {
    overallBias,
    direction,
    macroRegime,
    dominantDrivers,
    liquidityState: cleanText(readModel?.liquidity_state) ?? liquidityState,
    ratesState: mergeRateStructureState(cleanText(readModel?.rates_state), ratesState, shortCurveState),
    dollarState: cleanText(readModel?.dollar_state) ?? dollarState,
    optionsAlignment,
    confidence,
    invalidation,
    macroExplanation,
    researchMemo,
    liquidityExplanation: `${liquidityState}。当前流动性变量用于判断宏观背景强弱，不单独给出趋势方向。`,
    optionsExplanation: `${optionsAlignment}。Gamma/Pin/墙位不直接替代综合宏观方向。`,
    optionsMemo,
    decisionSummary,
    riskNote,
    tradeImplication: cleanText(readModel?.trade_implication) ?? tradeImplicationFor(direction),
    quickSupports: readModel?.quick_supports ?? [],
    macroLevels: {
      resistance: summary.strategy.key_levels.resistance.length ? summary.strategy.key_levels.resistance : summary.conclusion.resistance_levels,
      support: summary.strategy.key_levels.support.length ? summary.strategy.key_levels.support : summary.conclusion.support_levels,
    },
    dataCompleteness: sourceDataCompleteness(summary.source_trace),
  };
}

export function buildOptionsEvidenceSummary(summary: DashboardSummary): DashboardOptionsEvidenceSummary {
  const options = summary.cme_options;
  const readModel = summary.integrated_macro ?? null;
  const confidence = Math.max(0, Math.min(1, options.confidence?.score ?? options.intent_score ?? 0));
  const callWall = strongestWall(options.upper_resistance_walls);
  const putWall = strongestWall(options.lower_support_walls);
  const sourceRefs = summary.source_trace
    .filter((trace) => /cme|option|options|期权/i.test(`${trace.name} ${trace.source_ref}`))
    .slice(0, 3);
  const fallbackRefs = sourceRefs.length ? sourceRefs : summary.source_trace.slice(0, 2);
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
      ? "CME 为最新 PRELIM 数据，可用于当前结构分析；后续版本可能调整墙位、Gamma Zero 与置信度。"
      : null);
  const revisionNote = analysisSummary && /PRELIM.*(?:修订|调整)|(?:修订|调整).*PRELIM/i.test(analysisSummary)
    ? null
    : rawRevisionNote;

  return {
    reportType: "CME 期权结构报告",
    dataStatus: options.data_status || options.confidence?.data_status || "UNAVAILABLE",
    optionBias: translateIntent(options.intent),
    wallBias: getWallBias(options.wall_score).label,
    confidencePct: `${Math.round(confidence * 100)}%`,
    gammaZero: formatOptionalNumber(options.gamma_zero, 1),
    pin: formatOptionalNumber(options.pin_level, 1),
    callWall: formatOptionalNumber(callWall, 0),
    putWall: formatOptionalNumber(putWall, 0),
    sourceRefs: fallbackRefs,
    analysisSummary,
    upgradeCondition,
    failureCondition,
    revisionNote,
    usageNote: "用于观察短线价格吸附、墙位反应和结构风险，不单独作为黄金宏观方向判断。",
  };
}
