import type {
  GoldMainline,
  GoldNetBias,
  GoldPhase,
  GoldPricingLayer,
  GoldVerificationStatus,
  TransmissionPath,
} from "@/types/gold-mainlines";
import type { FAStatusTone } from "./FAStatusPill";
import type { SourceRef } from "@/types/common";

export interface GoldMainlineDisplayMeta {
  id: GoldMainline;
  label: string;
  shortLabel: string;
  pricingLayer: GoldPricingLayer;
  headline: string;
  description: string;
  evidenceTargets: string[];
  transmissionPaths: TransmissionPath[];
}

export const GOLD_MAINLINE_ORDER: GoldMainline[] = [
  "fed_policy_path",
  "real_rates_usd",
  "oil_prices",
  "geopolitical_war_risk",
  "etf_flows",
  "institutional_sentiment",
  "central_bank_gold",
  "china_asia_demand",
  "gold_technical_levels",
];

export const GOLD_PRICING_LAYER_LABELS: Record<GoldPricingLayer, string> = {
  rate_pricing: "利率定价",
  currency_pricing: "货币定价",
  risk_pricing: "风险定价",
  capital_pricing: "资金定价",
  regional_demand: "区域需求",
  pricing_center: "定价中枢",
  external_shock: "外部冲击",
  capital_confirmation: "资金验证",
  structural_support: "结构支撑",
  price_confirmation: "价格确认",
};

export const GOLD_MAINLINE_LABELS: Record<GoldMainline, string> = {
  fed_policy_path: "美联储路径",
  real_rates_usd: "实际利率/美元",
  oil_prices: "石油价格",
  geopolitical_war_risk: "地缘战争",
  etf_flows: "ETF资金流",
  institutional_sentiment: "COMEX/期权/机构",
  central_bank_gold: "央行买金/信用重估",
  china_asia_demand: "中国/亚洲需求",
  gold_technical_levels: "技术位/阶段",
};

export const GOLD_MAINLINE_META: Record<GoldMainline, GoldMainlineDisplayMeta> = {
  fed_policy_path: {
    id: "fed_policy_path",
    label: "美联储利率路径",
    shortLabel: "Fed 路径",
    pricingLayer: "pricing_center",
    headline: "政策利率预期是否改变黄金机会成本",
    description: "观察 FOMC、通胀、就业和利率预期如何影响名义利率与黄金持有成本。",
    evidenceTargets: ["FOMC/官员表态", "CPI/PCE/就业", "FedWatch/利率曲线", "2Y/10Y 美债"],
    transmissionPaths: ["inflation_to_real_rates"],
  },
  real_rates_usd: {
    id: "real_rates_usd",
    label: "实际利率与美元",
    shortLabel: "实际利率/美元",
    pricingLayer: "pricing_center",
    headline: "实际收益率与 DXY 是否形成同向压制",
    description: "黄金短线定价中枢，重点看实际利率、美元指数和美元购买力变化。",
    evidenceTargets: ["TIPS 实际收益率", "DXY", "通胀预期", "美债期限利差"],
    transmissionPaths: ["inflation_to_real_rates", "usd_pressure"],
  },
  oil_prices: {
    id: "oil_prices",
    label: "石油价格",
    shortLabel: "油价",
    pricingLayer: "external_shock",
    headline: "油价是地缘风险传向通胀和利率的桥",
    description: "油价上涨可能先带来避险，也可能通过通胀预期和鹰派利率反向压制黄金。",
    evidenceTargets: ["WTI/Brent", "能源供应事件", "通胀预期", "实际利率响应"],
    transmissionPaths: ["geopolitics_to_oil_to_rates"],
  },
  geopolitical_war_risk: {
    id: "geopolitical_war_risk",
    label: "地缘战争风险",
    shortLabel: "地缘战争",
    pricingLayer: "external_shock",
    headline: "战争风险是避险买盘与能源冲击的源头",
    description: "拆分避险利多和油价通胀利空，避免把战争事件简单等同于黄金上涨。",
    evidenceTargets: ["冲突升级/降级", "航运与能源风险", "避险资产反应", "油价联动"],
    transmissionPaths: ["geopolitics_to_oil_to_rates", "haven_bid"],
  },
  etf_flows: {
    id: "etf_flows",
    label: "ETF资金流",
    shortLabel: "ETF资金",
    pricingLayer: "capital_confirmation",
    headline: "资金是否真正进入黄金资产",
    description: "用全球、北美和亚洲 ETF 流入/流出验证宏观叙事是否转化为真实配置买盘。",
    evidenceTargets: ["全球黄金 ETF", "北美 ETF", "亚洲 ETF", "资金流入/流出"],
    transmissionPaths: ["capital_confirmation"],
  },
  institutional_sentiment: {
    id: "institutional_sentiment",
    label: "COMEX / 期权 / 机构情绪",
    shortLabel: "COMEX/期权",
    pricingLayer: "capital_confirmation",
    headline: "拥挤度和短线结构决定反弹质量",
    description: "COT、COMEX 净多、期权 Call/Put、波动率和机构目标价用于判断短线风险。",
    evidenceTargets: ["COT/COMEX 净多", "Call/Put OI", "期权偏度", "机构目标价"],
    transmissionPaths: ["capital_confirmation"],
  },
  central_bank_gold: {
    id: "central_bank_gold",
    label: "央行买金与货币信用重估",
    shortLabel: "央行买金",
    pricingLayer: "structural_support",
    headline: "储备资产再配置提供长期底层买盘",
    description: "央行买金是慢变量，解释长期底部支撑和美元信用重估，不用于日内追价。",
    evidenceTargets: ["官方储备数据", "WGC/IMF", "美元信用事件", "美债财政风险"],
    transmissionPaths: ["reserve_reallocation"],
  },
  china_asia_demand: {
    id: "china_asia_demand",
    label: "中国与亚洲需求",
    shortLabel: "亚洲需求",
    pricingLayer: "structural_support",
    headline: "人民币黄金和亚洲实物买盘是否形成区域支撑",
    description: "关注上海金溢价、人民币汇率、中国 ETF 与印度实物需求。",
    evidenceTargets: ["上海金溢价", "人民币汇率", "中国 ETF", "印度实物需求"],
    transmissionPaths: ["asia_demand"],
  },
  gold_technical_levels: {
    id: "gold_technical_levels",
    label: "黄金关键技术位与阶段判断",
    shortLabel: "技术位",
    pricingLayer: "price_confirmation",
    headline: "价格结构验证宏观叙事是否被市场接受",
    description: "3900 / 4000 / 4100-4120 / 4300 用于判断趋势恢复、弱修复或回调升级。",
    evidenceTargets: ["3900 风险线", "4000 多空分水岭", "4100-4120 修复确认", "4300 趋势恢复确认"],
    transmissionPaths: ["technical_confirmation"],
  },
};

export const TRANSMISSION_PATH_LABELS: Record<TransmissionPath, string> = {
  inflation_to_real_rates: "通胀->实际利率",
  usd_pressure: "美元链",
  geopolitics_to_oil_to_rates: "地缘->油价->利率",
  haven_bid: "避险买盘",
  capital_confirmation: "资金确认",
  reserve_reallocation: "储备再配置",
  asia_demand: "亚洲需求",
  technical_confirmation: "技术确认",
};

export const GOLD_NET_BIAS_LABELS: Record<GoldNetBias, string> = {
  strong_bullish: "强利多",
  bullish: "利多",
  neutral_bullish: "中性偏多",
  neutral: "中性",
  neutral_bearish: "中性偏空",
  bearish: "利空",
  strong_bearish: "强利空",
  mixed: "多空混合",
  mixed_bullish: "混合偏多",
  mixed_bearish: "混合偏空",
  unknown: "未知",
};

export const GOLD_PHASE_LABELS: Record<GoldPhase, string> = {
  strong_uptrend: "强趋势",
  high_level_range: "高位震荡",
  weak_repair_watch: "弱修复观察",
  correction_escalation: "回调升级",
  trend_failure: "趋势失效",
  unknown: "未知",
};

export const GOLD_VERIFICATION_STATUS_LABELS: Record<GoldVerificationStatus, string> = {
  confirmed: "已确认",
  pending: "待验证",
  failed: "验证失败",
  unavailable: "不可用",
  not_required: "无需验证",
  official_confirmed: "官方确认",
  multi_source: "多源确认",
  report_derived: "报告推导",
  single_source: "单一来源",
  unverified: "未验证",
  not_applicable: "不适用",
};

export const GOLD_DRIVER_LABELS: Record<string, string> = {
  higher_for_longer_rate_pressure: "高利率维持压力",
  oil_inflation_rate_pressure: "油价通胀压力",
  usd_strength_pressure: "美元强势压力",
  rate_cut_expectation_support: "降息预期支撑",
  safe_haven_bid: "避险买盘",
  usd_weakness_support: "美元走弱支撑",
  multi_source_confirmation_needed: "多源确认",
  oil_price_reaction_needed: "油价反应",
  real_rate_response_needed: "实际利率响应",
  flow_data_confirmation_needed: "资金流确认",
  price_level_confirmation_needed: "技术位确认",
  official_release_needed: "官方数据确认",
  official_reserve_data_needed: "央行储备数据",
  positioning_confirmation_needed: "持仓确认",
  macro_data_confirmation_needed: "宏观数据确认",
  fx_market_confirmation_needed: "外汇市场确认",
  news_sources: "新闻来源",
  oil_price: "油价数据",
  real_rates: "实际利率",
  etf_comex_flows: "ETF/COMEX 资金流",
  etf_flows: "ETF资金流",
  regional_etf_flows: "区域ETF资金流",
  xauusd_price: "XAUUSD 价格",
  market_candles: "行情K线",
  technical_levels: "技术位规则",
  official_data: "官方数据",
  fed_funds_futures: "利率期货",
  treasury_yields: "美债收益率",
  central_bank_reserves: "央行储备数据",
  wgc_data: "WGC数据",
  imf_reserves: "IMF储备数据",
  pboc_gold_holdings: "中国央行黄金储备",
  positioning_data: "持仓数据",
  cme_options: "CME期权",
  cot_report: "COT报告",
  institutional_forecasts: "机构预测",
  macro_data: "宏观数据",
  fx_market: "外汇市场",
  dxy: "DXY",
  inflation_expectations: "通胀预期",
  energy_inventory: "能源库存",
  vix: "VIX",
  equity_reaction: "股市反应",
  shanghai_gold_premium: "上海金溢价",
  china_gold_etf: "中国黄金ETF",
  asia_physical_demand: "亚洲实物需求",
  india_physical_demand: "印度实物需求",
};

export function formatGoldMainlineLabel(value: GoldMainline | string | null | undefined): string {
  if (!value) return "未归因";
  return GOLD_MAINLINE_LABELS[value as GoldMainline] ?? value;
}

export function normalizeGoldMainlineId(value: GoldMainline | string | null | undefined): GoldMainline | null {
  return GOLD_MAINLINE_ORDER.includes(value as GoldMainline) ? value as GoldMainline : null;
}

export function formatTransmissionPathLabel(value: TransmissionPath | string | null | undefined): string {
  if (!value) return "未返回";
  return TRANSMISSION_PATH_LABELS[value as TransmissionPath] ?? value;
}

export function formatGoldPricingLayerLabel(value: GoldPricingLayer | string | null | undefined): string {
  if (!value) return "未分层";
  return GOLD_PRICING_LAYER_LABELS[value as GoldPricingLayer] ?? value;
}

export function formatGoldNetBiasLabel(value: GoldNetBias | string | null | undefined): string {
  if (!value) return "未知";
  return GOLD_NET_BIAS_LABELS[value as GoldNetBias] ?? value;
}

export function formatGoldPhaseLabel(value: GoldPhase | string | null | undefined): string {
  if (!value) return "未知";
  return GOLD_PHASE_LABELS[value as GoldPhase] ?? value;
}

export function formatGoldDriverLabel(value: string | null | undefined): string {
  if (!value) return "待确认";
  return GOLD_DRIVER_LABELS[value] ?? value.replace(/_/g, " ");
}

export function formatGoldNarrativeText(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/\bstrong_bullish\b/g, "强利多")
    .replace(/\bneutral_bullish\b/g, "中性偏多")
    .replace(/\bstrong_bearish\b/g, "强利空")
    .replace(/\bneutral_bearish\b/g, "中性偏空")
    .replace(/\bbullish\b/g, "利多")
    .replace(/\bbearish\b/g, "利空")
    .replace(/\bneutral\b/g, "中性")
    .replace(/\bmixed\b/g, "多空混合")
    .replace(/\bunknown\b/g, "未知");
}

export function formatGoldVerificationReasonLabel(value: string | null | undefined): string {
  if (!value) return "待确认";
  return GOLD_DRIVER_LABELS[value] ?? value.replace(/_/g, " ");
}

export function formatGoldSourceRefLabel(ref: SourceRef | Record<string, unknown> | null | undefined, fallback = "溯源"): string {
  if (!ref) return fallback;
  const candidates = [
    ref.label,
    ref.source_ref,
    "title" in ref ? ref.title : undefined,
    "source" in ref ? ref.source : undefined,
    ref.provider,
    ref.snapshot_id,
    ref.artifact_path,
    "path" in ref ? ref.path : undefined,
    ref.source_url,
  ];
  const value = candidates.find((item): item is string => typeof item === "string" && item.trim().length > 0);
  if (!value) return fallback;
  const normalized = value.replace(/^event:/, "");
  const lower = normalized.toLowerCase();
  const exact: Record<string, string> = {
    jin10_external: "金十外部报告",
    jin10_report_events: "金十报告事件",
    macro_watchlist: "宏观观察清单",
    gold_fund_flow: "黄金资金流",
    gold_market_narrative: "黄金市场叙事",
  };
  if (exact[lower]) return exact[lower];
  if (lower.startsWith("news:jin10_report_events")) return "金十报告事件";
  if (lower.startsWith("macro_watchlist:")) return "宏观观察清单";
  if (lower.startsWith("gold_fund_flow:")) return "黄金资金流";
  if (lower.startsWith("gold_market_narrative:")) return "黄金市场叙事";
  return normalized;
}

export function formatGoldEventRefLabel(value: string | null | undefined): string {
  if (!value) return "事件";
  return formatGoldSourceRefLabel({ source_ref: value }, value.replace(/^event:/, ""));
}

export function formatGoldVerificationStatusLabel(value: GoldVerificationStatus | string | null | undefined): string {
  if (!value) return "未知";
  return GOLD_VERIFICATION_STATUS_LABELS[value] ?? value.replace(/_/g, " ");
}

export function goldNetBiasTone(value: GoldNetBias | string | null | undefined): FAStatusTone {
  if (value === "strong_bullish" || value === "bullish" || value === "neutral_bullish" || value === "mixed_bullish") return "up";
  if (value === "strong_bearish" || value === "bearish" || value === "neutral_bearish" || value === "mixed_bearish") return "down";
  if (value === "mixed") return "warn";
  if (value === "unknown") return "dim";
  return "neutral";
}

export function goldConflictTone(value: string | null | undefined): FAStatusTone {
  if (value === "aligned") return "up";
  if (value === "conflicted" || value === "mixed") return "warn";
  return "dim";
}

export function formatGoldConflictStatusLabel(value: string | null | undefined): string {
  if (value === "aligned") return "同向";
  if (value === "conflicted") return "冲突";
  if (value === "mixed") return "多空混合";
  if (value === "unknown") return "未知";
  return value || "未知";
}

export function goldVerificationStatusTone(value: GoldVerificationStatus | string | null | undefined): FAStatusTone {
  if (value === "official_confirmed" || value === "multi_source" || value === "confirmed") return "up";
  if (value === "report_derived" || value === "single_source" || value === "pending") return "warn";
  if (value === "unverified" || value === "unavailable" || value === "failed") return "down";
  if (value === "not_applicable" || value === "unknown") return "dim";
  return "neutral";
}
