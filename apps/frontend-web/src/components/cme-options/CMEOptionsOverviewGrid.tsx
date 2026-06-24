import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatNumber, resolveDirectionalWall, toneStyle, translateEvidence } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";

interface CMEOptionsOverviewGridProps {
  snapshot: CMEOptionsResponse;
  wallScores: CMEOptionsResponse["wall_scores"];
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
  return status ?? "未知";
}

function productLabel(product: string | null | undefined): string {
  if (!product) return "期权";
  if (product === "OG") return "COMEX 黄金期权 OG";
  if (/CME|Options|OG/i.test(product)) return "黄金期权";
  return product;
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
  return `GEX 回退 / ${wall.expiry ?? "近月"} / ${formatGex(wall.gexValue)}`;
}

function formatRange(min: number | null | undefined, max: number | null | undefined) {
  if (min === null || min === undefined || max === null || max === undefined) return "—";
  return `${formatNumber(min)} - ${formatNumber(max)}`;
}

function formatModelName(model: string | null | undefined) {
  if (!model) return "—";
  if (model.toLowerCase() === "black-76") return "Black-76";
  return model;
}

function reportAnchorSourceLabel(source: string | null | undefined) {
  if (!source) return "未标注";
  if (source === "not_provided") return "报告未直接提供，使用模型锚点";
  if (source === "parity_inferred") return "平价反推";
  if (source === "jin10_close") return "金十收盘价";
  return translateEvidence(source);
}

function sourceRangeLabel(source: string | null | undefined) {
  if (source === "report_p0_plus_minus_1000") return "报告锚点上下 1000";
  if (source === "user_explicit") return "手动指定";
  if (source === "normal") return "波动率区间";
  return source ?? "自动区间";
}

function findPinWall(wallScores: CMEOptionsResponse["wall_scores"]) {
  const explicitPin = wallScores.find((wall) => wall.wall_type === "Pin Wall");
  if (explicitPin) return explicitPin;
  return [...wallScores].sort((a, b) => b.pnt - a.pnt)[0] ?? null;
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

function expiryOrder(snapshot: CMEOptionsResponse) {
  const byExpiry = snapshot.gex?.by_expiry ?? {};
  const configured = snapshot.data_source?.expiries ?? [];
  const ordered = configured.filter((expiry) => byExpiry[expiry]);
  return ordered.length > 0 ? ordered : Object.keys(byExpiry);
}

function buildExpiryInsight(snapshot: CMEOptionsResponse, expiry: string | undefined): ExpiryInsight | null {
  if (!expiry) return null;
  const data = snapshot.gex?.by_expiry?.[expiry];
  if (!data) return null;
  const summary = data.summary ?? {};
  const callGex = summary.call_gex ?? data.gex_top.reduce((sum, item) => sum + Math.max(item.call_gex ?? 0, 0), 0);
  const putGex = summary.put_gex ?? data.gex_top.reduce((sum, item) => sum + Math.max(item.put_gex ?? 0, 0), 0);
  const netGex = summary.net_gex ?? callGex - putGex;
  const totalGex = summary.total_gex ?? callGex + putGex;
  const callTop = [...data.gex_top].sort((a, b) => b.call_gex - a.call_gex)[0];
  const putTop = [...data.gex_top].sort((a, b) => b.put_gex - a.put_gex)[0];
  const dominance = callGex > putGex * 1.08
    ? "看涨压力更强"
    : putGex > callGex * 1.08
      ? "看跌支撑更强"
      : "看涨/看跌接近平衡";
  const direction = netGex > 0
    ? "上方关键位更容易形成压制与突破观察"
    : netGex < 0
      ? "下方保护更重，跌破支撑后的波动风险更高"
      : "净伽马接近中性，优先看区间吸附";

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
    skewNote: data.iv_skew?.interpretation ?? null,
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
  const currentPrice = snapshot.parameters?.f_value ?? gex?.gamma_zero?.price ?? null;
  const callWall = resolveDirectionalWall(snapshot, wallScores, "CALL");
  const putWall = resolveDirectionalWall(snapshot, wallScores, "PUT");
  const pinWall = findPinWall(wallScores);
  const nearestResistance = nearestLevel(snapshot.support_resistance?.resistance ?? [], currentPrice);
  const nearestSupport = nearestLevel(snapshot.support_resistance?.support ?? [], currentPrice);

  return [
    {
      label: "上方看涨压制",
      value: formatNumber(callWall?.strike),
      detail: directionalWallDetail(callWall, "上方压制"),
      tone: "down",
    },
    {
      label: "下方看跌支撑",
      value: formatNumber(putWall?.strike),
      detail: directionalWallDetail(putWall, "下方支撑"),
      tone: "up",
    },
    {
      label: "Pin 位",
      value: formatNumber(pinWall?.strike),
      detail: `吸附值 ${formatNumber(pinWall?.pnt, 2)} / 持仓变化 ${formatSignedNumber(pinWall?.delta_oi)}`,
      tone: "violet",
    },
    {
      label: "突破门槛",
      value: formatNumber(nearestResistance?.strike),
      detail: `距远期价 ${formatPercent(nearestResistance?.distance_pct)} / 评分 ${formatNumber(nearestResistance?.wall_score, 2)}`,
      tone: "warn",
    },
    {
      label: "防守底线",
      value: formatNumber(nearestSupport?.strike),
      detail: `距远期价 ${formatPercent(nearestSupport?.distance_pct)} / 评分 ${formatNumber(nearestSupport?.wall_score, 2)}`,
      tone: "info",
    },
    {
      label: "伽马零点",
      value: formatNumber(gex?.gamma_zero?.price, 1),
      detail: `${translateEvidence(gex?.gamma_zero?.method ?? "推导值")} / 净伽马 ${formatNumber(gex?.net_gex)}`,
      tone: gex?.net_gex_direction === "negative" ? "down" : gex?.net_gex_direction === "positive" ? "up" : "slate",
    },
  ];
}

function buildValueRows(snapshot: CMEOptionsResponse, wallScores: CMEOptionsResponse["wall_scores"]) {
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
  const expiries = expiryOrder(snapshot);
  const nearInsight = buildExpiryInsight(snapshot, expiries[0]);
  const farInsight = buildExpiryInsight(snapshot, expiries[1]);
  const hasNearNextOi = Boolean(nearNext?.near_total_oi || nearNext?.next_total_oi || nearNext?.oi_ratio);

  return [
    {
      label: "墙位稳定性",
      value: hasWallDelta ? `看涨 ${formatSignedNumber(callDelta, 2)} / 看跌 ${formatSignedNumber(putDelta, 2)}` : "缺历史校准",
      detail: hasWallDelta ? "一日墙位评分变化，判断压制/支撑是否迁移" : "当前快照没有 wall_score_delta_1d，需要连续 CME 日报校准后才能判断稳定性",
    },
    {
      label: "近远月结构",
      value: hasNearNextOi ? `持仓比 ${formatNumber(nearNext?.oi_ratio, 2)}x` : `${nearInsight?.expiry ?? "近月"} / ${farInsight?.expiry ?? "次月"}`,
      detail: hasNearNextOi
        ? `近月持仓 ${formatNumber(nearNext?.near_total_oi)} / 次月持仓 ${formatNumber(nearNext?.next_total_oi)}`
        : `未返回近/次月总 OI；改用 GEX 结构：${nearInsight?.dominance ?? "近月缺失"} / ${farInsight?.dominance ?? "远月缺失"}`,
    },
    {
      label: "换月信号",
      value: rollSignal ? formatConfidence(rollSignal.confidence) : "无明显换月",
      detail: rollSignal
        ? `${translateEvidence(rollSignal.evidence?.[0])}；${translateEvidence(rollSignal.evidence?.[1])}`
        : "未检测到高置信换月证据",
    },
    {
      label: "数据价值",
      value: `${reportStatusLabel(snapshot.data_source.status)} / ${snapshot.data_source.row_count} 行`,
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
  const intentEvidence = snapshot.intent?.evidence?.map((item) => translateEvidence(item)) ?? [];
  const warnings = snapshot.data_quality?.warnings ?? [];

  return [
    {
      label: "报告 OI 信号",
      value: translateEvidence(snapshot.intent?.type ?? "—"),
      detail: intentEvidence.length ? intentEvidence.join(" / ") : "未返回 OI 意图证据",
      tone: "down",
    },
    {
      label: "降权点",
      value: `Delta缺口 ${formatNumber(missingDelta)} / 代理 ${formatNumber(proxyStrikes)}`,
      detail: `过滤 ${formatNumber(filteredRows)} 行，零持仓 ${formatNumber(zeroOi)}；${warnings.map((item) => translateEvidence(item)).slice(0, 2).join("；") || "暂无额外质量提示"}`,
      tone: "warn",
    },
    {
      label: "近远月读数",
      value: `${nearInsight?.expiry ?? "近月"} ${nearInsight?.dominance ?? "—"}`,
      detail: farInsight ? `远月 ${farInsight.expiry}：${farInsight.dominance}，看高 ${formatNumber(farInsight.callTop?.strike)} / 看低 ${formatNumber(farInsight.putTop?.strike)}` : "远月结构暂缺",
      tone: "info",
    },
  ];
}

function buildCMEReportBasis(snapshot: CMEOptionsResponse): ReportBasis {
  const range = buildRange(snapshot);
  const expiries = snapshot.data_source.expiries ?? [];
  const anchor = snapshot.parameters?.report_p0 ?? snapshot.parameters?.p0 ?? snapshot.parameters?.f_value;
  const gexMode = snapshot.parameters?.used_real_gex ? "真实GEX" : "代理GEX";
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
): InterpretationRow[] {
  const gex = snapshot.gex?.netgex_aggregate;
  const currentPrice = snapshot.parameters?.f_value ?? snapshot.parameters?.report_p0 ?? snapshot.parameters?.p0 ?? null;
  const gammaZero = gex?.gamma_zero?.price ?? null;
  const callWall = resolveDirectionalWall(snapshot, wallScores, "CALL");
  const putWall = resolveDirectionalWall(snapshot, wallScores, "PUT");
  const pinWall = findPinWall(wallScores);
  const riskSignals = snapshot.roll_signals?.map((signal) => translateEvidence(signal.evidence?.[0] ?? signal.roll_type)).slice(0, 2) ?? [];
  const priceVsGamma = currentPrice !== null && gammaZero !== null
    ? currentPrice < gammaZero
      ? "价格低于伽马零点，向下波动更容易被放大"
      : currentPrice > gammaZero
        ? "价格高于伽马零点，上方突破需要确认"
        : "价格贴近伽马零点，区间吸附更强"
    : "当前缺少价格与伽马零点关系";

  return [
    {
      label: "当前环境",
      value: gex?.net_gex_direction === "negative" ? "负伽马风险" : gex?.net_gex_direction === "positive" ? "正伽马缓冲" : "中性吸附",
      detail: priceVsGamma,
      tone: gex?.net_gex_direction === "negative" ? "down" : gex?.net_gex_direction === "positive" ? "up" : "slate",
    },
    {
      label: "近月影响区间",
      value: `${formatNumber(putWall?.strike)} - ${formatNumber(callWall?.strike)}`,
      detail: `下方 ${formatNumber(putWall?.strike)} 为保护/支撑，上方 ${formatNumber(callWall?.strike)} 为压制/突破观察`,
      tone: "info",
    },
    {
      label: "吸附与突破",
      value: `Pin ${formatNumber(pinWall?.strike)} / GZ ${formatNumber(gammaZero, 1)}`,
      detail: `若价格围绕 ${formatNumber(pinWall?.strike)} 震荡，优先看区间；偏离 ${formatNumber(gammaZero, 1)} 后波动结构会改变`,
      tone: "violet",
    },
    {
      label: "远月资金",
      value: farInsight ? `${farInsight.expiry} ${farInsight.dominance}` : "远月暂缺",
      detail: farInsight
        ? `看高观察 ${formatNumber(farInsight.callTop?.strike)}，看低保护 ${formatNumber(farInsight.putTop?.strike)}；${farInsight.direction}`
        : "当前 CME 快照未返回可用远月结构",
      tone: "warn",
    },
    {
      label: "风险确认",
      value: snapshot.data_source.status === "FINAL" ? "终版确认" : "预览待确认",
      detail: riskSignals.length ? riskSignals.join("；") : "未检测到高置信换月或尾部迁移信号",
      tone: snapshot.data_source.status === "FINAL" ? "up" : "warn",
    },
  ];
}

export function CMEOptionsOverviewGrid({ snapshot, wallScores }: CMEOptionsOverviewGridProps) {
  const analysis = snapshot.analysis;
  const primarySummary = analysis?.synthesis?.summary || analysis?.cme_options_agent?.summary || "当前未返回后端解释摘要。";
  const nextRisk = translateEvidence(analysis?.pending_reviews[0]?.reason
    || analysis?.synthesis?.risk_points[0]
    || analysis?.cme_options_agent?.risk_points[0]
    || "暂无额外风险提示。");
  const levelCards = buildLevelCards(snapshot, wallScores);
  const valueRows = buildValueRows(snapshot, wallScores);
  const expiries = expiryOrder(snapshot);
  const nearInsight = buildExpiryInsight(snapshot, expiries[0]);
  const farInsight = buildExpiryInsight(snapshot, expiries[1]);
  const analysisRange = buildRange(snapshot);
  const reportHighlights = buildCMEReportHighlights(snapshot, nearInsight, farInsight);
  const reportBasis = buildCMEReportBasis(snapshot);
  const analystReadout = buildAnalystReadout(snapshot, wallScores, nearInsight, farInsight);
  const boardPanel = {
    border: "1px solid var(--border-faint)",
    borderRadius: "var(--radius-lg)",
    background: "linear-gradient(180deg, var(--bg-panel), var(--bg-card-inner))",
  };
  const rowDivider = "1px solid var(--border-faint)";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,360px),1fr))", gap: 10, alignItems: "start" }}>
      <CMEOptionsSurface title="期权结构总览" bodyStyle={{ display: "grid", gap: 10, background: "var(--bg-card-inner)" }}>
        <div style={boardPanel}>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(190px,0.9fr) repeat(3,minmax(120px,1fr))", gap: 0 }}>
            <div style={{ padding: "12px 14px", borderRight: rowDivider }}>
              <div style={{ fontSize: 9, color: CME_META_TEXT, fontWeight: 700 }}>近月影响价格区间</div>
              <div className="fa-num" style={{ marginTop: 7, fontSize: 22, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 850 }}>
                {formatRange(analysisRange.min, analysisRange.max)}
              </div>
              <div style={{ marginTop: 6, fontSize: 10, color: "var(--fg-5)" }}>区间口径：{analysisRange.source}</div>
            </div>
            <div style={{ padding: "12px 14px", borderRight: rowDivider }}>
              <div style={{ fontSize: 9, color: "var(--down)", fontWeight: 700 }}>看涨压力</div>
              <div className="fa-num" style={{ marginTop: 7, fontSize: 17, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 800 }}>{formatGex(nearInsight?.callGex)}</div>
              <div style={{ marginTop: 5, fontSize: 10, color: "var(--fg-4)" }}>核心点位 {formatNumber(nearInsight?.callTop?.strike)}</div>
            </div>
            <div style={{ padding: "12px 14px", borderRight: rowDivider }}>
              <div style={{ fontSize: 9, color: "var(--up)", fontWeight: 700 }}>看跌支撑</div>
              <div className="fa-num" style={{ marginTop: 7, fontSize: 17, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 800 }}>{formatGex(nearInsight?.putGex)}</div>
              <div style={{ marginTop: 5, fontSize: 10, color: "var(--fg-4)" }}>核心点位 {formatNumber(nearInsight?.putTop?.strike)}</div>
            </div>
            <div style={{ padding: "12px 14px" }}>
              <div style={{ fontSize: 9, color: CME_META_TEXT, fontWeight: 700 }}>近月判断 · {nearInsight?.expiry ?? "—"}</div>
              <div style={{ marginTop: 7, fontSize: 12, color: "var(--fg-2)", fontWeight: 750 }}>{nearInsight?.dominance ?? "暂无近月分布"}</div>
              <div style={{ marginTop: 5, fontSize: 10, color: "var(--fg-4)", lineHeight: 1.45 }}>{nearInsight?.direction ?? "当前快照未返回近月伽马分布。"}</div>
            </div>
          </div>

          <div style={{ borderTop: rowDivider, padding: "11px 14px" }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
              <div style={{ fontSize: 9, color: CME_META_TEXT, fontWeight: 700 }}>远月资金押注</div>
              <div style={{ fontSize: 10, color: "var(--fg-4)" }}>{farInsight?.expiry ?? "无远月数据"}</div>
            </div>
            {farInsight ? (
              <>
                <div style={{ marginTop: 9, display: "grid", gridTemplateColumns: "minmax(150px,1.1fr) repeat(2,minmax(110px,0.75fr))", gap: 0, border: rowDivider, borderRadius: "var(--radius-md)", overflow: "hidden", background: "var(--bg-card)" }}>
                  <div style={{ padding: "9px 11px", borderRight: rowDivider }}>
                    <div style={{ fontSize: 9, color: CME_META_TEXT }}>资金倾向</div>
                    <div style={{ marginTop: 5, fontSize: 12, color: "var(--fg-2)", fontWeight: 750 }}>{farInsight.dominance}</div>
                    <div style={{ marginTop: 4, fontSize: 10, color: "var(--fg-4)" }}>净伽马 {formatGex(farInsight.netGex)} / 总量 {formatGex(farInsight.totalGex)}</div>
                  </div>
                  <div style={{ padding: "9px 11px", borderRight: rowDivider }}>
                    <div style={{ fontSize: 9, color: "var(--down)" }}>看高观察</div>
                    <div className="fa-num" style={{ marginTop: 5, fontSize: 16, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 800 }}>{formatNumber(farInsight.callTop?.strike)}</div>
                    <div style={{ marginTop: 4, fontSize: 10, color: "var(--fg-4)" }}>{formatGex(farInsight.callTop?.value)}</div>
                  </div>
                  <div style={{ padding: "9px 11px" }}>
                    <div style={{ fontSize: 9, color: "var(--up)" }}>看低保护</div>
                    <div className="fa-num" style={{ marginTop: 5, fontSize: 16, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 800 }}>{formatNumber(farInsight.putTop?.strike)}</div>
                    <div style={{ marginTop: 4, fontSize: 10, color: "var(--fg-4)" }}>{formatGex(farInsight.putTop?.value)}</div>
                  </div>
                </div>
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {farInsight.totalTop.map((item) => (
                    <span key={`${farInsight.expiry}-${item.strike}`} style={{ border: "1px solid var(--border-faint)", borderRadius: 999, background: "var(--bg-card)", padding: "3px 8px", fontSize: 10, color: "var(--fg-3)" }}>
                      {formatNumber(item.strike)} / {formatGex(item.value)}
                    </span>
                  ))}
                </div>
                {farInsight.skewNote ? <div style={{ marginTop: 8, fontSize: 10, color: "var(--fg-4)", lineHeight: 1.5 }}>{farInsight.skewNote}</div> : null}
              </>
            ) : (
              <div style={{ marginTop: 8, fontSize: 10, color: "var(--fg-5)" }}>当前快照未返回远月伽马分布。</div>
            )}
          </div>
        </div>

        <div style={boardPanel}>
          <div style={{ padding: "9px 12px", borderBottom: rowDivider, fontSize: 9, color: CME_META_TEXT, fontWeight: 700 }}>关键价位速查</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))" }}>
            {levelCards.map((level, index) => {
              const tone = toneStyle(level.tone);
              return (
                <div key={level.label} style={{ padding: "9px 12px", borderRight: index % 3 === 2 ? "none" : rowDivider, borderBottom: index < 3 ? rowDivider : "none", minHeight: 78 }}>
                  <div style={{ fontSize: 9, color: tone.text, fontWeight: 700 }}>{level.label}</div>
                  <div className="fa-num" style={{ marginTop: 6, fontSize: 17, fontWeight: 800, color: "var(--fg-1)", fontFamily: "var(--font-mono)" }}>{level.value}</div>
                  <div style={{ marginTop: 4, fontSize: 10, color: "var(--fg-4)", lineHeight: 1.45 }}>{level.detail}</div>
                </div>
              );
            })}
          </div>
        </div>

        <div style={{ ...boardPanel, padding: "10px 12px" }}>
          <div style={{ fontSize: 9, color: CME_META_TEXT, fontWeight: 700 }}>后端解释摘要</div>
          <div style={{ marginTop: 8, fontSize: 11, color: "var(--fg-3)", lineHeight: 1.7 }}>{primarySummary}</div>
        </div>

        <div style={boardPanel}>
          <div style={{ padding: "9px 12px", borderBottom: rowDivider, fontSize: 9, color: CME_META_TEXT, fontWeight: 700 }}>分析师读盘</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
            {analystReadout.map((row, index) => {
              const tone = toneStyle(row.tone);
              return (
                <div key={row.label} style={{ padding: "9px 12px", borderRight: index % 2 === 1 ? "none" : rowDivider, borderBottom: index < analystReadout.length - 1 ? rowDivider : "none", minHeight: 74 }}>
                  <div style={{ fontSize: 9, color: tone.text, fontWeight: 700 }}>{row.label}</div>
                  <div style={{ marginTop: 6, fontSize: 12, color: "var(--fg-2)", fontWeight: 760 }}>{row.value}</div>
                  <div style={{ marginTop: 4, fontSize: 10, color: "var(--fg-4)", lineHeight: 1.45 }}>{row.detail}</div>
                </div>
              );
            })}
          </div>
        </div>
      </CMEOptionsSurface>
      <CMEOptionsSurface title="价值数据 / 风险与溯源" bodyStyle={{ display: "grid", gap: 10, background: "var(--bg-card-inner)" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {analysis?.fact_review_status ? (
            <FAStatusPill tone={reviewStatusTone(analysis.fact_review_status)}>
              {reviewStatusLabel(analysis.fact_review_status)}
            </FAStatusPill>
          ) : null}
          <FAStatusPill tone={reportStatusTone(snapshot.data_source.status)}>{reportStatusLabel(snapshot.data_source.status)}</FAStatusPill>
          <FAStatusPill tone="neutral">{productLabel(snapshot.data_source.product)}</FAStatusPill>
        </div>
        <div style={{ ...boardPanel, padding: "9px 10px" }}>
          <div style={{ fontSize: 9, color: CME_META_TEXT, marginBottom: 5 }}>下一风险提示</div>
          <div style={{ fontSize: 11, color: "var(--fg-3)", lineHeight: 1.6 }}>{nextRisk}</div>
        </div>
        <div style={boardPanel}>
          <div style={{ padding: "9px 10px", borderBottom: rowDivider, fontSize: 9, color: CME_META_TEXT, fontWeight: 700 }}>CME 报告重点提取</div>
          <div style={{ padding: "8px 10px", borderBottom: rowDivider, background: "rgba(148,163,184,0.06)" }}>
            <div style={{ fontSize: 10, color: "var(--fg-3)", lineHeight: 1.45, fontWeight: 700 }}>{reportBasis.summary}</div>
            <div style={{ marginTop: 3, fontSize: 10, color: "var(--fg-5)", lineHeight: 1.45 }}>{reportBasis.detail}</div>
          </div>
          {reportHighlights.map((row) => {
            const tone = toneStyle(row.tone);
            return (
              <div key={row.label} style={{ padding: "8px 10px", borderBottom: row.label === reportHighlights[reportHighlights.length - 1]?.label ? "none" : rowDivider }}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
                  <span style={{ fontSize: 9, color: tone.text, flexShrink: 0, fontWeight: 700 }}>{row.label}</span>
                  <span className="fa-num" style={{ fontSize: 11, color: "var(--fg-2)", fontFamily: "var(--font-mono)", fontWeight: 740, textAlign: "right" }}>{row.value}</span>
                </div>
                <div style={{ marginTop: 4, fontSize: 10, color: "var(--fg-5)", lineHeight: 1.45 }}>{row.detail}</div>
              </div>
            );
          })}
        </div>
        <div style={boardPanel}>
          {valueRows.map((row) => (
            <div key={row.label} style={{ padding: "8px 10px", borderBottom: row.label === valueRows[valueRows.length - 1]?.label ? "none" : rowDivider }}>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
                <span style={{ fontSize: 9, color: CME_META_TEXT, flexShrink: 0 }}>{row.label}</span>
                <span className="fa-num" style={{ fontSize: 11, color: "var(--fg-2)", fontFamily: "var(--font-mono)", fontWeight: 700, textAlign: "right" }}>{row.value}</span>
              </div>
              <div style={{ marginTop: 4, fontSize: 10, color: "var(--fg-5)", lineHeight: 1.45 }}>{row.detail}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", border: rowDivider, borderRadius: "var(--radius-md)", overflow: "hidden", background: "var(--bg-panel)" }}>
          <div style={{ padding: "8px 10px", borderRight: rowDivider }}>
            <div style={{ fontSize: 9, color: CME_META_TEXT }}>来源引用</div>
            <div className="fa-num" style={{ marginTop: 4, fontSize: 14, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{snapshot.source_trace.length}</div>
          </div>
          <div style={{ padding: "8px 10px" }}>
            <div style={{ fontSize: 9, color: CME_META_TEXT }}>待复核</div>
            <div className="fa-num" style={{ marginTop: 4, fontSize: 14, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{analysis?.pending_review_count ?? 0}</div>
          </div>
        </div>
      </CMEOptionsSurface>
    </div>
  );
}
