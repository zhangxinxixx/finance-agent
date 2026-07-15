import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { CMEOptionsResponse } from "@/types/cme-options";
import { formatNumber, resolveDirectionalWall, toneStyle, translateEvidence } from "./cmeOptionsFormat";
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
      tone: "important",
    },
    {
      label: "防守底线",
      value: formatNumber(nearestSupport?.strike),
      detail: `距远期价 ${formatPercent(nearestSupport?.distance_pct)} / 评分 ${formatNumber(nearestSupport?.wall_score, 2)}`,
      tone: "important",
    },
    {
      label: "伽马零点",
      value: formatNumber(gex?.gamma_zero?.price, 1),
      detail: `${translateEvidence(gex?.gamma_zero?.method ?? "推导值")} / 聚合净伽马 ${formatNumber(gex?.net_gex)}`,
      tone: "important",
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
  const aggregateDirection = gex?.net_gex_direction ?? null;
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

  return (
    <div className="cme-options-overview-layout">
      <main className="cme-options-overview-main">
        <CMEOptionsSurface title="结构判断工作台" bodyStyle={{ display: "grid", gap: 10, background: "var(--bg-card-inner)" }}>
          <section className="cme-options-decision-board" aria-label="期权结构总览">
            <div className="cme-options-decision-cell cme-options-decision-cell--range">
              <span className="cme-options-mini-label">近月影响区间</span>
              <strong className="cme-options-range-value fa-num">
                {formatRange(analysisRange.min, analysisRange.max)}
              </strong>
              <span className="cme-options-cell-detail">区间口径：{analysisRange.source}</span>
            </div>

            <div className="cme-options-decision-cell">
              <span className="cme-options-mini-label cme-options-mini-label--down">看涨压力</span>
              <strong className="cme-options-decision-value fa-num">{formatGex(nearInsight?.callGex)}</strong>
              <span className="cme-options-cell-detail cme-options-cell-detail--important">核心点位 {formatNumber(nearInsight?.callTop?.strike)}</span>
            </div>

            <div className="cme-options-decision-cell">
              <span className="cme-options-mini-label cme-options-mini-label--up">看跌支撑</span>
              <strong className="cme-options-decision-value fa-num">{formatGex(nearInsight?.putGex)}</strong>
              <span className="cme-options-cell-detail cme-options-cell-detail--important">核心点位 {formatNumber(nearInsight?.putTop?.strike)}</span>
            </div>

            <div className="cme-options-decision-cell cme-options-decision-cell--judgement">
              <span className="cme-options-mini-label cme-options-mini-label--important">近月判断 · {nearInsight?.expiry ?? "—"}</span>
              <strong className="cme-options-decision-title">{nearInsight?.dominance ?? "暂无近月分布"}</strong>
              <span className="cme-options-cell-detail">{nearInsight?.direction ?? "当前快照未返回近月伽马分布。"}</span>
            </div>
          </section>

          <section className="cme-options-thesis-panel">
            <div className="cme-options-thesis-copy">
              <span className="cme-options-mini-label">后端综合判断</span>
              <p>{primarySummary}</p>
            </div>

            <div className="cme-options-far-panel">
              <div className="cme-options-section-heading">
                <span>远月资金押注</span>
                <strong>{farInsight ? `${farInsight.expiry} · ${farInsight.dominance}` : "无远月数据"}</strong>
              </div>
              {farInsight ? (
                <>
                  <div className="cme-options-far-grid">
                    <div className="cme-options-far-cell cme-options-far-cell--wide">
                      <span>资金倾向</span>
                      <strong>{farInsight.dominance}</strong>
                      <small>净伽马 {formatGex(farInsight.netGex)} / 总量 {formatGex(farInsight.totalGex)}</small>
                    </div>
                    <div className="cme-options-far-cell">
                      <span>看高观察</span>
                      <strong className="fa-num">{formatNumber(farInsight.callTop?.strike)}</strong>
                      <small>{formatGex(farInsight.callTop?.value)}</small>
                    </div>
                    <div className="cme-options-far-cell">
                      <span>看低保护</span>
                      <strong className="fa-num">{formatNumber(farInsight.putTop?.strike)}</strong>
                      <small>{formatGex(farInsight.putTop?.value)}</small>
                    </div>
                  </div>
                  <div className="cme-options-far-tags">
                    {farInsight.totalTop.map((item) => (
                      <span key={`${farInsight.expiry}-${item.strike}`}>
                        {formatNumber(item.strike)} / {formatGex(item.value)}
                      </span>
                    ))}
                  </div>
                  {farInsight.skewNote ? <p className="cme-options-muted-note">{farInsight.skewNote}</p> : null}
                </>
              ) : (
                <p className="cme-options-muted-note">当前快照未返回远月伽马分布。</p>
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
            <span className="cme-options-mini-label">下一风险提示</span>
            <p>{nextRisk}</p>
          </div>

          <div className="cme-options-rail-block">
            <span className="cme-options-mini-label">CME 报告基准</span>
            <strong>{reportBasis.summary}</strong>
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
              <span>来源引用</span>
              <strong className="fa-num">{snapshot.source_trace.length}</strong>
            </div>
            <div>
              <span>待复核</span>
              <strong className="fa-num">{analysis?.pending_review_count ?? 0}</strong>
            </div>
          </div>
        </CMEOptionsSurface>
      </aside>
    </div>
  );
}
