import type { DagEdge, DagNodeSpec, DagNodeStatus, DagNodeType } from "@/types/pipeline-dag";

export type DagGroupId =
  | "data_collection"
  | "raw_archive"
  | "raw_parse"
  | "feature_processing"
  | "analysis_agents"
  | "decision_synthesis"
  | "final_presentation";

export interface DagGroupMeta {
  id: DagGroupId;
  label: string;
  type: DagNodeType;
  module: string;
  order: number;
  summary: string;
  tasks: DagGroupTaskMeta[];
}

export interface DagGroupTaskMeta {
  id: string;
  label: string;
  description: string;
}

export const DAG_GROUPS: Record<DagGroupId, DagGroupMeta> = {
  data_collection: {
    id: "data_collection",
    label: "采集相关",
    type: "collector",
    module: "collectors",
    order: 1,
    summary: "FRED、Fed、Treasury、CME、Jin10、行情等源数据采集",
    tasks: [
      { id: "fred_source", label: "FRED", description: "FRED macro series" },
      { id: "fed_source", label: "Fed", description: "Federal Reserve sources" },
      { id: "treasury_source", label: "Treasury", description: "US Treasury data" },
      { id: "dxy_source", label: "DXY", description: "Dollar index source" },
      { id: "market_price_source", label: "行情", description: "XAUUSD / candles / market price" },
      { id: "cme_bulletin_source", label: "CME", description: "CME Daily Bulletin" },
      { id: "jin10_flash_source", label: "金十快讯", description: "Jin10 realtime messages" },
      { id: "jin10_report_source", label: "金十报告", description: "Jin10 article/report source" },
    ],
  },
  raw_archive: {
    id: "raw_archive",
    label: "Raw 归档",
    type: "collector",
    module: "raw",
    order: 2,
    summary: "保存原始响应、PDF、HTML、消息与上传文件",
    tasks: [
      { id: "macro_api_raw", label: "宏观 Raw", description: "Macro API raw JSON" },
      { id: "market_api_raw", label: "行情 Raw", description: "Market candle raw payload" },
      { id: "cme_pdf_raw", label: "CME PDF", description: "CME bulletin PDF archive" },
      { id: "jin10_message_raw", label: "快讯 Raw", description: "Jin10 message raw archive" },
      { id: "jin10_report_raw", label: "报告 Raw", description: "Jin10 report/article raw archive" },
      { id: "artifact_raw", label: "文件 Raw", description: "Uploaded/generated artifact archive" },
    ],
  },
  raw_parse: {
    id: "raw_parse",
    label: "Raw 解析",
    type: "parser",
    module: "parsers",
    order: 3,
    summary: "把原始文件和响应解析成结构化记录",
    tasks: [
      { id: "fred_parse", label: "FRED解析", description: "FRED time series normalization" },
      { id: "treasury_parse", label: "Treasury解析", description: "Treasury curve parsing" },
      { id: "dxy_parse", label: "DXY解析", description: "Dollar index parsing" },
      { id: "cme_bulletin_parse", label: "CME公报", description: "CME bulletin parser" },
      { id: "cme_options_parse", label: "CME期权", description: "CME options table parser" },
      { id: "jin10_flash_parse", label: "快讯解析", description: "Jin10 flash parsing" },
      { id: "jin10_report_parse", label: "报告解析", description: "Jin10 report/article parsing" },
      { id: "market_candle_parse", label: "K线解析", description: "Market candle parsing" },
    ],
  },
  feature_processing: {
    id: "feature_processing",
    label: "二次加工",
    type: "features",
    module: "features",
    order: 4,
    summary: "指标计算、快照合并、期权墙、事件特征与市场状态加工",
    tasks: [
      { id: "real_rate_feature", label: "实际利率", description: "Real rate and rate spread features" },
      { id: "liquidity_feature", label: "流动性", description: "Liquidity and macro regime features" },
      { id: "option_wall", label: "期权墙", description: "CME wall / GEX / OI" },
      { id: "positioning_feature", label: "持仓特征", description: "COT/positioning features" },
      { id: "technical_feature", label: "技术结构", description: "Technical trend/level features" },
      { id: "event_flow_feature", label: "事件特征", description: "Impact/sentiment/event flow" },
      { id: "oil_geopolitical_feature", label: "石油地缘", description: "Oil and geopolitical shock features" },
      { id: "source_health_check", label: "数据健康门控", description: "Gold v3 P0/P1/P2 source health gate" },
      { id: "mainline_attribution", label: "主线归因", description: "Gold mainline driver attribution" },
      { id: "transmission_chain_detection", label: "传导链识别", description: "Cross-market transmission chain detection" },
      { id: "market_validation", label: "市场验证", description: "Market reaction validation" },
      { id: "snapshot_merge", label: "快照合并", description: "analysis snapshot merge" },
    ],
  },
  analysis_agents: {
    id: "analysis_agents",
    label: "分析 Agent",
    type: "analysis",
    module: "agents",
    order: 5,
    summary: "宏观、CME、风险、技术、持仓、新闻等 Agent 分析",
    tasks: [
      { id: "macro_agent", label: "宏观 Agent", description: "macro liquidity" },
      { id: "cme_agent", label: "CME Agent", description: "options / positioning" },
      { id: "risk_agent", label: "风险 Agent", description: "risk regime" },
      { id: "technical_agent", label: "技术 Agent", description: "technical structure" },
      { id: "positioning_agent", label: "持仓 Agent", description: "positioning analysis" },
      { id: "news_agent", label: "新闻 Agent", description: "news/event impact" },
      { id: "market_odds_agent", label: "概率 Agent", description: "market odds analysis" },
      { id: "gold_mainline_agent", label: "黄金主线 Agent", description: "gold mainline synthesis agent" },
    ],
  },
  decision_synthesis: {
    id: "decision_synthesis",
    label: "合成决策",
    type: "analysis",
    module: "coordinator",
    order: 6,
    summary: "协调 Agent 聚合输出、冲突检测、置信度和风险归纳",
    tasks: [
      { id: "coordinator", label: "协调器", description: "agent output aggregation" },
      { id: "driver_decomposition", label: "驱动拆解", description: "bullish/bearish driver decomposition" },
      { id: "gold_macro_overview", label: "黄金总览模型", description: "gold macro overview read model" },
      { id: "verification_matrix", label: "待验证矩阵", description: "driver verification matrix" },
      { id: "review_gate", label: "ReviewGate", description: "source health and conclusion quality gate" },
      { id: "conflict_check", label: "冲突检测", description: "bias/confidence conflicts" },
      { id: "bias_confidence", label: "Bias置信", description: "weighted bias and confidence" },
      { id: "final_report_json", label: "报告 JSON", description: "final report payload" },
    ],
  },
  final_presentation: {
    id: "final_presentation",
    label: "最终展现",
    type: "output",
    module: "renderer",
    order: 7,
    summary: "日报、策略卡片、Dashboard、调度页面与飞书监控展现",
    tasks: [
      { id: "daily_report", label: "日报", description: "markdown/json report" },
      { id: "strategy_card", label: "策略卡片", description: "strategy card artifact" },
      { id: "dashboard", label: "Dashboard", description: "frontend read model" },
      { id: "gold_mainlines_page", label: "黄金主线页", description: "gold mainline analysis page" },
      { id: "oil_geopolitics_page", label: "石油地缘页", description: "oil geopolitics analysis page" },
      { id: "processing_monitor", label: "加工监控", description: "processing trace monitor" },
      { id: "market_monitor", label: "市场监控", description: "market monitor page" },
      { id: "feishu_monitor", label: "飞书监控", description: "message monitor view" },
      { id: "source_trace", label: "溯源面板", description: "source trace display" },
    ],
  },
};

export const DAG_GROUP_ORDER = Object.values(DAG_GROUPS)
  .sort((a, b) => a.order - b.order)
  .map((item) => item.id);

export interface DagTaskDataFlowEdge {
  from: string;
  to: string;
  edge_type: DagEdge["edge_type"];
  stage: string;
  data_contract?: Pick<DagEdge["data_contract"], "fields">;
}

const GOLD_MAINLINE_DATA_CONTRACT_FIELDS = [
  "mainlines",
  "primary_mainline",
  "transmission_chains",
  "bullish_drivers",
  "bearish_drivers",
  "dominant_driver",
  "verification_needed",
  "theme_rankings",
  "gold_phase",
  "war_oil_rate_chain",
  "source_health",
  "p0_missing",
  "p1_missing",
  "p2_missing",
  "mainline_impact",
  "can_build_gold_macro_overview",
  "processing_trace_id",
];

function goldMainlineEdge(edge: Omit<DagTaskDataFlowEdge, "data_contract">): DagTaskDataFlowEdge {
  return {
    ...edge,
    data_contract: {
      fields: [...GOLD_MAINLINE_DATA_CONTRACT_FIELDS],
    },
  };
}

export const DAG_TASK_DATA_FLOW_EDGES: DagTaskDataFlowEdge[] = [
  { from: "fred_source", to: "macro_api_raw", edge_type: "data_flow", stage: "FRED→宏观 Raw" },
  { from: "fed_source", to: "macro_api_raw", edge_type: "data_flow", stage: "Fed→宏观 Raw" },
  { from: "treasury_source", to: "macro_api_raw", edge_type: "data_flow", stage: "Treasury→宏观 Raw" },
  { from: "dxy_source", to: "macro_api_raw", edge_type: "data_flow", stage: "DXY→宏观 Raw" },
  { from: "market_price_source", to: "market_api_raw", edge_type: "data_flow", stage: "行情→行情 Raw" },
  { from: "cme_bulletin_source", to: "cme_pdf_raw", edge_type: "data_flow", stage: "CME→CME PDF" },
  { from: "jin10_flash_source", to: "jin10_message_raw", edge_type: "data_flow", stage: "金十快讯→快讯 Raw" },
  { from: "jin10_report_source", to: "jin10_report_raw", edge_type: "data_flow", stage: "金十报告→报告 Raw" },

  { from: "macro_api_raw", to: "fred_parse", edge_type: "data_flow", stage: "宏观 Raw→FRED 解析" },
  { from: "macro_api_raw", to: "treasury_parse", edge_type: "data_flow", stage: "宏观 Raw→Treasury 解析" },
  { from: "macro_api_raw", to: "dxy_parse", edge_type: "data_flow", stage: "宏观 Raw→DXY 解析" },
  { from: "market_api_raw", to: "market_candle_parse", edge_type: "data_flow", stage: "行情 Raw→K线解析" },
  { from: "cme_pdf_raw", to: "cme_bulletin_parse", edge_type: "data_flow", stage: "CME PDF→公报解析" },
  { from: "cme_bulletin_parse", to: "cme_options_parse", edge_type: "data_flow", stage: "公报解析→期权解析" },
  { from: "jin10_message_raw", to: "jin10_flash_parse", edge_type: "data_flow", stage: "快讯 Raw→快讯解析" },
  { from: "jin10_report_raw", to: "jin10_report_parse", edge_type: "data_flow", stage: "报告 Raw→报告解析" },
  { from: "artifact_raw", to: "jin10_report_parse", edge_type: "dependency", stage: "文件 Raw→报告解析" },

  { from: "fred_parse", to: "real_rate_feature", edge_type: "data_flow", stage: "FRED解析→实际利率" },
  { from: "treasury_parse", to: "real_rate_feature", edge_type: "data_flow", stage: "Treasury解析→实际利率" },
  { from: "fred_parse", to: "liquidity_feature", edge_type: "data_flow", stage: "FRED解析→流动性" },
  { from: "dxy_parse", to: "liquidity_feature", edge_type: "data_flow", stage: "DXY解析→流动性" },
  { from: "market_candle_parse", to: "technical_feature", edge_type: "data_flow", stage: "K线解析→技术结构" },
  { from: "cme_options_parse", to: "option_wall", edge_type: "data_flow", stage: "期权解析→期权墙" },
  { from: "jin10_flash_parse", to: "event_flow_feature", edge_type: "data_flow", stage: "快讯解析→事件特征" },
  { from: "jin10_report_parse", to: "event_flow_feature", edge_type: "data_flow", stage: "报告解析→事件特征" },
  goldMainlineEdge({ from: "jin10_flash_parse", to: "oil_geopolitical_feature", edge_type: "data_flow", stage: "快讯解析→石油地缘" }),
  goldMainlineEdge({ from: "market_candle_parse", to: "oil_geopolitical_feature", edge_type: "data_flow", stage: "K线解析→石油地缘" }),
  goldMainlineEdge({ from: "event_flow_feature", to: "source_health_check", edge_type: "signal_flow", stage: "事件特征→数据健康门控" }),
  goldMainlineEdge({ from: "real_rate_feature", to: "source_health_check", edge_type: "signal_flow", stage: "实际利率→数据健康门控" }),
  goldMainlineEdge({ from: "technical_feature", to: "source_health_check", edge_type: "signal_flow", stage: "技术结构→数据健康门控" }),
  goldMainlineEdge({ from: "option_wall", to: "source_health_check", edge_type: "signal_flow", stage: "期权墙→数据健康门控" }),
  goldMainlineEdge({ from: "positioning_feature", to: "source_health_check", edge_type: "signal_flow", stage: "持仓特征→数据健康门控" }),
  goldMainlineEdge({ from: "oil_geopolitical_feature", to: "source_health_check", edge_type: "signal_flow", stage: "石油地缘→数据健康门控" }),
  goldMainlineEdge({ from: "source_health_check", to: "mainline_attribution", edge_type: "signal_flow", stage: "数据健康门控→主线归因" }),
  goldMainlineEdge({ from: "event_flow_feature", to: "mainline_attribution", edge_type: "signal_flow", stage: "事件特征→主线归因" }),
  goldMainlineEdge({ from: "real_rate_feature", to: "mainline_attribution", edge_type: "signal_flow", stage: "实际利率→主线归因" }),
  goldMainlineEdge({ from: "technical_feature", to: "mainline_attribution", edge_type: "signal_flow", stage: "技术结构→主线归因" }),
  goldMainlineEdge({ from: "option_wall", to: "mainline_attribution", edge_type: "signal_flow", stage: "期权墙→主线归因" }),
  goldMainlineEdge({ from: "positioning_feature", to: "mainline_attribution", edge_type: "signal_flow", stage: "持仓特征→主线归因" }),
  goldMainlineEdge({ from: "oil_geopolitical_feature", to: "transmission_chain_detection", edge_type: "signal_flow", stage: "石油地缘→传导链识别" }),
  goldMainlineEdge({ from: "mainline_attribution", to: "transmission_chain_detection", edge_type: "signal_flow", stage: "主线归因→传导链识别" }),

  { from: "real_rate_feature", to: "macro_agent", edge_type: "signal_flow", stage: "实际利率→宏观 Agent" },
  { from: "liquidity_feature", to: "macro_agent", edge_type: "signal_flow", stage: "流动性→宏观 Agent" },
  { from: "option_wall", to: "cme_agent", edge_type: "signal_flow", stage: "期权墙→CME Agent" },
  { from: "positioning_feature", to: "positioning_agent", edge_type: "signal_flow", stage: "持仓特征→持仓 Agent" },
  { from: "technical_feature", to: "technical_agent", edge_type: "signal_flow", stage: "技术结构→技术 Agent" },
  { from: "event_flow_feature", to: "news_agent", edge_type: "signal_flow", stage: "事件特征→新闻 Agent" },
  { from: "snapshot_merge", to: "risk_agent", edge_type: "signal_flow", stage: "快照合并→风险 Agent" },
  { from: "snapshot_merge", to: "market_odds_agent", edge_type: "signal_flow", stage: "快照合并→概率 Agent" },
  goldMainlineEdge({ from: "source_health_check", to: "gold_mainline_agent", edge_type: "signal_flow", stage: "数据健康门控→黄金主线 Agent" }),
  goldMainlineEdge({ from: "transmission_chain_detection", to: "gold_mainline_agent", edge_type: "signal_flow", stage: "传导链识别→黄金主线 Agent" }),

  { from: "macro_agent", to: "coordinator", edge_type: "signal_flow", stage: "宏观 Agent→协调器" },
  { from: "cme_agent", to: "coordinator", edge_type: "signal_flow", stage: "CME Agent→协调器" },
  { from: "risk_agent", to: "coordinator", edge_type: "signal_flow", stage: "风险 Agent→协调器" },
  { from: "technical_agent", to: "coordinator", edge_type: "signal_flow", stage: "技术 Agent→协调器" },
  { from: "positioning_agent", to: "coordinator", edge_type: "signal_flow", stage: "持仓 Agent→协调器" },
  { from: "news_agent", to: "coordinator", edge_type: "signal_flow", stage: "新闻 Agent→协调器" },
  { from: "market_odds_agent", to: "coordinator", edge_type: "signal_flow", stage: "概率 Agent→协调器" },
  goldMainlineEdge({ from: "gold_mainline_agent", to: "coordinator", edge_type: "signal_flow", stage: "黄金主线 Agent→协调器" }),
  goldMainlineEdge({ from: "coordinator", to: "driver_decomposition", edge_type: "signal_flow", stage: "协调器→驱动拆解" }),
  goldMainlineEdge({ from: "driver_decomposition", to: "gold_macro_overview", edge_type: "signal_flow", stage: "驱动拆解→黄金总览模型" }),
  goldMainlineEdge({ from: "source_health_check", to: "gold_macro_overview", edge_type: "signal_flow", stage: "数据健康门控→黄金总览模型" }),
  goldMainlineEdge({ from: "source_health_check", to: "review_gate", edge_type: "signal_flow", stage: "数据健康门控→ReviewGate" }),
  goldMainlineEdge({ from: "gold_macro_overview", to: "verification_matrix", edge_type: "signal_flow", stage: "黄金总览模型→待验证矩阵" }),
  goldMainlineEdge({ from: "gold_macro_overview", to: "review_gate", edge_type: "signal_flow", stage: "黄金总览模型→ReviewGate" }),
  goldMainlineEdge({ from: "review_gate", to: "final_report_json", edge_type: "signal_flow", stage: "ReviewGate→报告 JSON" }),
  goldMainlineEdge({ from: "gold_macro_overview", to: "dashboard", edge_type: "data_flow", stage: "黄金总览模型→Dashboard" }),
  goldMainlineEdge({ from: "gold_macro_overview", to: "gold_mainlines_page", edge_type: "data_flow", stage: "黄金总览模型→黄金主线页" }),
  goldMainlineEdge({ from: "gold_macro_overview", to: "oil_geopolitics_page", edge_type: "data_flow", stage: "黄金总览模型→石油地缘页" }),
  goldMainlineEdge({ from: "source_health_check", to: "processing_monitor", edge_type: "data_flow", stage: "数据健康门控→加工监控" }),
  goldMainlineEdge({ from: "verification_matrix", to: "processing_monitor", edge_type: "data_flow", stage: "待验证矩阵→加工监控" }),
  goldMainlineEdge({ from: "mainline_attribution", to: "source_trace", edge_type: "data_flow", stage: "主线归因→溯源面板" }),
  { from: "coordinator", to: "conflict_check", edge_type: "signal_flow", stage: "协调器→冲突检测" },
  { from: "conflict_check", to: "bias_confidence", edge_type: "signal_flow", stage: "冲突检测→Bias置信" },
  { from: "bias_confidence", to: "final_report_json", edge_type: "signal_flow", stage: "Bias置信→报告 JSON" },

  { from: "final_report_json", to: "daily_report", edge_type: "data_flow", stage: "报告 JSON→日报" },
  { from: "final_report_json", to: "strategy_card", edge_type: "data_flow", stage: "报告 JSON→策略卡片" },
  { from: "daily_report", to: "dashboard", edge_type: "data_flow", stage: "日报→Dashboard" },
  { from: "strategy_card", to: "dashboard", edge_type: "data_flow", stage: "策略卡片→Dashboard" },
  { from: "dashboard", to: "market_monitor", edge_type: "data_flow", stage: "Dashboard→市场监控" },
  { from: "dashboard", to: "source_trace", edge_type: "data_flow", stage: "Dashboard→溯源面板" },
  { from: "jin10_message_raw", to: "feishu_monitor", edge_type: "data_flow", stage: "快讯 Raw→飞书监控" },
  { from: "jin10_flash_parse", to: "feishu_monitor", edge_type: "signal_flow", stage: "快讯解析→飞书监控" },
];

export function groupForOpName(opName: string): DagGroupId {
  if (opName.includes("init") || opName.includes("collect") || opName.includes("download")) return "data_collection";
  if (opName.includes("raw") || opName.includes("archive")) return "raw_archive";
  if (opName.includes("parse") || opName.includes("ingest")) return "raw_parse";
  if (opName.includes("feature") || opName.includes("source_health") || opName.includes("option_wall") || opName.includes("merge_analysis_snapshot") || opName.includes("oil_geopolitical") || opName.includes("mainline_attribution") || opName.includes("transmission_chain") || opName.includes("market_validation")) return "feature_processing";
  if (opName.includes("coordinator") || opName.includes("driver_decomposition") || opName.includes("gold_macro_overview") || opName.includes("verification_matrix") || opName.includes("review_gate")) return "decision_synthesis";
  if (opName.includes("strategy_card") || opName.includes("report_render") || opName.includes("brief") || opName.includes("gold_mainlines_page") || opName.includes("oil_geopolitics_page") || opName.includes("processing_monitor")) return "final_presentation";
  if (opName.includes("agent") || opName.includes("risk") || opName.includes("technical") || opName.includes("positioning")) return "analysis_agents";
  return "analysis_agents";
}

export function groupForTaskLike(taskType: string, category?: string | null): DagGroupId {
  const task = taskType.toLowerCase();
  const cat = (category || "").toLowerCase();

  if (task.includes("collect") || task.includes("fetch") || task.includes("download") || task.includes("source") || task.includes("fred") || task.includes("fed") || task.includes("treasury")) {
    return "data_collection";
  }
  if (task.includes("raw") || task.includes("archive") || task.includes("artifact") || task.includes("storage")) {
    return "raw_archive";
  }
  if (task.includes("parse") || task.includes("parser") || task.includes("ingest") || cat === "data_parsing") {
    return "raw_parse";
  }
  if (task.includes("feature") || task.includes("source_health") || task.includes("snapshot") || task.includes("merge") || task.includes("option") || task.includes("wall") || task.includes("compute") || task.includes("calculate") || task.includes("oil_geopolitical") || task.includes("mainline_attribution") || task.includes("transmission_chain") || task.includes("market_validation")) {
    return "feature_processing";
  }
  if (task.includes("coordinator") || task.includes("final_analysis") || task.includes("synthesis") || task.includes("driver_decomposition") || task.includes("gold_macro_overview") || task.includes("verification_matrix") || task.includes("review_gate")) {
    return "decision_synthesis";
  }
  if (task.includes("strategy") || task.includes("render") || task.includes("report") || task.includes("output") || task.includes("dashboard") || task.includes("brief") || task.includes("gold_mainlines_page") || task.includes("oil_geopolitics_page") || task.includes("processing_monitor") || cat === "report") {
    return "final_presentation";
  }
  if (task.includes("agent") || task.includes("analysis") || task.includes("regime") || task.includes("impact") || task.includes("technical") || task.includes("positioning") || task.includes("news") || task.includes("jin10") || task.includes("flash") || cat === "analysis") {
    return "analysis_agents";
  }
  return "data_collection";
}

export function taskNodeForOpName(groupId: DagGroupId, opName: string): string | null {
  return taskNodesForOpName(groupId, opName)[0] ?? null;
}

export function taskNodesForOpName(groupId: DagGroupId, opName: string): string[] {
  if (groupId === "data_collection") {
    if (opName.startsWith("macro_")) return ["fred_source", "fed_source", "treasury_source", "dxy_source"];
    if (opName.startsWith("cme_") || opName.includes("option")) return ["cme_bulletin_source"];
    if (opName.startsWith("news_")) return ["jin10_flash_source", "jin10_report_source"];
    return ["market_price_source"];
  }
  if (groupId === "raw_archive") {
    if (opName.startsWith("macro_")) return ["macro_api_raw"];
    if (opName.startsWith("cme_") || opName.includes("download")) return ["cme_pdf_raw"];
    if (opName.startsWith("news_")) return ["jin10_message_raw", "jin10_report_raw"];
    if (opName.includes("artifact") || opName.includes("upload")) return ["artifact_raw"];
    return ["market_api_raw"];
  }
  if (groupId === "raw_parse") {
    if (opName.startsWith("macro_")) return ["fred_parse", "treasury_parse", "dxy_parse"];
    if (opName.startsWith("cme_") || opName.includes("option")) return ["cme_bulletin_parse", "cme_options_parse"];
    if (opName.startsWith("news_")) return ["jin10_flash_parse", "jin10_report_parse"];
    return ["market_candle_parse"];
  }
  if (groupId === "feature_processing") {
    if (opName.includes("macro_feature")) return ["real_rate_feature", "liquidity_feature"];
    if (opName.includes("option_wall")) return ["option_wall"];
    if (opName.includes("positioning")) return ["positioning_feature"];
    if (opName.includes("technical")) return ["technical_feature"];
    if (opName.includes("news_feature")) return ["event_flow_feature"];
    if (opName.includes("oil_geopolitical")) return ["oil_geopolitical_feature"];
    if (opName.includes("source_health")) return ["source_health_check"];
    if (opName.includes("mainline_attribution")) return ["mainline_attribution"];
    if (opName.includes("transmission_chain")) return ["transmission_chain_detection"];
    if (opName.includes("market_validation")) return ["market_validation"];
    if (opName.includes("merge") || opName.includes("snapshot")) return ["snapshot_merge"];
    return [];
  }
  if (groupId === "analysis_agents") {
    if (opName.includes("gold_mainline")) return ["gold_mainline_agent"];
    if (opName.includes("macro")) return ["macro_agent"];
    if (opName.includes("cme")) return ["cme_agent"];
    if (opName.includes("risk")) return ["risk_agent"];
    if (opName.includes("technical")) return ["technical_agent"];
    if (opName.includes("positioning")) return ["positioning_agent"];
    if (opName.includes("market_odds")) return ["market_odds_agent"];
    if (opName.includes("news")) return ["news_agent"];
    return [];
  }
  if (groupId === "decision_synthesis") {
    if (opName.includes("driver_decomposition")) return ["driver_decomposition"];
    if (opName.includes("gold_macro_overview")) return ["gold_macro_overview"];
    if (opName.includes("verification_matrix")) return ["verification_matrix"];
    if (opName.includes("review_gate")) return ["review_gate"];
    if (opName.includes("coordinator")) return ["coordinator", "conflict_check", "bias_confidence"];
    if (opName.includes("merge") || opName.includes("snapshot")) return ["conflict_check", "bias_confidence"];
    return ["final_report_json"];
  }
  if (groupId === "final_presentation") {
    if (opName.includes("gold_mainlines_page")) return ["gold_mainlines_page"];
    if (opName.includes("oil_geopolitics_page")) return ["oil_geopolitics_page"];
    if (opName.includes("processing_monitor")) return ["processing_monitor"];
    if (opName.includes("strategy_card")) return ["strategy_card"];
    if (opName.includes("report_render")) return ["daily_report"];
    if (opName.includes("dashboard")) return ["dashboard"];
    if (opName.includes("market_monitor")) return ["market_monitor"];
    if (opName.includes("feishu")) return ["feishu_monitor"];
    if (opName.includes("trace")) return ["source_trace"];
    return [];
  }
  return [];
}

export function taskNodeForTaskLike(groupId: DagGroupId, taskType: string, category?: string | null): string | null {
  return taskNodesForTaskLike(groupId, taskType, category)[0] ?? null;
}

export function taskNodesForTaskLike(groupId: DagGroupId, taskType: string, category?: string | null): string[] {
  const task = taskType.toLowerCase();
  const cat = (category || "").toLowerCase();
  if (groupId === "data_collection") {
    if (task.includes("macro")) return ["fred_source", "fed_source", "treasury_source", "dxy_source"];
    if (task.includes("cme") || task.includes("bulletin") || task.includes("option")) return ["cme_bulletin_source"];
    if (task.includes("jin10") || task.includes("news") || task.includes("flash")) return ["jin10_flash_source", "jin10_report_source"];
    if (task.includes("market") || task.includes("xau") || task.includes("candle")) return ["market_price_source"];
    if (task.includes("dxy")) return ["dxy_source"];
    if (task.includes("fed")) return ["fed_source"];
    if (task.includes("treasury")) return ["treasury_source"];
    if (task.includes("fred")) return ["fred_source"];
    return [];
  }
  if (groupId === "raw_archive") {
    if (task.includes("macro")) return ["macro_api_raw"];
    if (task.includes("pdf") || task.includes("cme") || task.includes("bulletin")) return ["cme_pdf_raw"];
    if (task.includes("message") || task.includes("flash")) return ["jin10_message_raw"];
    if (task.includes("jin10") || task.includes("news")) return ["jin10_message_raw", "jin10_report_raw"];
    if (task.includes("artifact") || task.includes("upload") || task.includes("file")) return ["artifact_raw"];
    if (task.includes("market") || task.includes("candle")) return ["market_api_raw"];
    return [];
  }
  if (groupId === "raw_parse") {
    if (task.includes("macro")) return ["fred_parse", "treasury_parse", "dxy_parse"];
    if (task.includes("cme") || task.includes("option") || task.includes("bulletin")) return ["cme_bulletin_parse", "cme_options_parse"];
    if (task.includes("jin10") || task.includes("news") || task.includes("flash")) return ["jin10_flash_parse", "jin10_report_parse"];
    if (task.includes("market") || task.includes("candle")) return ["market_candle_parse"];
    if (task.includes("dxy")) return ["dxy_parse"];
    if (task.includes("treasury")) return ["treasury_parse"];
    if (task.includes("fred")) return ["fred_parse"];
    return [];
  }
  if (groupId === "feature_processing") {
    if (task.includes("macro") || task.includes("rate") || task.includes("liquidity")) return ["real_rate_feature", "liquidity_feature"];
    if (task.includes("option") || task.includes("wall") || task.includes("gex")) return ["option_wall"];
    if (task.includes("positioning") || task.includes("cot")) return ["positioning_feature"];
    if (task.includes("technical")) return ["technical_feature"];
    if (task.includes("news") || task.includes("event") || task.includes("sentiment")) return ["event_flow_feature"];
    if (task.includes("oil_geopolitical")) return ["oil_geopolitical_feature"];
    if (task.includes("source_health")) return ["source_health_check"];
    if (task.includes("mainline_attribution")) return ["mainline_attribution"];
    if (task.includes("transmission_chain")) return ["transmission_chain_detection"];
    if (task.includes("market_validation")) return ["market_validation"];
    if (task.includes("merge") || task.includes("snapshot")) return ["snapshot_merge"];
    return [];
  }
  if (groupId === "analysis_agents") {
    if (task.includes("gold_mainline")) return ["gold_mainline_agent"];
    if (task.includes("macro")) return ["macro_agent"];
    if (task.includes("cme") || task.includes("option")) return ["cme_agent"];
    if (task.includes("positioning")) return ["positioning_agent"];
    if (task.includes("risk")) return ["risk_agent"];
    if (task.includes("technical")) return ["technical_agent"];
    if (task.includes("market_odds")) return ["market_odds_agent"];
    if (task.includes("news") || task.includes("jin10") || task.includes("flash")) return ["news_agent"];
    return [];
  }
  if (groupId === "decision_synthesis") {
    if (task.includes("driver_decomposition")) return ["driver_decomposition"];
    if (task.includes("gold_macro_overview")) return ["gold_macro_overview"];
    if (task.includes("verification_matrix")) return ["verification_matrix"];
    if (task.includes("review_gate")) return ["review_gate"];
    if (task.includes("conflict") || task.includes("merge")) return ["conflict_check", "bias_confidence"];
    if (task.includes("json") || task.includes("final")) return ["final_report_json"];
    return ["coordinator"];
  }
  if (groupId === "final_presentation") {
    if (task.includes("gold_mainlines_page")) return ["gold_mainlines_page"];
    if (task.includes("oil_geopolitics_page")) return ["oil_geopolitics_page"];
    if (task.includes("processing_monitor")) return ["processing_monitor"];
    if (task.includes("strategy")) return ["strategy_card"];
    if (task.includes("market_monitor")) return ["market_monitor"];
    if (task.includes("dashboard")) return ["dashboard"];
    if (task.includes("feishu")) return ["feishu_monitor"];
    if (task.includes("trace")) return ["source_trace"];
    return cat === "report" || task.includes("report") ? ["daily_report"] : ["dashboard"];
  }
  return [];
}

export function aggregateDagStatus(statuses: DagNodeStatus[]): DagNodeStatus {
  if (statuses.some((status) => status === "failed")) return "failed";
  if (statuses.some((status) => status === "running")) return "running";
  if (statuses.some((status) => status === "partial")) return "partial";
  if (statuses.some((status) => status === "success")) return "success";
  return "pending";
}

export function buildFixedTaskDataFlowEdges(nodes: DagNodeSpec[]): DagEdge[] {
  const nodeMap = new Map(nodes.map((node) => [node.node_id, node]));

  return DAG_TASK_DATA_FLOW_EDGES
    .filter((edge) => nodeMap.has(edge.from) && nodeMap.has(edge.to))
    .map((edge) => {
      const fromNode = nodeMap.get(edge.from);
      const toNode = nodeMap.get(edge.to);
      const status = aggregateDagStatus([
        fromNode?.status ?? "pending",
        toNode?.status ?? "pending",
      ]);
      return {
        from: edge.from,
        to: edge.to,
        edge_type: edge.edge_type,
        data_contract: {
          fields: edge.data_contract?.fields ?? [],
          stage: edge.stage,
          status,
        },
      };
    });
}

export function attachDagLineage(nodes: DagNodeSpec[], edges: DagEdge[]): void {
  const nodeMap = new Map(nodes.map((node) => [node.node_id, node]));
  for (const edge of edges) {
    nodeMap.get(edge.from)?.downstream_ids.push(edge.to);
    nodeMap.get(edge.to)?.upstream_ids.push(edge.from);
  }
}
