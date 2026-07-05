import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(__dirname, "../src/adapters/pipeline-dag-groups.ts");
const source = readFileSync(sourcePath, "utf8");

const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    esModuleInterop: true,
  },
}).outputText;

const module = { exports: {} };
vm.runInNewContext(transpiled, {
  exports: module.exports,
  module,
  console,
}, { filename: sourcePath });

const {
  DAG_GROUPS,
  DAG_TASK_DATA_FLOW_EDGES,
  buildFixedTaskDataFlowEdges,
} = module.exports;

const requiredTasksByGroup = {
  feature_processing: {
    oil_geopolitical_feature: "石油地缘",
    source_health_check: "数据健康门控",
    mainline_attribution: "主线归因",
    transmission_chain_detection: "传导链识别",
    market_validation: "市场验证",
  },
  analysis_agents: {
    gold_mainline_agent: "黄金主线 Agent",
  },
  decision_synthesis: {
    driver_decomposition: "驱动拆解",
    gold_macro_overview: "黄金总览模型",
    verification_matrix: "待验证矩阵",
    review_gate: "ReviewGate",
  },
  final_presentation: {
    gold_mainlines_page: "黄金主线页",
    oil_geopolitics_page: "石油地缘页",
    processing_monitor: "加工监控",
  },
};

const requiredContractFields = [
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

const requiredEdges = [
  ["event_flow_feature", "source_health_check"],
  ["real_rate_feature", "source_health_check"],
  ["technical_feature", "source_health_check"],
  ["option_wall", "source_health_check"],
  ["positioning_feature", "source_health_check"],
  ["oil_geopolitical_feature", "source_health_check"],
  ["source_health_check", "mainline_attribution"],
  ["event_flow_feature", "mainline_attribution"],
  ["real_rate_feature", "mainline_attribution"],
  ["technical_feature", "mainline_attribution"],
  ["option_wall", "mainline_attribution"],
  ["positioning_feature", "mainline_attribution"],
  ["jin10_flash_parse", "oil_geopolitical_feature"],
  ["market_candle_parse", "oil_geopolitical_feature"],
  ["oil_geopolitical_feature", "transmission_chain_detection"],
  ["mainline_attribution", "transmission_chain_detection"],
  ["transmission_chain_detection", "gold_mainline_agent"],
  ["source_health_check", "gold_mainline_agent"],
  ["gold_mainline_agent", "coordinator"],
  ["coordinator", "driver_decomposition"],
  ["driver_decomposition", "gold_macro_overview"],
  ["source_health_check", "gold_macro_overview"],
  ["source_health_check", "review_gate"],
  ["gold_macro_overview", "verification_matrix"],
  ["gold_macro_overview", "review_gate"],
  ["review_gate", "final_report_json"],
  ["gold_macro_overview", "dashboard"],
  ["gold_macro_overview", "gold_mainlines_page"],
  ["gold_macro_overview", "oil_geopolitics_page"],
  ["source_health_check", "processing_monitor"],
  ["verification_matrix", "processing_monitor"],
  ["mainline_attribution", "source_trace"],
];

function assertContractFields(actual, message) {
  assert.equal(JSON.stringify(actual), JSON.stringify(requiredContractFields), message);
}

for (const [groupId, tasks] of Object.entries(requiredTasksByGroup)) {
  const groupTasks = new Map(DAG_GROUPS[groupId].tasks.map((task) => [task.id, task.label]));
  for (const [taskId, label] of Object.entries(tasks)) {
    assert.equal(groupTasks.get(taskId), label, `${groupId} missing task ${taskId}`);
  }
}

for (const [from, to] of requiredEdges) {
  const edge = DAG_TASK_DATA_FLOW_EDGES.find((item) => item.from === from && item.to === to);
  assert.ok(edge, `missing edge ${from} -> ${to}`);
  const fields = edge.data_contract?.fields ?? [];
  assertContractFields(
    fields,
    `edge ${from} -> ${to} must declare the Gold v3 data contract fields`,
  );
}

const allNodes = Object.values(DAG_GROUPS).flatMap((group) =>
  group.tasks.map((task) => ({
    node_id: task.id,
    type: group.type,
    label: task.label,
    sub_type: group.label,
    trade_date: null,
    status: "pending",
    category: group.id,
    module: group.module,
    input: { source: "test", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
    output: { source: "test", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
    execution: { started_at: null, ended_at: null, duration_ms: null, retries: 0 },
    upstream_ids: [],
    downstream_ids: [],
  })),
);

const builtEdges = buildFixedTaskDataFlowEdges(allNodes);
for (const [from, to] of requiredEdges) {
  const edge = builtEdges.find((item) => item.from === from && item.to === to);
  assert.ok(edge, `built DAG missing edge ${from} -> ${to}`);
  assertContractFields(
    edge.data_contract.fields,
    `built edge ${from} -> ${to} must preserve the Gold v3 data contract fields`,
  );
}

console.log("Gold v3 pipeline DAG contract OK");
