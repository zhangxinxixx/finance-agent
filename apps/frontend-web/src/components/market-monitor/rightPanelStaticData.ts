export const CALENDAR_ITEMS = [
  { time: "05/28", event: "FOMC 会议纪要", impact: "高", change: "+0.3%" },
  { time: "05/30", event: "核心 PCE 物价指数", impact: "高", change: "-0.1%" },
  { time: "06/02", event: "ISM 制造业 PMI", impact: "中", change: "+0.2%" },
  { time: "06/05", event: "非农就业数据", impact: "高", change: "---" },
  { time: "06/07", event: "密歇根消费者信心", impact: "低", change: "---" },
];

export const EVENT_ITEMS = [
  {
    category: "货币政策",
    title: "FOMC 释放鸽派信号",
    impact: "high",
    pricing: "已定价",
    color: "#3b82f6",
  },
  {
    category: "通胀数据",
    title: "核心 PCE 符合预期",
    impact: "medium",
    pricing: "部分定价",
    color: "#f59e0b",
  },
  {
    category: "地缘风险",
    title: "中东局势升温",
    impact: "high",
    pricing: "未定价",
    color: "#f05252",
  },
];

export const REPORT_ITEMS = [
  { title: "黄金周度策略报告", date: "05-26" },
  { title: "美元指数技术分析", date: "05-25" },
  { title: "利率曲线监控周报", date: "05-24" },
];

export const KNOWLEDGE_TAGS = [
  "实际利率定价",
  "美元微笑理论",
  "TIPS收益率",
  "联储资产负债表",
  "逆回购机制",
  "财政账户影响",
];

export const EVENT_IMPACT_COLOR: Record<string, string> = {
  high: "#f05252",
  medium: "#f59e0b",
  low: "var(--fg-5)",
};

export const EVENT_IMPACT_LABEL: Record<string, string> = {
  high: "高影响",
  medium: "中影响",
  low: "低影响",
};
