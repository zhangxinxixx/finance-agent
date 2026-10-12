import { normalizeResearchIdentity } from "@/adapters/researchIdentity";
import { normalizeResearchTradePlan } from "@/adapters/researchTradePlan";
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
  ReportAnalysisInputsView,
  ReportArtifactContentView,
  ReportArtifactPayloadResponse,
  ReportArtifactResponse,
  ReportArtifactTabKey,
  ReportDetailResponse,
  ReportDetailTabKey,
  ReportDetailView,
  ReportGenerationTrace,
  ReportWarningItem,
  ReportsDatesResponse,
  ReportsIndexResponse,
  VisualReportResponse,
  VisualReportView,
} from "@/types/reports";
import { normalizeDataStatus } from "@/lib/status";
import { normalizeResultIdentity } from "@/adapters/resultIdentity";
import { createInFlightRequest } from "./inFlightRequest";

const REPORTS_INDEX_PATH = "/api/reports/index";
const REPORTS_DATES_PATH = "/api/reports/dates";
const REPORTS_DETAIL_PATH = "/api/reports";
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
const fetchReportsIndexRequest = createInFlightRequest(() => fetchJson<ReportsIndexResponse>(REPORTS_INDEX_PATH));
const fetchReportsDatesRequest = createInFlightRequest(() => fetchJson<ReportsDatesResponse>(REPORTS_DATES_PATH));
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

export function fetchReportsIndex(): Promise<ReportsIndexResponse> {
  return fetchReportsIndexRequest();
}

export function fetchReportsDates(): Promise<ReportsDatesResponse> {
  return fetchReportsDatesRequest();
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
  const title = content.match(/^#\s+(XAUUSD 宏观 \/ 流动性更新（[^\n]+）)\s*$/m);
  const table = content.match(/## 流动性与利率统一数据表\s*\n([\s\S]*?)(?=\n##\s|$)/);
  if (!title || !table) return content;

  const dataRows = table[1]
    .split("\n")
    .filter((line) => /^\|/.test(line.trim()))
    .slice(2);
  const allRowsMissing = dataRows.length > 0
    && dataRows.every((line) => (line.match(/明确缺失/g) ?? []).length >= 5);
  if (!allRowsMissing) return content;

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

interface OptionalReportPart<T> {
  value: T | null;
  warning: ReportWarningItem | null;
}

function isAbortFailure(cause: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) {
    return true;
  }
  if (cause instanceof ApiError) {
    return isAbortFailure(cause.cause, signal);
  }
  return typeof cause === "object" && cause !== null && "name" in cause && cause.name === "AbortError";
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw signal.reason ?? new DOMException("请求已取消", "AbortError");
  }
}

async function readOptionalReportPart<T>(
  read: () => Promise<T | null>,
  missingWarning: ReportWarningItem | null,
  failedWarning: ReportWarningItem,
  signal?: AbortSignal,
): Promise<OptionalReportPart<T>> {
  throwIfAborted(signal);
  try {
    const value = await read();
    throwIfAborted(signal);
    return { value, warning: value === null ? missingWarning : null };
  } catch (cause) {
    if (isAbortFailure(cause, signal)) {
      throw cause;
    }
    return { value: null, warning: failedWarning };
  }
}

function artifactReadWarnings(tab: ReportArtifactTabKey): { missing: ReportWarningItem; failed: ReportWarningItem } {
  const label = REPORT_DETAIL_TAB_CONFIG[tab].label;
  return {
    missing: {
      code: "report-artifact-content-missing",
      message: `${label}已在报告元数据登记，但内容读取返回 404，无法核验该证据。`,
      severity: "warning",
      field: tab,
    },
    failed: {
      code: "report-artifact-read-failed",
      message: `${label}读取失败，无法核验该证据。`,
      severity: "warning",
      field: tab,
    },
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

  const readArtifact = (tab: ReportArtifactTabKey): Promise<OptionalReportPart<ReportArtifactContentView>> => {
    if (!shouldFetchTab(tab)) {
      return Promise.resolve({ value: null, warning: null });
    }
    const warnings = artifactReadWarnings(tab);
    return readOptionalReportPart(
      () => fetchReportArtifactPayload(reportId, tab, signal),
      warnings.missing,
      warnings.failed,
      signal,
    );
  };
  const [analysisPart, sourcePart, visualPart, evidencePart] = await Promise.all([
    readArtifact("analysis"),
    readArtifact("source"),
    readArtifact("visual"),
    readArtifact("evidence"),
  ]);
  return normalizeReportDetail(detail, {
    analysis: analysisPart.value, source: sourcePart.value, visual: visualPart.value,
    evidence: evidencePart.value, analysis_inputs: null,
    warnings: [analysisPart, sourcePart, visualPart, evidencePart]
      .map(part => part.warning).filter((warning): warning is ReportWarningItem => warning !== null),
  });
}

export function normalizeReportDetail(detail: ReportDetailResponse, parts: {
  analysis?: ReportArtifactContentView | null;
  source?: ReportArtifactContentView | null;
  visual?: ReportArtifactContentView | null;
  evidence?: ReportArtifactContentView | null;
  analysis_inputs?: ReportAnalysisInputsView | null;
  warnings?: ReportWarningItem[];
} = {}): ReportDetailView {
  const { analysis = null, source = null, visual = null, evidence = null, analysis_inputs: analysisInputs = null } = parts;
  const sourceTrace = null;

  const tabs: Partial<Record<ReportArtifactTabKey, ReportArtifactContentView>> = {};
  if (analysis) tabs.analysis = analysis;
  if (source) tabs.source = source;
  if (visual) tabs.visual = visual;
  if (evidence) tabs.evidence = evidence;

  const availableTabs: ReportDetailTabKey[] = (Object.keys(REPORT_DETAIL_TAB_CONFIG) as ReportArtifactTabKey[]).filter(
    (tab) => tabs[tab]?.available,
  );
  const analysisUnavailable = detail.family === "macro_report"
    && analysis?.content.includes("## 本次报告不可用") === true;
  const dataStatus = analysisUnavailable
    ? "unavailable"
    : normalizeDataStatus(detail.data_status) as DataStatus;
  const sourceRefs = dedupeSourceRefViews((detail.source_refs ?? []).map(mapSourceRef));
  const artifactRefs = (detail.artifact_refs ?? detail.artifacts ?? []).map(mapArtifactRef);
  const warnings = [
    ...(detail.warnings ?? []),
    ...(analysisInputs?.warnings ?? []),
    ...(parts.warnings ?? []),
  ]
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
      asOf: normalizeResearchIdentity(detail.research_identity)?.data_as_of ?? undefined,
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
      report_identity: detail.report_identity ?? null,
    },
    data_status: dataStatus,
    source_refs: sourceRefs,
    artifact_refs: artifactRefs,
    warnings,
    source_trace: sourceTrace,
    analysis_inputs: analysisInputs,
    tabs,
    available_tabs: availableTabs,
    final_trade_plan: normalizeResearchTradePlan(detail.structured_payload?._reader_trade_plan, {
      report_id: detail.report_id, run_id: detail.run_id, snapshot_id: detail.snapshot_id ?? null, trade_date: detail.trade_date,
    }),
    structured_payload: detail.structured_payload ?? null,
    research_identity: normalizeResearchIdentity(detail.research_identity),
    current_context: detail.current_context?.relationship === "current_context_only" ? detail.current_context : null,
    result_identity: normalizeResultIdentity(detail.result_identity),
    generation_trace: extractGenerationTrace(detail.structured_payload),
    gold_macro_overview: detail.gold_macro_overview ?? null,
    market_odds_evidence: detail.market_odds_evidence ?? null,
    llm_audits: detail.llm_audits ?? [],
  };
}
