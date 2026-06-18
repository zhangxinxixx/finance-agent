import type {
  EventFlowChainStep,
  EventFlowBriefSummary,
  EventFlowReportInputItem,
  EventFlowRadarAxis,
  EventFlowReportItem,
  EventFlowSentimentItem,
  EventFlowTableRow,
  EventFlowTimelineItem,
  EventImpactSummary,
  EventFlowViewModel,
  EventImportance,
  EventStatus,
  EventImpact,
  EventType,
  PricingStatus,
  EventFlowActionResponse,
  Jin10ArticleBriefBundle,
} from "@/types/event-flow";
import type { SourceRef } from "@/types/common";
import { fetchJson } from "@/adapters/apiClient";

const TIMELINE: EventFlowTimelineItem[] = [
  {
    id: "0",
    time: "08:30 ET",
    date: "06-11",
    title: "美国 5 月 PPI 即将公布，验证 CPI 后通胀压力",
    desc: "PPI 将验证能源冲击是否继续向生产端和服务端扩散，是 CPI 后第一道验证关口。",
    type: "宏观数据",
    importance: "高",
    status: "即将公布",
    impact: "高波动待定",
    source: "BLS",
    assets: "XAUUSD / DXY / US10Y / US2Y",
    period: "日内",
    pricing: "未定价",
  },
  {
    id: "1",
    time: "现货时段",
    date: "06-11",
    title: "黄金自六个月低点反弹，4000 一线成为短线心理支撑",
    desc: "XAUUSD 触及 4022 附近后反弹至 4095 一线，但反弹暂按弱修复而非趋势反转处理。",
    type: "市场价格",
    importance: "高",
    status: "发展中",
    impact: "弱修复承压",
    source: "Reuters",
    assets: "XAUUSD / GC",
    period: "短线",
    pricing: "部分定价",
  },
  {
    id: "2",
    time: "08:30 ET",
    date: "06-10",
    title: "美国 5 月 CPI 同比 4.2%，能源项显著抬升",
    desc: "核心 CPI 同比 2.9%，能源项同比上涨 23.5%，市场更关注油价冲击是否转化为更持久通胀。",
    type: "通胀数据",
    importance: "高",
    status: "已公布",
    impact: "混合偏空",
    source: "BLS",
    assets: "US10Y / DXY / XAUUSD",
    period: "短线",
    pricing: "部分定价",
  },
  {
    id: "3",
    time: "08:30 ET",
    date: "06-05",
    title: "美国 5 月非农新增 17.2 万，强于预期",
    desc: "就业韧性强化 Fed 不急于转鸽的交易逻辑，12 月再加息定价明显升温。",
    type: "就业数据",
    importance: "高",
    status: "已公布",
    impact: "偏空黄金",
    source: "BLS / Reuters",
    assets: "US2Y / US10Y / DXY / XAUUSD",
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
    source: "Reuters",
    assets: "Oil / XAUUSD / Nasdaq / EM FX",
    period: "短中期",
    pricing: "部分定价",
  },
  {
    id: "5",
    time: "官方公告",
    date: "05-22",
    title: "Kevin Warsh 宣誓就任 Fed 主席，并被选为 FOMC 主席",
    desc: "Warsh 更适合放在政策背景层，当前市场更关注其首次完整会议沟通将如何塑造反应函数。",
    type: "政策变量",
    importance: "中",
    status: "已公布",
    impact: "偏鹰扰动",
    source: "Federal Reserve",
    assets: "Fed Funds / DXY / US10Y / XAUUSD",
    period: "中期",
    pricing: "部分定价",
  },
  {
    id: "6",
    time: "月度流向",
    date: "06-04",
    title: "全球黄金 ETF 5 月小幅流出，但年内仍净流入",
    desc: "短线配置资金边际转弱，但年内总流入尚未被完全破坏，中期配置需求仍在。",
    type: "资金流",
    importance: "中",
    status: "已公布",
    impact: "边际偏空",
    source: "World Gold Council",
    assets: "Gold ETF / XAUUSD",
    period: "中期",
    pricing: "已定价",
  },
  {
    id: "7",
    time: "两日会议",
    date: "06-16/17",
    title: "下一次 FOMC 会议临近，关注 Warsh 首次政策沟通",
    desc: "FOMC 将决定当前“能源冲击 + 高利率压力”的链条是被强化还是被缓和。",
    type: "政策会议",
    importance: "高",
    status: "即将公布",
    impact: "事件前谨慎",
    source: "Federal Reserve",
    assets: "Fed Funds / US2Y / XAUUSD",
    period: "事件前",
    pricing: "未定价",
  },
];

const CHAIN: EventFlowChainStep[] = [
  { num: "①", title: "地缘冲突冲击油价", kind: "blue", items: ["美伊紧张与 Hormuz 风险推升能源风险溢价", "油价↑ / 通胀预期↑"], pricing: null },
  { num: "②", title: "CPI 能源项抬升", kind: "warn", items: ["5 月 CPI 同比 4.2%，能源项同比 23.5%", "Fed 转鸽空间下降"], pricing: null },
  { num: "③", title: "非农强化经济韧性", kind: "teal", items: ["5 月非农 17.2 万，高于市场此前预期", "加息定价升温"], pricing: null },
  { num: "④", title: "美债收益率压制黄金", kind: "down", items: ["短端利率更敏感，10Y 高位压制无息资产", "黄金机会成本↑"], pricing: null },
  { num: "⑤", title: "黄金测试 4000 支撑", kind: "warn", items: ["XAUUSD 触及 4022 附近后反弹", "技术反弹，但未反转"], pricing: "部分定价" },
  { num: "⑥", title: "交易判断", kind: "down", items: ["PPI 与 FOMC 前维持高波动", "反弹需等待收益率回落验证"], pricing: null },
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
    label: "Risk Sentiment Score",
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
    title: "美国 5 月 PPI 即将公布，验证 CPI 后通胀压力",
    type: "宏观数据",
    source: "BLS",
    assets: "XAUUSD / DXY / US10Y / US2Y",
    impact: "高波动待定",
    pricing: "未定价",
    period: "日内",
    stars: 5,
  },
  {
    time: "2026-06-11 现货时段",
    title: "黄金自六个月低点反弹，4000 一线成为短线心理支撑",
    type: "市场价格",
    source: "Reuters",
    assets: "XAUUSD / GC",
    impact: "弱修复承压",
    pricing: "部分定价",
    period: "短线",
    stars: 5,
  },
  {
    time: "2026-06-10 08:30 ET",
    title: "美国 5 月 CPI 同比 4.2%，能源项显著抬升",
    type: "通胀数据",
    source: "BLS",
    assets: "US10Y / DXY / XAUUSD",
    impact: "混合偏空",
    pricing: "部分定价",
    period: "短期",
    stars: 5,
  },
  {
    time: "2026-06-05 08:30 ET",
    title: "美国 5 月非农新增 17.2 万，强于预期",
    type: "就业数据",
    source: "BLS / Reuters",
    assets: "US2Y / US10Y / DXY / XAUUSD",
    impact: "偏空黄金",
    pricing: "已定价",
    period: "短中期",
    stars: 5,
  },
  {
    time: "2026-06-10/11 持续",
    title: "美伊紧张局势升级，油价上行、亚洲股市承压",
    type: "地缘/能源",
    source: "Reuters",
    assets: "Oil / XAUUSD / Nasdaq / EM FX",
    impact: "双向波动",
    pricing: "部分定价",
    period: "短中期",
    stars: 4,
  },
  {
    time: "2026-05-22 官方公告",
    title: "Kevin Warsh 宣誓就任 Fed 主席，并被选为 FOMC 主席",
    type: "政策变量",
    source: "Federal Reserve",
    assets: "Fed Funds / DXY / US10Y / XAUUSD",
    impact: "偏鹰扰动",
    pricing: "部分定价",
    period: "中期",
    stars: 4,
  },
  {
    time: "2026-06-04 月度流向",
    title: "全球黄金 ETF 5 月小幅流出，但年内仍净流入",
    type: "资金流",
    source: "World Gold Council",
    assets: "Gold ETF / XAUUSD",
    impact: "边际偏空",
    pricing: "已定价",
    period: "中期",
    stars: 3,
  },
  {
    time: "2026-06-16/17 两日会议",
    title: "下一次 FOMC 会议临近，关注 Warsh 首次政策沟通",
    type: "政策会议",
    source: "Federal Reserve",
    assets: "Fed Funds / US2Y / XAUUSD",
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

export async function fetchEventFlowView(): Promise<EventFlowViewModel> {
  const curated = _getMockViewModel();
  try {
    const [overviewResp, reportInputsResp] = await Promise.all([
      fetch("/api/events/flow/overview"),
      fetch("/api/events/report-inputs"),
    ]);

    let nextData = curated;

    if (overviewResp.ok) {
      const rawOverview = await overviewResp.json();
      if (rawOverview.status !== "unavailable") {
        nextData = _mergeApiIntoCurated(nextData, rawOverview);
      }
    }

    if (reportInputsResp.ok) {
      nextData = _mergeReportInputsIntoViewModel(nextData, await reportInputsResp.json());
    }

    return nextData;
  } catch {
    // API 不可用，fallback 到 mock
  }
  return curated;
}

function _getMockViewModel(): EventFlowViewModel {
  return {
    status: "available",
    source: "event_materials_2026-06-11",
    updated_at: "2026-06-11T12:30:00Z",
    timeline: TIMELINE,
    chain: CHAIN,
    sentiment: SENTIMENT,
    radar: RADAR,
    table: TABLE,
    reports: REPORTS,
    event_impact_summary: null,
    brief_summary: {
      headline: "美国通胀再升温，PPI 前夕黄金测试 4000 心理支撑",
      summary:
        "美国 5 月 CPI 同比升至 4.2%，能源价格是核心扰动项；此前非农就业强于预期，推动市场重新定价 Fed 年内加息概率。中东冲突与油价上行一方面提供黄金避险需求，另一方面又通过通胀和美债收益率抬升黄金机会成本。黄金短线从 4022 附近反弹，但只要实际利率与 10Y 收益率维持高位，反弹仍应先按弱修复处理。",
      status: "available",
      riskLevel: "high",
      verificationStatus: "待 PPI / FOMC 验证",
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
        "黄金从六个月低点附近反弹，4000 美元成为短线心理支撑；但市场仍在等待 PPI 数据确认通胀压力是否进一步扩散。",
        "美国 5 月 CPI 同比 4.2%，核心 CPI 同比 2.9%，能源项同比上涨 23.5%；快速降息路径继续被压缩。",
        "5 月非农新增 17.2 万，强化美国经济韧性；强非农后市场对 12 月加息的概率定价升至约 68.4%。",
        "Warsh 已接任 Fed 主席，6 月 16/17 FOMC 将成为其首次完整政策沟通窗口。",
      ],
      watchlist: [
        "PPI：2026-06-11 08:30 ET，确认 CPI 后通胀是否继续向生产端扩散。",
        "FOMC：2026-06-16/17，观察 Warsh 首次完整政策沟通是否强化偏鹰预期。",
        "XAUUSD 关键位：下方看 4022 / 4000，上方先看 4095-4120。",
        "10Y 美债收益率能否重新跌破 4.50%，决定黄金修复是否能延续。",
        "黄金 ETF 资金流是否继续走弱，验证配置型资金是否停止追涨。",
      ],
      riskPoints: [
        "PPI 若继续超预期，尤其能源与服务价格同步走强，黄金仍可能被利率上行继续压制。",
        "PPI 若低于预期，市场会下修加息路径，黄金存在反弹窗口。",
        "中东冲突若继续升级，黄金可能先受避险推动上冲，随后再被通胀与收益率反复压制。",
        "油价若快速回落，避险溢价与通胀担忧会同步回吐，黄金弹性可能减弱。",
        "FOMC 若偏鹰，Warsh 明确保留加息选项，将抬升 2Y/10Y 并压制黄金。",
        "当前页面未接入实时 K 线、FRED 自动拉取与 CME OI/GEX，本页仅代表事件材料层判断。",
      ],
    },
    article_briefs: null,
    report_input_items: [],
    has_data: true,
    source_refs: [
      { source_ref: "bls:cpi:2026-05", label: "BLS CPI 2026-05", status: "ok" },
      { source_ref: "bls:employment:2026-05", label: "BLS Employment 2026-05", status: "ok" },
      { source_ref: "bls:ppi-calendar:2026-06-11", label: "BLS PPI Schedule", status: "ok" },
      { source_ref: "reuters:gold:2026-06-11", label: "Reuters Gold Rebound", status: "ok" },
      { source_ref: "fed:warsh:2026-05-22", label: "Federal Reserve Warsh Oath", status: "ok" },
      { source_ref: "wgc:etf:2026-05", label: "WGC Gold ETF Flows", status: "ok" },
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
  return value.filter((item): item is SourceRef => Boolean(item) && typeof item === "object");
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

  const headline = asString(marketMainline.headline) || asString(marketMainline.summary);
  const summary = asString(marketMainline.summary, headline);

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
    newsHighlights: normalizeBriefList(reportInputs.news_highlights),
    watchlist: normalizeBriefList(reportInputs.watchlist),
    riskPoints: normalizeBriefList(reportInputs.risk_points),
  };
}

function normalizeArticleBriefBundle(value: unknown): Jin10ArticleBriefBundle | null {
  const raw = asRecord(value);
  if (Object.keys(raw).length === 0) return null;
  const briefs = Array.isArray(raw.briefs) ? raw.briefs.filter((item): item is Jin10ArticleBriefBundle["briefs"][number] => Boolean(item) && typeof item === "object") : [];
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
        title,
        summary: asString(raw.summary, title),
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
  const timeline: EventFlowTimelineItem[] = events.map((e, i) => ({
    id: String(i),
    time: (e.time as string) ?? "",
    date: "",
    title: (e.title as string) ?? "",
    desc: "",
    type: "市场事件" as EventType,
    importance: ((e.importance as string) ?? "低") as EventImportance,
    status: "已公布" as EventStatus,
    impact: "混合" as EventImpact,
    source: (e.source as string) ?? "Jin10",
    assets: "",
    period: "",
    pricing: ((e.pricing as string) ?? "未定价") as PricingStatus,
  }));

  const table: EventFlowTableRow[] = events.map((e) => ({
    time: (e.time as string) ?? "",
    title: (e.title as string) ?? "",
    type: "市场事件" as EventType,
    source: (e.source as string) ?? "Jin10",
    assets: "",
    impact: "混合" as EventImpact,
    pricing: ((e.pricing as string) ?? "未定价") as PricingStatus,
    period: "",
    stars: e.importance === "高" ? 5 : e.importance === "中" ? 3 : 1,
  }));

  return {
    status: (raw.status as EventFlowViewModel["status"]) ?? "partial",
    source: (raw.source as string) ?? "api",
    updated_at: (raw.updated_at as string) ?? new Date().toISOString(),
    timeline,
    chain: CHAIN, // 传导链仍用 mock，后端未实现
    sentiment: SENTIMENT, // 情绪指标仍用 mock
    radar: RADAR, // 风险雷达仍用 mock
    table,
    reports: REPORTS, // 报告仍用 mock
    event_impact_summary: normalizeEventImpactSummary(raw.event_impact_summary),
    brief_summary: briefSummary,
    article_briefs: normalizeArticleBriefBundle(raw.article_briefs),
    report_input_items: [],
    has_data: events.length > 0 || briefSummary !== null,
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
    has_data: true,
  };
}

function _mergeReportInputsIntoViewModel(curated: EventFlowViewModel, raw: Record<string, unknown>): EventFlowViewModel {
  const nextBrief = normalizeBriefSummary(raw.brief_summary) ?? curated.brief_summary ?? null;
  return {
    ...curated,
    brief_summary: nextBrief,
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
