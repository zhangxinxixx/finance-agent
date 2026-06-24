import type {
  KnowledgeItem,
  KnowledgeItemType,
  KnowledgeItemStatus,
  KnowledgeViewModel,
} from "@/types/knowledge";

const KNOWLEDGE_ITEMS_PATH = "/api/knowledge/items";

const MOCK_ITEMS: KnowledgeItem[] = [
  {
    id: "gold-liquidity-cme",
    title: "黄金 / 宏观流动性与 CME 期权综合分析",
    type: "method",
    typeLabel: "方法论",
    topic: "黄金",
    status: "长期有效",
    summary: "把实际利率、美元、流动性与期权墙位收束为一个可复用的主驱动框架，当前仍是日报、监控和盘前判断的总纲。",
    thesis: "当前框架的价值不是解释所有波动，而是先快速决定主要驱动落在哪条链路上，再把无关噪声排除掉。它最适合盘前定向、盘中验证和日报复盘三个环节串起来用。",
    updated: "今天 07:30",
    createdAt: "2026-04-17 07:30",
    verifiedAt: "2026-05-25 07:30",
    version: "v2.4",
    author: "张锐",
    confidence: 92,
    citations: 128,
    references: 14,
    dashboards: 6,
    agentReady: true,
    playbookReady: true,
    pinned: true,
    reviewQueued: false,
    tags: ["黄金", "CME", "宏观流动性", "期权墙位", "实际利率"],
    scenes: [
      "盘前判断当天主驱动：利率、美元还是墙位压制。",
      "盘中二次确认是否需要切换到事件驱动剧本。",
      "日报里快速统一叙事口径，避免不同模块写出互相冲突的解释。",
    ],
    rules: [
      "实际利率下行且 DXY 走弱时，黄金主方向优先看多，只有当墙位压制极强时才降级为震荡。",
      "若 CME 墙位在当前价格上方密集，先把上涨节奏按受阻处理，再观察突破后的加速条件。",
      "当地缘风险升温却没有带动油价和隐波，优先视为情绪脉冲而不是持续性主线。",
      "任何结论都必须回到至少两条独立数据链验证，避免把单一报价噪声沉淀成知识。",
    ],
    inputs: [
      "10Y 实际利率",
      "美元指数 DXY",
      "XAUUSD 现货",
      "CME OI / Delta / GEX",
      "30D 隐含波动率",
      "Market Odds / 利率预期",
    ],
    monitorMetrics: [
      { label: "10Y 实际利率", value: "2.11%", change: "-1.6bp", tone: "negative" },
      { label: "美元指数 DXY", value: "106.02", change: "-0.46%", tone: "negative" },
      { label: "XAUUSD", value: "3333.40", change: "+0.82%", tone: "positive" },
      { label: "30D 隐波", value: "18.6", change: "-0.4", tone: "neutral" },
    ],
    evidence: [
      { title: "近三个月验证摘要", body: "12 次方向判断里有 9 次主驱动命中。误判主要发生在事件流突然接管、但监控面板仍按宏观主线解释的时候。", meta: "验证批次 2026-W20 / 命中率 75%" },
      { title: "冲突案例", body: "当 DXY 与实际利率同向走弱，但上方 WallScore 大于 80 时，黄金容易出现冲高回落，框架里必须先插入墙位约束。", meta: "案例 04-29 / 05-07" },
      { title: "下游依赖", body: "黄金总览、期权结构页、日报 Prompt 规范和盘前要点都直接引用该框架字段。", meta: "Dashboard 6 / Agent 3" },
    ],
    downstream: [
      { name: "黄金总览页", state: "实时引用", note: "驱动判断卡片 + 方向结论" },
      { name: "CME 期权结构", state: "部分引用", note: "墙位优先级、Breakout 观察条件" },
      { name: "黄金日报 Prompt", state: "强依赖", note: "结论段和风险段都从这里取规则" },
    ],
    timeline: [
      { time: "07:30", title: "完成今日验证", copy: "实际利率和美元继续共振转弱，框架维持多头优先，但因为墙位在 3350 上方密集，节奏判断仍保守。" },
      { time: "昨天", title: "补充 CME 墙位约束", copy: "新增当 WallScore > 80 且 Put-GEX 重新转正时，对上涨节奏减速处理的规则。" },
      { time: "05-18", title: "合并流动性子框架", copy: "把 TGA / RRP / QT 变化统一到流动性分层描述，减少日报里重复判断。" },
    ],
    citationFlow: {
      upstream: [
        { title: "实际利率驱动框架与黄金定价", meta: "方法论 / v1.8 / 引用 74" },
        { title: "流动性指标体系与市场联动研究", meta: "研究笔记 / v1.4 / 引用 52" },
        { title: "CME 期权数据字典与字段说明", meta: "数据字典 / v3.0 / 引用 88" },
      ],
      downstream: [
        { title: "黄金日报分析 Prompt 规范", meta: "Agent 规则 / v4.2 / 引用 205" },
        { title: "CME 期权墙位监控与策略应用指南", meta: "Playbook / v1.5 / 引用 94" },
        { title: "盘前三段式结论模板", meta: "模板 / v1.2 / 引用 39" },
      ],
    },
  },
  {
    id: "cme-wall-monitor",
    title: "CME 期权墙位监控与策略应用指南",
    type: "playbook",
    typeLabel: "Playbook",
    topic: "CME",
    status: "长期有效",
    summary: "把 Put-GEX、Call Wall、Flip 区间、WallScore 变成盘中可执行动作，而不是只做静态表格展示。",
    thesis: "墙位知识的目标不是解释图，而是提前定义在不同墙位结构下应该做什么、不应该做什么，让盘中反应速度比解释速度更快。",
    updated: "昨天",
    createdAt: "2026-04-19 09:10",
    verifiedAt: "2026-05-24 22:05",
    version: "v1.5",
    author: "张锐",
    confidence: 88,
    citations: 94,
    references: 11,
    dashboards: 4,
    agentReady: true,
    playbookReady: true,
    pinned: true,
    reviewQueued: false,
    tags: ["CME", "期权墙位", "Playbook", "盘中策略"],
    scenes: [
      "盘前根据 Flip 和主墙位确定观察区间。",
      "盘中价格贴近墙位时判断是吸附、回落还是突破。",
      "与黄金主框架结合，限制追价和逆势动作。",
    ],
    rules: [
      "Put-GEX 转正且价格回到主地板上方，优先视为下行保护增强。",
      "WallScore 超过 80 时，不再用裸价格突破判断，必须联动成交与隐波。",
      "若 Call Wall 快速上移，先视为做市商对冲结构改变，而不是直接看多。",
    ],
    inputs: ["Call Wall", "Put Wall", "Flip", "GEX", "WallScore", "隐波斜率"],
    monitorMetrics: [
      { label: "主 Call Wall", value: "3380", change: "+20", tone: "neutral" },
      { label: "主 Put Wall", value: "3300", change: "0", tone: "neutral" },
      { label: "Flip Zone", value: "3342", change: "+6", tone: "positive" },
      { label: "WallScore", value: "84", change: "+4", tone: "negative" },
    ],
    evidence: [
      { title: "突破误判复盘", body: "本月两次冲高回落都发生在 WallScore 高位、但日报没有明确写出追价禁令的场景。", meta: "05-06 / 05-16" },
      { title: "跨模块收益", body: "把墙位动作沉淀为 Playbook 后，盘前会议和盘中提示词能直接复用，不再重复解释字段。", meta: "会议纪要 7 次" },
    ],
    downstream: [
      { name: "期权结构页", state: "强依赖", note: "主图和提醒卡片直接引用" },
      { name: "盘中提示", state: "实时调用", note: "触及墙位时触发动作建议" },
    ],
    timeline: [
      { time: "昨天", title: "补充高 WallScore 禁追规则", copy: "把高压区间下的禁止动作写入规则卡，减少盘中自由裁量。" },
      { time: "05-20", title: "新增主地板验证字段", copy: "要求 Put-GEX 转正必须和价格站回主地板同时满足。" },
    ],
    citationFlow: {
      upstream: [{ title: "CME 期权数据字典与字段说明", meta: "数据字典 / v3.0" }],
      downstream: [{ title: "盘中提示模板", meta: "Agent 规则 / v1.7" }, { title: "黄金总览主结论", meta: "总览卡片 / 实时引用" }],
    },
  },
  {
    id: "real-rate-framework",
    title: "实际利率驱动框架与黄金定价",
    type: "method",
    typeLabel: "方法论",
    topic: "实际利率",
    status: "长期有效",
    summary: "黄金长期定价最稳定的锚点之一，但需要和美元及流动性分层使用，不能孤立外推。",
    thesis: "实际利率决定方向的可靠性仍然最高，但对节奏解释不足，所以必须和 DXY、流动性、事件流做多层过滤。",
    updated: "昨天",
    createdAt: "2026-04-11 08:40",
    verifiedAt: "2026-05-24 19:20",
    version: "v1.8",
    author: "张锐",
    confidence: 85,
    citations: 74,
    references: 9,
    dashboards: 3,
    agentReady: true,
    playbookReady: false,
    pinned: false,
    reviewQueued: false,
    tags: ["黄金", "实际利率", "宏观"],
    scenes: ["判断趋势是否来自真实利率压缩。", "为日报中的方向段提供最稳妥的解释锚点。"],
    rules: [
      "只要实际利率和美元出现明显背离，就暂停单变量外推，优先回到综合框架。",
      "对事件日和非农周，实际利率更多用来校正中线方向，不直接决定盘中动作。",
    ],
    inputs: ["TIPS 10Y", "Breakeven 10Y", "DXY", "XAUUSD"],
    monitorMetrics: [
      { label: "TIPS 10Y", value: "2.11%", change: "-1.6bp", tone: "negative" },
      { label: "Breakeven", value: "2.29%", change: "+0.3bp", tone: "positive" },
      { label: "DXY", value: "106.02", change: "-0.46%", tone: "negative" },
      { label: "XAUUSD", value: "3333.40", change: "+0.82%", tone: "positive" },
    ],
    evidence: [{ title: "过去 6 周回测", body: "只看实际利率的胜率稳定，但对非农和 CPI 日的盘中波动解释不足。", meta: "回测窗口 6W" }],
    downstream: [{ name: "黄金总览页", state: "中线解释", note: "用于中线偏多 / 偏空" }],
    timeline: [{ time: "05-21", title: "修正背离处理", copy: "增加美元走强时不追随利率结论的约束。" }],
    citationFlow: { upstream: [], downstream: [{ title: "黄金综合框架", meta: "方法论 / v2.4" }] },
  },
  {
    id: "liquidity-linkage",
    title: "流动性指标体系与市场联动研究",
    type: "note",
    typeLabel: "研究笔记",
    topic: "流动性",
    status: "长期有效",
    summary: "把 TGA、RRP、QT、准备金和风险资产反馈整理成观测面板，为黄金框架提供第二层上下文。",
    thesis: "流动性并不总是直接推动黄金，但它决定风险资产能否接住事件冲击，也决定宏观框架里哪些信号更容易被放大。",
    updated: "04-16",
    createdAt: "2026-04-16 11:10",
    verifiedAt: "2026-05-21 18:12",
    version: "v1.4",
    author: "李墨",
    confidence: 81,
    citations: 52,
    references: 7,
    dashboards: 2,
    agentReady: true,
    playbookReady: false,
    pinned: true,
    reviewQueued: false,
    tags: ["流动性", "TGA", "RRP", "研究笔记"],
    scenes: ["判断风险偏好切换是否值得提高权重。", "辅助解释为什么黄金和美股会短暂同涨。"],
    rules: [
      "TGA 回落与 RRP 同时释放时，先把风险偏好提高一级，再看黄金是否同步受益。",
      "当 QT 继续推进但准备金没有明显收缩时，不把流动性恶化当成当天主因。",
    ],
    inputs: ["TGA", "RRP", "Fed Balance Sheet", "SOFR", "风险资产"],
    monitorMetrics: [
      { label: "TGA", value: "-64B", change: "周变动", tone: "positive" },
      { label: "RRP", value: "421B", change: "-18B", tone: "positive" },
      { label: "QT", value: "持续", change: "低速", tone: "neutral" },
      { label: "风险偏好", value: "中偏强", change: "+1", tone: "positive" },
    ],
    evidence: [{ title: "最近同步案例", body: "5 月两次黄金与纳指同涨都发生在流动性改善和实际利率回落共振的场景。", meta: "05-09 / 05-17" }],
    downstream: [{ name: "黄金综合框架", state: "辅助依赖", note: "第二层过滤条件" }],
    timeline: [{ time: "05-17", title: "补充风险偏好层", copy: "把流动性变化和风险资产反应合并成统一记录格式。" }],
    citationFlow: { upstream: [], downstream: [{ title: "黄金综合框架", meta: "方法论 / v2.4" }] },
  },
  {
    id: "geo-risk-review",
    title: "地缘风险事件对黄金的影响复盘",
    type: "review",
    typeLabel: "复盘",
    topic: "地缘风险",
    status: "阶段有效",
    summary: "整理美伊谈判、红海冲突等事件在黄金、油价、隐波和美元上的传导差异，防止把所有风险事件一概写成利多黄金。",
    thesis: "事件本身不会自动变成持续性主线，只有当油价、隐波、美元或利率预期出现联动时，地缘风险才值得被升级到主驱动层。",
    updated: "04-16",
    createdAt: "2026-04-12 16:20",
    verifiedAt: "2026-05-10 10:10",
    version: "v1.1",
    author: "李墨",
    confidence: 68,
    citations: 31,
    references: 4,
    dashboards: 1,
    agentReady: true,
    playbookReady: false,
    pinned: false,
    reviewQueued: true,
    tags: ["地缘风险", "复盘", "黄金"],
    scenes: ["事件流页的解释校验。", "日报里决定是写成脉冲还是持续逻辑。"],
    rules: [
      "只有油价与隐波一起抬升，才把地缘事件从标题噪声升级为资产主线。",
      "若美元同步走强，要重新评估黄金是否真的能维持涨幅。",
    ],
    inputs: ["新闻流", "油价", "隐波", "DXY", "黄金"],
    monitorMetrics: [
      { label: "事件热度", value: "72", change: "+11", tone: "positive" },
      { label: "油价联动", value: "弱", change: "无共振", tone: "neutral" },
      { label: "隐波响应", value: "+0.2", change: "偏弱", tone: "neutral" },
      { label: "复核倒计时", value: "7d", change: "待处理", tone: "negative" },
    ],
    evidence: [{ title: "复核原因", body: "样本集中在中东冲突，对其他类型地缘事件的可迁移性仍不足。", meta: "待补欧洲样本" }],
    downstream: [{ name: "事件流页", state: "条件引用", note: "解释层使用" }],
    timeline: [{ time: "04-26", title: "标记阶段有效", copy: "缺少更多异质事件样本，先降级为阶段知识。" }],
    citationFlow: { upstream: [], downstream: [{ title: "事件流页解释模板", meta: "模板 / 条件引用" }] },
  },
  {
    id: "agent-prompt-spec",
    title: "黄金日报分析 Prompt 规范",
    type: "agent",
    typeLabel: "Agent 规则",
    topic: "Agent规则",
    status: "长期有效",
    summary: "规定日报 Agent 在结论段、证据段、风险段调用哪些知识块，保证输出风格和推理顺序稳定。",
    thesis: "如果 Prompt 只是堆资料，Agent 会把结构写散；只有把调用顺序、证据优先级和禁用表述一起写成规则，日报才会长期稳定。",
    updated: "04-15",
    createdAt: "2026-04-15 09:00",
    verifiedAt: "2026-05-25 06:50",
    version: "v4.2",
    author: "张锐",
    confidence: 95,
    citations: 205,
    references: 18,
    dashboards: 0,
    agentReady: true,
    playbookReady: false,
    pinned: false,
    reviewQueued: false,
    tags: ["Prompt", "Agent规则", "黄金"],
    scenes: ["日报 Agent 输出结构控制。", "盘前摘要和盘中提示的共用底座。"],
    rules: [
      "结论段永远先写主驱动，再写节奏约束，最后写风险切换条件。",
      "没有两条以上证据链时，禁止输出\"确定性极强\"类措辞。",
      "引用事件流时必须说明它是否已经接管宏观框架。",
    ],
    inputs: ["黄金综合框架", "墙位 Playbook", "事件流", "市场监控"],
    monitorMetrics: [
      { label: "本周调用", value: "205", change: "+18", tone: "positive" },
      { label: "规则版本", value: "4.2", change: "已生效", tone: "positive" },
      { label: "结构稳定度", value: "94%", change: "+3%", tone: "positive" },
      { label: "需人工修正", value: "2/26", change: "下降", tone: "positive" },
    ],
    evidence: [{ title: "输出质量监控", body: "升级到 v4.2 后，日报里主驱动和风险段的冲突减少，人工改写次数显著下降。", meta: "近 26 篇日报" }],
    downstream: [{ name: "黄金日报 Agent", state: "强依赖", note: "模板入口" }],
    timeline: [{ time: "今天", title: "同步最新综合框架", copy: "调用顺序改成先综合框架后墙位 Playbook。" }],
    citationFlow: {
      upstream: [{ title: "黄金综合框架", meta: "方法论 / v2.4" }, { title: "墙位 Playbook", meta: "Playbook / v1.5" }],
      downstream: [{ title: "黄金日报 Agent", meta: "每日调用" }],
    },
  },
  {
    id: "cme-dictionary",
    title: "CME 期权数据字典与字段说明",
    type: "dict",
    typeLabel: "数据字典",
    topic: "CME",
    status: "长期有效",
    summary: "统一字段口径，特别是 WallScore、GEX、Flip、主墙位和补充列的解释，减少图表与文案脱节。",
    thesis: "数据字典本身不负责给结论，但它决定所有人是不是在说同一件事。数据层一旦飘，后面的框架和 Agent 规则都会跟着飘。",
    updated: "04-14",
    createdAt: "2026-04-14 18:30",
    verifiedAt: "2026-05-18 12:00",
    version: "v3.0",
    author: "张锐",
    confidence: 97,
    citations: 88,
    references: 21,
    dashboards: 5,
    agentReady: true,
    playbookReady: false,
    pinned: false,
    reviewQueued: false,
    tags: ["CME", "数据字典", "字段说明"],
    scenes: ["期权结构页字段统一。", "Agent 规则取字段解释。"],
    rules: [
      "任何新字段进入图表前必须先补充字典描述、单位和用途。",
      "WallScore 和 Flip 属于解释字段，必须搭配观测上下文使用，禁止孤立输出。",
    ],
    inputs: ["原始 CME 数据表", "派生字段", "图表列映射"],
    monitorMetrics: [
      { label: "字段总数", value: "43", change: "+2", tone: "positive" },
      { label: "图表覆盖", value: "100%", change: "稳定", tone: "positive" },
      { label: "Agent 映射", value: "11", change: "+1", tone: "positive" },
      { label: "待命名", value: "0", change: "清零", tone: "positive" },
    ],
    evidence: [{ title: "最近变更", body: "补充 WallScore 解释与主地板字段定义后，图表与日报用词已统一。", meta: "05-18" }],
    downstream: [{ name: "期权结构页", state: "底层依赖", note: "字段说明和 tooltip" }],
    timeline: [{ time: "05-18", title: "补主地板字段", copy: "统一 Put-GEX 转正和主地板的命名。" }],
    citationFlow: {
      upstream: [],
      downstream: [{ title: "墙位 Playbook", meta: "Playbook / 引用解释字段" }, { title: "期权结构页", meta: "Tooltip / legend" }],
    },
  },
];

const TOPIC_OPTIONS = ["全部主题", "黄金", "实际利率", "流动性", "地缘风险", "CME", "Agent规则"];
const STATUS_OPTIONS: Array<"全部状态" | KnowledgeItemStatus> = ["全部状态", "长期有效", "待复核", "阶段有效"];

export const KNOWLEDGE_TOPICS = TOPIC_OPTIONS;
export const KNOWLEDGE_STATUSES = STATUS_OPTIONS;

function computeStats(items: KnowledgeItem[]) {
  const reviewQueueCount = items.filter((item) => item.reviewQueued).length;
  const pinnedCount = items.filter((item) => item.pinned).length;
  const agentReadyCount = items.filter((item) => item.agentReady).length;
  const playbookCount = items.filter((item) => item.type === "playbook").length;
  const playbookCandidateCount = items.filter((item) => item.type !== "playbook" && item.confidence >= 80).length;
  const playbookPublishedCount = items.filter((item) => item.type === "playbook" && item.agentReady).length;
  const totalCitations = items.reduce((sum, item) => sum + item.citations, 0);

  return {
    total: items.length,
    agentReady: agentReadyCount,
    playbookCount,
    playbookCandidateCount,
    playbookPublishedCount,
    reviewQueueCount,
    pinnedCount,
    totalCitations,
  };
}

function readNumber(record: Record<string, unknown>, keys: string[], fallback: number): number {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return fallback;
}

function normalizeApiStats(rawStats: unknown, items: KnowledgeItem[]): KnowledgeViewModel["stats"] {
  const fallback = computeStats(items);
  if (!rawStats || typeof rawStats !== "object") {
    return fallback;
  }

  const record = rawStats as Record<string, unknown>;
  return {
    total: readNumber(record, ["total"], fallback.total),
    agentReady: readNumber(record, ["agentReady", "agent_ready"], fallback.agentReady),
    playbookCount: readNumber(record, ["playbookCount", "playbook_count"], fallback.playbookCount),
    playbookCandidateCount: readNumber(record, ["playbookCandidateCount", "playbook_candidate_count"], fallback.playbookCandidateCount),
    playbookPublishedCount: readNumber(record, ["playbookPublishedCount", "playbook_published_count"], fallback.playbookPublishedCount),
    reviewQueueCount: readNumber(record, ["reviewQueueCount", "review_queue_count"], fallback.reviewQueueCount),
    pinnedCount: readNumber(record, ["pinnedCount", "pinned_count"], fallback.pinnedCount),
    totalCitations: readNumber(record, ["totalCitations", "total_citations"], fallback.totalCitations),
  };
}

function isKnowledgeItem(value: unknown): value is KnowledgeItem {
  return Boolean(value && typeof value === "object" && typeof (value as KnowledgeItem).id === "string");
}

function normalizeApiStatus(status: unknown): KnowledgeViewModel["status"] {
  switch (status) {
    case "available":
    case "partial":
    case "unavailable":
    case "error":
      return status;
    case "ok":
    case "live":
      return "available";
    case "warn":
    case "fallback":
      return "partial";
    default:
      return "available";
  }
}

async function fetchKnowledgeItemDetail(itemId: string): Promise<KnowledgeItem | null> {
  const mockItem = MOCK_ITEMS.find((item) => item.id === itemId) ?? null;
  if (mockItem) {
    return mockItem;
  }

  const resp = await fetch(`${KNOWLEDGE_ITEMS_PATH}/${encodeURIComponent(itemId)}`);
  if (resp.status === 404) {
    return null;
  }
  if (!resp.ok) {
    return null;
  }

  const raw = (await resp.json()) as unknown;
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const record = raw as Record<string, unknown>;
  if (record.status === "unavailable") {
    return null;
  }

  const candidate = isKnowledgeItem(record.item) ? record.item : raw;
  return isKnowledgeItem(candidate) ? candidate : null;
}

function mergeSelectedItem(items: KnowledgeItem[], selectedItem: KnowledgeItem | null): KnowledgeItem[] {
  if (!selectedItem || items.some((item) => item.id === selectedItem.id)) {
    return items;
  }
  return [selectedItem, ...items];
}

export async function fetchKnowledgeView(options?: {
  search?: string;
  topic?: string;
  status?: string;
  typeTab?: string;
  selectedId?: string | null;
}): Promise<KnowledgeViewModel> {
  // 优先尝试后端 API
  try {
    const resp = await fetch(KNOWLEDGE_ITEMS_PATH);
    if (resp.ok) {
      const raw = (await resp.json()) as Record<string, unknown>;
      const apiItems: KnowledgeItem[] = Array.isArray(raw.items) ? raw.items.filter(isKnowledgeItem) : [];
      const { selectedId = null } = options ?? {};
      let selectedItem = selectedId ? await fetchKnowledgeItemDetail(selectedId) : null;
      const selectedExistsInList = selectedId ? apiItems.some((item) => item.id === selectedId) : false;
      let effectiveId = selectedItem?.id ?? (selectedExistsInList ? selectedId : apiItems[0]?.id ?? null);

      if (!selectedItem && effectiveId) {
        selectedItem = await fetchKnowledgeItemDetail(effectiveId);
      }

      selectedItem = selectedItem ?? (effectiveId ? apiItems.find((item) => item.id === effectiveId) ?? null : null);
      effectiveId = selectedItem?.id ?? effectiveId;

      const items = mergeSelectedItem(apiItems, selectedItem);
      if ((raw.status !== "unavailable" || selectedItem) && items.length > 0) {
        // 后端有真实数据时直接返回
        return {
          status: normalizeApiStatus(raw.status),
          source: "api",
          updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null,
          items,
          selectedId: effectiveId,
          selectedItem,
          stats: normalizeApiStats(raw.stats, items),
          has_data: true,
          source_refs: Array.isArray(raw.source_refs) ? raw.source_refs : [],
        };
      }
    }
  } catch {
    // API 不可用，fallback 到 mock
  }

  // ── Mock fallback ──
  const { search = "", topic = "全部主题", status = "全部状态", typeTab = "all", selectedId = null } = options ?? {};

  const filtered = MOCK_ITEMS.filter((item) => {
    const matchesSearch =
      !search ||
      [item.title, item.summary, item.thesis, item.tags.join(" "), item.inputs.join(" ")]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase());
    const matchesTopic = topic === "全部主题" || item.topic === topic || item.tags.includes(topic);
    const matchesStatus = status === "全部状态" || item.status === status;
    const matchesType = typeTab === "all" || item.type === typeTab;
    return matchesSearch && matchesTopic && matchesStatus && matchesType;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    if (a.reviewQueued !== b.reviewQueued) return a.reviewQueued ? -1 : 1;
    return b.citations - a.citations;
  });

  const effectiveId = selectedId && sorted.some((item) => item.id === selectedId)
    ? selectedId
    : sorted[0]?.id ?? null;

  const selectedItem = effectiveId ? sorted.find((item) => item.id === effectiveId) ?? null : null;

  return Promise.resolve({
    items: sorted,
    selectedId: effectiveId,
    selectedItem,
    stats: computeStats(MOCK_ITEMS),
  });
}

export function fetchAllKnowledgeItems(): Promise<KnowledgeItem[]> {
  return Promise.resolve(MOCK_ITEMS);
}
