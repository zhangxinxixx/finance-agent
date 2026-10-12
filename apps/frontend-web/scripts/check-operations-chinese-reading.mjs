import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
const require = createRequire(import.meta.url);
const ts = require("typescript");

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (relative) => fs.readFileSync(path.join(here, "..", "src", relative), "utf8");
const page = (name) => fs.readFileSync(path.join(here, "..", "src", "pages", name), "utf8");
const component = (name) => fs.readFileSync(path.join(here, "..", "src", "components", name), "utf8");

const labels = src("components/operations/operationsLabels.ts");
assert.match(labels, /export function operationStatusLabel/);
assert.match(labels, /export function operationEventLabel/);
assert.match(labels, /return STATUS_LABELS\[key\] \?\? "状态尚未说明"/);
assert.match(labels, /export function operationSourceTypeLabel/);
assert.match(labels, /export function evidenceLabel/);
assert.match(labels, /export function operationReadableLabel/);

const sourceCard = component("data-ingestion/DataSourceCard.tsx");
assert.match(sourceCard, /operationSourceGroupLabel\(source\.group\)/);
assert.match(sourceCard, /operationStatusLabel\(source\.status\)/);
assert.doesNotMatch(sourceCard, /`page \$\{source\.status\}`/);

const sourceSections = component("data-ingestion/DataSourceCardSections.tsx");
assert.match(sourceSections, /来源接口依据/);
assert.match(sourceSections, /EvidenceRecordActions/);
assert.match(sourceSections, /source\.row_count == null \? "未返回"/);

const groupedSources = component("data-ingestion/GroupedSourceTableParts.tsx");
assert.match(groupedSources, /operationSourceTypeLabel/);
assert.match(groupedSources, /operationStatusLabel/);
assert.match(groupedSources, /未返回/);
assert.doesNotMatch(groupedSources, /全部 live/);

const stageNode = component("data-ingestion/StageNode.tsx");
assert.match(stageNode, /OK: "正常"/);
assert.doesNotMatch(stageNode, /READY: "RDY"/);

const taskDisplay = component("agent-tasks/AgentTaskDisplayBlocks.tsx");
assert.match(taskDisplay, /EvidenceRecordActions/);
assert.match(taskDisplay, /export function JsonBlock/);
const taskSummary = component("agent-tasks/AgentTaskSummaryPanels.tsx");
assert.match(taskSummary, /原始运行日志/);
assert.match(taskSummary, /步骤依据记录/);
assert.match(taskSummary, /原始事件记录/);
assert.match(taskSummary, /source: "运行日志"/);
assert.doesNotMatch(taskSummary, /source: log\.task_id/);
assert.doesNotMatch(taskSummary, /execution events/);
const runtimeLog = component("shared/FARuntimeLog.tsx");
assert.match(runtimeLog, /debug: "调试"/);
assert.match(runtimeLog, /success: "成功"/);

const inspection = component("agent-tasks/AgentInspectionPanel.tsx");
assert.match(inspection, /展开原始提示记录/);
assert.match(inspection, /展开原始输出记录/);

const processing = page("ProcessingMonitorPage.tsx");
assert.match(processing, /来源引用/);
assert.match(processing, /输入主线名称或标识/);
const traceDetails = component("processing-monitor/TraceDetailPanels.tsx");
assert.match(traceDetails, /详细证据字段/);

const trace = component("processing-monitor/ArtifactSourceTracePanel.tsx");
assert.match(trace, /operationStatusLabel\(trace\.data_status\)/);
assert.match(trace, /EvidenceRecordActions/);
assert.match(traceDetails, /EvidenceRecordActions/);

const review = component("review-center/ReviewCenterSections.tsx");
assert.match(review, /EvidenceRecordActions/);
assert.match(review, /复核依据记录/);
assert.doesNotMatch(review, /<pre[^>]*>\s*\{JSON\.stringify/);
assert.doesNotMatch(review, /compactId\(/);

const scheduler = page("SchedulerCenterPage.tsx");
assert.match(scheduler, /operationStatusLabel\(payload\.from_status\)/);
assert.match(scheduler, /operationEventLabel\(event\.event_type\)/);
assert.match(scheduler, /evidenceLabel\(detail\.run_id\)/);
assert.match(scheduler, /<Fragment key=\{stage\}>/);

const scheduleList = page("TaskScheduleListPage.tsx");
assert.match(scheduleList, /operationStatusLabel\(run\.status\)/);
assert.match(scheduleList, /分类待确认/);

const dag = page("PipelineDagPage.tsx");
assert.match(dag, /展开原始输入记录/);
assert.match(dag, /operationEventLabel\(event\.event_type\)/);
assert.match(dag, /operationFieldLabel/);
assert.match(dag, /controls\.zoomIn\.ariaLabel/);
assert.match(dag, /"放大"/);
assert.doesNotMatch(dag, /Trace Payload Only/);

const sourceMatrix = component("data-ingestion/SourcePipelineMatrix.tsx");
assert.match(sourceMatrix, /原始落地/);
assert.doesNotMatch(sourceMatrix, /全部 live/);
const stageProgress = component("data-ingestion/PipelineStageProgress.tsx");
assert.match(stageProgress, /key: "rawLanding",\s+label: "原始落地"/);
const ingestionPipeline = component("data-ingestion/IngestionPipelineStatus.tsx");
assert.match(ingestionPipeline, /raw_ingested: "原始数据落地"/);
const sourcePipelineRow = component("data-ingestion/SourcePipelineRow.tsx");
assert.match(sourcePipelineRow, /title=\{operationReadableLabel\(mod, "影响模块已登记"\)\}/);
const reviewSections = component("review-center/ReviewCenterSections.tsx");
assert.match(reviewSections, /machine endpoint/);

const ingestionTypes = src("types/data-ingestion.ts");
const ingestionAdapter = src("adapters/dataIngestion.ts");
assert.match(ingestionTypes, /row_count:\s*number \| null/);
assert.match(ingestionAdapter, /row_count:\s*source\.row_count \?\? null/);
assert.doesNotMatch(ingestionAdapter, /DATA_INGESTION_MOCK_URL|loadMockDataIngestion/);
assert.match(ingestionAdapter, /throw apiCause instanceof Error/);

const agentTasksAdapter = src("adapters/agentTasks.ts");
assert.doesNotMatch(agentTasksAdapter, /AGENT_TASKS_MOCK_URL|fetchMockFile/);
assert.match(agentTasksAdapter, /throw cause instanceof Error/);

function loadAdapter(relativePath, modules) {
  const output = ts.transpileModule(src(relativePath), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  let fixtureFetches = 0;
  const sandbox = {
    module,
    exports: module.exports,
    console,
    fetch() {
      fixtureFetches += 1;
      throw new Error("fixture fetch must not be used by a formal page adapter");
    },
    URL,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    require(specifier) {
      if (specifier in modules) return modules[specifier];
      throw new Error(`Unexpected adapter import: ${specifier}`);
    },
  };
  vm.runInNewContext(output, sandbox, { filename: relativePath });
  return { adapter: module.exports, fixtureFetches: () => fixtureFetches };
}

class TestApiError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? null;
    this.url = options.url ?? "";
  }
}

async function assertIngestionFailure(label, failureFactory) {
  const calls = [];
  const loaded = loadAdapter("adapters/dataIngestion.ts", {
    "@/adapters/apiClient": {
      ApiError: TestApiError,
      fetchJson: async (requestPath) => {
        calls.push(requestPath);
        if (requestPath === "/api/data-sources/status") {
          const outcome = failureFactory();
          if (outcome && outcome.kind === "return") return outcome.value;
          throw outcome;
        }
        if (requestPath === "/api/data-status/summary") return null;
        throw new Error(`unexpected request ${requestPath}`);
      },
    },
  });

  await assert.rejects(() => loaded.adapter.fetchDataIngestionData(), `${label} must surface an unavailable read`);
  assert.ok(calls.includes("/api/data-sources/status"), `${label} must request the real status endpoint`);
  assert.equal(loaded.fixtureFetches(), 0, `${label} must not load a local fixture`);
}

await assertIngestionFailure("HTTP 503", () => new TestApiError("HTTP 503", { status: 503, url: "/api/data-sources/status" }));
await assertIngestionFailure("network failure", () => new Error("network unavailable"));
await assertIngestionFailure("malformed response", () => ({ kind: "return", value: { sources: null } }));

const agentCalls = [];
const loadedAgentTasks = loadAdapter("adapters/agentTasks.ts", {
  "@/adapters/apiClient": {
    ApiError: TestApiError,
    fetchJson: async (requestPath) => {
      agentCalls.push(requestPath);
      throw new TestApiError("HTTP 503", { status: 503, url: requestPath });
    },
  },
  "@/lib/date": { formatDateTime: (value) => String(value ?? "") },
  "@/lib/status": {
    mergeDataStatus: (values) => values[0] ?? "unavailable",
    normalizeDataStatus: (value) => value ?? "unavailable",
  },
  "@/components/operations/operationsLabels": {
    operationStageLabel: (value) => ({ collector: "采集", raw: "原始数据", parser: "解析" }[String(value ?? "").toLowerCase()] ?? "阶段尚未说明"),
    operationStatusLabel: (value) => ({ success: "成功", failed: "失败", running: "运行中" }[String(value ?? "").toLowerCase()] ?? "状态尚未说明"),
    operationReadableLabel: (value, fallback = "记录已登记") => /[\u3400-\u9fff]/.test(String(value ?? "")) ? String(value) : fallback,
  },
});
await assert.rejects(
  () => loadedAgentTasks.adapter.fetchAgentTasksView(),
  "Agent Tasks HTTP failure must surface an unavailable read",
);
assert.ok(agentCalls.includes("/api/runs?limit=20"), "Agent Tasks must request the real run endpoint");
assert.equal(loadedAgentTasks.fixtureFetches(), 0, "Agent Tasks must not load a local fixture");

const operationsFixturePath = path.resolve(
  here,
  "../../../../finance-agent-workbench/implementations/20261005-human-readable-round4/logs/operations-fixtures.json",
);
const operationsFixture = JSON.parse(fs.readFileSync(operationsFixturePath, "utf8"));
const successCalls = [];
const loadedAgentSuccess = loadAdapter("adapters/agentTasks.ts", {
  "@/adapters/apiClient": {
    ApiError: TestApiError,
    fetchJson: async (requestPath) => {
      successCalls.push(requestPath);
      if (!(requestPath in operationsFixture)) throw new Error(`missing fixture route ${requestPath}`);
      return operationsFixture[requestPath];
    },
  },
  "@/lib/date": { formatDateTime: (value) => String(value ?? "") },
  "@/lib/status": {
    mergeDataStatus: (values) => values[0] ?? "unavailable",
    normalizeDataStatus: (value) => value ?? "unavailable",
  },
  "@/components/operations/operationsLabels": {
    operationStageLabel: (value) => ({ collector: "采集", raw: "原始数据", parser: "解析" }[String(value ?? "").toLowerCase()] ?? "阶段尚未说明"),
    operationStatusLabel: (value) => ({ success: "成功", failed: "失败", running: "运行中" }[String(value ?? "").toLowerCase()] ?? "状态尚未说明"),
    operationReadableLabel: (value, fallback = "记录已登记") => /[\u3400-\u9fff]/.test(String(value ?? "")) ? String(value) : fallback,
  },
});
const fixtureView = await loadedAgentSuccess.adapter.fetchAgentTasksView("fixture-run-001");
const fixtureRun = fixtureView.selected_run;
assert.equal(fixtureView.source, "api", "fixture success must still be represented as an API-shaped isolated response");
assert.equal(fixtureRun?.steps[0]?.label, "宏观数据采集", "human-readable step label must remain visible");
assert.equal(fixtureRun?.logs[0]?.lines[0], "宏观数据采集 · 成功", "status and task name must be translated in the reading layer");
assert.equal(fixtureRun?.logs[0]?.source_record?.step_id, "fixture-step-collect", "raw step record must remain copyable");
assert.ok(fixtureRun?.events[0]?.source_record?.id === "fixture-event-001", "raw event record must remain copyable");
assert.ok(fixtureRun?.logs[0]?.lines.every((line) => !/(?:started_at|ended_at|fixture-run-001|fixture-step-collect)/.test(line)), "reading lines must not expose machine field names or identifiers");
assert.ok(successCalls.includes("/api/runs/fixture-run-001/logs"), "success fixture must cover the expanded logs route");

console.log("operations Chinese reading contract: PASS");
