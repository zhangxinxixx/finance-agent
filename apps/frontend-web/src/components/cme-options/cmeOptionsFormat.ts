import type { CMEOptionsResponse } from "@/types/cme-options";

export const CME_META_TEXT = "#8c9cc8";

export const CME_TONE = {
  up: { text: "var(--up)", bg: "var(--up-soft)", border: "var(--up-border)" },
  down: { text: "var(--down)", bg: "var(--down-soft)", border: "var(--down-border)" },
  warn: { text: "var(--warn)", bg: "var(--warn-soft)", border: "var(--warn-border)" },
  info: { text: "var(--brand-hover)", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.24)" },
  important: { text: "var(--fa-important)", bg: "var(--fa-important-soft)", border: "var(--fa-important-border)" },
  violet: { text: "var(--fa-important)", bg: "var(--fa-important-soft)", border: "var(--fa-important-border)" },
  slate: { text: "var(--fg-3)", bg: "rgba(148,163,184,0.10)", border: "rgba(148,163,184,0.18)" },
} as const;

export function toneStyle(kind: string) {
  return CME_TONE[kind as keyof typeof CME_TONE] || CME_TONE.slate;
}

export function formatNumber(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
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
