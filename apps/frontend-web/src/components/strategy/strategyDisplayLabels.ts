export interface StrategyDisplayLabel {
  label: string;
  raw: string | null;
  known: boolean;
}

const STRATEGY_ASSET_LABELS: LabelMap = {
  XAUUSD: "现货黄金（XAUUSD）",
  BTCUSD: "比特币美元（BTCUSD）",
  EURUSD: "欧元美元（EURUSD）",
  DXY: "美元指数（DXY）",
  US10Y: "美国10年期国债收益率（US10Y）",
};

export function strategyAssetLabel(value: string | null | undefined): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return "未提供资产";
  return STRATEGY_ASSET_LABELS[raw.toUpperCase()] ?? "未解释资产（技术记录可核对）";
}

type LabelMap = Readonly<Record<string, string>>;

function displayEnum(value: string | null | undefined, labels: LabelMap, unknownLabel: string): StrategyDisplayLabel {
  const raw = typeof value === "string" && value.trim() ? value.trim() : null;
  if (!raw) return { label: "未提供", raw: null, known: false };
  const label = labels[raw] ?? labels[raw.toLowerCase()] ?? labels[raw.toUpperCase()];
  return label
    ? { label, raw, known: true }
    : { label: `${unknownLabel}（技术值见依据记录）`, raw, known: false };
}

export function enumRawTitle(value: StrategyDisplayLabel): string | undefined {
  return value.raw ? value.label : undefined;
}

const LIVE_MARKET_STATUS_LABELS: LabelMap = {
  available: "行情可用",
  live: "行情可用",
  partial: "行情部分可用",
  stale: "行情已过期",
  unavailable: "行情不可用",
  missing: "行情缺失",
};

export function liveMarketStatusLabel(value: string | null | undefined) {
  return displayEnum(value, LIVE_MARKET_STATUS_LABELS, "未知行情状态");
}

const DATA_STATUS_LABELS: LabelMap = {
  available: "可用",
  live: "可用",
  partial: "部分可用",
  verified: "已核验",
  prelim: "初步发布",
  preliminary: "初步发布",
  final: "已定稿",
  stale: "已过期",
  unavailable: "不可用",
  missing: "缺失",
  error: "错误",
};

export function dataStatusLabel(value: string | null | undefined) {
  return displayEnum(value, DATA_STATUS_LABELS, "未知数据状态");
}

const LIVE_STRATEGY_STATUS_LABELS: LabelMap = {
  waiting: "等待中",
  watching: "观察中",
  armed: "待确认",
  triggered: "已触发",
  suspended_data: "数据暂停",
};

export function liveStrategyStatusLabel(value: string | null | undefined) {
  return displayEnum(value, LIVE_STRATEGY_STATUS_LABELS, "未知策略状态");
}

const LIVE_SCENARIO_STATUS_LABELS: LabelMap = {
  watching: "观察中",
  armed: "待确认",
  ready: "条件已就绪",
  triggered: "已触发",
  blocked: "数据阻断",
  blocked_data: "数据阻断",
  blocked_rr: "收益风险阻断",
  unavailable: "不可用",
};

export function liveStrategyScenarioStatusLabel(value: string | null | undefined) {
  return displayEnum(value, LIVE_SCENARIO_STATUS_LABELS, "未知场景状态");
}

const STRATEGY_VALUE_LABELS: LabelMap = {
  available: "可用",
  unavailable: "不可用",
  partial: "部分可用",
  bullish: "看多",
  bearish: "看空",
  neutral: "中性",
  trend_tailwind: "趋势顺风",
  magnet_pin: "磁吸位",
  balanced: "均衡",
  consolidation: "盘整",
  breakout_accumulation: "突破蓄势",
  aggregate: "汇总范围",
  high: "较高",
  medium: "中等",
  med: "中等",
  low: "较低",
};

export function strategyValueLabel(value: string | null | undefined) {
  return displayEnum(value, STRATEGY_VALUE_LABELS, "未知业务值");
}

const STRATEGY_REASON_LABELS: LabelMap = {
  blocked_data: "数据完整性条件未通过",
  canonical_candle_stale: "现货黄金 5 分钟 K 线已过期",
  canonical_candle_window_gap: "现货黄金 5 分钟 K 线缺失、过期或时间戳不在允许窗口",
  quote_cache_stale: "实时报价缓存已过期",
  cme_unavailable: "芝商所期权结构数据不可用",
  cme_quality_not_final: "芝商所数据尚未达到最终质量状态",
  baseline_options_trade_date_mismatch: "期权基线日期与当前策略不一致",
  option_key_levels_coordinate_mismatch: "黄金期货结构位未验证基差，不与现货黄金价格计算距离",
  reference_level_unavailable: "参考关键位不可用",
  risk_reward_insufficient: "风险收益比参数不足",
  execution_intentionally_not_supported: "当前后端未提供执行条件支持",
  fresh_canonical_5m_required: "等待新的现货黄金 5 分钟 K 线",
  confirmed_price_event_required: "等待关键位价格事件确认",
  canonical_xauusd_5m_unavailable_or_stale: "等待新的现货黄金 5 分钟 K 线",
  no_directional_price_event: "尚未出现方向性关键位事件",
  gold_direction_authority_unavailable: "等待已核验的黄金日结方向",
  gold_daily_close_prebootstrap_hold: "尚无可用黄金日结基线（首个有效日结尚未建立）",
  gold_direction_authority_invalid: "黄金日结方向基线校验未通过",
  gold_strategy_status_not_directional: "黄金日结未给出可用方向",
};

const STRATEGY_SOURCE_LABELS: LabelMap = {
  cme: "芝商所",
  reuters_public_news: "路透快讯",
  fred: "美国经济数据库",
  google_news_rss: "Google 新闻聚合",
  treasury_rates: "美国财政部利率",
  gdelt_news: "GDELT 新闻",
  cftc: "美国商品期货委员会",
  fed_rss: "美联储公告订阅",
  bls_public_api_v2: "美国劳工统计局公开接口",
};

const STRATEGY_TIMESTAMP_LABELS: LabelMap = {
  canonical: "规范化行情观测时间",
  canonical_closed_at: "规范化 K 线收盘时间",
  quote_cache: "报价缓存时间",
};

const STRATEGY_EXACT_SENTENCE_LABELS: LabelMap = {
  "Gold macro context remains neutral_bearish with dominant mainline fed_policy_path.":
    "黄金宏观背景为中性偏空，主导主线为联邦政策路径。",
  "Gold macro priority regime is policy_event_cycle.": "黄金宏观优先状态为政策事件周期。",
  "Gold macro condition can raise conviction only after pending verification items are resolved.":
    "黄金宏观条件只有在待核验事项解决后才能提高判断信心。",
  "Gold macro readiness partial: 0/9 mainlines ready.": "黄金宏观就绪度为部分可用：9 条主线中 0 条就绪。",
  "Strategy card must be rechecked if GoldMacroOverview dominant mainline changes.":
    "如果黄金宏观总览的主导主线发生变化，需要重新核验策略卡。",
  "Macro prior agent status is partial; risk view is provisional.": "宏观先验智能体状态为部分可用；风险视图为临时结论。",
  "Options prior agent status is partial; risk view is provisional.": "期权先验智能体状态为部分可用；风险视图为临时结论。",
  "macro/options bias alignment": "宏观/期权偏向一致性",
  "unavailable modules": "不可用模块",
  "prior agent status": "先验智能体状态",
  "invalid conditions": "失效条件",
  "risk invalidation triggers": "风险失效触发条件",
  "SOFR−IORB / EFFR−IORB": "融资利率利差（SOFR−IORB / EFFR−IORB）",
  "Gold macro pending verification: oil_price_reaction_needed": "黄金宏观待核验：需要油价反应证据",
  "Gold macro pending verification: real_rate_response_needed": "黄金宏观待核验：需要实际利率反应证据",
  "Gold macro pending verification: positioning_confirmation_needed": "黄金宏观待核验：需要持仓确认",
  "Data quality warning: expiry_date_estimated_from_delivery_month": "数据质量警告：到期日根据交割月份估算",
  "Data quality warning: grid_skipped_rows_without_iv": "数据质量警告：缺少隐含波动率的网格行已跳过",
  "No official-confirmed news event in daily_market_brief.": "日度市场简报中没有官方核验的新闻事件。",
  "Single-source or unofficial events must remain watchlist until verified.":
    "单一来源或非官方事件在核验前只能保留在观察清单。",
};

function translateStrategySentence(raw: string): string | null {
  const exact = STRATEGY_EXACT_SENTENCE_LABELS[raw];
  if (exact) return exact;

  let translated = raw;
  let match = /^Macro prior invalid condition:\s*(.*)$/i.exec(translated);
  if (match) translated = `宏观先验失效条件：${match[1]}`;
  match = /^Macro prior risk:\s*(.*)$/i.exec(translated);
  if (match) translated = `宏观先验风险：${match[1]}`;
  match = /^Options prior risk:\s*(.*)$/i.exec(translated);
  if (match) translated = `期权先验风险：${match[1]}`;
  match = /^Unavailable macro symbols:\s*(.*)$/i.exec(translated);
  if (match) translated = "不可用宏观指标（技术值见依据记录）";
  match = /^Unavailable probability sources:\s*(.*)$/i.exec(translated);
  if (match) translated = "不可用的概率来源（技术值见依据记录）";
  match = /^Data quality reports (\d+) PRELIM-derived option rows\/signals\.?$/i.exec(translated);
  if (match) translated = `数据质量显示有 ${match[1]} 行/信号来自初步发布数据。`;
  match = /^Market odds event (.*)$/i.exec(translated);
  if (match) translated = "市场赔率事件尚不可用（来源数据尚未接入；原文见依据记录）";

  translated = translated
    .replace(
      "DXY daily/weekly/monthly delta is missing; dollar direction must remain unconfirmed.",
      "缺少 DXY 日/周/月变动；美元方向必须保持未核验。",
    )
    .replace(
      "CME options source status is PRELIM; treat conclusions as provisional.",
      "芝商所期权数据源状态为初步发布；结论仅作临时参考。",
    )
    .replace("Data quality warning: expiry_date_estimated_from_delivery_month", "数据质量警告：到期日根据交割月份估算")
    .replace("Data quality warning: grid_skipped_rows_without_iv", "数据质量警告：缺少隐含波动率的网格行已跳过")
    .replace(/Gold war-oil-rate chain C:\s*/gi, "黄金战争—油价—利率链路 C：")
    .replace(/若周末\/近两天宏观动态仍为 degraded/gi, "若周末/近两天宏观动态仍为数据降级")
    .replace(/新增宏观事件被确认但尚未进入正式 premarket 综合分析链路/gi, "新增宏观事件被确认但尚未进入正式盘前综合分析链路")
    .replace(/No official-confirmed news event in daily_market_brief\.?/gi, "日度市场简报中没有官方核验的新闻事件。")
    .replace(/Single-source or unofficial events must remain watchlist until verified\.?/gi, "单一来源或非官方事件在核验前只能保留在观察清单。")
    .replace(/Market odds event '[^']+' is unavailable — source data not yet integrated\.?/gi, "市场赔率事件尚不可用（来源数据尚未接入；原文见依据记录）。")
    .replace(/DXY directional change is unavailable; only the current level is confirmed\.?/gi, "DXY 方向变化不可用；目前仅确认当前水平。")
    .replace(/EIA\/FRED 原油是延迟发布的现货价格；不能把它写成最新 Brent\/WTI 期货结算\.?/gi, "EIA/FRED 原油为延迟发布的现货价格；不能将其写成最新布伦特/WTI 期货结算。")
    .replace(/前置 agent 状态为/gi, "前置智能体状态为")
    .replace(/Volatility elevated \(ATR≈([^)]*) of price\);/gi, "波动率偏高（ATR≈$1 的价格）；")
    .replace(/Spot\/OTC provider proxy; technical levels require confirmation from a primary spot source\.?/gi, "现货/OTC 数据源为代理；技术位需要主现货源确认。")
    .replace(/Market odds are based on CME only — Bloomberg, Internal model, Polymarket data missing, reducing reliability\.?/gi, "市场赔率仅基于芝商所；彭博社、内部模型与预测市场数据缺失，可靠性降低。")
    .replace(/Market odds are partial — only CME-implied probabilities are available\.?/gi, "市场赔率不完整——目前仅有芝商所隐含概率。")
    .replace(/待确认风险:\s*/gi, "待确认风险：")
    .replace(/\bReuters\b/gi, "路透社")
    .replace(/\bmulti_source\b/gi, "多来源")
    .replace(/\bsingle_source\b/gi, "单一来源")
    .replace(/\bgeo_risk_to_oil_to_inflation\b/gi, "地缘风险→油价→通胀")
    .replace(/\bexternal_report_watchlist\b/gi, "外部报告观察清单")
    .replace(/\bpricing=unpriced\b/gi, "定价影响=未定价")
    .replace(/\bpricing=unknown\b/gi, "定价影响=未知")
    .replace(/\bevent_id=/gi, "事件标识=")
    .replace(/\bInternal model\b/gi, "内部模型")
    .replace(/rows_missing_delta:\s*(\d+)\s*行/gi, "缺少 Delta 的行：$1 行")
    .replace(/Data quality reports (\d+) (?:PRELIM|初步发布)-derived option rows\/signals\.?/gi, "数据质量显示有 $1 行/信号来自初步发布数据。")
    .replace(/\bStrategyCard\b/g, "策略卡")
    .replace(/\bAgent\b/g, "智能体")
    .replace(/\bbearish\b/gi, "看空")
    .replace(/\btransition_release\b/gi, "过渡释放")
    .replace(/\bshort_curve\b/g, "短端利率曲线")
    .replace(/\bpremarket\b/gi, "盘前")
    .replace(/\bdegraded\b/gi, "数据降级")
    .replace(/\bFINAL\b/g, "最终版本")
    .replace(/\bPRELIM\b/g, "初步发布")
    .replace(/\brows\b/gi, "行")
    .replace(/\boptions\b/gi, "期权")
    .replace(/\bsignals\b/gi, "信号")
    .replace(/\boption\b/gi, "期权")
    .replace(/\bsource data not yet integrated\b/gi, "来源数据尚未接入")
    .replace(/\bCME 期权关键价位\b/g, "芝商所期权关键价位")
    .replace(/\bCME 到期结构与期现基差\b/g, "芝商所到期结构与期现基差")
    .replace(/\bCME\b/g, "芝商所")
    .replace(/\bCFTC\b/g, "美国商品期货委员会（CFTC）")
    .replace(/\bETF\b/g, "黄金 ETF（ETF）")
    .replace(/\bpartial\b/gi, "部分可用")
    .replace(/TGA 周均与准备金/g, "财政账户（TGA）周均与准备金")
    .replace(/新闻\s*前置风险：待确认风险：/g, "新闻前置风险：待确认风险（原文待整理）：")
    .replace(/\bCFTC 周二/g, "美国商品期货委员会（CFTC）周二")
    .replace(/\bIV\b/g, "隐含波动率（IV）")
    .replace(/Unavailable macro symbols:\s*[^.;]+[.;]?/gi, "不可用宏观指标（技术值见依据记录）。")
    .replace(/Unavailable probability sources:\s*[^.;]+[.;]?/gi, "不可用的概率来源（技术值见依据记录）。")
    .replace(/Data quality warning:\s*/gi, "数据质量警告：")
    .replace(/Macro prior invalid condition:\s*/gi, "宏观先验失效条件：")
    .replace(/Macro prior risk:\s*/gi, "宏观先验风险：")
    .replace(/Options prior risk:\s*/gi, "期权先验风险：")
    .replace(/Data quality reports (\d+) PRELIM-derived option rows\/signals\.?/gi, "数据质量显示有 $1 行/信号来自初步发布数据。")
    .replace(/Unavailable macro symbols:\s*/gi, "不可用宏观指标：")
    .replace(/Unavailable probability sources:\s*/gi, "不可用的概率来源：")
    .replace(/Macro prior agent status is (?:partial|部分可用); risk view is provisional\.?/gi, "宏观先验智能体状态为部分可用；风险视图为临时结论。")
    .replace(/Options prior agent status is (?:partial|部分可用); risk view is provisional\.?/gi, "期权先验智能体状态为部分可用；风险视图为临时结论。")
    .replace(/^No official-confirmed news event in daily_market_brief\.?$/i, "日度市场简报中没有官方核验的新闻事件。")
    .replace(/^Single-source or unofficial events must remain watchlist until verified\.?$/i, "单一来源或非官方事件在核验前只能保留在观察清单。")
    .replace(/^Volatility elevated/i, "波动率偏高")
    .replace(/^Spot\/OTC provider proxy/i, "现货/OTC 数据源为 Proxy")
    .replace(/。{2,}/g, "。");

  return translated === raw ? null : translated;
}

const VISIBLE_TECHNICAL_TOKENS = new Set([
  "ATR",
  "bp",
  "Brent",
  "CFTC",
  "CME",
  "DXY",
  "EIA",
  "ETF",
  "FRED",
  "GLD",
  "HOLD",
  "IORB",
  "IV",
  "M",
  "SOFR",
  "TGA",
  "US10Y",
  "WTI",
  "XAUUSD",
  "Y",
]);

function containsUntranslatedEnglish(value: string): boolean {
  const tokens = value.match(/[A-Za-z][A-Za-z0-9_-]*/g) ?? [];
  return tokens.some((token) => {
    if (VISIBLE_TECHNICAL_TOKENS.has(token)) return false;
    if (/^US\d+[A-Z0-9]*$/.test(token)) return false;
    return true;
  });
}

function evidenceGapLabel(raw: string): string {
  if (/^(?:https?:\/\/|\/|[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9_-]+)+)/.test(raw)) {
    return "中文说明缺口：技术路径或机器字段尚未转换（技术值见依据记录）";
  }
  if (/^[A-Za-z][A-Za-z0-9_/-]*$/.test(raw)) return "中文说明缺口：未解释业务枚举（技术值见依据记录）";
  if (/[A-Za-z]{3}/.test(raw)) return "中文说明缺口：后端英文说明尚未整理（原文见依据记录）";
  return "中文说明缺口：后端值尚未整理（技术值见依据记录）";
}

/**
 * Conditions are evidence, so known backend sentences are translated
 * deterministically. Unknown values get a Chinese explanation gap; the raw
 * value stays in the caller's evidence record instead of ordinary text or a
 * hover title.
 */
export function strategyEvidenceLabel(value: string | null | undefined): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return "";
  const compact = STRATEGY_REASON_LABELS[raw] ?? STRATEGY_EXACT_SENTENCE_LABELS[raw];
  if (compact) return compact;
  const translated = translateStrategySentence(raw);
  if (translated) return containsUntranslatedEnglish(translated) ? evidenceGapLabel(raw) : translated;
  const meta = strategyValueLabel(raw);
  if (meta.known) return meta.label;
  if (!/[A-Za-z]/.test(raw)) return raw;
  if (/[㐀-鿿]/.test(raw) && !containsUntranslatedEnglish(raw) && !/\b[a-z]+_[a-z_]+\b|\/(?:home|api|storage|raw|parsed)\//i.test(raw)) return raw;
  return evidenceGapLabel(raw);
}

export function strategySourceLabel(value: string | null | undefined): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return "来源未提供";
  const known = STRATEGY_SOURCE_LABELS[raw.toLowerCase()];
  if (known) return known;
  if (/[㐀-鿿]/.test(raw)) return raw;
  return "已关联数据源（技术标识见详情）";
}

export function strategyTimestampLabel(value: string | null | undefined): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return "未提供数据时间字段";
  return STRATEGY_TIMESTAMP_LABELS[raw] ?? (/^[A-Za-z][A-Za-z0-9_/-]*$/.test(raw) ? "数据时间字段未解释（技术记录可核对）" : raw);
}

const CME_PATH_STATUS_LABELS: LabelMap = {
  confirmed: "已确认",
  active: "活跃",
  watching: "观察中",
  watch: "观察中",
};

export function cmePathStatusLabel(value: string | null | undefined) {
  return displayEnum(value, CME_PATH_STATUS_LABELS, "未知路径状态");
}

const CME_SCOPE_LABELS: LabelMap = {
  nearby_6pct: "主战区（约 ±6%）",
  full_chain: "全链条",
  aggregate: "汇总范围",
};

export function cmeScopeLabel(value: string | null | undefined) {
  return displayEnum(value, CME_SCOPE_LABELS, "未知范围");
}

const SHADOW_SUMMARY_STATUS_LABELS: LabelMap = {
  blocked: "质量阻断",
  unscorable: "不可评分",
  verified: "已核验",
  legacy: "历史待核验",
  no_sample: "暂无样本",
};

export function shadowSummaryStatusLabel(value: string | null | undefined) {
  return displayEnum(value, SHADOW_SUMMARY_STATUS_LABELS, "未知评估状态");
}

const SHADOW_OUTCOME_STATUS_LABELS: LabelMap = {
  scored: "已评分",
  blocked: "质量阻断",
  unscorable: "不可评分",
};

export function shadowOutcomeStatusLabel(value: string | null | undefined) {
  return displayEnum(value, SHADOW_OUTCOME_STATUS_LABELS, "未知结果状态");
}

const SHADOW_CLASSIFICATION_LABELS: LabelMap = {
  correct: "判断正确",
  incorrect: "判断错误",
  neutral: "中性",
  hold: "观望（HOLD）",
  invalidated: "已失效",
  blocked: "质量阻断",
  unscorable: "不可评分",
};

export function shadowClassificationLabel(value: string | null | undefined) {
  return displayEnum(value, SHADOW_CLASSIFICATION_LABELS, "未知分类");
}

const SHADOW_VERIFICATION_LABELS: LabelMap = {
  verified: "已核验",
  legacy_unverified: "历史待核验",
};

export function shadowVerificationLabel(value: string | null | undefined) {
  return displayEnum(value, SHADOW_VERIFICATION_LABELS, "未知核验状态");
}

const SHADOW_LIFECYCLE_LABELS: LabelMap = {
  never_triggered: "未触发",
  invalidated_before_entry: "入场前失效",
  triggered: "已触发",
  triggered_then_invalidated: "触发后失效",
  target_reached: "目标命中",
  same_bar_ambiguous: "同 K 线歧义",
  insufficient_market_path: "行情路径不足",
  insufficient_strategy_contract: "策略契约不足",
  blocked: "质量阻断",
};

export function shadowLifecycleLabel(value: string | null | undefined) {
  return displayEnum(value, SHADOW_LIFECYCLE_LABELS, "未知生命周期");
}

/** Preserve every backend condition in the primary reading path. */
export function preserveStrategyItems(items: readonly string[] | null | undefined): string[] {
  return items ? Array.from(items) : [];
}
