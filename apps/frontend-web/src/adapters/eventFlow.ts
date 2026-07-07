import type {
  EventFlowChainStep,
  EventFlowBriefSummary,
  EventFlowReportInputItem,
  EventFlowRadarAxis,
  EventFlowReportItem,
  EventFlowSentimentItem,
  EventFlowTableRow,
  EventFlowTimelineItem,
  EventFlowRelatedNewsItem,
  EventImpactSummary,
  EventFlowViewModel,
  EventImportance,
  EventStatus,
  EventImpact,
  EventType,
  PricingStatus,
  EventFlowActionResponse,
  EventFlowProgressTrigger,
  EventFlowProgressTriggerBundle,
  Jin10ArticleBrief,
  Jin10ArticleBriefBundle,
} from "@/types/event-flow";
import type { SourceRef } from "@/types/common";
import type {
  GoldMacroOverview,
  GoldMainline,
  GoldMainlineEventLink,
  GoldMainlinesViewModel,
  GoldNetBias,
  TransmissionPath,
} from "@/types/gold-mainlines";
import { fetchJson } from "@/adapters/apiClient";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatTransmissionPathLabel,
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";

const TIMELINE: EventFlowTimelineItem[] = [
  {
    id: "0",
    time: "08:30 ET",
    date: "06-11",
    title: "美国 5 月生产者价格指数即将公布，验证消费者价格指数后的通胀压力",
    desc: "生产者价格指数将验证能源冲击是否继续向生产端和服务端扩散，是消费者价格指数公布后的第一道验证关口。",
    type: "宏观数据",
    importance: "高",
    status: "即将公布",
    impact: "高波动待定",
    source: "美国劳工统计局",
    assets: "黄金 / 美元指数 / 10年期美债 / 2年期美债",
    period: "日内",
    pricing: "未定价",
  },
  {
    id: "1",
    time: "现货时段",
    date: "06-11",
    title: "黄金自六个月低点反弹，4000 一线成为短线心理支撑",
    desc: "现货黄金触及 4022 附近后反弹至 4095 一线，但反弹暂按弱修复而非趋势反转处理。",
    type: "市场价格",
    importance: "高",
    status: "发展中",
    impact: "弱修复承压",
    source: "路透",
    assets: "黄金 / COMEX 黄金",
    period: "短线",
    pricing: "部分定价",
  },
  {
    id: "2",
    time: "08:30 ET",
    date: "06-10",
    title: "美国 5 月消费者价格指数同比 4.2%，能源项显著抬升",
    desc: "核心消费者价格指数同比 2.9%，能源项同比上涨 23.5%，市场更关注油价冲击是否转化为更持久通胀。",
    type: "通胀数据",
    importance: "高",
    status: "已公布",
    impact: "混合偏空",
    source: "美国劳工统计局",
    assets: "10年期美债 / 美元指数 / 黄金",
    period: "短线",
    pricing: "部分定价",
  },
  {
    id: "3",
    time: "08:30 ET",
    date: "06-05",
    title: "美国 5 月非农新增 17.2 万，强于预期",
    desc: "就业韧性强化美联储不急于转鸽的交易逻辑，12 月再加息定价明显升温。",
    type: "就业数据",
    importance: "高",
    status: "已公布",
    impact: "偏空黄金",
    source: "美国劳工统计局 / 路透",
    assets: "2年期美债 / 10年期美债 / 美元指数 / 黄金",
    period: "短中期",
    pricing: "已定价",
  },
  {
    id: "4",
    time: "持续",
    date: "06-10/11",
    title: "美伊紧张局势升级，油价上行、亚洲股市承压",
    desc: "地缘冲突一方面提升避险需求，另一方面也通过油价与通胀预期抬升利率压力。",
    type: "地缘/能源",
    importance: "高",
    status: "发展中",
    impact: "双向波动",
    source: "路透",
    assets: "原油 / 黄金 / 纳指 / 新兴市场汇率",
    period: "短中期",
    pricing: "部分定价",
  },
  {
    id: "5",
    time: "官方公告",
    date: "05-22",
    title: "凯文·沃什宣誓就任美联储主席，并被选为联邦公开市场委员会主席",
    desc: "凯文·沃什更适合放在政策背景层，当前市场更关注其首次完整会议沟通将如何塑造政策反应函数。",
    type: "政策变量",
    importance: "中",
    status: "已公布",
    impact: "偏鹰扰动",
    source: "美联储",
    assets: "联邦基金利率 / 美元指数 / 10年期美债 / 黄金",
    period: "中期",
    pricing: "部分定价",
  },
  {
    id: "6",
    time: "月度流向",
    date: "06-04",
    title: "全球黄金交易型基金 5 月小幅流出，但年内仍净流入",
    desc: "短线配置资金边际转弱，但年内总流入尚未被完全破坏，中期配置需求仍在。",
    type: "资金流",
    importance: "中",
    status: "已公布",
    impact: "边际偏空",
    source: "世界黄金协会",
    assets: "黄金交易型基金 / 黄金",
    period: "中期",
    pricing: "已定价",
  },
  {
    id: "7",
    time: "两日会议",
    date: "06-16/17",
    title: "下一次联储议息会议临近，关注凯文·沃什首次政策沟通",
    desc: "联储议息会议将决定当前“能源冲击 + 高利率压力”的链条是被强化还是被缓和。",
    type: "政策会议",
    importance: "高",
    status: "即将公布",
    impact: "事件前谨慎",
    source: "美联储",
    assets: "联邦基金利率 / 2年期美债 / 黄金",
    period: "事件前",
    pricing: "未定价",
  },
];

const CHAIN: EventFlowChainStep[] = [
  { num: "①", title: "地缘冲突冲击油价", kind: "blue", items: ["美伊紧张与霍尔木兹风险推升能源风险溢价", "油价↑ / 通胀预期↑"], pricing: null },
  { num: "②", title: "消费者价格指数能源项抬升", kind: "warn", items: ["5 月消费者价格指数同比 4.2%，能源项同比 23.5%", "美联储转鸽空间下降"], pricing: null },
  { num: "③", title: "非农强化经济韧性", kind: "teal", items: ["5 月非农 17.2 万，高于市场此前预期", "加息定价升温"], pricing: null },
  { num: "④", title: "美债收益率压制黄金", kind: "down", items: ["短端利率更敏感，10年期美债收益率高位压制无息资产", "黄金机会成本上升"], pricing: null },
  { num: "⑤", title: "黄金测试 4000 支撑", kind: "warn", items: ["现货黄金触及 4022 附近后反弹", "技术反弹，但未反转"], pricing: "部分定价" },
  { num: "⑥", title: "交易判断", kind: "down", items: ["生产者价格指数与联储议息会议前维持高波动", "反弹需等待收益率回落验证"], pricing: null },
];

const SENTIMENT: EventFlowSentimentItem[] = [
  {
    label: "高冲击事件数量",
    value: "8",
    unit: "",
    delta: "+2",
    deltaDir: "up",
    deltaLabel: "较昨日",
    points: [5, 5, 6, 6, 7, 7, 7, 8, 8, 8, 8, 8],
    kind: "bar",
    accent: "#ef4444",
  },
  {
    label: "风险情绪评分",
    value: "72",
    unit: "/100",
    delta: "+6",
    deltaDir: "up",
    deltaLabel: "较昨日",
    points: [60, 61, 63, 64, 65, 66, 67, 69, 70, 71, 72, 72],
    kind: "line",
    accent: "#f59e0b",
  },
  {
    label: "避险需求强度",
    value: "64",
    unit: "/100",
    delta: "+5",
    deltaDir: "up",
    deltaLabel: "较昨日",
    points: [52, 53, 54, 55, 57, 58, 59, 60, 62, 63, 64, 64],
    kind: "line",
    accent: "#10b981",
  },
  {
    label: "未定价事件占比",
    value: "31",
    unit: "%",
    delta: "+4pp",
    deltaDir: "up",
    deltaLabel: "较昨日",
    points: [24, 25, 26, 27, 27, 28, 29, 30, 30, 31, 31, 31],
    kind: "line",
    accent: "#a855f7",
  },
];

const RADAR: EventFlowRadarAxis[] = [
  { label: "利率风险", value: 79, idx: 0 },
  { label: "通胀风险", value: 76, idx: 1 },
  { label: "地缘风险", value: 74, idx: 2 },
  { label: "油价冲击", value: 73, idx: 3 },
  { label: "黄金技术位", value: 66, idx: 4 },
  { label: "政策不确定性", value: 64, idx: 5 },
];

const TABLE: EventFlowTableRow[] = [
  {
    time: "2026-06-11 08:30 ET",
    title: "美国 5 月生产者价格指数即将公布，验证消费者价格指数后的通胀压力",
    type: "宏观数据",
    source: "美国劳工统计局",
    assets: "黄金 / 美元指数 / 10年期美债 / 2年期美债",
    impact: "高波动待定",
    pricing: "未定价",
    period: "日内",
    stars: 5,
  },
  {
    time: "2026-06-11 现货时段",
    title: "黄金自六个月低点反弹，4000 一线成为短线心理支撑",
    type: "市场价格",
    source: "路透",
    assets: "黄金 / COMEX 黄金",
    impact: "弱修复承压",
    pricing: "部分定价",
    period: "短线",
    stars: 5,
  },
  {
    time: "2026-06-10 08:30 ET",
    title: "美国 5 月消费者价格指数同比 4.2%，能源项显著抬升",
    type: "通胀数据",
    source: "美国劳工统计局",
    assets: "10年期美债 / 美元指数 / 黄金",
    impact: "混合偏空",
    pricing: "部分定价",
    period: "短期",
    stars: 5,
  },
  {
    time: "2026-06-05 08:30 ET",
    title: "美国 5 月非农新增 17.2 万，强于预期",
    type: "就业数据",
    source: "美国劳工统计局 / 路透",
    assets: "2年期美债 / 10年期美债 / 美元指数 / 黄金",
    impact: "偏空黄金",
    pricing: "已定价",
    period: "短中期",
    stars: 5,
  },
  {
    time: "2026-06-10/11 持续",
    title: "美伊紧张局势升级，油价上行、亚洲股市承压",
    type: "地缘/能源",
    source: "路透",
    assets: "原油 / 黄金 / 纳指 / 新兴市场汇率",
    impact: "双向波动",
    pricing: "部分定价",
    period: "短中期",
    stars: 4,
  },
  {
    time: "2026-05-22 官方公告",
    title: "凯文·沃什宣誓就任美联储主席，并被选为联邦公开市场委员会主席",
    type: "政策变量",
    source: "美联储",
    assets: "联邦基金利率 / 美元指数 / 10年期美债 / 黄金",
    impact: "偏鹰扰动",
    pricing: "部分定价",
    period: "中期",
    stars: 4,
  },
  {
    time: "2026-06-04 月度流向",
    title: "全球黄金交易型基金 5 月小幅流出，但年内仍净流入",
    type: "资金流",
    source: "世界黄金协会",
    assets: "黄金交易型基金 / 黄金",
    impact: "边际偏空",
    pricing: "已定价",
    period: "中期",
    stars: 3,
  },
  {
    time: "2026-06-16/17 两日会议",
    title: "下一次联储议息会议临近，关注凯文·沃什首次政策沟通",
    type: "政策会议",
    source: "美联储",
    assets: "联邦基金利率 / 2年期美债 / 黄金",
    impact: "事件前谨慎",
    pricing: "未定价",
    period: "事件前",
    stars: 5,
  },
];

const REPORTS: EventFlowReportItem[] = [
  { title: "事件影响分析报告", desc: "深度分析事件对资产策略", color: "#3b82f6" },
  { title: "事件简报（自动生成）", desc: "每周自动汇总与摘要", color: "#a855f7" },
  { title: "事件与资产相关性分析", desc: "量化分析相关性与传导路径", color: "#10b981" },
  { title: "自定义报告", desc: "按配置生成报告", color: "#f59e0b" },
];

export async function fetchEventFlowOverviewView(): Promise<EventFlowViewModel> {
  const curated = _getMockViewModel();
  try {
    const overviewResp = await fetch("/api/events/flow/overview");
    if (overviewResp.ok) {
      const rawOverview = await overviewResp.json();
      if (rawOverview.status !== "unavailable") {
        return _mapApiToViewModel(rawOverview);
      }
    }
  } catch {
    // API 不可用，fallback 到 mock
  }
  return curated;
}

export async function fetchEventFlowReportInputsView(current: EventFlowViewModel): Promise<EventFlowViewModel> {
  try {
    const reportInputsResp = await fetch("/api/events/report-inputs");
    if (reportInputsResp.ok) {
      return _mergeReportInputsIntoViewModel(current, await reportInputsResp.json());
    }
  } catch {
    // Report inputs are supplementary; keep the event-flow shell usable.
  }
  return current;
}

export async function fetchEventFlowView(): Promise<EventFlowViewModel> {
  const overview = await fetchEventFlowOverviewView();
  return fetchEventFlowReportInputsView(overview);
}

function _getMockViewModel(): EventFlowViewModel {
  return {
    status: "unavailable",
    source: "mock_fallback",
    updated_at: "2026-06-11T12:30:00Z",
    timeline: TIMELINE,
    chain: CHAIN,
    sentiment: SENTIMENT,
    radar: RADAR,
    table: TABLE,
    reports: REPORTS,
    event_impact_summary: null,
    brief_summary: {
      headline: "美国通胀再升温，生产者价格指数公布前夕黄金测试 4000 心理支撑",
      summary:
        "美国 5 月消费者价格指数同比升至 4.2%，能源价格是核心扰动项；此前非农就业强于预期，推动市场重新定价美联储年内加息概率。中东冲突与油价上行一方面提供黄金避险需求，另一方面又通过通胀和美债收益率抬升黄金机会成本。黄金短线从 4022 附近反弹，但只要实际利率与 10年期美债收益率维持高位，反弹仍应先按弱修复处理。",
      status: "available",
      riskLevel: "high",
      verificationStatus: "待生产者价格指数 / 联储议息会议验证",
      pricingStatus: "部分定价",
      artifactPath: null,
      counts: {
        confirmedEventCount: 5,
        candidateEventCount: 3,
        unconfirmedRiskCount: 3,
        calendarEventCount: 2,
        sourceRefCount: 6,
      },
      newsHighlights: [
        "黄金从六个月低点附近反弹，4000 美元成为短线心理支撑；但市场仍在等待生产者价格指数数据确认通胀压力是否进一步扩散。",
        "美国 5 月消费者价格指数同比 4.2%，核心消费者价格指数同比 2.9%，能源项同比上涨 23.5%；快速降息路径继续被压缩。",
        "5 月非农新增 17.2 万，强化美国经济韧性；强非农后市场对 12 月加息的概率定价升至约 68.4%。",
        "凯文·沃什已接任美联储主席，6 月 16/17 联储议息会议将成为其首次完整政策沟通窗口。",
      ],
      watchlist: [
        "生产者价格指数：2026-06-11 08:30 美东时间，确认消费者价格指数公布后通胀是否继续向生产端扩散。",
        "联储议息会议：2026-06-16/17，观察凯文·沃什首次完整政策沟通是否强化偏鹰预期。",
        "黄金关键位：下方看 4022 / 4000，上方先看 4095-4120。",
        "10年期美债收益率能否重新跌破 4.50%，决定黄金修复是否能延续。",
        "黄金交易型基金资金流是否继续走弱，验证配置型资金是否停止追涨。",
      ],
      riskPoints: [
        "生产者价格指数若继续超预期，尤其能源与服务价格同步走强，黄金仍可能被利率上行继续压制。",
        "生产者价格指数若低于预期，市场会下修加息路径，黄金存在反弹窗口。",
        "中东冲突若继续升级，黄金可能先受避险推动上冲，随后再被通胀与收益率反复压制。",
        "油价若快速回落，避险溢价与通胀担忧会同步回吐，黄金弹性可能减弱。",
        "联储议息会议若偏鹰，凯文·沃什明确保留加息选项，将抬升2年期与10年期美债收益率并压制黄金。",
        "当前页面未接入实时价格曲线、联储经济数据库自动拉取与芝商所持仓/伽马数据，本页仅代表事件材料层判断。",
      ],
    },
    article_briefs: null,
    daily_analysis_triggers: null,
    report_input_items: [],
    has_data: true,
    source_refs: [
      { source_ref: "bls:cpi:2026-05", label: "美国劳工统计局消费者价格指数 2026-05", status: "ok" },
      { source_ref: "bls:employment:2026-05", label: "美国劳工统计局就业数据 2026-05", status: "ok" },
      { source_ref: "bls:ppi-calendar:2026-06-11", label: "美国劳工统计局生产者价格指数日历", status: "ok" },
      { source_ref: "reuters:gold:2026-06-11", label: "路透：黄金反弹", status: "ok" },
      { source_ref: "fed:warsh:2026-05-22", label: "美联储凯文·沃什宣誓公告", status: "ok" },
      { source_ref: "wgc:etf:2026-05", label: "世界黄金协会黄金交易型基金资金流", status: "ok" },
    ],
  };
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asSourceRefs(value: unknown): SourceRef[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is SourceRef => Boolean(item) && typeof item === "object")
    .map(normalizeSourceRef);
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function asGoldMainlineList(value: unknown): GoldMainline[] {
  return asStringList(value)
    .map((item) => normalizeGoldMainlineId(item))
    .filter((item): item is GoldMainline => Boolean(item));
}

function goldLinkMainlineIds(link: GoldMainlineEventLink | undefined): GoldMainline[] {
  if (!link) return [];
  return [
    ...asGoldMainlineList(link.mainline_ids),
    ...asGoldMainlineList([link.primary_mainline]),
  ].filter((item, index, items) => items.indexOf(item) === index);
}

function asTransmissionPathList(value: unknown): TransmissionPath[] {
  return asStringList(value) as TransmissionPath[];
}

const GOLD_NET_BIAS_VALUES = new Set<string>([
  "strong_bullish",
  "bullish",
  "neutral_bullish",
  "neutral",
  "neutral_bearish",
  "bearish",
  "strong_bearish",
  "mixed",
  "unknown",
]);

function asGoldNetBias(value: unknown): GoldNetBias | null {
  const text = asString(value);
  if (!text) return null;
  if (text === "uncertain") return "unknown";
  return GOLD_NET_BIAS_VALUES.has(text) ? text as GoldNetBias : null;
}

function asGoldMainline(value: unknown): GoldMainline | null {
  const text = asString(value);
  return normalizeGoldMainlineId(text);
}

function normalizeGoldMacroOverview(value: unknown): GoldMacroOverview | null {
  const record = asRecord(value);
  return Object.keys(record).length > 0 ? record as unknown as GoldMacroOverview : null;
}

function normalizeGoldMainlinesViewModel(value: unknown): GoldMainlinesViewModel | null {
  const record = asRecord(value);
  return Object.keys(record).length > 0 ? record as unknown as GoldMainlinesViewModel : null;
}

function goldEventLinksById(value: GoldMainlinesViewModel | null): Map<string, GoldMainlineEventLink> {
  const links = Array.isArray(value?.event_links) ? value.event_links : [];
  return new Map(
    links
      .filter((link) => typeof link.event_id === "string" && link.event_id.trim().length > 0)
      .map((link) => [link.event_id, link]),
  );
}

function goldNetEffectFromLink(link: GoldMainlineEventLink | undefined): GoldNetBias | null {
  const directionByAsset = asRecord(link?.direction_by_asset);
  return asGoldNetBias(directionByAsset.XAUUSD)
    ?? asGoldNetBias(directionByAsset.gold)
    ?? asGoldNetBias(directionByAsset.GC)
    ?? null;
}

function goldPricingToEventPricing(value: string | null | undefined): PricingStatus {
  const normalized = value?.toLowerCase();
  if (normalized === "priced" || normalized === "confirmed" || normalized === "已定价") return "已定价";
  if (normalized === "partial" || normalized === "partially_priced" || normalized === "部分定价") return "部分定价";
  return "未定价";
}

function goldBiasToEventImpact(value: GoldNetBias | null): EventImpact {
  if (value === "strong_bullish" || value === "bullish" || value === "neutral_bullish") return "利多黄金";
  if (value === "strong_bearish" || value === "bearish" || value === "neutral_bearish") return "利空黄金";
  if (value === "mixed") return "混合";
  return "双向波动";
}

function goldMainlineToEventType(value: GoldMainline | null | undefined): EventType {
  if (value === "fed_policy_path" || value === "real_rates_usd") return "宏观数据";
  if (value === "oil_prices" || value === "geopolitical_war_risk") return "地缘/能源";
  if (value === "etf_flows" || value === "institutional_sentiment") return "资金流";
  if (value === "gold_technical_levels") return "市场价格";
  return "市场事件";
}

function goldLinkSummary(link: GoldMainlineEventLink): string {
  const paths = (link.transmission_path_ids ?? []).map(formatTransmissionPathLabel);
  const drivers = [
    ...(link.bullish_drivers ?? []),
    ...(link.bearish_drivers ?? []),
    link.dominant_driver ?? "",
  ].filter(Boolean).map(formatGoldDriverLabel);
  const checks = (link.verification_needed ?? []).map(formatGoldDriverLabel);
  const parts = [
    paths.length ? `传导链：${paths.join(" / ")}` : "",
    drivers.length ? `驱动：${drivers.join(" / ")}` : "",
    checks.length ? `待验证：${checks.join(" / ")}` : "",
  ].filter(Boolean);
  return parts.join("；") || "黄金主线引擎返回事件归因，但尚未返回驱动拆解。";
}

function timelineFromGoldLinks(
  goldMainlines: GoldMainlinesViewModel | null,
  goldMacroOverview: GoldMacroOverview | null,
  fallbackUpdatedAt: string,
): EventFlowTimelineItem[] {
  const links = Array.isArray(goldMainlines?.event_links) ? goldMainlines.event_links : [];
  const asOf = goldMainlines?.as_of || goldMacroOverview?.as_of || fallbackUpdatedAt;
  const date = asOf?.slice(0, 10) || "";
  const time = asOf?.slice(11, 16) || "";

  return links.map((link, index) => {
    const mainlineIds = goldLinkMainlineIds(link);
    const primaryMainline = asGoldMainline(link.primary_mainline) ?? mainlineIds[0] ?? null;
    const netEffect = goldNetEffectFromLink(link);
    const title = `${formatGoldMainlineLabel(primaryMainline)}归因：${formatGoldNetBiasLabel(netEffect ?? "unknown")}`;
    const assets = Object.keys(asRecord(link.direction_by_asset)).join(" / ") || goldMainlines?.asset || "XAUUSD";

    return {
      id: link.event_id || `gold-mainline-link-${index}`,
      time,
      date,
      title,
      desc: goldLinkSummary(link),
      type: goldMainlineToEventType(primaryMainline),
      importance: link.changed_dominant_theme ? "高" : "中",
      status: "发展中",
      impact: goldBiasToEventImpact(netEffect),
      source: "黄金主线引擎",
      assets,
      period: "主线归因",
      pricing: goldPricingToEventPricing(link.pricing_status),
      verification_status: link.verification_status ?? null,
      risk_level: link.changed_dominant_theme ? "high" : "medium",
      event_kind: "gold_mainline_link",
      raw_event_type: "gold_mainline_link",
      source_refs: link.source_refs,
      affected_assets: assets.split("/").map((item) => item.trim()).filter(Boolean),
      impact_path: (link.transmission_path_ids ?? []).map(formatTransmissionPathLabel).join(" / ") || null,
      gold_impact: formatGoldNetBiasLabel(netEffect ?? "unknown"),
      market_validation: {},
      market_snapshot: {},
      related_news_items: [],
      mainlines: mainlineIds,
      primary_mainline: primaryMainline,
      transmission_chains: link.transmission_path_ids ?? [],
      dominant_driver: link.dominant_driver ?? null,
      bullish_drivers: link.bullish_drivers ?? [],
      bearish_drivers: link.bearish_drivers ?? [],
      net_effect: netEffect,
      verification_needed: link.verification_needed ?? [],
      verification_chain: link.verification_chain ?? null,
      changed_dominant_theme: Boolean(link.changed_dominant_theme),
    };
  });
}

function tableRowsFromTimeline(timeline: EventFlowTimelineItem[]): EventFlowTableRow[] {
  return timeline.map((event) => ({
    id: event.id,
    time: [event.date, event.time].filter(Boolean).join(" ").trim() || event.time,
    title: event.title,
    type: event.type,
    source: event.source ?? "事件流",
    assets: event.assets ?? event.affected_assets?.join(", ") ?? "—",
    impact: event.impact,
    pricing: event.pricing ?? "未定价",
    period: event.period ?? "主线",
    stars: event.importance === "高" ? 5 : event.importance === "中" ? 3 : 1,
    verification_status: event.verification_status,
    risk_level: event.risk_level,
    event_kind: event.event_kind,
    source_refs: event.source_refs,
    related_news_items: event.related_news_items,
  }));
}

const SOURCE_NAME_MAP: Record<string, string> = {
  reuters: "路透",
  reuters_public_news: "路透快讯",
  google_news_rss: "Google 新闻",
  gdelt_news: "GDELT 新闻",
  jin10: "金十",
  jin10_article_briefs: "金十文章摘要",
  federal_reserve: "美联储",
  fed: "美联储",
  bls: "美国劳工统计局",
  world_gold_council: "世界黄金协会",
};

const SOURCE_REF_LABEL_MAP: Record<string, string> = {
  "fed:warsh:2026-05-22": "美联储凯文·沃什宣誓公告",
  "wgc:etf:2026-05": "世界黄金协会黄金交易型基金资金流",
  "reuters:gold:2026-06-11": "路透：黄金反弹",
  "bls:cpi:2026-05": "美国劳工统计局消费者价格指数 2026-05",
  "bls:employment:2026-05": "美国劳工统计局就业数据 2026-05",
  "bls:ppi-calendar:2026-06-11": "美国劳工统计局生产者价格指数日历",
};

const ASSET_NAME_MAP: Record<string, string> = {
  XAUUSD: "黄金",
  GC: "芝商所黄金",
  DXY: "美元指数",
  WTI: "纽约原油",
  BRENT: "布伦特原油",
  US10Y: "10年期美债",
  US02Y: "2年期美债",
  USDJPY: "美元/日元",
  OIL: "原油",
  ETF: "黄金交易型基金",
};

const TOPIC_NAME_MAP: Record<string, string> = {
  gold: "黄金",
  silver: "白银",
  inflation: "通胀",
  rates: "利率",
  energy: "能源",
  macro: "宏观",
  geopolitics: "地缘",
  geopolitical: "地缘",
  safe_haven: "避险",
  shipping: "航运",
  fx: "外汇",
  oil: "原油",
};

function hasChinese(value: string | null | undefined): boolean {
  const text = value ?? "";
  return /[\u4e00-\u9fff]/.test(text);
}

function normalizeInlineText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

function cleanupWireTitle(value: string): string {
  return normalizeInlineText(value)
    .replace(/\s*-\s*Reuters$/i, "")
    .replace(/\s+Reuters$/i, "")
    .replace(/\s*,?\s*data shows$/i, "")
    .trim();
}

function includesAll(text: string, parts: string[]): boolean {
  return parts.every((part) => text.includes(part));
}

function translateSourceName(value: string | null | undefined): string {
  const text = normalizeInlineText(value);
  if (!text) return "来源未知";
  if (hasChinese(text)) return text;
  const key = text.toLowerCase().replace(/[\s/-]+/g, "_");
  if (SOURCE_NAME_MAP[key]) return SOURCE_NAME_MAP[key];
  if (key.includes("reuters")) return "路透";
  if (key.includes("google_news")) return "Google 新闻";
  if (key.includes("gdelt")) return "GDELT 新闻";
  if (key.includes("jin10")) return "金十";
  if (key.includes("federal_reserve") || key.includes("fed")) return "美联储";
  if (key.includes("world_gold_council")) return "世界黄金协会";
  if (key.includes("bls")) return "美国劳工统计局";
  return text;
}

function translateAssetToken(token: string): string {
  const text = normalizeInlineText(token);
  if (!text) return "";
  if (hasChinese(text)) return text;
  const upper = text.toUpperCase();
  return ASSET_NAME_MAP[upper] ?? text;
}

function translateAssetList(values: string[] | null | undefined): string[] {
  return (values ?? []).map(translateAssetToken);
}

function translateTopicToken(token: string): string {
  const text = normalizeInlineText(token);
  if (!text) return "";
  if (hasChinese(text)) return text;
  const key = text.toLowerCase().replace(/[\s/-]+/g, "_");
  return TOPIC_NAME_MAP[key] ?? text;
}

function chineseNameText(value: string): string {
  return value
    .replace(/\bKevin Warsh\b/gi, "凯文·沃什")
    .replace(/\bWarsh\b/gi, "凯文·沃什")
    .replace(/\bFederal Reserve\b/gi, "美联储")
    .replace(/\bReuters\b/gi, "路透")
    .replace(/\bBLS\b/gi, "美国劳工统计局")
    .replace(/\bWorld Gold Council\b/gi, "世界黄金协会")
    .replace(/\bFOMC\b/gi, "联邦公开市场委员会")
    .replace(/\bCPI\b/gi, "消费者价格指数")
    .replace(/\bPPI\b/gi, "生产者价格指数")
    .replace(/\bGDP\b/gi, "国内生产总值")
    .replace(/\bIEA\b/gi, "国际能源署")
    .replace(/\bWTI\b/gi, "纽约原油")
    .replace(/\bBrent\b/gi, "布伦特原油")
    .replace(/\bNagel\b/gi, "纳格尔")
    .replace(/\bETF\b/gi, "交易型基金")
    .replace(/\bXAUUSD\b/gi, "黄金")
    .replace(/\bGC\b/g, "芝商所黄金")
    .replace(/\bDXY\b/gi, "美元指数")
    .replace(/\bUS10Y\b/gi, "10年期美债")
    .replace(/\bUS02Y\b/gi, "2年期美债")
    .replace(/\bUS2Y\b/gi, "2年期美债")
    .replace(/\b2Y\/10Y\b/gi, "2年期与10年期美债");
}

function buildSourceRefLabel(ref: SourceRef): string {
  if (ref.source_ref && SOURCE_REF_LABEL_MAP[ref.source_ref]) return SOURCE_REF_LABEL_MAP[ref.source_ref];
  if (ref.label) return chineseNameText(ref.label);
  if (ref.provider) return translateSourceName(ref.provider);
  if (ref.source_ref?.startsWith("reuters:")) return "路透来源";
  if (ref.source_ref?.startsWith("fed:")) return "美联储来源";
  if (ref.source_ref?.startsWith("bls:")) return "美国劳工统计局来源";
  if (ref.source_ref?.startsWith("wgc:")) return "世界黄金协会来源";
  return chineseNameText(ref.source_ref ?? "来源");
}

function normalizeSourceRef(ref: SourceRef): SourceRef {
  return {
    ...ref,
    provider: ref.provider ? translateSourceName(ref.provider) : ref.provider,
    label: buildSourceRefLabel(ref),
  };
}

function normalizeRelatedNewsItems(value: unknown): EventFlowRelatedNewsItem[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .flatMap((item, index) => {
      const source = asString(item.source, "unknown");
      const title = asString(item.title, "");
      const sourceType = asString(item.source_type) || null;
      const headline = title ? buildChineseHeadline(title, asString(item.source_type) || null) : "";
      if (!headline) return [];
      const summary = toChineseContent(asString(item.summary), {
        eventType: sourceType,
        fallback: buildChineseSummary(title, sourceType),
      });
      return {
        news_item_id: asString(item.news_item_id) || asString(item.source_ref) || `${source}-${index}`,
        source_ref: asString(item.source_ref) || null,
        source,
        source_label: translateSourceName(asString(item.source_label) || source),
        source_type: sourceType,
        title: headline,
        summary: summary || null,
        importance: asString(item.importance) || null,
        confidence: item.confidence == null ? null : asNumber(item.confidence),
        url: asString(item.url) || null,
        domain: asString(item.domain) || null,
        published_at: asString(item.published_at) || null,
        raw_path: asString(item.raw_path) || null,
        parsed_path: asString(item.parsed_path) || null,
        status: asString(item.status) || null,
        evaluation_role: asString(item.evaluation_role) || null,
      };
    });
}

function fallbackEventHeadline(eventType: string | null | undefined): string {
  if (eventType === "hormuz_risk") return "美伊协议与霍尔木兹通航主线更新";
  if (eventType === "macro_data") return "宏观数据主线更新";
  if (eventType === "fomc_statement") return "联储政策表态更新";
  if (eventType === "oil_supply_shock") return "油价与供给主线更新";
  if (eventType === "scheduled_calendar") return "宏观日历事件更新";
  return "";
}

function buildChineseHeadline(value: string | null | undefined, eventType?: string | null): string {
  const text = cleanupWireTitle(value ?? "");
  if (!text) return fallbackEventHeadline(eventType);
  if (hasChinese(text)) return chineseNameText(text);

  const lower = text.toLowerCase();
  if (lower.includes("three saudi-flagged supertankers") && lower.includes("hormuz")) {
    return "伊朗协议签署后，三艘沙特籍超级油轮通过霍尔木兹海峡";
  }
  if (lower.includes("hormuz reopening") && lower.includes("oil supply")) {
    return "霍尔木兹航道重开或释放原油供给，油价面临回落压力";
  }
  if (lower.includes("stocks slip") && lower.includes("fed rate outlook") && lower.includes("iran deal")) {
    return "联储利率前景压过伊朗协议利好，股市回落";
  }
  if (lower.includes("oil falls to lowest since start of iran war")) {
    return "停火协议签署后，油价跌至伊朗战争爆发以来最低";
  }
  if (lower.includes("us and iran presidents sign ceasefire agreement")) {
    return "美伊总统签署停火协议，但特朗普称仍可能恢复打击";
  }
  if (lower.includes("14-point us-iran pact")) {
    return "美国官员解读美伊 14 点协议框架";
  }
  if (lower.includes("lebanon ceasefire")) {
    return "黎巴嫩停火后，战争破坏与创伤规模逐步显现";
  }
  if (lower.includes("iea sees significant 2027 oil surplus")) {
    return "国际能源署预计霍尔木兹恢复后，2027 年原油将出现明显过剩";
  }
  if (lower.includes("hezbollah") && lower.includes("iran-us deal")) {
    return "伊朗与美国达成协议后，真主党或从战损中获得喘息";
  }
  if (lower.includes("oil prices fall 5%") && lower.includes("strait of hormuz")) {
    return "市场押注霍尔木兹恢复通行，油价大跌 5% 至三个月低位";
  }
  if (lower.includes("middle east crude slips into discounts")) {
    return "美伊协议抬升供给预期，中东原油现货转入贴水";
  }
  if (lower.includes("oil rises 1%") && lower.includes("iran deal doubts")) {
    return "市场质疑美伊协议落实，油价反弹 1%，国际能源署仍警告供给过剩";
  }
  if (includesAll(lower, ["gold rises over 1%", "peace deal"])) {
    return "美伊和平协议缓和加息担忧，黄金上涨逾 1%";
  }
  if (includesAll(lower, ["iran deal includes $300 billion fund"])) {
    return "消息称美伊协议包含 3000 亿美元基金安排";
  }
  if (includesAll(lower, ["tehran can immediately sell oil", "deal"])) {
    return "美国官员称德黑兰签署协议后可立即出售原油";
  }
  if (includesAll(lower, ["hezbollah believes iran will not sign final nuclear deal", "lebanon"])) {
    return "真主党称若以色列仍留在黎巴嫩，伊朗不会签署最终核协议";
  }
  if (includesAll(lower, ["spot oil premiums slip", "shipping angst provides floor"])) {
    return "美伊协议压低现货油升水，但航运忧虑仍提供底部支撑";
  }
  if (includesAll(lower, ["stocks gain", "oil slides", "iran deal signed"])) {
    return "特朗普称伊朗协议已签署，股市走高而油价回落";
  }
  if (includesAll(lower, ["transit will take", "weeks", "largest tanker operator"])) {
    return "大型油轮运营商称霍尔木兹恢复通航仍需数周";
  }
  if (includesAll(lower, ["global shippers cautious", "hormuz transit"])) {
    return "尽管美伊达成协议，全球航运商对霍尔木兹通行仍保持谨慎";
  }
  if (includesAll(lower, ["ceasefire agreement to be public soon", "permanent truce"])) {
    return "美伊停火协议即将公布，但永久停战仍待后续谈判";
  }
  if (includesAll(lower, ["oil markets bet trump would chicken out on iran"])) {
    return "油市押注特朗普不会进一步升级对伊局势，这一判断已被市场兑现";
  }
  if (includesAll(lower, ["gold drifts higher", "halt war"])) {
    return "美伊同意停战，黄金震荡走高";
  }
  if (includesAll(lower, ["market gains", "consumer shares", "small caps"])) {
    return "伊朗协议若继续推进，消费与小盘股或受益于市场进一步上行";
  }
  if (includesAll(lower, ["citi cuts brent forecasts", "flow normalization"])) {
    return "花旗因霍尔木兹通航正常化预期下调布伦特油价预测";
  }
  if (includesAll(lower, ["israeli fire kills four in gaza", "ceasefire talks"])) {
    return "加沙再遭火力打击，停火斡旋仍在继续";
  }
  if (includesAll(lower, ["us energy shares slump", "supply disruption risk"])) {
    return "霍尔木兹断供风险下降，美国能源股回落";
  }
  if (includesAll(lower, ["dollar falls to 10-day low", "war deal"])) {
    return "美伊战争协议压低避险买盘，美元跌至十日低位";
  }
  if (includesAll(lower, ["oil settles at three-month low", "deal signed"])) {
    return "结束伊朗战争的协议落地后，油价收于三个月低位";
  }
  if (includesAll(lower, ["funds won't be transferred to iran", "signing deal"])) {
    return "万斯称不会因签署停战协议向伊朗转移资金";
  }
  if (includesAll(lower, ["what the us and iran say is in the memorandum"])) {
    return "美伊双方披露停战备忘录主要内容";
  }
  if (includesAll(lower, ["maersk welcomes us-iran deal", "middle east operation"])) {
    return "马士基欢迎美伊协议，但暂未调整中东运营安排";
  }
  if (includesAll(lower, ["no inflation relief in sight", "hormuz strait reopens"])) {
    return "纳格尔称即便霍尔木兹重开，通胀压力也难迅速缓解";
  }
  if (includesAll(lower, ["won't pull the yen back from the brink"])) {
    return "伊朗和平协议也难让日元脱离脆弱区间";
  }
  if (includesAll(lower, ["global leaders react", "peace agreement"])) {
    return "全球领导人回应美伊和平协议声明";
  }
  if (includesAll(lower, ["won't change boj's rate-hike plans"])) {
    return "专家称伊朗和平协议不会改变日本央行加息路径";
  }
  if (includesAll(lower, ["markets cheer iran deal", "oil to start flowing"])) {
    return "市场欢迎伊朗协议，但仍等待原油真正恢复流动";
  }
  if (includesAll(lower, ["ready to lift iran sanctions", "us-iran deal"])) {
    return "英法德意表示美伊协议后准备解除对伊制裁";
  }
  if (includesAll(lower, ["reach preliminary agreement to end war", "signing set for friday"])) {
    return "美伊达成结束战争的初步协议，签署定于周五";
  }
  if (includesAll(lower, ["draft us deal includes oil sanctions waiver", "asset release"])) {
    return "伊朗称美方协议草案包含石油制裁豁免、核限制与资产释放";
  }
  if (includesAll(lower, ["trump says deal to end war", "signed on sunday"])) {
    return "特朗普称结束战争的协议将于周日签署，伊朗质疑时间安排";
  }
  if (includesAll(lower, ["signal peace deal near", "tehran claims victory"])) {
    return "美伊释放和平协议临近信号，德黑兰称己方已取得胜利";
  }
  if (includesAll(lower, ["main provisions", "2015 iran nuclear deal"])) {
    return "特朗普放弃的 2015 年伊朗核协议主要条款回顾";
  }
  if (includesAll(lower, ["gold rises 2%", "canceling iran strikes"])) {
    return "特朗普取消对伊朗打击后，通胀忧虑缓和，黄金上涨 2%";
  }
  if (includesAll(lower, ["hormuz reopening", "opec’s undoing"])) {
    return "霍尔木兹重开或将反噬欧佩克";
  }
  if (includesAll(lower, ["i love the inflation", "prices rise amid iran war"])) {
    return "特朗普称“我喜欢通胀”，伊朗战争背景下物价继续上行";
  }
  if (includesAll(lower, ["equities rally", "dollar dips", "trump cancels iran attacks"])) {
    return "特朗普取消对伊朗袭击后，股市反弹、美元回落、油价走软";
  }
  if (includesAll(lower, ["consumer inflation vaults above 4%", "energy prices"])) {
    return "伊朗战争推升能源价格，美国消费者通胀跃升至 4% 以上";
  }
  if (includesAll(lower, ["hormuz strait will be open", "transit fees"])) {
    return "伊朗驻莫斯科使节称霍尔木兹海峡将开放，但会收取通行费";
  }
  if (includesAll(lower, ["indian shares continue to rise", "softer oil", "hawkish fed"])) {
    return "油价走软压过联储鹰派影响，印度股市继续走高";
  }
  if (lower === "federal reserve issues fomc statement") {
    return "美联储发布利率决议声明";
  }
  if (includesAll(lower, ["release economic projections", "june 16-17 fomc meeting"])) {
    return "美联储公布 6 月议息会议经济预测";
  }
  if (lower === "personal income and outlays") {
    return "美国个人收入与支出";
  }
  if (lower === "gross domestic product by state and personal income by state") {
    return "美国各州地区生产总值与个人收入";
  }
  if (lower === "gross domestic product") {
    return "美国国内生产总值";
  }
  if (lower.includes("hormuz") && (lower.includes("tanker") || lower.includes("sail through"))) {
    return "霍尔木兹油轮通行恢复，地缘风险边际缓和";
  }
  if (lower.includes("hormuz") && (lower.includes("reopen") || lower.includes("reopening"))) {
    return "霍尔木兹航道重开预期升温";
  }
  if (lower.includes("iran deal") && lower.includes("signed")) {
    return "伊朗协议落地，市场重估中东风险溢价";
  }
  if (lower.includes("fed") && lower.includes("rate")) {
    return "联储利率预期继续压制风险偏好";
  }
  return chineseNameText(text);
}

function buildChineseSummary(
  value: string | null | undefined,
  eventType?: string | null,
  impactPath?: string | null,
): string {
  const text = cleanupWireTitle(value ?? "");
  if (!text) {
    if (eventType === "hormuz_risk") {
      return "当前事件围绕霍尔木兹与伊朗主线展开，核心影响是原油、通胀预期、美元与黄金之间的再定价。";
    }
    return "当前事件仍在发酵，市场主要通过利率、美元、原油与黄金链条重新定价。";
  }
  if (hasChinese(text)) return chineseNameText(text);

  const lower = text.toLowerCase();
  if (lower.includes("three saudi-flagged supertankers") && lower.includes("hormuz")) {
    return "协议落地后油轮恢复通行，说明霍尔木兹封锁风险阶段性缓和；市场会据此下修原油风险溢价，并重新评估黄金与通胀链条的短线反应。";
  }
  if (lower.includes("hormuz reopening") && lower.includes("oil supply")) {
    return "如果霍尔木兹通航恢复持续，原油供给预期会回升，油价上方风险溢价可能回吐；对黄金而言，避险需求与通胀担忧会同步重新定价。";
  }
  if (lower.includes("stocks slip") && lower.includes("fed rate outlook")) {
    return "地缘缓和并未改善风险偏好，联储高利率预期重新主导交易，股市与黄金弹性都受到美元和收益率约束。";
  }
  if (lower.includes("oil falls to lowest since start of iran war")) {
    return "停火协议如果继续兑现，原油风险溢价会快速回吐，市场会同步下修能源通胀冲击与黄金避险需求。";
  }
  if (lower.includes("us and iran presidents sign ceasefire agreement")) {
    return "协议本身缓和了地缘主线，但特朗普保留恢复打击的表态意味着风险并未完全出清，油价和黄金仍可能反复。";
  }
  if (lower.includes("14-point us-iran pact")) {
    return "这类协议框架信息决定后续停火能否真正落地，市场会据此重新评估供给恢复、制裁节奏与中东风险溢价。";
  }
  if (lower.includes("lebanon ceasefire")) {
    return "停火后的破坏评估会影响市场对中东局势是否真正降温的判断，也会间接影响原油与避险资产的风险定价。";
  }
  if (lower.includes("iea sees significant 2027 oil surplus")) {
    return "国际能源署的过剩判断强化了中期供给宽松预期，如果霍尔木兹恢复稳定，油价上方空间会继续受限。";
  }
  if (lower.includes("hezbollah") && lower.includes("iran-us deal")) {
    return "协议外溢到地区代理力量，说明停火并不只影响油价，也会改变后续中东安全格局与地缘风险贴水。";
  }
  if (lower.includes("oil prices fall 5%") && lower.includes("strait of hormuz")) {
    return "市场将霍尔木兹重开视为供给恢复信号，油价快速下杀，意味着地缘溢价正在被集中释放。";
  }
  if (lower.includes("middle east crude slips into discounts")) {
    return "现货贴水说明供给宽松预期已开始压到中东原油现货端，市场不再只交易情绪，而是在重估实际供需。";
  }
  if (lower.includes("oil rises 1%") && lower.includes("iran deal doubts")) {
    return "协议执行仍存不确定性，短线油价会在供给过剩与停火反复之间来回拉扯，黄金也会跟随风险偏好反复摆动。";
  }
  if (includesAll(lower, ["gold rises over 1%", "peace deal"])) {
    return "停战预期缓和了原油与通胀上冲风险，市场同步下修进一步加息押注，黄金因此获得利率端支撑，但避险溢价回落仍会限制其持续性。";
  }
  if (includesAll(lower, ["iran deal includes $300 billion fund"])) {
    return "巨额资金安排说明协议不只停留在停火层面，还涉及重建与履约保障，市场会据此重新评估伊朗供给恢复和地区风险溢价的下降速度。";
  }
  if (includesAll(lower, ["tehran can immediately sell oil", "deal"])) {
    return "若伊朗签署后可立刻恢复售油，供给端宽松预期会进一步强化，原油上方风险溢价和相关通胀担忧都可能继续回吐。";
  }
  if (includesAll(lower, ["hezbollah believes iran will not sign final nuclear deal", "lebanon"])) {
    return "这表明地区代理冲突仍可能拖住正式协议进程，市场不能把停火消息简单视为风险完全出清，原油与黄金的波动仍会反复。";
  }
  if (includesAll(lower, ["spot oil premiums slip", "shipping angst provides floor"])) {
    return "现货升水回落说明供给担忧正在缓解，但航运端仍未完全恢复正常，意味着原油下行虽有空间，却未到彻底失去支撑的阶段。";
  }
  if (includesAll(lower, ["stocks gain", "oil slides", "iran deal signed"])) {
    return "风险偏好回升和油价回落同步出现，说明市场正把协议解读为中东风险降温与供给恢复信号，黄金则会在避险回落与利率预期之间重新平衡。";
  }
  if (includesAll(lower, ["transit will take", "weeks", "largest tanker operator"])) {
    return "即便协议已落地，航运恢复仍有时滞，意味着原油风险溢价不会在一夜之间完全消失，市场对供给恢复的定价仍需分阶段修正。";
  }
  if (includesAll(lower, ["global shippers cautious", "hormuz transit"])) {
    return "航运商仍保持谨慎，说明纸面协议与真实通航恢复之间存在落差，油价和运费相关资产短线仍会保留一部分地缘贴水。";
  }
  if (includesAll(lower, ["ceasefire agreement to be public soon", "permanent truce"])) {
    return "公开协议会提升短线风险偏好，但永久停战仍待谈判，说明当前更像阶段性缓和而非彻底解决，市场仍会保留对反复的定价。";
  }
  if (includesAll(lower, ["oil markets bet trump would chicken out on iran"])) {
    return "油市此前就押注局势不会升级到全面断供，这一交易方向兑现后，市场会更关注剩余风险贴水还能释放多少。";
  }
  if (includesAll(lower, ["gold drifts higher", "halt war"])) {
    return "黄金温和走强反映市场一边下修加息预期，一边尚未完全放弃避险配置，说明停战消息对黄金的影响并非单边利空。";
  }
  if (includesAll(lower, ["market gains", "consumer shares", "small caps"])) {
    return "如果协议继续推进，风险偏好改善会优先利好消费和小盘等高弹性板块，说明市场交易主线正从地缘冲击逐步切回增长与估值修复。";
  }
  if (includesAll(lower, ["citi cuts brent forecasts", "flow normalization"])) {
    return "机构下调油价预测说明霍尔木兹正常化预期已开始进入中期供需定价，油价回落也会缓和后续通胀与利率压力。";
  }
  if (includesAll(lower, ["israeli fire kills four in gaza", "ceasefire talks"])) {
    return "加沙方向仍有冲突与谈判并行，说明中东局势并未整体出清，市场对地区风险的定价仍需保留一定缓冲。";
  }
  if (includesAll(lower, ["us energy shares slump", "supply disruption risk"])) {
    return "能源股回落说明市场在压缩霍尔木兹断供溢价，若这一预期延续，原油相关资产和通胀交易都将继续降温。";
  }
  if (includesAll(lower, ["dollar falls to 10-day low", "war deal"])) {
    return "避险买盘回落与加息担忧缓和共同压低美元，意味着黄金和风险资产的短线弹性会改善，但持续性仍取决于协议执行进度。";
  }
  if (includesAll(lower, ["oil settles at three-month low", "deal signed"])) {
    return "油价收于低位说明市场已大幅回吐战争溢价，接下来更关键的是实际通航、制裁节奏与供给恢复能否跟上预期。";
  }
  if (includesAll(lower, ["funds won't be transferred to iran", "signing deal"])) {
    return "资金不转移的表态说明协议仍有政治约束，市场会把它理解为停战推进但执行条件较严，后续反复风险仍在。";
  }
  if (includesAll(lower, ["what the us and iran say is in the memorandum"])) {
    return "备忘录细节会直接影响市场对停战约束力、制裁松绑和原油恢复路径的判断，是后续重新定价的核心依据。";
  }
  if (includesAll(lower, ["maersk welcomes us-iran deal", "middle east operation"])) {
    return "航运龙头暂未调整运营，说明产业侧仍在等待更明确的安全确认，真实物流恢复仍慢于金融市场的乐观定价。";
  }
  if (includesAll(lower, ["no inflation relief in sight", "hormuz strait reopens"])) {
    return "即便霍尔木兹恢复通行，通胀压力也未必立刻消散，说明市场不能仅凭油价回落就完全下修后续利率风险。";
  }
  if (includesAll(lower, ["won't pull the yen back from the brink"])) {
    return "和平协议缓和了地缘压力，但不足以改变日元自身的利差与政策困境，说明外汇主线仍由各国货币政策主导。";
  }
  if (includesAll(lower, ["global leaders react", "peace agreement"])) {
    return "各国表态会影响协议执行的外部支持力度，也关系到制裁、航运和地区安全安排能否顺利推进。";
  }
  if (includesAll(lower, ["won't change boj's rate-hike plans"])) {
    return "这类表态说明日本政策路径仍更多取决于本土通胀与工资，而非单一地缘缓和事件，日元与全球利率链条不会被轻易改写。";
  }
  if (includesAll(lower, ["markets cheer iran deal", "oil to start flowing"])) {
    return "市场情绪先行改善，但真正决定油价能否继续回落的仍是原油是否实质恢复流动，交易会从情绪转向兑现验证。";
  }
  if (includesAll(lower, ["ready to lift iran sanctions", "us-iran deal"])) {
    return "欧洲主要国家准备松动制裁，会进一步强化供给恢复与贸易正常化预期，对原油、通胀和风险资产都是方向明确的宽松信号。";
  }
  if (includesAll(lower, ["reach preliminary agreement to end war", "signing set for friday"])) {
    return "初步协议意味着主线已经从军事冲突转向文本落地和执行条件，市场会提前交易风险降温，但也会盯紧签署前后的反复。";
  }
  if (includesAll(lower, ["draft us deal includes oil sanctions waiver", "asset release"])) {
    return "草案若包含制裁豁免与资产释放，意味着伊朗供给恢复会更快进入现实预期，对油价和通胀链条的压制也更直接。";
  }
  if (includesAll(lower, ["trump says deal to end war", "signed on sunday"])) {
    return "即便特朗普给出签署时间表，伊朗仍质疑节奏，说明停战仍处在口头承诺向正式文本过渡的阶段，市场对反复风险不会完全松手。";
  }
  if (includesAll(lower, ["signal peace deal near", "tehran claims victory"])) {
    return "双方同时释放接近协议的信号，说明主线已经从军事升级转向胜利叙事与条款博弈，风险偏好会改善，但真正的供给修复仍待确认。";
  }
  if (includesAll(lower, ["main provisions", "2015 iran nuclear deal"])) {
    return "回看 2015 年核协议条款有助于市场判断当前谈判可能恢复到什么程度，以及制裁、原油出口和地缘风险贴水能释放多少。";
  }
  if (includesAll(lower, ["gold rises 2%", "canceling iran strikes"])) {
    return "取消打击缓和了能源通胀进一步失控的担忧，也压低了美元与收益率的上行压力，因此黄金同时受益于利率回落与避险需求修复。";
  }
  if (includesAll(lower, ["hormuz reopening", "opec’s undoing"])) {
    return "如果霍尔木兹重新开放并恢复稳定流量，供给约束会显著缓和，欧佩克对油价的控制力反而可能被削弱。";
  }
  if (includesAll(lower, ["i love the inflation", "prices rise amid iran war"])) {
    return "这类表态会强化市场对政策容忍通胀的担忧，使原油、通胀预期和利率主线重新缠绕在一起，黄金也会在避险与高利率之间摇摆。";
  }
  if (includesAll(lower, ["equities rally", "dollar dips", "trump cancels iran attacks"])) {
    return "风险资产同步反弹、美元回落，说明市场把取消袭击解读为地缘降温与能源压力缓解信号，短线交易重心回到风险偏好修复。";
  }
  if (includesAll(lower, ["consumer inflation vaults above 4%", "energy prices"])) {
    return "能源价格上行把战争冲击直接传导到美国通胀，这会抬升联储维持高利率的必要性，也是黄金难以单边走强的关键约束。";
  }
  if (includesAll(lower, ["hormuz strait will be open", "transit fees"])) {
    return "即便海峡保持开放，新增通行费也意味着物流成本和供应链风险不会完全回到战前水平，油价与通胀压力只会部分缓和。";
  }
  if (includesAll(lower, ["indian shares continue to rise", "softer oil", "hawkish fed"])) {
    return "油价回落改善了输入型通胀预期，足以暂时压过联储鹰派表态对估值的压制，说明亚洲权益市场开始交易能源降温带来的风险偏好修复。";
  }
  if (lower === "federal reserve issues fomc statement") {
    return "联储利率决议声明会直接重置市场对利率路径的判断，是黄金、美元和收益率短线重新定价的核心政策锚点。";
  }
  if (includesAll(lower, ["release economic projections", "june 16-17 fomc meeting"])) {
    return "经济预测决定市场如何理解联储对增长、通胀和终端利率的判断，通常比单句措辞更能影响中期利率预期。";
  }
  if (lower === "personal income and outlays") {
    return "个人收入与支出数据会影响消费韧性和通胀黏性的判断，是联储观察需求侧压力的重要依据。";
  }
  if (lower === "gross domestic product by state and personal income by state") {
    return "各州地区生产总值与收入数据主要用于补充区域景气度判断，对主线市场影响次于核心通胀和联储事件，但仍可辅助验证增长广度。";
  }
  if (lower === "gross domestic product") {
    return "国内生产总值数据是验证增长强弱的核心宏观指标，会通过增长预期影响收益率、美元和黄金的中短线交易。";
  }
  if (impactPath === "geo_risk_to_oil_to_inflation") {
    return "当前主线是地缘风险通过原油传导至通胀预期，再影响美元、收益率和黄金定价，市场尚未给出一致方向。";
  }
  if (eventType === "hormuz_risk") {
    return "当前事件仍围绕霍尔木兹与伊朗主线展开，核心影响是原油、通胀预期、美元与黄金之间的再定价。";
  }
  return "当前事件仍在发酵，市场主要通过利率、美元、原油与黄金链条重新定价。";
}

function toChineseContent(
  value: string | null | undefined,
  options: { eventType?: string | null; impactPath?: string | null; fallback?: string } = {},
): string {
  const text = normalizeInlineText(value);
  if (!text) return options.fallback ?? "";
  if (hasChinese(text)) return chineseNameText(text);
  return buildChineseSummary(text, options.eventType, options.impactPath) || options.fallback || "";
}

function normalizeBrief(brief: Record<string, unknown>): Jin10ArticleBrief {
  const articleClass = asString(brief.article_class);
  const headline = buildChineseHeadline(asString(brief.headline), articleClass);
  const analysisSummary = toChineseContent(asString(brief.analysis_summary), {
    eventType: articleClass,
    fallback: "当前摘要已接入事件流，可作为日报与主线判断的补充依据。",
  });
  const originalExcerpt = toChineseContent(asString(brief.original_excerpt), {
    eventType: articleClass,
    fallback: analysisSummary || headline,
  });

  return {
    brief_id: asString(brief.brief_id),
    article_class: articleClass,
    display_bucket: asString(brief.display_bucket),
    headline,
    source_url: asString(brief.source_url),
    final_url: asString(brief.final_url) || null,
    access_status: asString(brief.access_status),
    original_excerpt: originalExcerpt,
    key_points: Array.isArray(brief.key_points)
      ? brief.key_points.map((item) => toChineseContent(typeof item === "string" ? item : "", { fallback: "" })).filter(Boolean)
      : [],
    analysis_summary: analysisSummary,
    asset_tags: translateAssetList(Array.isArray(brief.asset_tags) ? brief.asset_tags.filter((item): item is string => typeof item === "string") : []),
    topic_tags: Array.isArray(brief.topic_tags)
      ? brief.topic_tags.filter((item): item is string => typeof item === "string").map(translateTopicToken)
      : [],
    suggested_actions: Array.isArray(brief.suggested_actions) ? brief.suggested_actions.filter((item): item is string => typeof item === "string") : [],
    source_refs: Array.isArray(brief.source_refs) ? brief.source_refs as Array<Record<string, unknown>> : [],
    detail_artifacts: asRecord(brief.detail_artifacts),
    data_quality: asRecord(brief.data_quality),
    created_at: asString(brief.created_at) || null,
  };
}

function normalizeEventImpactSummary(value: unknown): EventImpactSummary | null {
  const raw = asRecord(value);
  if (Object.keys(raw).length === 0) return null;
  const events = Array.isArray(raw.events) ? raw.events.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
  return {
    bias: asString(raw.bias, "neutral"),
    confidence: asNumber(raw.confidence),
    summary: asString(raw.summary),
    sentiment: asRecord(raw.sentiment),
    riskRadar: asRecord(raw.risk_radar),
    events,
    llmModel: typeof raw.llm_model === "string" ? raw.llm_model : null,
    llmElapsedSeconds: typeof raw.llm_elapsed_seconds === "number" ? raw.llm_elapsed_seconds : null,
  };
}

function normalizeBriefList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      const raw = asRecord(item);
      return (
        asString(raw.what_happened) ||
        asString(raw.event_name) ||
        asString(raw.title) ||
        asString(raw.summary) ||
        asString(raw.event_type)
      );
    })
    .filter((item) => item.length > 0)
    .slice(0, 5);
}

function normalizeBriefSummary(value: unknown): EventFlowBriefSummary | null {
  const raw = asRecord(value);
  if (Object.keys(raw).length === 0) return null;

  const marketMainline = asRecord(raw.market_mainline);
  const counts = asRecord(raw.counts);
  const reportInputs = asRecord(raw.report_inputs);
  const artifactRef = asRecord(raw.artifact_ref);

  const headline = buildChineseHeadline(asString(marketMainline.headline) || asString(marketMainline.summary), asString(marketMainline.event_type) || null);
  const summary = toChineseContent(asString(marketMainline.summary, headline), {
    eventType: asString(marketMainline.event_type) || null,
    impactPath: asString(marketMainline.impact_path) || null,
    fallback: headline,
  });

  return {
    headline: headline || "事件主线待确认",
    summary: summary || "暂无可用事件摘要。",
    status: asString(marketMainline.status) || null,
    riskLevel: asString(marketMainline.risk_level) || null,
    verificationStatus: asString(marketMainline.verification_status) || null,
    pricingStatus: asString(marketMainline.pricing_status) || null,
    artifactPath: asString(artifactRef.path) || null,
    counts: {
      confirmedEventCount: asNumber(counts.confirmed_event_count),
      candidateEventCount: asNumber(counts.candidate_event_count),
      unconfirmedRiskCount: asNumber(counts.unconfirmed_risk_count),
      calendarEventCount: asNumber(counts.calendar_event_count),
      sourceRefCount: asNumber(counts.source_ref_count),
    },
    newsHighlights: normalizeBriefList(reportInputs.news_highlights).map((item) => toChineseContent(item, { fallback: item })),
    watchlist: normalizeBriefList(reportInputs.watchlist).map((item) => toChineseContent(item, { fallback: item })),
    riskPoints: normalizeBriefList(reportInputs.risk_points).map((item) => toChineseContent(item, { fallback: item })),
  };
}

function normalizeArticleBriefBundle(value: unknown): Jin10ArticleBriefBundle | null {
  const raw = asRecord(value);
  if (Object.keys(raw).length === 0) return null;
  const briefs = Array.isArray(raw.briefs)
    ? raw.briefs
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
        .map((item) => normalizeBrief(item))
    : [];
  return {
    status: (asString(raw.status, "empty") as Jin10ArticleBriefBundle["status"]),
    date: asString(raw.date),
    run_id: asString(raw.run_id),
    artifact_path: asString(raw.artifact_path),
    as_of: asString(raw.as_of) || null,
    rule_version: asString(raw.rule_version) || null,
    brief_count: asNumber(raw.brief_count, briefs.length),
    display_bucket_counts: asRecord(raw.display_bucket_counts) as Record<string, number>,
    article_class_counts: asRecord(raw.article_class_counts) as Record<string, number>,
    access_status_counts: asRecord(raw.access_status_counts) as Record<string, number>,
    briefs,
    data_quality: asRecord(raw.data_quality),
  };
}

function sourceDomainFromRefs(refs: SourceRef[]): string | null {
  for (const ref of refs) {
    const domain = asString((ref as unknown as Record<string, unknown>).domain);
    if (domain) return domain;
  }
  return null;
}

function publishedAtFromRefs(refs: SourceRef[]): string | null {
  for (const ref of refs) {
    const publishedAt = asString((ref as unknown as Record<string, unknown>).published_at);
    if (publishedAt) return publishedAt;
  }
  return null;
}

function normalizeProgressTrigger(value: Record<string, unknown>): EventFlowProgressTrigger {
  const refs = asSourceRefs(value.source_refs);
  const sourceTitle = asString(value.source_title) || asString(value.evidence_text) || "重点事件进展";
  return {
    trigger_id: asString(value.trigger_id) || asString(value.source_event_id) || sourceTitle,
    trigger_type: asString(value.trigger_type),
    event_type: asString(value.event_type),
    priority: asString(value.priority),
    status: asString(value.status),
    source_title: toChineseContent(sourceTitle, {
      eventType: asString(value.event_type) || null,
      fallback: buildChineseHeadline(sourceTitle, asString(value.event_type) || null),
    }),
    evidence_text: toChineseContent(asString(value.evidence_text, sourceTitle), {
      eventType: asString(value.event_type) || null,
      fallback: sourceTitle,
    }),
    source_url: asString(value.source_url),
    created_at: asString(value.created_at) || null,
    published_at: publishedAtFromRefs(refs),
    source_domain: sourceDomainFromRefs(refs),
    asset_tags: translateAssetList(Array.isArray(value.asset_tags) ? value.asset_tags.filter((item): item is string => typeof item === "string") : []),
    topic_tags: Array.isArray(value.topic_tags)
      ? value.topic_tags.filter((item): item is string => typeof item === "string").map(translateTopicToken)
      : [],
    source_refs: refs,
    data_quality: asRecord(value.data_quality),
  };
}

function normalizeProgressTriggerBundle(value: unknown): EventFlowProgressTriggerBundle | null {
  const raw = asRecord(value);
  if (Object.keys(raw).length === 0) return null;
  const triggers = Array.isArray(raw.triggers)
    ? raw.triggers
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
        .map((item) => normalizeProgressTrigger(item))
    : [];
  return {
    status: (asString(raw.status, "empty") as EventFlowProgressTriggerBundle["status"]),
    date: asString(raw.date),
    run_id: asString(raw.run_id),
    artifact_path: asString(raw.artifact_path),
    as_of: asString(raw.as_of) || null,
    rule_version: asString(raw.rule_version) || null,
    trigger_count: asNumber(raw.trigger_count, triggers.length),
    triggers,
    data_quality: asRecord(raw.data_quality),
  };
}

function normalizeReportInputItems(value: unknown): EventFlowReportInputItem[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const raw = asRecord(item);
      const inputId = asString(raw.input_id);
      const title = asString(raw.title);
      if (!inputId || !title) return null;
      const normalized: EventFlowReportInputItem = {
        input_id: inputId,
        input_kind: asString(raw.input_kind, "summary"),
        group: asString(raw.group, "未分类"),
        title: buildChineseHeadline(title, asString(raw.input_kind) || null),
        summary: toChineseContent(asString(raw.summary, title), {
          eventType: asString(raw.input_kind) || null,
          fallback: buildChineseHeadline(title, asString(raw.input_kind) || null),
        }),
        verification_status: asString(raw.verification_status) || null,
        access_status: asString(raw.access_status) || null,
        artifact_path: asString(raw.artifact_path) || null,
        source_url: asString(raw.source_url) || null,
        source_refs: asSourceRefs(raw.source_refs),
        task_status: asString(raw.task_status) || null,
      };
      return normalized;
    })
    .filter(Boolean) as EventFlowReportInputItem[];
}

function _mapApiToViewModel(raw: Record<string, unknown>): EventFlowViewModel {
  const events = (raw.events as Array<Record<string, unknown>>) ?? [];
  const briefSummary = normalizeBriefSummary(raw.brief_summary);
  const goldMacroOverview = normalizeGoldMacroOverview(raw.gold_macro_overview);
  const goldMainlines = normalizeGoldMainlinesViewModel(raw.gold_mainlines);
  const goldLinksByEventId = goldEventLinksById(goldMainlines);
  const normalizedEvents = events.flatMap((e, i) => {
    const title = buildChineseHeadline(asString(e.title), asString(e.event_type) || null).trim();
    if (!title) return [];
    return [{
      raw: e,
      index: i,
      title,
    }];
  });

  const eventTimeline: EventFlowTimelineItem[] = normalizedEvents.map(({ raw: e, index, title }) => {
    const eventId = asString(e.id, String(index));
    const goldLink = goldLinksByEventId.get(eventId);
    return {
      id: eventId,
      time: (e.time as string) ?? "",
      date: "",
      title,
      desc: buildChineseSummary(asString(e.title), asString(e.event_type) || null, asString(e.impact_path) || null),
      type: "市场事件" as EventType,
      importance: ((e.importance as string) ?? "低") as EventImportance,
      status: "已公布" as EventStatus,
      impact: "混合" as EventImpact,
      source: translateSourceName((e.source as string) ?? "Jin10"),
      assets: Array.isArray(e.affected_assets) ? translateAssetList(e.affected_assets.filter((item): item is string => typeof item === "string")).join(" / ") : "",
      period: "",
      pricing: ((e.pricing as string) ?? "未定价") as PricingStatus,
      verification_status: asString(e.verification_status) || goldLink?.verification_status || null,
      risk_level: asString(e.risk_level) || null,
      event_kind: asString(e.kind) || null,
      raw_event_type: asString(e.event_type) || null,
      source_refs: asSourceRefs(e.source_refs),
      affected_assets: Array.isArray(e.affected_assets) ? e.affected_assets.filter((item): item is string => typeof item === "string") : [],
      impact_path: asString(e.impact_path) || null,
      gold_impact: asString(e.gold_impact) || null,
      silver_impact: asString(e.silver_impact) || null,
      dollar_impact: asString(e.dollar_impact) || null,
      yield_impact: asString(e.yield_impact) || null,
      oil_impact: asString(e.oil_impact) || null,
      market_validation: asRecord(e.market_validation),
      market_snapshot: asRecord(e.market_snapshot),
      related_news_items: normalizeRelatedNewsItems(e.related_news_items),
      mainlines: goldLinkMainlineIds(goldLink).length ? goldLinkMainlineIds(goldLink) : asGoldMainlineList(e.mainline_ids),
      primary_mainline: asGoldMainline(goldLink?.primary_mainline) ?? asGoldMainline(e.primary_mainline),
      transmission_chains: goldLink?.transmission_path_ids ?? asTransmissionPathList(e.transmission_path_ids),
      dominant_driver: goldLink?.dominant_driver ?? (asString(e.dominant_driver) || null),
      bullish_drivers: goldLink?.bullish_drivers ?? asStringList(e.bullish_drivers),
      bearish_drivers: goldLink?.bearish_drivers ?? asStringList(e.bearish_drivers),
      net_effect: goldNetEffectFromLink(goldLink) ?? asGoldNetBias(e.net_effect),
      verification_needed: goldLink?.verification_needed ?? asStringList(e.verification_needed),
      verification_chain: goldLink?.verification_chain ?? asRecord(e.verification_chain),
      changed_dominant_theme: Boolean(goldLink?.changed_dominant_theme ?? e.changed_dominant_theme),
    };
  });

  const timeline: EventFlowTimelineItem[] = eventTimeline.length > 0
    ? eventTimeline
    : timelineFromGoldLinks(goldMainlines, goldMacroOverview, asString(raw.updated_at));

  const table: EventFlowTableRow[] = normalizedEvents.length > 0 ? normalizedEvents.map(({ raw: e, title }) => ({
    id: asString(e.id),
    time: (e.time as string) ?? "",
    title,
    type: "市场事件" as EventType,
    source: translateSourceName((e.source as string) ?? "Jin10"),
    assets: Array.isArray(e.affected_assets) ? translateAssetList(e.affected_assets.filter((item): item is string => typeof item === "string")).join(" / ") : "",
    impact: "混合" as EventImpact,
    pricing: ((e.pricing as string) ?? "未定价") as PricingStatus,
    period: "",
    stars: e.importance === "高" ? 5 : e.importance === "中" ? 3 : 1,
    verification_status: asString(e.verification_status) || null,
    risk_level: asString(e.risk_level) || null,
    event_kind: asString(e.kind) || null,
    source_refs: asSourceRefs(e.source_refs),
    related_news_items: normalizeRelatedNewsItems(e.related_news_items),
  })) : tableRowsFromTimeline(timeline);

  return {
    status: (raw.status as EventFlowViewModel["status"]) ?? "partial",
    source: (raw.source as string) ?? "api",
    updated_at: (raw.updated_at as string) ?? new Date().toISOString(),
    timeline,
    chain: [],
    sentiment: [],
    radar: [],
    table,
    reports: [],
    event_impact_summary: normalizeEventImpactSummary(raw.event_impact_summary),
    brief_summary: briefSummary,
    daily_analysis_triggers: normalizeProgressTriggerBundle(raw.daily_analysis_triggers),
    article_briefs: normalizeArticleBriefBundle(raw.article_briefs),
    report_input_items: [],
    gold_macro_overview: goldMacroOverview,
    gold_mainlines: goldMainlines,
    has_data: events.length > 0 || timeline.length > 0 || briefSummary !== null,
    source_refs: (raw.source_refs as EventFlowViewModel["source_refs"]) ?? [],
  };
}

function _mergeApiIntoCurated(curated: EventFlowViewModel, raw: Record<string, unknown>): EventFlowViewModel {
  const apiView = _mapApiToViewModel(raw);
  const curatedBrief = curated.brief_summary;
  const apiBrief = apiView.brief_summary;

  return {
    ...curated,
    updated_at: apiView.updated_at || curated.updated_at,
    timeline: apiView.timeline.length > 0 ? apiView.timeline : curated.timeline,
    table: apiView.table.length > 0 ? apiView.table : curated.table,
    event_impact_summary: apiView.event_impact_summary ?? curated.event_impact_summary,
    source_refs: apiView.source_refs && apiView.source_refs.length > 0 ? apiView.source_refs : curated.source_refs,
    brief_summary: curatedBrief && apiBrief
      ? {
          ...curatedBrief,
          // Keep the curated 2026-06-11 page narrative as the primary surface.
          // API brief data only supplements traceability/status metadata here.
          status: apiBrief.status || curatedBrief.status,
          riskLevel: apiBrief.riskLevel || curatedBrief.riskLevel,
          verificationStatus: apiBrief.verificationStatus || curatedBrief.verificationStatus,
          pricingStatus: apiBrief.pricingStatus || curatedBrief.pricingStatus,
          artifactPath: apiBrief.artifactPath || curatedBrief.artifactPath,
          counts: {
            confirmedEventCount: Math.max(curatedBrief.counts.confirmedEventCount, apiBrief.counts.confirmedEventCount),
            candidateEventCount: Math.max(curatedBrief.counts.candidateEventCount, apiBrief.counts.candidateEventCount),
            unconfirmedRiskCount: Math.max(curatedBrief.counts.unconfirmedRiskCount, apiBrief.counts.unconfirmedRiskCount),
            calendarEventCount: Math.max(curatedBrief.counts.calendarEventCount, apiBrief.counts.calendarEventCount),
            sourceRefCount: Math.max(curatedBrief.counts.sourceRefCount, apiBrief.counts.sourceRefCount),
          },
          newsHighlights: curatedBrief.newsHighlights,
          watchlist: curatedBrief.watchlist,
          riskPoints: curatedBrief.riskPoints,
        }
      : curatedBrief,
    article_briefs: apiView.article_briefs ?? curated.article_briefs ?? null,
    daily_analysis_triggers: apiView.daily_analysis_triggers ?? curated.daily_analysis_triggers ?? null,
    gold_macro_overview: apiView.gold_macro_overview ?? curated.gold_macro_overview ?? null,
    gold_mainlines: apiView.gold_mainlines ?? curated.gold_mainlines ?? null,
    has_data: true,
  };
}

function _mergeReportInputsIntoViewModel(curated: EventFlowViewModel, raw: Record<string, unknown>): EventFlowViewModel {
  const nextBrief = normalizeBriefSummary(raw.brief_summary) ?? curated.brief_summary ?? null;
  return {
    ...curated,
    brief_summary: nextBrief,
    daily_analysis_triggers: normalizeProgressTriggerBundle(raw.daily_analysis_triggers) ?? curated.daily_analysis_triggers ?? null,
    article_briefs: normalizeArticleBriefBundle(raw.article_briefs) ?? curated.article_briefs ?? null,
    report_input_items: normalizeReportInputItems(raw.actionable_inputs),
    source_refs: asSourceRefs(raw.source_refs).length > 0 ? asSourceRefs(raw.source_refs) : curated.source_refs,
  };
}

// ── Event Flow Actions (write operations) ──────────────────────

export async function linkEventFlowBrief(
  briefId: string,
  body: { target_event_id: string; report_id?: string },
): Promise<EventFlowActionResponse> {
  return fetchJson<EventFlowActionResponse>(`/api/events/briefs/${briefId}/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function ignoreEventFlowBrief(
  briefId: string,
  body: { reason?: string },
): Promise<EventFlowActionResponse> {
  return fetchJson<EventFlowActionResponse>(`/api/events/briefs/${briefId}/ignore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function reviewEventFlowEvent(
  eventId: string,
  body: { reason?: string; review?: string },
): Promise<EventFlowActionResponse> {
  return fetchJson<EventFlowActionResponse>(`/api/events/${eventId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      reason: body.reason ?? body.review,
    }),
  });
}

export async function includeEventFlowReportInput(
  inputId: string,
  body: { reason?: string },
): Promise<EventFlowActionResponse> {
  return fetchJson<EventFlowActionResponse>(`/api/events/report-inputs/${inputId}/include`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function excludeEventFlowReportInput(
  inputId: string,
  body: { reason?: string },
): Promise<EventFlowActionResponse> {
  return fetchJson<EventFlowActionResponse>(`/api/events/report-inputs/${inputId}/exclude`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
