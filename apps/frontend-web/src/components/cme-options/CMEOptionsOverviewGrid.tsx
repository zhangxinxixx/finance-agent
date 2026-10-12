import { readableWarning } from "@/lib/researchReading";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { CMEOptionsDecisionResponse, CMEOptionsResponse } from "@/types/cme-options";
import { formatCMEExpiryLabel, formatCMEProductLabel, formatCompactNumber, formatNumber, resolveDirectionalWall, summarizeDecision, toneStyle, translateDecisionText } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";
import { resolveCMEExpiryScope, selectCMEPinWall } from "./cmeDecisionIdentity";

interface CMEOptionsOverviewGridProps {
  snapshot: CMEOptionsResponse;
  wallScores: CMEOptionsResponse["wall_scores"];
  decision?: CMEOptionsDecisionResponse | null;
  selectedExpiry?: string;
}

interface LevelCard {
  label: string;
  value: string;
  detail: string;
  tone: string;
}

interface InterpretationRow {
  label: string;
  value: string;
  detail: string;
  tone: string;
}

interface ReportBasis {
  summary: string;
  detail: string;
}

interface ExpiryInsight {
  expiry: string;
  callGex: number | null;
  putGex: number | null;
  netGex: number | null;
  totalGex: number | null;
  gammaZero: number | null;
  structure: string | null;
  callTop: { strike: number; value: number } | null;
  putTop: { strike: number; value: number } | null;
  totalTop: Array<{ strike: number; value: number }>;
  skewNote: string | null;
  dominance: string;
  direction: string;
}

function reportStatusTone(status: string | undefined) {
  return getStatusTone(status, "report");
}

function reviewStatusTone(status: string | null | undefined) {
  return getStatusTone(status, "review");
}

function reviewStatusLabel(status: string | null | undefined): string {
  return getStatusLabel(status, "review");
}

function reportStatusLabel(status: string | undefined): string {
  if (status === "FINAL") return "终版";
  if (status === "PRELIM") return "预览";
  return status ? "公告状态待确认" : "未提供";
}

function productLabel(product: string | null | undefined): string {
  return formatCMEProductLabel(product);
}

function formatPercent(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function formatSignedNumber(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, digits)}`;
}

function formatConfidence(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "无置信度";
  const pct = value * 100;
  if (pct > 0 && pct < 1) return `极低 ${pct.toFixed(2)}%`;
  return `${pct.toFixed(0)}%`;
}

function formatGex(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value / 100000000).toFixed(2)}亿`;
}

function directionalWallDetail(wall: ReturnType<typeof resolveDirectionalWall>, fallbackLabel: string) {
  if (!wall) return `${fallbackLabel} 暂无可用点位`;
  if (wall.source === "wall_scores") {
    return `评分 ${formatNumber(wall.wallScore, 2)} / 持仓 ${formatNumber(wall.oi)}`;
  }
  if (wall.source === "support_resistance") {
    return `支撑阻力回退 / 距远期价 ${formatPercent(wall.distancePct)} / 评分 ${formatNumber(wall.wallScore, 2)}`;
  }
  return `GEX 回退 / ${formatCMEExpiryLabel(wall.expiry)} / ${formatGex(wall.gexValue)}`;
}

function formatRange(min: number | null | undefined, max: number | null | undefined) {
  if (min === null || min === undefined || max === null || max === undefined) return "—";
  return `${formatNumber(min)}–${formatNumber(max)} 点`;
}

function formatHoldingEvidence(value: string) {
  return translateDecisionText(value).replace(
    /(看涨持仓|看跌持仓|看涨变化|看跌变化)\s*(-?[0-9]+)/g,
    (_, label: string, raw: string) => `${label} ${formatNumber(Number(raw))} 张`,
  );
}

function formatModelName(model: string | null | undefined) {
  if (!model) return "—";
  const normalized = model.trim().toLowerCase();
  if (normalized === "black-76" || normalized === "black_76") return "Black-76 定价模型";
  if (normalized.includes("proxy") || normalized.includes("settlement_iv")) return "结算隐含波动率代理模型";
  return /[\u3400-\u9fff]/.test(model) ? model : "模型口径待确认";
}

function reportAnchorSourceLabel(source: string | null | undefined) {
  if (!source) return "未标注";
  if (source === "not_provided") return "报告未直接提供，使用模型锚点";
  if (source === "parity_inferred") return "平价反推";
  if (source === "jin10_close") return "金十收盘价";
  const translated = translateDecisionText(source);
  return /[\u3400-\u9fff]/.test(translated) ? translated : "报告锚点来源待确认";
}

function sourceRangeLabel(source: string | null | undefined) {
  if (source === "report_p0_plus_minus_1000") return "报告锚点上下 1000";
  if (source === "user_explicit") return "手动指定";
  if (source === "normal") return "波动率区间";
  return source ? "区间来源待确认" : "自动区间";
}

function findPinWall(wallScores: CMEOptionsResponse["wall_scores"]) {
  return selectCMEPinWall(wallScores);
}

function nearestLevel(
  levels: CMEOptionsResponse["support_resistance"]["support" | "resistance"],
  currentPrice: number | null | undefined,
) {
  if (!levels.length) return null;
  if (!currentPrice) return levels[0] ?? null;
  return [...levels].sort((a, b) => Math.abs(a.strike - currentPrice) - Math.abs(b.strike - currentPrice))[0] ?? null;
}

function wallScoreDelta(snapshot: CMEOptionsResponse, strike: number | null | undefined) {
  if (!strike) return null;
  const map = snapshot.calibration?.wall_score_delta_1d ?? {};
  return map[String(strike)] ?? map[String(Math.round(strike))] ?? null;
}

function dataQualityCount(snapshot: CMEOptionsResponse, key: string) {
  return snapshot.data_quality?.categories?.[key] ?? null;
}

function expiryOrder(snapshot: CMEOptionsResponse, selectedExpiry?: string) {
  const byExpiry = snapshot.gex?.by_expiry ?? {};
  const configured = snapshot.data_source?.expiries ?? [];
  if (selectedExpiry) return byExpiry[selectedExpiry] ? [selectedExpiry] : [];
  const ordered = configured.filter((expiry) => byExpiry[expiry]);
  return ordered.length > 0 ? ordered : Object.keys(byExpiry);
}

function buildExpiryInsight(snapshot: CMEOptionsResponse, expiry: string | undefined): ExpiryInsight | null {
  if (!expiry) return null;
  const data = snapshot.gex?.by_expiry?.[expiry];
  if (!data) return null;
  const summary = data.summary ?? {};
  const callGex = summary.call_gex ?? null;
  const putGex = summary.put_gex ?? null;
  const netGex = summary.net_gex ?? null;
  const totalGex = summary.total_gex ?? null;
  const callTop = [...data.gex_top].sort((a, b) => b.call_gex - a.call_gex)[0];
  const putTop = [...data.gex_top].sort((a, b) => b.put_gex - a.put_gex)[0];
  const structureLabel: Record<string, string> = {
    balanced: "模型看涨/看跌伽马敞口接近（Call/Put GEX）",
    net_call_dominated: "模型看涨伽马敞口较高（Call GEX）",
    net_put_dominated: "模型看跌伽马敞口较高（Put GEX）",
  };
  const dominance = summary.structure
    ? structureLabel[summary.structure] ?? "模型结构待确认"
    : callGex !== null || putGex !== null
      ? "模型看涨/看跌伽马敞口数值已返回，未提供结构标签（Call/Put GEX）"
      : "模型看涨/看跌伽马敞口不可用（Call/Put GEX）";
  const direction = netGex === null
    ? "模型净 GEX 不可用；未给出实盘方向"
    : `模型净 GEX ${netGex > 0 ? "为正" : netGex < 0 ? "为负" : "为 0"}；正负号仅代表模型敞口符号，不代表实盘方向`;

  return {
    expiry,
    callGex,
    putGex,
    netGex,
    totalGex,
    gammaZero: summary.gamma_zero ?? null,
    structure: summary.structure ?? null,
    callTop: callTop ? { strike: callTop.strike, value: callTop.call_gex } : null,
    putTop: putTop ? { strike: putTop.strike, value: putTop.put_gex } : null,
    totalTop: [...data.gex_top]
      .sort((a, b) => b.total_gex - a.total_gex)
      .slice(0, 4)
      .map((item) => ({ strike: item.strike, value: item.total_gex })),
    skewNote: data.iv_skew?.interpretation ? translateDecisionText(data.iv_skew.interpretation) : null,
    dominance,
    direction,
  };
}

function buildRange(snapshot: CMEOptionsResponse) {
  const range = snapshot.parameters?.analysis_range;
  const support = snapshot.support_resistance?.support ?? [];
  const resistance = snapshot.support_resistance?.resistance ?? [];
  const fallbackMin = support.length ? Math.min(...support.map((item) => item.strike)) : null;
  const fallbackMax = resistance.length ? Math.max(...resistance.map((item) => item.strike)) : null;
  return {
    min: range?.strike_min ?? fallbackMin,
    max: range?.strike_max ?? fallbackMax,
    source: sourceRangeLabel(range?.source),
  };
}

function buildLevelCards(snapshot: CMEOptionsResponse, wallScores: CMEOptionsResponse["wall_scores"]): LevelCard[] {
  const gex = snapshot.gex?.netgex_aggregate;
  const currentPrice = snapshot.parameters?.report_p0
    ?? snapshot.parameters?.p0
    ?? null;
  const callWall = resolveDirectionalWall(snapshot, wallScores, "CALL");
  const putWall = resolveDirectionalWall(snapshot, wallScores, "PUT");
  const pinWall = findPinWall(wallScores);
  const nearestResistance = nearestLevel(snapshot.support_resistance?.resistance ?? [], currentPrice);
  const nearestSupport = nearestLevel(snapshot.support_resistance?.support ?? [], currentPrice);

  return [
    {
      label: "上方看涨压制",
      value: `${formatNumber(callWall?.strike)} 点`,
      detail: directionalWallDetail(callWall, "上方压制"),
      tone: "down",
    },
    {
      label: "下方看跌支撑",
      value: `${formatNumber(putWall?.strike)} 点`,
      detail: directionalWallDetail(putWall, "下方支撑"),
      tone: "up",
    },
    {
      label: "吸附位",
      value: `${formatNumber(pinWall?.strike)} 点`,
      detail: `吸附值 ${formatNumber(pinWall?.pnt, 2)} / 持仓变化 ${formatSignedNumber(pinWall?.delta_oi)}`,
      tone: "violet",
    },
    {
      label: "突破门槛",
      value: `${formatNumber(nearestResistance?.strike)} 点`,
      detail: `距远期价 ${formatPercent(nearestResistance?.distance_pct)} / 评分 ${formatNumber(nearestResistance?.wall_score, 2)}`,
      tone: "important",
    },
    {
      label: "防守底线",
      value: `${formatNumber(nearestSupport?.strike)} 点`,
      detail: `距远期价 ${formatPercent(nearestSupport?.distance_pct)} / 评分 ${formatNumber(nearestSupport?.wall_score, 2)}`,
      tone: "important",
    },
    {
      label: "伽马零点",
      value: `${formatNumber(gex?.gamma_zero?.price, 1)} 点`,
      detail: `${translateDecisionText(gex?.gamma_zero?.method ?? "推导值")} / 聚合净伽马 ${formatCompactNumber(gex?.net_gex)}`,
      tone: "important",
    },
  ];
}

function buildValueRows(
  snapshot: CMEOptionsResponse,
  wallScores: CMEOptionsResponse["wall_scores"],
  decision?: CMEOptionsDecisionResponse | null,
  selectedExpiry?: string,
) {
  const callWall = resolveDirectionalWall(snapshot, wallScores, "CALL");
  const putWall = resolveDirectionalWall(snapshot, wallScores, "PUT");
  const nearNext = snapshot.calibration?.near_month_vs_next_month;
  const rollSignal = snapshot.roll_signals?.[0] ?? snapshot.calibration?.expiry_roll_signal?.[0] ?? null;
  const qualityWarnings = snapshot.data_quality?.warnings ?? [];
  const calibrationWarnings = snapshot.calibration?.calibration_warnings ?? [];
  const warnings = calibrationWarnings.length > 0 ? calibrationWarnings : qualityWarnings;
  const callDelta = wallScoreDelta(snapshot, callWall?.strike);
  const putDelta = wallScoreDelta(snapshot, putWall?.strike);
  const hasWallDelta = callDelta !== null || putDelta !== null;
  const expiries = expiryOrder(snapshot, selectedExpiry);
  const nearInsight = buildExpiryInsight(snapshot, expiries[0]);
  const farInsight = buildExpiryInsight(snapshot, expiries[1]);
  const hasNearNextOi = !selectedExpiry && Boolean(nearNext?.near_total_oi || nearNext?.next_total_oi || nearNext?.oi_ratio);
  const comparisonWindow = decision?.meta.previous_trade_date && decision.meta.current_trade_date
    ? `${decision.meta.previous_trade_date} → ${decision.meta.current_trade_date}`
    : "上一交易日 → 当前交易日";

  return [
    {
      label: "墙位稳定性",
      value: hasWallDelta ? `看涨 ${formatSignedNumber(callDelta, 2)} / 看跌 ${formatSignedNumber(putDelta, 2)}` : "缺历史校准",
      detail: hasWallDelta ? `区间墙位评分变化（${comparisonWindow}），用于判断压制或支撑是否迁移` : `当前快照缺少区间墙位评分变化（${comparisonWindow}），需要连续 CME 日报校准后才能判断稳定性`,
    },
    {
      label: selectedExpiry ? "当前到期月结构" : "近远月结构",
      value: selectedExpiry
        ? (nearInsight ? formatCMEExpiryLabel(nearInsight.expiry) : "所选到期月缺失")
        : hasNearNextOi
          ? `持仓比 ${formatNumber(nearNext?.oi_ratio, 2)} 倍`
          : `${nearInsight ? formatCMEExpiryLabel(nearInsight.expiry) : "近月"} / ${farInsight ? formatCMEExpiryLabel(farInsight.expiry) : "次月"}`,
      detail: selectedExpiry
        ? nearInsight ? `${nearInsight.dominance}；${nearInsight.direction}` : "所选到期月没有可用 GEX 结构"
        : hasNearNextOi
          ? `近月持仓 ${formatCompactNumber(nearNext?.near_total_oi, "张")} / 次月持仓 ${formatCompactNumber(nearNext?.next_total_oi, "张")}`
          : `未返回近月与次月总持仓；改用 GEX 结构：${nearInsight?.dominance ?? "近月缺失"} / ${farInsight?.dominance ?? "远月缺失"}`,
    },
    {
      label: "换月信号",
      value: rollSignal ? formatConfidence(rollSignal.confidence) : "无明显换月",
      detail: rollSignal
        ? `${translateDecisionText(rollSignal.evidence?.[0])}；${translateDecisionText(rollSignal.evidence?.[1])}`
        : "未检测到高置信换月证据",
    },
    {
      label: "数据价值",
      value: `${reportStatusLabel(snapshot.data_source.status)} / ${formatNumber(snapshot.data_source.row_count)} 行`,
      detail: `${snapshot.source_trace.length} 条溯源记录，${calibrationWarnings.length > 0 ? `${calibrationWarnings.length} 条校准提示` : "缺历史校准"}，${qualityWarnings.length} 条质量提示`,
    },
  ];
}

function buildCMEReportHighlights(
  snapshot: CMEOptionsResponse,
  nearInsight: ExpiryInsight | null,
  farInsight: ExpiryInsight | null,
): InterpretationRow[] {
  const missingDelta = dataQualityCount(snapshot, "rows_missing_delta");
  const proxyStrikes = dataQualityCount(snapshot, "proxy_strikes");
  const filteredRows = dataQualityCount(snapshot, "rows_filtered_by_strike");
  const zeroOi = dataQualityCount(snapshot, "zero_oi");
  const intentEvidence = snapshot.intent?.evidence?.map((item) => formatHoldingEvidence(item)) ?? [];
  const warnings = snapshot.data_quality?.warnings ?? [];

  return [
    {
      label: "报告持仓信号",
      value: translateDecisionText(snapshot.intent?.type ?? "—"),
      detail: intentEvidence.length ? intentEvidence.join(" / ") : "未返回持仓意图证据",
      tone: "down",
    },
    {
      label: "降权点",
      value: `Delta缺口 ${formatNumber(missingDelta)} / 代理 ${formatNumber(proxyStrikes)}`,
      detail: `过滤 ${formatNumber(filteredRows)} 行，零持仓 ${formatNumber(zeroOi)}；${warnings.map((item) => translateDecisionText(item)).join("；") || "暂无额外质量提示"}`,
      tone: "warn",
    },
    {
      label: "近远月读数",
      value: `${nearInsight ? formatCMEExpiryLabel(nearInsight.expiry) : "近月"} ${nearInsight?.dominance ?? "—"}`,
      detail: farInsight ? `远月 ${formatCMEExpiryLabel(farInsight.expiry)}：${farInsight.dominance}，看涨伽马敞口最高点（Call GEX）${formatNumber(farInsight.callTop?.strike)} / 看跌伽马敞口最高点（Put GEX）${formatNumber(farInsight.putTop?.strike)}` : "远月结构暂缺",
      tone: "info",
    },
  ];
}

function buildCMEReportBasis(snapshot: CMEOptionsResponse): ReportBasis {
  const range = buildRange(snapshot);
  const expiries = snapshot.data_source.expiries ?? [];
  const anchor = snapshot.parameters?.report_p0 ?? snapshot.parameters?.p0;
  const gexMode = snapshot.parameters?.used_real_gex === true
    ? "模型伽马敞口（GEX）"
    : snapshot.parameters?.used_real_gex === false
      ? "代理伽马敞口（GEX）"
      : "伽马敞口（GEX）口径未标注";
  const sourceNote = snapshot.data_source.source_url ? "CME官方" : "来源未标注";

  return {
    summary: `${reportStatusLabel(snapshot.data_source.status)} ${snapshot.data_source.report_date ?? snapshot.trade_date} · ${productLabel(snapshot.data_source.product)} · ${formatNumber(snapshot.data_source.row_count)}行/${formatNumber(expiries.length)}到期月`,
    detail: `锚点 ${formatNumber(anchor, 1)} · 区间 ${formatRange(range.min, range.max)} · ${formatModelName(snapshot.parameters?.model)}/${gexMode} · ${sourceNote} · ${reportAnchorSourceLabel(snapshot.parameters?.report_p0_source ?? snapshot.parameters?.p0_source)}`,
  };
}

function buildAnalystReadout(
  snapshot: CMEOptionsResponse,
  wallScores: CMEOptionsResponse["wall_scores"],
  nearInsight: ExpiryInsight | null,
  farInsight: ExpiryInsight | null,
  decision?: CMEOptionsDecisionResponse | null,
): InterpretationRow[] {
  const gex = snapshot.gex?.netgex_aggregate;
  const currentPrice = snapshot.parameters?.report_p0
    ?? snapshot.parameters?.p0
    ?? null;
  const gammaZero = gex?.gamma_zero?.price ?? decision?.gamma_summary.gamma_zero ?? null;
  const callWall = resolveDirectionalWall(snapshot, wallScores, "CALL");
  const putWall = resolveDirectionalWall(snapshot, wallScores, "PUT");
  const pinWall = findPinWall(wallScores);
  const riskSignals = snapshot.roll_signals?.map((signal) => {
    const evidence = signal.evidence?.map(translateDecisionText).filter(Boolean) ?? [];
    return evidence.length > 0 ? evidence.join("；") : translateDecisionText(signal.roll_type);
  }) ?? [];
  const snapshotDirection = gex?.net_gex_direction === "negative" || gex?.net_gex_direction === "positive" || gex?.net_gex_direction === "neutral"
    ? gex.net_gex_direction
    : null;
  const decisionDirection = decision?.gamma_summary.regime === "negative_gamma"
    ? "negative"
    : decision?.gamma_summary.regime === "positive_gamma"
      ? "positive"
      : decision?.gamma_summary.regime === "flip_zone"
        ? "neutral"
        : null;
  const aggregateDirection = snapshotDirection ?? decisionDirection;
  const priceVsGamma = currentPrice !== null && gammaZero !== null
    ? currentPrice < gammaZero
      ? "黄金期货（GC）报告锚点低于伽马零点，仅描述报告结构"
      : currentPrice > gammaZero
        ? "黄金期货（GC）报告锚点高于伽马零点，现货突破仍待独立确认"
        : "黄金期货（GC）报告锚点贴近伽马零点，仅作结构观察"
    : "缺少黄金期货（GC）报告锚点或伽马零点，无法比较";

  return [
    {
      label: "黄金期货（GC）报告环境",
      value: aggregateDirection === "negative" ? "负伽马风险" : aggregateDirection === "positive" ? "正伽马缓冲" : aggregateDirection === "neutral" ? "中性吸附" : "聚合方向未提供",
      detail: priceVsGamma,
      tone: "important",
    },
    {
      label: "近月影响区间",
      value: `${formatNumber(putWall?.strike)} - ${formatNumber(callWall?.strike)}`,
      detail: `下方 ${formatNumber(putWall?.strike)} 为保护/支撑，上方 ${formatNumber(callWall?.strike)} 为压制/突破观察`,
      tone: "important",
    },
    {
      label: "吸附与突破",
      value: `吸附位 ${formatNumber(pinWall?.strike)} / 伽马零点 ${formatNumber(gammaZero, 1)}`,
      detail: `若价格围绕 ${formatNumber(pinWall?.strike)} 震荡，优先看区间；偏离 ${formatNumber(gammaZero, 1)} 后波动结构会改变`,
      tone: "violet",
    },
    {
      label: "远月模型分布",
      value: farInsight ? `${formatCMEExpiryLabel(farInsight.expiry)} ${farInsight.dominance}` : "远月暂缺",
      detail: farInsight
        ? `看涨伽马敞口最高点（Call GEX）${formatNumber(farInsight.callTop?.strike)}，看跌伽马敞口最高点（Put GEX）${formatNumber(farInsight.putTop?.strike)}；${farInsight.direction}`
        : "当前 CME 快照未返回可用远月结构",
      tone: "important",
    },
    {
      label: "风险确认",
      value: snapshot.data_source.status === "FINAL" ? "终版确认" : "预览待确认",
      detail: riskSignals.length ? riskSignals.join("；") : "未检测到高置信换月或尾部迁移信号",
      tone: "important",
    },
  ];
}

export function CMEOptionsOverviewGrid({ snapshot, wallScores, decision, selectedExpiry }: CMEOptionsOverviewGridProps) {
  const analysis = snapshot.analysis;
  const agentSummary = analysis?.synthesis?.summary || analysis?.cme_options_agent?.summary;
  const decisionSummary = summarizeDecision(decision);
  const primarySummary = translateDecisionText(agentSummary || decisionSummary || "综合分析暂不可用，请以当前结构数据和风险提示为准。");
  const primarySummaryLabel = agentSummary ? "Agent 综合判断" : decisionSummary ? "决策数据摘要" : "结构数据说明";
  const rollRiskNotices = (snapshot.roll_signals ?? []).flatMap((signal) => {
    const evidence = signal.evidence?.map(translateDecisionText).filter(Boolean) ?? [];
    return evidence.length > 0 ? [evidence.join("；")] : [translateDecisionText(signal.roll_type)];
  });
  const riskNotices = [
    ...(analysis?.pending_reviews.map((item) => item.reason) ?? []),
    ...(analysis?.synthesis?.risk_points ?? []),
    ...(analysis?.cme_options_agent?.risk_points ?? []),
    ...(decision?.data_quality.warnings ?? []),
    ...(snapshot.data_quality?.warnings ?? []),
    ...(snapshot.calibration?.calibration_warnings ?? []),
    ...rollRiskNotices,
  ].filter((item, index, items) => item && items.indexOf(item) === index);
  const levelCards = buildLevelCards(snapshot, wallScores);
  const valueRows = buildValueRows(snapshot, wallScores, decision, selectedExpiry);
  const expiries = expiryOrder(snapshot, selectedExpiry);
  const nearInsight = buildExpiryInsight(snapshot, expiries[0]);
  const farInsight = buildExpiryInsight(snapshot, expiries[1]);
  const distributionInsight = selectedExpiry ? nearInsight : farInsight;
  const analysisRange = buildRange(snapshot);
  const reportHighlights = buildCMEReportHighlights(snapshot, nearInsight, farInsight);
  const reportBasis = buildCMEReportBasis(snapshot);
  const analystReadout = buildAnalystReadout(snapshot, wallScores, nearInsight, farInsight, decision);
  const selectedExpiryScope = selectedExpiry ? resolveCMEExpiryScope(expiries, selectedExpiry) : null;

  return (
    <div className="cme-options-overview-layout">
      {selectedExpiry ? (
        <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[length:var(--type-caption)] text-[var(--fg-3)]">
          {selectedExpiryScope?.missing
            ? `所选到期月 ${formatCMEExpiryLabel(selectedExpiry)} 未返回结构数据；当前总览不会静默改用其他期限。`
            : `当前总览已限定到期月 ${formatCMEExpiryLabel(selectedExpiry)}。墙位与聚合净伽马仍按接口返回的快照聚合口径展示。`}
        </div>
      ) : null}
      <main className="cme-options-overview-main">
        <CMEOptionsSurface title="结构判断工作台" bodyStyle={{ display: "grid", gap: 10, background: "var(--bg-card-inner)" }}>
          <section className="cme-options-decision-board" aria-label="期权结构总览">
            <div className="cme-options-decision-cell cme-options-decision-cell--range">
              <span className="cme-options-mini-label">{selectedExpiry ? "当前到期月影响区间" : "近月影响区间"}</span>
              <strong className="cme-options-range-value fa-num">
                {formatRange(analysisRange.min, analysisRange.max)}
              </strong>
              <span className="cme-options-cell-detail">区间口径：{analysisRange.source}</span>
            </div>

            <div className="cme-options-decision-cell">
              <span className="cme-options-mini-label">看涨（Call）模型 GEX</span>
              <strong className="cme-options-decision-value fa-num">{formatGex(nearInsight?.callGex)}</strong>
              <span className="cme-options-cell-detail cme-options-cell-detail--important">最高点位 {formatNumber(nearInsight?.callTop?.strike)}</span>
            </div>

            <div className="cme-options-decision-cell">
              <span className="cme-options-mini-label">看跌（Put）模型 GEX</span>
              <strong className="cme-options-decision-value fa-num">{formatGex(nearInsight?.putGex)}</strong>
              <span className="cme-options-cell-detail cme-options-cell-detail--important">最高点位 {formatNumber(nearInsight?.putTop?.strike)}</span>
            </div>

            <div className="cme-options-decision-cell cme-options-decision-cell--judgement">
              <span className="cme-options-mini-label cme-options-mini-label--important">{selectedExpiry ? "当前到期月判断" : "近月判断"} · {nearInsight ? formatCMEExpiryLabel(nearInsight.expiry) : "—"}</span>
              <strong className="cme-options-decision-title">{nearInsight?.dominance ?? "暂无近月分布"}</strong>
              <span className="cme-options-cell-detail">{nearInsight?.direction ?? "当前快照未返回近月伽马分布。"}</span>
            </div>
          </section>

          <section className="cme-options-thesis-panel">
            <div className="cme-options-thesis-copy">
              <span className="cme-options-mini-label">{primarySummaryLabel}</span>
              <p>{primarySummary}</p>
            </div>

            <div className="cme-options-far-panel">
              <div className="cme-options-section-heading">
                <span>{selectedExpiry ? "当前到期月模型 GEX 分布" : "远月模型 GEX 分布"}</span>
                <strong>{distributionInsight ? `${formatCMEExpiryLabel(distributionInsight.expiry)} · ${distributionInsight.dominance}` : selectedExpiry ? "所选到期月无数据" : "无远月数据"}</strong>
              </div>
              {distributionInsight ? (
                <>
                  <div className="cme-options-far-grid">
                    <div className="cme-options-far-cell cme-options-far-cell--wide">
                      <span>模型分布</span>
                      <strong>{distributionInsight.dominance}</strong>
                      <small>净伽马 {formatGex(distributionInsight.netGex)} / 总量 {formatGex(distributionInsight.totalGex)}</small>
                    </div>
                    <div className="cme-options-far-cell">
                      <span>看涨（Call）GEX 最高点</span>
                      <strong className="fa-num">{formatNumber(distributionInsight.callTop?.strike)}</strong>
                      <small>{formatGex(distributionInsight.callTop?.value)}</small>
                    </div>
                    <div className="cme-options-far-cell">
                      <span>看跌（Put）GEX 最高点</span>
                      <strong className="fa-num">{formatNumber(distributionInsight.putTop?.strike)}</strong>
                      <small>{formatGex(distributionInsight.putTop?.value)}</small>
                    </div>
                  </div>
                  <div className="cme-options-far-tags">
                    {distributionInsight.totalTop.map((item) => (
                      <span key={`${distributionInsight.expiry}-${item.strike}`}>
                        {formatNumber(item.strike)} / {formatGex(item.value)}
                      </span>
                    ))}
                  </div>
                  {distributionInsight.skewNote ? <p className="cme-options-muted-note">{distributionInsight.skewNote}</p> : null}
                </>
              ) : (
                <p className="cme-options-muted-note">{selectedExpiry ? "当前快照未返回所选到期月伽马分布。" : "当前快照未返回远月伽马分布。"}</p>
              )}
            </div>
          </section>
        </CMEOptionsSurface>

        <CMEOptionsSurface title="关键价位矩阵" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
          <div className="cme-options-level-grid">
            {levelCards.map((level, index) => {
              const tone = toneStyle(level.tone);
              return (
                <div key={level.label} className="cme-options-level-card">
                  <span style={{ color: tone.text }}>{level.label}</span>
                  <strong className="fa-num">{level.value}</strong>
                  <p>{level.detail}</p>
                </div>
              );
            })}
          </div>
        </CMEOptionsSurface>

        <CMEOptionsSurface title="分析师读盘" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
          <div className="cme-options-readout-grid">
            {analystReadout.map((row, index) => {
              const tone = toneStyle(row.tone);
              return (
                <div key={row.label} className="cme-options-readout-card">
                  <span style={{ color: tone.text }}>{row.label}</span>
                  <strong>{row.value}</strong>
                  <p>{row.detail}</p>
                </div>
              );
            })}
          </div>
        </CMEOptionsSurface>
      </main>

      <aside className="cme-options-overview-rail">
        <CMEOptionsSurface title="风险与可信度" bodyStyle={{ display: "grid", gap: 10, background: "var(--bg-card-inner)" }}>
          <div className="cme-options-status-row">
            {analysis?.fact_review_status ? (
              <FAStatusPill tone={reviewStatusTone(analysis.fact_review_status)}>
                {reviewStatusLabel(analysis.fact_review_status)}
              </FAStatusPill>
            ) : null}
            <FAStatusPill tone={reportStatusTone(snapshot.data_source.status)}>{reportStatusLabel(snapshot.data_source.status)}</FAStatusPill>
            <FAStatusPill tone="neutral">{productLabel(snapshot.data_source.product)}</FAStatusPill>
          </div>

          <div className="cme-options-rail-block cme-options-rail-block--risk">
            <span className="cme-options-mini-label">风险提示（全部）</span>
            {riskNotices.length > 0 ? (
              <div className="space-y-1">
                {riskNotices.map((risk) => <p key={risk}>{translateDecisionText(risk)}</p>)}
              </div>
            ) : <p>暂无额外风险提示。</p>}
          </div>

          <div className="cme-options-rail-block">
            <span className="cme-options-mini-label">CME 报告基准</span>
            <strong>{readableWarning(reportBasis.summary)}</strong>
            <p>{reportBasis.detail}</p>
          </div>

          <div className="cme-options-rail-list">
            {reportHighlights.map((row) => {
              const tone = toneStyle(row.tone);
              return (
                <div key={row.label} className="cme-options-rail-row">
                  <div>
                    <span style={{ color: tone.text }}>{row.label}</span>
                    <strong className="fa-num">{row.value}</strong>
                  </div>
                  <p>{row.detail}</p>
                </div>
              );
            })}
          </div>

          <div className="cme-options-rail-list">
            {valueRows.map((row) => (
              <div key={row.label} className="cme-options-rail-row cme-options-rail-row--important">
                <div>
                  <span>{row.label}</span>
                  <strong className="fa-num">{row.value}</strong>
                </div>
                <p>{row.detail}</p>
              </div>
            ))}
          </div>

          <div className="cme-options-count-grid">
            <div>
              <span>待复核</span>
              <strong className="fa-num">{analysis?.pending_review_count == null ? "—" : `${analysis.pending_review_count} 项`}</strong>
            </div>
          </div>
        </CMEOptionsSurface>
      </aside>
    </div>
  );
}
