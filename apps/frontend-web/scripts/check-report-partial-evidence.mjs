import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const source = readFileSync(new URL("../src/adapters/reports.ts", import.meta.url), "utf8");

class ApiError extends Error {
  constructor(message, { status = null, url, responseBody = null, cause } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
    this.responseBody = responseBody;
    this.cause = cause;
  }
}

const responses = new Map();
let calls = [];
const apiClient = {
  ApiError,
  fetchJson(path, init) {
    calls.push({ path, signal: init?.signal });
    const response = responses.get(path);
    if (!response) throw new Error(`Unexpected request: ${path}`);
    return typeof response === "function" ? response(init) : Promise.resolve(response);
  },
};

const exports = {};
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
vm.runInNewContext(code, {
  exports,
  require(name) {
    if (name === "@/adapters/apiClient") return apiClient;
    if (name === "@/lib/status") return { normalizeDataStatus: (value) => value ?? "unavailable" };
    if (name === "@/adapters/resultIdentity") return { normalizeResultIdentity: (value) => value ?? null };
    if (name === "./inFlightRequest") return { createInFlightRequest: (loader) => loader };
    throw new Error(`Unexpected import: ${name}`);
  },
  console,
});

const { fetchReportDetailView } = exports;
const reportId = "report-partial-evidence";
const detailPath = `/api/reports/${reportId}`;
const endpoint = (name) => `/api/reports/${reportId}/${name}`;
const apiError = (status, path, cause) => new ApiError(`HTTP ${status}`, { status, url: path, cause });

function detail(artifactTypes = []) {
  return {
    report_id: reportId,
    family: "macro_report",
    title: "可信正文测试报告",
    asset: "XAUUSD",
    trade_date: "2026-10-04",
    generated_at: "2026-10-04T00:00:00Z",
    data_status: "available",
    lifecycle_status: "reviewed",
    source_refs: [],
    artifact_refs: [],
    warnings: [],
    artifacts: artifactTypes.map((artifact_type, index) => ({
      artifact_id: `${artifact_type}-${index}`,
      artifact_type,
      file_path: `/reports/${artifact_type}`,
    })),
    input_snapshot_ids: [],
    review_items: [],
  };
}

function artifact(tab) {
  const type = { analysis: "analysis_md", source: "source_md", visual: "visual_html", evidence: "structured_json" }[tab];
  return {
    report_id: reportId,
    artifact_id: `${tab}-1`,
    artifact_type: type,
    content_type: tab === "visual" ? "text/html" : tab === "evidence" ? "application/json" : "text/markdown",
    path: `/reports/${reportId}/${tab}`,
    content: `${tab} 正文`,
  };
}

function inputs() {
  return {
    report_id: reportId,
    data_status: "available",
    source_refs: [],
    artifact_refs: [],
    warnings: [],
    deterministic_inputs: [],
    agent_outputs: [],
    fact_reviews: [],
    synthesis_outputs: [],
  };
}

function reset(artifactTypes, overrides = {}) {
  calls = [];
  responses.clear();
  responses.set(detailPath, detail(artifactTypes));
  responses.set(endpoint("analysis-inputs"), inputs());
  for (const [tab, type] of Object.entries({ analysis: "analysis_md", source: "source_md", visual: "visual_html", evidence: "structured_json" })) {
    if (artifactTypes.includes(type)) responses.set(endpoint(tab), artifact(tab));
  }
  for (const [path, value] of Object.entries(overrides)) responses.set(path, value);
}

function assertSameReportId() {
  assert.ok(calls.length > 0, "scenario must issue requests");
  assert.ok(calls.every(({ path }) => path === detailPath || path.startsWith(`${detailPath}/`)), "all payload requests must retain the requested reportId");
}

reset(["analysis_md", "structured_json"], {
  [endpoint("evidence")]: () => Promise.reject(apiError(503, endpoint("evidence"))),
});
let result = await fetchReportDetailView(reportId);
assert.equal(result.tabs.analysis.content, "analysis 正文", "evidence 503 must preserve the exact readable analysis");
assert.ok(result.warnings.some((warning) => warning.code === "report-artifact-read-failed" && warning.message.includes("证据包")), "evidence 503 must be visible as a Chinese verification warning");
assertSameReportId();

reset(["analysis_md"], {
  [endpoint("analysis-inputs")]: () => Promise.reject(apiError(503, endpoint("analysis-inputs"))),
});
result = await fetchReportDetailView(reportId);
assert.equal(result.tabs.analysis.content, "analysis 正文", "analysis-inputs 503 must preserve the exact analysis");
assert.ok(result.warnings.some((warning) => warning.code === "report-analysis-inputs-unavailable"), "analysis-inputs 503 must be visible");
assertSameReportId();

reset(["analysis_md", "source_md"], {
  [endpoint("analysis")]: () => Promise.reject(apiError(503, endpoint("analysis"))),
});
result = await fetchReportDetailView(reportId);
assert.equal(result.tabs.source.content, "source 正文", "analysis 503 must not hide readable source");
assert.ok(!result.tabs.analysis, "failed analysis must not be presented as readable");

reset(["analysis_md"], {
  [detailPath]: () => Promise.reject(apiError(503, detailPath)),
});
await assert.rejects(() => fetchReportDetailView(reportId), (error) => error instanceof ApiError && error.status === 503, "required report detail 503 must reject");

reset(["analysis_md"], {
  [endpoint("analysis")]: () => Promise.reject(apiError(404, endpoint("analysis"))),
});
result = await fetchReportDetailView(reportId);
assert.ok(result.warnings.some((warning) => warning.code === "report-artifact-content-missing" && warning.message.includes("已在报告元数据登记")), "declared artifact 404 must state that registered content is missing");

reset(["analysis_md"], {
  [endpoint("analysis-inputs")]: () => Promise.reject(apiError(404, endpoint("analysis-inputs"))),
});
result = await fetchReportDetailView(reportId);
assert.equal(result.analysis_inputs, null, "optional analysis-inputs 404 remains an ordinary missing optional resource");
assert.ok(!result.warnings.some((warning) => warning.code === "report-analysis-inputs-unavailable"), "optional analysis-inputs 404 must not be misreported as a failed read");

reset(["analysis_md", "source_md", "visual_html", "structured_json"], {
  [endpoint("analysis")]: () => Promise.reject(apiError(503, endpoint("analysis"))),
  [endpoint("source")]: () => Promise.reject(apiError(503, endpoint("source"))),
  [endpoint("visual")]: () => Promise.reject(apiError(503, endpoint("visual"))),
  [endpoint("evidence")]: () => Promise.reject(apiError(503, endpoint("evidence"))),
  [endpoint("analysis-inputs")]: () => Promise.reject(apiError(503, endpoint("analysis-inputs"))),
});
result = await fetchReportDetailView(reportId);
assert.equal(result.report_id, reportId, "all optional failures must retain readable report metadata");
assert.equal(result.meta.title, "可信正文测试报告", "metadata must remain readable when every optional part fails");
assert.equal(result.warnings.length, 5, "every failed optional read must have a visible warning");

reset(["analysis_md"], {
  [endpoint("analysis")]: () => Promise.reject(apiError(null, endpoint("analysis"), new DOMException("cancelled", "AbortError"))),
});
await assert.rejects(() => fetchReportDetailView(reportId), /HTTP null/, "AbortError from an optional read must reject instead of producing partial success");

const controller = new AbortController();
reset(["analysis_md"], {
  [detailPath]: () => {
    controller.abort(new DOMException("cancelled", "AbortError"));
    return Promise.resolve(detail(["analysis_md"]));
  },
});
await assert.rejects(
  () => fetchReportDetailView(reportId, controller.signal),
  (error) => error?.name === "AbortError",
  "an aborted AbortSignal must reject instead of producing partial success",
);

reset([], {
  [endpoint("analysis-inputs")]: () => Promise.reject(apiError(404, endpoint("analysis-inputs"))),
});
result = await fetchReportDetailView(reportId);
assert.equal(result.available_tabs.length, 0, "a report without artifacts remains readable without synthetic tabs");
assert.equal(result.warnings.length, 0, "a report without optional artifacts must not gain failure warnings");

reset(["analysis_md", "source_md", "visual_html", "structured_json"]);
result = await fetchReportDetailView(reportId);
assert.equal(result.available_tabs.join(","), "analysis,source,visual,evidence,inputs", "all successful optional parts remain available");
assert.equal(result.warnings.length, 0, "normal successful reads remain warning-free");
assertSameReportId();

console.log("Report partial evidence behavior OK");
