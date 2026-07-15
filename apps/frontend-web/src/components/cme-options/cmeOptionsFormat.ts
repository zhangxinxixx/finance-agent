import type { CMEOptionsDecisionResponse, CMEOptionsResponse } from "@/types/cme-options";

export const CME_META_TEXT = "var(--fa-text-label)";

export const CME_TONE = {
  up: { text: "var(--up)", bg: "var(--up-soft)", border: "var(--up-border)" },
  down: { text: "var(--down)", bg: "var(--down-soft)", border: "var(--down-border)" },
  warn: { text: "var(--warn)", bg: "var(--warn-soft)", border: "var(--warn-border)" },
  info: { text: "var(--info)", bg: "var(--info-soft)", border: "var(--info-border)" },
  important: { text: "var(--fa-important)", bg: "var(--fa-important-soft)", border: "var(--fa-important-border)" },
  violet: { text: "var(--fa-important)", bg: "var(--fa-important-soft)", border: "var(--fa-important-border)" },
  slate: { text: "var(--fg-3)", bg: "var(--bg-panel)", border: "var(--border-faint)" },
} as const;

export function toneStyle(kind: string) {
  return CME_TONE[kind as keyof typeof CME_TONE] || CME_TONE.slate;
}

export function formatNumber(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatCompactNumber(
  value: number | null | undefined,
  unit = "",
  digits = 2,
  signed = false,
) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const absolute = Math.abs(value);
  const scale = absolute >= 100_000_000
    ? { divisor: 100_000_000, suffix: "亿" }
    : absolute >= 10_000
      ? { divisor: 10_000, suffix: "万" }
      : { divisor: 1, suffix: "" };
  const formatted = (value / scale.divisor).toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: scale.divisor === 1 ? 0 : digits,
  });
  return `${signed && value > 0 ? "+" : ""}${formatted}${scale.suffix}${unit}`;
}

export function summarizeDecision(decision: CMEOptionsDecisionResponse | null | undefined) {
  if (!decision) return null;
  if (decision.intraday_strategy.status === "available" && decision.intraday_strategy.summary) {
    return translateDecisionText(decision.intraday_strategy.summary);
  }

  const resolvedRegime = decision.gamma_summary.regime === "negative_gamma" || decision.gamma_summary.regime === "positive_gamma" || decision.gamma_summary.regime === "flip_zone"
    ? decision.gamma_summary.regime
    : decision.gamma_summary.net_gex === null
      ? "unavailable"
      : decision.gamma_summary.net_gex < 0
        ? "negative_gamma"
        : decision.gamma_summary.net_gex > 0
          ? "positive_gamma"
          : "flip_zone";
  const regime = resolvedRegime === "negative_gamma"
    ? "负伽马环境"
    : resolvedRegime === "positive_gamma"
      ? "正伽马环境"
      : resolvedRegime === "flip_zone"
        ? "伽马翻转区"
        : "伽马环境未确认";
  const parts = [
    `${regime}，净伽马 ${formatCompactNumber(decision.gamma_summary.net_gex)}`,
    decision.gamma_summary.gamma_zero === null
      ? null
      : `伽马零点 ${formatNumber(decision.gamma_summary.gamma_zero, 1)} 点`,
    decision.swing_strategy.status === "available"
      ? `中期持仓变化：看涨 ${formatCompactNumber(decision.swing_strategy.call_oi_change, "张", 2, true)}，看跌 ${formatCompactNumber(decision.swing_strategy.put_oi_change, "张", 2, true)}`
      : null,
    decision.intraday_strategy.status === "unavailable"
      ? `日内策略因${translateDecisionText(decision.intraday_strategy.reason ?? "实时条件不足")}暂不可用`
      : null,
  ].filter((part): part is string => Boolean(part));
  return `${parts.join("；")}。`;
}

export function topWall(wallScores: CMEOptionsResponse["wall_scores"], side: "CALL" | "PUT") {
  return [...wallScores].filter((wall) => wall.side === side).sort((a, b) => b.wall_score - a.wall_score)[0] ?? null;
}

export interface DirectionalWallDisplay {
  strike: number;
  wallScore: number | null;
  oi: number | null;
  deltaOi: number | null;
  pnt: number | null;
  distancePct: number | null;
  gexValue: number | null;
  expiry: string | null;
  source: "wall_scores" | "support_resistance" | "gex";
}

function wallTypeMatches(side: "CALL" | "PUT", wallType: string | null | undefined) {
  if (!wallType) return false;
  return side === "CALL"
    ? /call wall|resistance wall/i.test(wallType)
    : /put wall|support wall/i.test(wallType);
}

function nearestDirectionalLevel(
  levels: CMEOptionsResponse["support_resistance"]["support" | "resistance"],
  currentPrice: number | null | undefined,
) {
  if (!levels.length) return null;
  if (currentPrice === null || currentPrice === undefined || Number.isNaN(currentPrice)) {
    return [...levels].sort((a, b) => b.wall_score - a.wall_score)[0] ?? null;
  }
  return [...levels].sort((a, b) => Math.abs(a.strike - currentPrice) - Math.abs(b.strike - currentPrice))[0] ?? null;
}

export function resolveDirectionalWall(
  snapshot: CMEOptionsResponse,
  wallScores: CMEOptionsResponse["wall_scores"],
  side: "CALL" | "PUT",
): DirectionalWallDisplay | null {
  const directWall = [...wallScores]
    .filter((wall) => wall.side === side || wallTypeMatches(side, wall.wall_type))
    .sort((a, b) => {
      if (b.wall_score !== a.wall_score) return b.wall_score - a.wall_score;
      return b.oi - a.oi;
    })[0];

  if (directWall) {
    return {
      strike: directWall.strike,
      wallScore: directWall.wall_score,
      oi: directWall.oi,
      deltaOi: directWall.delta_oi,
      pnt: directWall.pnt,
      distancePct: null,
      gexValue: null,
      expiry: null,
      source: "wall_scores",
    };
  }

  const currentPrice = snapshot.parameters?.f_value ?? snapshot.gex?.netgex_aggregate?.gamma_zero?.price ?? null;
  const supportResistanceLevels = side === "CALL"
    ? snapshot.support_resistance?.resistance ?? []
    : snapshot.support_resistance?.support ?? [];
  const directionalLevel = nearestDirectionalLevel(supportResistanceLevels, currentPrice);

  if (directionalLevel) {
    return {
      strike: directionalLevel.strike,
      wallScore: directionalLevel.wall_score,
      oi: null,
      deltaOi: null,
      pnt: null,
      distancePct: directionalLevel.distance_pct,
      gexValue: null,
      expiry: null,
      source: "support_resistance",
    };
  }

  const byExpiry = snapshot.gex?.by_expiry ?? {};
  const expiryOrder = snapshot.data_source?.expiries?.length
    ? snapshot.data_source.expiries
    : Object.keys(byExpiry);

  for (const expiry of expiryOrder) {
    const gexTop = byExpiry[expiry]?.gex_top ?? [];
    if (!gexTop.length) continue;
    const best = [...gexTop].sort((a, b) => {
      const aValue = side === "CALL" ? a.call_gex : a.put_gex;
      const bValue = side === "CALL" ? b.call_gex : b.put_gex;
      return bValue - aValue;
    })[0];
    if (!best) continue;
    const gexValue = side === "CALL" ? best.call_gex : best.put_gex;
    if (!gexValue) continue;
    return {
      strike: best.strike,
      wallScore: null,
      oi: null,
      deltaOi: null,
      pnt: null,
      distancePct: null,
      gexValue,
      expiry,
      source: "gex",
    };
  }

  return null;
}

export function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length <= 18 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}

export function translateIntent(text: string | null | undefined): string {
  if (!text) return "—";
  const normalized = text.trim().replace(/^i(?=\d_)/i, "l").toLowerCase();
  const map: Record<string, string> = {
    "neutral-bullish": "中性偏多",
    "neutral-bearish": "中性偏空",
    bullish: "偏多",
    bearish: "偏空",
    neutral: "中性",
    "Pin Compression": "Pin 压缩",
    "Gamma Squeeze": "Gamma 挤压",
    I1_defensive: "防守结构",
    i1_defensive: "防守结构",
    l1_defensive: "防守结构",
    I2_structured_rebalance: "结构再平衡",
    i2_structured_rebalance: "结构再平衡",
    l2_structured_rebalance: "结构再平衡",
    I3_trap: "诱多/诱空",
    i3_trap: "诱多/诱空",
    l3_trap: "诱多/诱空",
    I4_trend_launch: "趋势启动",
    i4_trend_launch: "趋势启动",
    l4_trend_launch: "趋势启动",
    l3_breakout_watch: "突破观察",
    i3_breakout_watch: "突破观察",
    l2_range_pressure: "区间压力",
    i2_range_pressure: "区间压力",
    l1_pin_balance: "吸附平衡",
    i1_pin_balance: "吸附平衡",
    trend_launch: "趋势启动",
    breakout_watch: "突破观察",
    range_pressure: "区间压力",
    pin_balance: "吸附平衡",
  };
  return map[text] ?? map[normalized] ?? text;
}

export function translateEvidence(text: string | null | undefined): string {
  if (!text) return "—";
  const labels: Record<string, string> = {
    call_oi: "看涨持仓",
    put_oi: "看跌持仓",
    call_change: "看涨变化",
    put_change: "看跌变化",
    call_wall: "看涨墙",
    put_wall: "看跌墙",
    net_gex: "净伽马",
    total_gex: "总伽马",
    gamma_zero: "伽马零点",
    expiry: "到期",
    pnt: "吸附值",
    delta_oi: "持仓变化",
    near: "近月",
    far: "远月",
    next: "次月",
  };
  let translated = text;
  Object.entries(labels).forEach(([from, to]) => {
    translated = translated.replace(new RegExp(`\\b${from}\\b`, "gi"), to);
  });
  translated = translated.replace(
    /CME options source status is PRELIM;?\s*treat conclusions as provisional\.?/gi,
    "CME 期权数据为 PRELIM，结论需等待 FINAL 确认。",
  );
  translated = translated.replace(/\bClaim\s+/gi, "断言 ");
  translated = translated.replace(/\bOptions intent\b/gi, "期权意图");
  translated = translated.replace(/\bTop wall score highlights active near\s+([0-9.,]+)\s+with score\s+([0-9.]+)\.?/gi, "最高墙位评分指向 $1，评分 $2。");
  translated = translated.replace(/\bNearest options support is\s+([0-9.,]+)\.?/gi, "最近期权支撑为 $1。");
  translated = translated.replace(/\bExpiration coverage:\s*/gi, "覆盖到期月份：");
  translated = translated.replace(/\bExpiration roll signals:\s*/gi, "换月信号：");
  translated = translated.replace(
    /Wall scores are missing,\s*so support\/resistance conviction is limited\.?/gi,
    "墙位评分缺失，支撑/阻力置信度受限。",
  );
  translated = translated.replace(/\bnear low-strike 看跌持仓 down\b/gi, "近端低行权价看跌持仓下降");
  translated = translated.replace(/\bnear low-strike put OI down\b/gi, "近端低行权价看跌持仓下降");
  translated = translated.replace(/\blow-strike\b/gi, "低行权价");
  translated = translated.replace(/\bdown\b/gi, "下降");
  translated = translated.replace(/\bup\b/gi, "上升");
  translated = translated.replace(/\blinear_interpolation\b/gi, "线性插值");
  translated = translated.replace(/\brows_missing_delta:\s*([0-9.,]+)\s*行/gi, "Delta 缺口 $1 行");
  translated = translated.replace(/\bProxy\b/gi, "代理");
  translated = translated.replace(/\bproxy_strikes\b/gi, "代理行权价");
  translated = translated.replace(/\bGamma Proxy\b/gi, "Gamma 代理");
  translated = translated.replace(/\bstrike\b/gi, "行权价");
  translated = translated.replace(/\bexpiry_date_estimated_from_delivery_month\b/gi, "到期日由交割月份估算");
  translated = translated.replace(/\bgrid_skipped_rows_without_iv\b/gi, "波动率网格已跳过缺 IV 行");
  translated = translated.replace(/\bput OI\b/gi, "看跌持仓");
  translated = translated.replace(/\bcall OI\b/gi, "看涨持仓");
  translated = translated.replace(/\bsupport\/resistance\b/gi, "支撑/阻力");
  translated = translated.replace(/\bconviction\b/gi, "置信度");
  translated = translated.replace(/\bmissing\b/gi, "缺失");
  translated = translated.replace(/\b(i1_defensive|l1_defensive)\b/gi, "防守结构");
  translated = translated.replace(/\b(i2_structured_rebalance|l2_structured_rebalance|structured_rebalance)\b/gi, "结构再平衡");
  translated = translated.replace(/\b(i3_trap|l3_trap)\b/gi, "诱多/诱空");
  translated = translated.replace(/\b(i4_trend_launch|l4_trend_launch|trend_launch)\b/gi, "趋势启动");
  translated = translated.replace(/\b(l4_trend_launch|trend_launch)\b/gi, "趋势启动");
  translated = translated.replace(/\b(l3_breakout_watch|breakout_watch)\b/gi, "突破观察");
  translated = translated.replace(/\b(l2_range_pressure|range_pressure)\b/gi, "区间压力");
  translated = translated.replace(/\b(l1_pin_balance|pin_balance)\b/gi, "吸附平衡");
  translated = translated.replace(/\s+/g, " ").trim();
  return translated || "—";
}

export function translateDecisionText(text: string | null | undefined): string {
  if (!text) return "—";

  const exactLabels: Record<string, string> = {
    aggregate_across_expiries: "跨到期月聚合",
    constructive: "建设性偏多",
    defensive_repair: "防守修复",
    near_month_outflow: "近月流出",
    far_month_inflow: "远月流入",
    PRELIM: "预览版",
    FINAL: "终版",
    active: "活跃",
    pin: "吸附",
    high: "高",
    medium: "中",
    low: "低",
    available: "可用",
    partial: "部分可用",
    unavailable: "不可用",
    success: "通过",
    needs_review: "需复核",
    failed: "失败",
    negative_gamma: "负伽马",
    positive_gamma: "正伽马",
    flip_zone: "伽马翻转区",
    flip_watch: "Gamma 翻转观察",
    watch: "观察",
    confirmed: "已确认",
    "weighted-average": "加权平均",
    "neutral-bullish": "中性偏多",
    "neutral-bearish": "中性偏空",
  };
  const normalized = text.trim();
  if (exactLabels[normalized]) return exactLabels[normalized];

  let translated = translateEvidence(normalized);
  const replacements: Array<[RegExp, string]> = [
    [/Model negative-gamma regime: wait for boundary confirmation because breaks may extend\.?/gi, "负伽马环境：先等待边界确认，突破后的波动可能延续。"],
    [/Model gamma-flip regime: wait for price acceptance outside the flip band\.?/gi, "Gamma 翻转区：等待价格在翻转带外形成有效接受。"],
    [/Model positive-gamma regime: prefer range reversion until price acceptance confirms a break\.?/gi, "正伽马环境：突破被有效接受前，优先按区间回归处理。"],
    [/primary support remains defended while price rotates toward (?:the )?Gamma Flip band/gi, "主支撑未失守，价格向伽马翻转带回归"],
    [/primary support\s+([0-9.,]+)\s+breaks with acceptance/gi, "主支撑 $1 被有效跌破"],
    [/subsequent CME trade dates retain or improve (?:Call OI|看涨持仓|看涨 OI) participation/gi, "后续 CME 交易日看涨 OI 参与度保持或增强"],
    [/price falls back below Gamma Flip\s+([0-9.,]+)/gi, "价格跌回伽马翻转位 $1 下方"],
    [/the reclaimed structure cannot hold on retest/gi, "收复后回踩无法守住"],
    [/Put protection and downside skew strengthen again/gi, "看跌保护与下行 Skew 重新增强"],
    [/broken support\s+([0-9.,]+)\s+is reclaimed and held/gi, "重新收复并守住已跌破支撑 $1"],
    [/live_p0 unavailable/gi, "实时价格不可用"],
    [/Do not fabricate an intraday decision without canonical live price and gamma regime\.?/gi, "缺少标准实时价格和伽马环境时，不生成日内决策。"],
    [/primary support rejects a break and price reclaims the level/gi, "主支撑拒绝跌破，价格重新站回该价位"],
    [/price accepts above the Gamma Flip band and confirms on retest/gi, "价格有效站上伽马翻转区间，并在回踩时确认"],
    [/price accepts below structural support\s+([0-9.,]+)/gi, "价格有效跌破结构支撑 $1"],
    [/Gamma regime deteriorates after entry/gi, "入场后伽马环境恶化"],
    [/primary support breaks with price acceptance and the retest fails/gi, "价格有效跌破主支撑，且回踩确认失败"],
    [/price remains below the Gamma Flip band while downside walls strengthen/gi, "价格持续位于伽马翻转区间下方，同时下方墙位增强"],
    [/price accepts above Gamma Flip\s+([0-9.,]+)/gi, "价格有效站上伽马翻转位 $1"],
    [/broken support is reclaimed and held/gi, "重新收复并守住已跌破的支撑"],
    [/price acceptance beyond Gamma Flip/gi, "价格有效突破伽马翻转位"],
    [/OI expansion persists across subsequent CME trade dates/gi, "后续 CME 交易日持仓继续扩张"],
    [/Static decision card only; this is not the #63 intraday state machine\.?/gi, "仅为静态决策卡，不代表 #63 日内状态机。"],
    [/Avoid chasing the first move through a two-sided volatility hub\.?/gi, "双向波动枢纽被首次穿越时，避免追价。"],
    [/This multi-day view uses observed OI history and does not infer dealer inventory\.?/gi, "该多日视图仅使用已观察的持仓历史，不推断做市商库存。"],
    [/Model GEX is a Black-76\/proxy estimate, not real dealer inventory\.?/gi, "模型 GEX 为 Black-76 代理估算，不代表真实做市商库存。"],
    [/25D Skew=/gi, "25Δ 偏度="],
    [/10D Tail Skew=/gi, "10Δ 尾部偏度="],
    [/\bPut 偏贵/gi, "看跌期权偏贵"],
    [/high-行权价/gi, "高行权价"],
    [/low-行权价/gi, "低行权价"],
    [/near_expiry_parity_fallback/gi, "近月平价回退"],
    [/使用 Gamma 代理 的 行权价:\s*/gi, "使用伽马代理的行权价："],
    [/wall_type=pin/gi, "墙位类型=吸附"],
    [/wall_type=active/gi, "墙位类型=活跃"],
    [/wall_score=/gi, "墙位评分="],
    [/\boi=/gi, "持仓="],
    [/call-dominant model exposure above report_p0/gi, "报告基准价上方以看涨模型敞口为主"],
    [/put-dominant model exposure below report_p0/gi, "报告基准价下方以看跌模型敞口为主"],
    [/two-sided GEX is large while net GEX is comparatively balanced/gi, "双向 GEX 均较大，净 GEX 相对均衡"],
    [/accepted break below\s+([0-9.,]+); negative-gamma conditions may amplify downside/gi, "价格有效跌破 $1，负伽马环境可能放大下行"],
    [/price accepts away from\s+([0-9.,]+)\s+and the pin wall weakens/gi, "价格有效远离 $1，且吸附墙减弱"],
    [/price accepts above\s+([0-9.,]+)\s+while the call wall weakens or rolls/gi, "价格有效站上 $1，同时看涨墙减弱或换月"],
    [/price accepts outside the\s+([0-9.,]+)\s+hub and two-sided activity fades/gi, "价格有效离开 $1 枢纽，且双向活跃度减弱"],
    [/strongest put-dominant wall below primary support/gi, "主支撑下方最强看跌墙"],
    [/tail-protection OI weakens or price accepts below\s+([0-9.,]+)/gi, "尾部保护持仓减弱，或价格有效跌破 $1"],
    [/price holds outside\s+([0-9.,]+)-([0-9.,]+)/gi, "价格持续位于 $1–$2 区间之外"],
    [/aggregate Gamma Zero price grid/gi, "聚合伽马零点价格网格"],
    [/method=线性插值/gi, "方法=线性插值"],
    [/rows_缺失_settlement/gi, "结算价缺口"],
  ];

  replacements.forEach(([pattern, replacement]) => {
    translated = translated.replace(pattern, replacement);
  });
  translated = translated.replace(/(?:net_gex|净伽马)=(-?[0-9.]+)/gi, (_, raw: string) => `净伽马=${formatCompactNumber(Number(raw))}`);
  translated = translated.replace(/持仓=(-?[0-9]+)/g, (_, raw: string) => `持仓=${formatNumber(Number(raw))} 张`);
  translated = translated.replace(/-?[0-9]+\.[0-9]{4,}/g, (raw) => formatNumber(Number(raw), 1));
  return translated.replace(/\s+/g, " ").trim() || "—";
}
