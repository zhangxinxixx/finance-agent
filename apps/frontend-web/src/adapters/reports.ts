import { ApiError, fetchJson } from "@/adapters/apiClient";
import type { ArtifactRef } from "@/types/artifact";
import type { DataStatus, ReportFormat, SourceRef } from "@/types/common";
import type {
  BackendArtifactRef,
  BackendSourceRef,
  FinalReportResponse,
  FinalReportView,
  Jin10ReportBundleResponse,
  Jin10ReportBundleView,
  Jin10WeeklyReportResponse,
  Jin10WeeklyReportView,
  ReportAnalysisAgentOutputResponse,
  ReportAnalysisAgentOutputView,
  ReportAnalysisInputItemView,
  ReportAnalysisInputsResponse,
  ReportAnalysisInputsView,
  ReportArtifactContentView,
  ReportArtifactPayloadResponse,
  ReportArtifactResponse,
  ReportArtifactTabKey,
  ReportDetailResponse,
  ReportDetailTabKey,
  ReportDetailView,
  ReportGenerationTrace,
  ReportDeterministicInputResponse,
  ReportsDatesResponse,
  ReportsIndexResponse,
  VisualReportResponse,
  VisualReportView,
} from "@/types/reports";
import { normalizeDataStatus } from "@/lib/status";

const REPORTS_INDEX_PATH = "/api/reports/index";
const REPORTS_DATES_PATH = "/api/reports/dates";
const REPORTS_DETAIL_PATH = "/api/reports";
const REPORTS_ANALYSIS_INPUTS_PATH = "/api/reports";
const FINAL_REPORT_LATEST_PATH = "/api/final-report/latest";
const FINAL_REPORT_PATH = "/api/final-report";
const OPTIONS_VISUAL_REPORT_LATEST_PATH = "/api/options/visual-report/latest";
const OPTIONS_VISUAL_REPORT_PATH = "/api/options/visual-report";
const JIN10_DAILY_REPORT_LATEST_PATH = "/api/jin10/daily-report/latest";
const JIN10_DAILY_REPORT_PATH = "/api/jin10/daily-report";
const JIN10_REPORT_BUNDLE_LATEST_PATH = "/api/jin10/report-bundle/latest";
const JIN10_REPORT_BUNDLE_PATH = "/api/jin10/report-bundle";
const JIN10_WEEKLY_REPORT_LATEST_PATH = "/api/jin10/weekly-report/latest";
const JIN10_WEEKLY_REPORT_PATH = "/api/jin10/weekly-report";
const REPORT_DETAIL_TAB_CONFIG: Record<ReportArtifactTabKey, { label: string; endpoint: string }> = {
  analysis: { label: "分析稿", endpoint: "analysis" },
  source: { label: "来源稿", endpoint: "source" },
  visual: { label: "可视稿", endpoint: "visual" },
  evidence: { label: "证据包", endpoint: "evidence" },
};

const REPORT_TAB_ARTIFACT_TYPES: Record<ReportArtifactTabKey, string[]> = {
  analysis: ["analysis_md"],
  source: ["source_md"],
  visual: ["visual_html"],
  evidence: ["structured_json"],
};

const INFO_ONLY_WARNING_CODES = new Set([
  "legacy-report-adapter",
  "analysis-inputs-agent-fallback",
  "analysis-inputs-unavailable",
  "agent-outputs-unavailable",
]);

function countWarnings(content: string): number {
  const matches = content.match(/WARNING|告警|风险/g);
  return matches?.length ?? 0;
}

function toFinalReportView(payload: FinalReportResponse, sourceEndpoint: string): FinalReportView {
  return {
    ...payload,
    format: payload.format ?? "markdown",
    report_type: "final_report",
    source_endpoint: sourceEndpoint,
    content_length: payload.content.length,
    warning_count: countWarnings(payload.content),
  };
}

function toVisualReportView(payload: VisualReportResponse, sourceEndpoint: string, reportFamily: VisualReportView["report_family"]): VisualReportView {
  return {
    ...payload,
    report_family: reportFamily,
    source_endpoint: sourceEndpoint,
  };
}

function toJin10ReportBundleView(payload: Jin10ReportBundleResponse, sourceEndpoint: string): Jin10ReportBundleView {
  return {
    ...payload,
    report_family: "jin10_daily_visual",
    source_endpoint: sourceEndpoint,
  };
}

export async function fetchReportsIndex(): Promise<ReportsIndexResponse> {
  return fetchJson<ReportsIndexResponse>(REPORTS_INDEX_PATH);
}

export async function fetchReportsDates(): Promise<ReportsDatesResponse> {
  return fetchJson<ReportsDatesResponse>(REPORTS_DATES_PATH);
}

export async function fetchLatestFinalReport(): Promise<FinalReportView> {
  const payload = await fetchJson<FinalReportResponse>(FINAL_REPORT_LATEST_PATH);
  return toFinalReportView(payload, FINAL_REPORT_LATEST_PATH);
}

export async function fetchFinalReport(tradeDate: string, runId: string): Promise<FinalReportView> {
  const search = new URLSearchParams({ date: tradeDate, run_id: runId });
  const sourceEndpoint = `${FINAL_REPORT_PATH}?${search.toString()}`;
  const payload = await fetchJson<FinalReportResponse>(sourceEndpoint);
  return toFinalReportView(payload, sourceEndpoint);
}

export async function fetchLatestOptionsVisualReport(): Promise<VisualReportView> {
  const payload = await fetchJson<VisualReportResponse>(OPTIONS_VISUAL_REPORT_LATEST_PATH);
  return toVisualReportView(payload, OPTIONS_VISUAL_REPORT_LATEST_PATH, "cme_options_visual");
}

export async function fetchOptionsVisualReport(tradeDate: string, runId?: string): Promise<VisualReportView> {
  const search = new URLSearchParams({ date: tradeDate });
  if (runId) {
    search.set("run_id", runId);
  }
  const sourceEndpoint = `${OPTIONS_VISUAL_REPORT_PATH}?${search.toString()}`;
  const payload = await fetchJson<VisualReportResponse>(sourceEndpoint);
  return toVisualReportView(payload, sourceEndpoint, "cme_options_visual");
}

export async function fetchLatestJin10DailyVisualReport(): Promise<VisualReportView> {
  const payload = await fetchJson<VisualReportResponse>(JIN10_DAILY_REPORT_LATEST_PATH);
  return toVisualReportView(payload, JIN10_DAILY_REPORT_LATEST_PATH, "jin10_daily_visual");
}

export async function fetchJin10DailyVisualReport(tradeDate: string, runId: string): Promise<VisualReportView> {
  const search = new URLSearchParams({ date: tradeDate, run_id: runId });
  const sourceEndpoint = `${JIN10_DAILY_REPORT_PATH}?${search.toString()}`;
  const payload = await fetchJson<VisualReportResponse>(sourceEndpoint);
  return toVisualReportView(payload, sourceEndpoint, "jin10_daily_visual");
}

export async function fetchLatestJin10ReportBundle(): Promise<Jin10ReportBundleView> {
  const payload = await fetchJson<Jin10ReportBundleResponse>(JIN10_REPORT_BUNDLE_LATEST_PATH);
  return toJin10ReportBundleView(payload, JIN10_REPORT_BUNDLE_LATEST_PATH);
}

export async function fetchJin10ReportBundle(tradeDate: string, runId: string): Promise<Jin10ReportBundleView> {
  const search = new URLSearchParams({ date: tradeDate, run_id: runId });
  const sourceEndpoint = `${JIN10_REPORT_BUNDLE_PATH}?${search.toString()}`;
  const payload = await fetchJson<Jin10ReportBundleResponse>(sourceEndpoint);
  return toJin10ReportBundleView(payload, sourceEndpoint);
}

export async function fetchLatestJin10WeeklyReport(): Promise<Jin10WeeklyReportView> {
  const payload = await fetchJson<Jin10WeeklyReportResponse>(JIN10_WEEKLY_REPORT_LATEST_PATH);
  return { ...payload, report_family: "jin10_weekly_visual", source_endpoint: JIN10_WEEKLY_REPORT_LATEST_PATH };
}

export async function fetchJin10WeeklyReport(date: string, runId: string): Promise<Jin10WeeklyReportView> {
  const search = new URLSearchParams({ date, run_id: runId });
  const sourceEndpoint = `${JIN10_WEEKLY_REPORT_PATH}?${search.toString()}`;
  const payload = await fetchJson<Jin10WeeklyReportResponse>(sourceEndpoint);
  return { ...payload, report_family: "jin10_weekly_visual", source_endpoint: sourceEndpoint };
}

function mapSourceRef(source: BackendSourceRef): SourceRef {
  return {
    source_ref: source.source_name || source.source_id,
    label: source.source_name,
    endpoint: source.endpoint,
    artifact_path: source.file_path,
    trade_date: source.data_date,
    dataDate: source.data_date,
    asOf: source.captured_at,
    generated_at: source.captured_at,
    provider: source.source_type,
    source_url: source.url,
    status: normalizeDataStatus(source.status),
  };
}

function dedupeSourceRefViews(refs: SourceRef[]): SourceRef[] {
  const seen = new Set<string>();
  return refs.filter((ref) => {
    const key = ref.source_url ? `url:${ref.source_url}` : [ref.source_ref, ref.artifact_path ?? ""].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function extractGenerationTrace(payload: Record<string, unknown> | null | undefined): ReportGenerationTrace | null {
  const trace = payload?._generation_trace;
  if (!trace || typeof trace !== "object" || Array.isArray(trace)) {
    return null;
  }
  return trace as ReportGenerationTrace;
}

function mapArtifactRef(artifact: BackendArtifactRef | ReportArtifactResponse): ArtifactRef {
  return {
    artifact_id: artifact.artifact_id,
    artifact_type: artifact.artifact_type,
    file_path: artifact.file_path,
    path: artifact.file_path,
    content_type: "content_type" in artifact ? artifact.content_type : null,
    is_primary: "is_primary" in artifact ? artifact.is_primary : null,
    asOf: artifact.generated_at,
  };
}

function inferArtifactFormat(payload: ReportArtifactPayloadResponse): ReportFormat {
  const contentType = payload.content_type?.toLowerCase() ?? "";
  const artifactType = payload.artifact_type?.toLowerCase() ?? "";
  const path = payload.path?.toLowerCase() ?? "";
  if (contentType.includes("html") || artifactType.includes("html") || path.endsWith(".html")) return "html";
  if (contentType.includes("json") || artifactType.includes("json") || path.endsWith(".json")) return "json";
  if (contentType.includes("markdown") || artifactType.includes("_md") || path.endsWith(".md")) return "markdown";
  return "text";
}

function normalizeArtifactContent(payload: ReportArtifactPayloadResponse): string {
  if (typeof payload.content === "string") {
    return payload.content;
  }
  if (payload.content == null) {
    return "";
  }
  try {
    return JSON.stringify(payload.content, null, 2);
  } catch {
    return String(payload.content);
  }
}

export function stripEmbeddedSourceSection(content: string): string {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const result: string[] = [];
  let skipping = false;
  let skippedHeadingLevel = 0;
  for (const line of lines) {
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading && /(?:数据源|数据来源|Data Sources|Source Refs)/i.test(heading[2])) {
      skipping = true;
      skippedHeadingLevel = heading[1].length;
      continue;
    }
    if (skipping && heading && heading[1].length <= skippedHeadingLevel) {
      skipping = false;
    }
    if (!skipping) result.push(line);
  }
  return result.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd() + "\n";
}

export function sanitizeReportAnalysisMarkdown(content: string): string {
  const withoutSources = stripEmbeddedSourceSection(content);
  const title = withoutSources.match(/^#\s+(XAUUSD 宏观 \/ 流动性更新（[^\n]+）)\s*$/m);
  const table = withoutSources.match(/## 流动性与利率统一数据表\s*\n([\s\S]*?)(?=\n##\s|$)/);
  if (!title || !table) return withoutSources;

  const dataRows = table[1]
    .split("\n")
    .filter((line) => /^\|/.test(line.trim()))
    .slice(2);
  const allRowsMissing = dataRows.length > 0
    && dataRows.every((line) => (line.match(/明确缺失/g) ?? []).length >= 5);
  if (!allRowsMissing) return withoutSources;

  return [
    `# ${title[1]}`,
    "",
    "## 本次报告不可用",
    "",
    "本次宏观采集没有获得任何有效指标，因此不展示方向、阶段或交易含义判断。",
    "",
    "请在数据接入或调度中心检查该次运行的采集失败原因并重试。",
    "",
  ].join("\n");
}

async function fetchOptionalJson<T>(path: string, signal?: AbortSignal): Promise<T | null> {
  try {
    return await fetchJson<T>(path, { signal });
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      return null;
    }
    throw cause;
  }
}

async function fetchReportArtifactPayload(
  reportId: string,
  tab: ReportArtifactTabKey,
  signal?: AbortSignal,
): Promise<ReportArtifactContentView | null> {
  const config = REPORT_DETAIL_TAB_CONFIG[tab];
  const sourceEndpoint = `${REPORTS_DETAIL_PATH}/${reportId}/${config.endpoint}`;
  const payload = await fetchOptionalJson<ReportArtifactPayloadResponse>(sourceEndpoint, signal);
  if (!payload) {
    return null;
  }
  const format = inferArtifactFormat(payload);
  const rawContent = normalizeArtifactContent(payload);
  return {
    key: tab,
    label: config.label,
    available: true,
    artifact_type: payload.artifact_type,
    content_type: payload.content_type,
    format,
    content: tab === "analysis" && format === "markdown" ? sanitizeReportAnalysisMarkdown(rawContent) : rawContent,
    path: payload.path,
    asset_base_url: payload.asset_base_url ?? null,
    source_endpoint: sourceEndpoint,
  };
}

function mapDeterministicInput(item: ReportDeterministicInputResponse): ReportAnalysisInputItemView {
  return {
    input_id: item.input_id,
    input_type: item.input_type,
    title: item.title,
    data_status: normalizeDataStatus(item.data_status) as DataStatus,
    snapshot_id: item.snapshot?.snapshot_id ?? null,
    run_id: item.snapshot?.run_id ?? null,
    snapshot_type: item.snapshot?.snapshot_type ?? null,
    trade_date: item.snapshot?.data_date ?? null,
    created_at: item.snapshot?.created_at ?? null,
    input_snapshot_ids: item.snapshot?.input_snapshot_ids ?? [],
    sections: item.sections ?? [],
    source_refs: (item.source_refs ?? []).map(mapSourceRef),
    artifact_refs: (item.artifact_refs ?? []).map(mapArtifactRef),
    payload: item.payload ?? null,
  };
}

function mapAnalysisAgentOutput(item: ReportAnalysisAgentOutputResponse): ReportAnalysisAgentOutputView {
  return {
    agent_output_id: item.agent_output_id,
    registry_id: item.registry_id ?? null,
    agent_name: item.agent_name,
    display_name: item.display_name,
    role: item.role,
    module: item.module,
    version: item.version,
    run_id: item.run_id ?? null,
    snapshot_id: item.snapshot_id ?? null,
    status: normalizeDataStatus(item.status) as DataStatus,
    bias: item.bias,
    confidence: item.confidence,
    summary: item.summary,
    summary_zh: item.summary_zh,
    key_findings: item.key_findings ?? [],
    risk_points: item.risk_points ?? [],
    watchlist: item.watchlist ?? [],
    invalid_conditions: item.invalid_conditions ?? [],
    source_refs: (item.source_refs ?? []).map(mapSourceRef),
    artifact_refs: (item.artifact_refs ?? []).map(mapArtifactRef),
    claim_count: item.claim_count ?? 0,
    fact_review_status: item.fact_review_status ?? null,
    prompt_version: item.prompt_version ?? null,
    generated_by: item.generated_by ?? null,
    llm_model: item.llm_model ?? null,
    llm_audit: item.llm_audit ?? null,
    created_at: item.created_at ?? null,
  };
}

async function fetchReportAnalysisInputs(reportId: string, signal?: AbortSignal): Promise<ReportAnalysisInputsView | null> {
  const sourceEndpoint = `${REPORTS_ANALYSIS_INPUTS_PATH}/${reportId}/analysis-inputs`;
  const payload = await fetchOptionalJson<ReportAnalysisInputsResponse>(sourceEndpoint, signal);
  if (!payload) {
    return null;
  }
  return {
    report_id: payload.report_id,
    family: payload.family ?? null,
    title: payload.title ?? null,
    asset: payload.asset ?? null,
    trade_date: payload.trade_date ?? null,
    run_id: payload.run_id ?? null,
    snapshot_id: payload.snapshot_id ?? null,
    source_endpoint: sourceEndpoint,
    data_status: normalizeDataStatus(payload.data_status) as DataStatus,
    source_refs: (payload.source_refs ?? []).map(mapSourceRef),
    artifact_refs: (payload.artifact_refs ?? []).map(mapArtifactRef),
    warnings: payload.warnings ?? [],
    deterministic_inputs: (payload.deterministic_inputs ?? []).map(mapDeterministicInput),
    agent_outputs: (payload.agent_outputs ?? []).map(mapAnalysisAgentOutput),
    fact_reviews: (payload.fact_reviews ?? []).map(mapAnalysisAgentOutput),
    synthesis_outputs: (payload.synthesis_outputs ?? []).map(mapAnalysisAgentOutput),
  };
}

export async function fetchReportDetail(reportId: string, signal?: AbortSignal): Promise<ReportDetailResponse> {
  return fetchJson<ReportDetailResponse>(`${REPORTS_DETAIL_PATH}/${reportId}`, { signal });
}

export async function fetchReportDetailView(reportId: string, signal?: AbortSignal): Promise<ReportDetailView> {
  const detail = await fetchReportDetail(reportId, signal);
  const artifactTypes = new Set((detail.artifacts ?? []).map((artifact) => artifact.artifact_type?.toLowerCase()).filter(Boolean));
  const shouldFetchTab = (tab: ReportArtifactTabKey) =>
    REPORT_TAB_ARTIFACT_TYPES[tab].some((artifactType) => artifactTypes.has(artifactType));

  const [analysis, source, visual, evidence, sourceTrace, analysisInputs] = await Promise.all([
    shouldFetchTab("analysis") ? fetchReportArtifactPayload(reportId, "analysis", signal) : Promise.resolve(null),
    shouldFetchTab("source") ? fetchReportArtifactPayload(reportId, "source", signal) : Promise.resolve(null),
    shouldFetchTab("visual") ? fetchReportArtifactPayload(reportId, "visual", signal) : Promise.resolve(null),
    shouldFetchTab("evidence") ? fetchReportArtifactPayload(reportId, "evidence", signal) : Promise.resolve(null),
    Promise.resolve(null),
    fetchReportAnalysisInputs(reportId, signal),
  ]);

  const tabs: Partial<Record<ReportArtifactTabKey, ReportArtifactContentView>> = {};
  if (analysis) tabs.analysis = analysis;
  if (source) tabs.source = source;
  if (visual) tabs.visual = visual;
  if (evidence) tabs.evidence = evidence;

  const availableTabs: ReportDetailTabKey[] = (Object.keys(REPORT_DETAIL_TAB_CONFIG) as ReportArtifactTabKey[]).filter(
    (tab) => tabs[tab]?.available,
  );
  if (analysisInputs) {
    availableTabs.push("inputs");
  }
  const analysisUnavailable = detail.family === "macro_report"
    && analysis?.content.includes("## 本次报告不可用") === true;
  const dataStatus = analysisUnavailable
    ? "unavailable"
    : normalizeDataStatus(detail.data_status) as DataStatus;
  const sourceRefs = dedupeSourceRefViews((detail.source_refs ?? []).map(mapSourceRef));
  const artifactRefs = (detail.artifact_refs ?? detail.artifacts ?? []).map(mapArtifactRef);
  const warnings = [...(detail.warnings ?? []), ...(analysisInputs?.warnings ?? [])]
    .filter((item, index, array) => array.findIndex((candidate) => candidate.code === item.code && candidate.message === item.message) === index)
    .filter((item) => !INFO_ONLY_WARNING_CODES.has(item.code));

  return {
    report_id: detail.report_id,
    meta: {
      report_id: detail.report_id,
      type: detail.family,
      family: detail.family,
      title: detail.title,
      asset: detail.asset ?? undefined,
      trade_date: detail.trade_date ?? undefined,
      dataDate: detail.trade_date ?? undefined,
      asOf: detail.generated_at ?? undefined,
      run_id: detail.run_id ?? undefined,
      snapshot_id: detail.snapshot_id ?? undefined,
      format: analysis?.format ?? visual?.format ?? evidence?.format ?? source?.format ?? "markdown",
      status: dataStatus,
      generated_at: detail.generated_at ?? undefined,
      source_refs: sourceRefs,
      lifecycle_status: detail.lifecycle_status,
      review_status: detail.review_status,
      input_snapshot_ids: detail.input_snapshot_ids ?? [],
      warning_count: warnings.length,
      artifact_count: detail.artifacts?.length ?? 0,
    },
    data_status: dataStatus,
    source_refs: sourceRefs,
    artifact_refs: artifactRefs,
    warnings,
    source_trace: sourceTrace,
    analysis_inputs: analysisInputs,
    tabs,
    available_tabs: availableTabs,
    structured_payload: detail.structured_payload ?? null,
    generation_trace: extractGenerationTrace(detail.structured_payload),
    gold_macro_overview: detail.gold_macro_overview ?? null,
    market_odds_evidence: detail.market_odds_evidence ?? null,
    llm_audits: detail.llm_audits ?? [],
  };
}
