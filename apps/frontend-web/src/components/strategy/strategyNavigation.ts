import type { DashboardDataResponse, DashboardSummary, DashboardViewModel } from "@/types/dashboard";
import type { ResultIdentity } from "@/types/result-identity";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
export type StrategyReturnTarget = "/dashboard" | "/dashboard/analysis";

function isKnownResultIdentity(identity: ResultIdentity | null | undefined): boolean {
  return identity?.schema_version === "gold_result_identity.v1";
}

export interface StrategySourceContext {
  source: "dashboard";
  returnTo: StrategyReturnTarget;
  returnLabel: string;
  label: string;
  reportType: string | null;
  tradeDate: string | null;
  asOf: string | null;
  runId: string | null;
  snapshotId: string | null;
  reportId: string | null;
  authority: string | null;
  publishAllowed: boolean | null;
  sourceRefs: string[];
  sourceResultIdentity: ResultIdentity | null;
}

export interface StrategyNavigationState {
  strategySource: StrategySourceContext;
  /** The frozen dashboard DTO is returned to DashboardAnalysisPage when present. */
  dashboardResult?: DashboardDataResponse | null;
}

interface BuildStrategyNavigationInput {
  summary?: DashboardSummary | null;
  viewModel?: DashboardViewModel | null;
  dashboardResult?: DashboardDataResponse | null;
  /** Supplied by the existing DashboardIntegratedMacroModel helper. */
  researchDate?: string | null;
  researchAsOf?: string | null;
  returnTo?: StrategyReturnTarget;
  returnLabel?: string;
}

function nonEmpty(value: string | null | undefined): string | null {
  const text = value?.trim();
  return text ? text : null;
}

function normalizeDate(value: string | null | undefined): string | null {
  const text = nonEmpty(value);
  return text && text !== "未提供" && text !== "—" ? text : null;
}

function returnLabelFor(target: StrategyReturnTarget): string {
  return target === "/dashboard/analysis" ? "返回判断与依据" : "返回总览";
}

function sourceReportId(summary: DashboardSummary, tradeDate: string | null, runId: string | null): string | null {
  if (!runId) return null;
  const report = summary.latest_reports.find((item) => (
    item.report_id
    && item.run_id === runId
    && (!tradeDate || item.trade_date === tradeDate)
  ));
  return nonEmpty(report?.report_id);
}

function sourceSnapshotId(summary: DashboardSummary): string | null {
  const snapshots = [...new Set(
    (summary.integrated_macro?.source_refs ?? [])
      .map((ref) => nonEmpty(ref.snapshot_id))
      .filter((ref): ref is string => ref !== null),
  )];
  return snapshots.length === 1 ? snapshots[0] : null;
}

export function buildDashboardStrategyNavigationState({
  summary,
  viewModel,
  dashboardResult,
  researchDate,
  researchAsOf,
  returnTo = "/dashboard",
  returnLabel = returnLabelFor(returnTo),
}: BuildStrategyNavigationInput): StrategyNavigationState {
  const resolvedSummary = summary ?? dashboardResult?.summary ?? null;
  const resolvedViewModel = viewModel ?? dashboardResult?.view_model ?? null;
  const integrated = resolvedSummary?.integrated_macro ?? null;
  const tradeDate = normalizeDate(researchDate ?? integrated?.trade_date ?? null);
  const asOf = nonEmpty(researchAsOf ?? integrated?.as_of ?? null);
  const runId = nonEmpty(integrated?.run_id);
  const reportType = nonEmpty(integrated?.report_type) ?? "dashboard_summary";
  const sourceRefs = integrated?.source_refs ?? resolvedViewModel?.source_refs ?? [];

  return {
    strategySource: {
      source: "dashboard",
      returnTo,
      returnLabel,
      label: reportType === "research_observation_summary" ? "首页研究观察" : "首页综合分析",
      reportType,
      tradeDate,
      asOf,
      runId,
      snapshotId: resolvedSummary ? sourceSnapshotId(resolvedSummary) : null,
      reportId: resolvedSummary ? sourceReportId(resolvedSummary, tradeDate, runId) : null,
      authority: nonEmpty(integrated?.authority),
      publishAllowed: integrated?.publish_allowed ?? null,
      sourceRefs: sourceRefs
        .map((ref) => nonEmpty("source_ref" in ref ? ref.source_ref : null))
        .filter((ref): ref is string => ref !== null)
        .slice(0, 4),
      // DashboardSummary has no explicit formal result identity.  Do not use
      // the target live strategy identity as a proxy for this source.
      sourceResultIdentity: null,
    },
    dashboardResult: dashboardResult ?? undefined,
  };
}

export function buildMinimalStrategyNavigationState({
  dataDate,
  sourceRefs,
  returnTo = "/dashboard",
}: {
  dataDate: string;
  sourceRefs: string[];
  returnTo?: StrategyReturnTarget;
}): StrategyNavigationState {
  return {
    strategySource: {
      source: "dashboard",
      returnTo,
      returnLabel: returnLabelFor(returnTo),
      label: "首页综合分析",
      reportType: "dashboard_summary",
      tradeDate: normalizeDate(dataDate),
      asOf: null,
      runId: null,
      snapshotId: null,
      reportId: null,
      authority: null,
      publishAllowed: null,
      sourceRefs: sourceRefs.map(nonEmpty).filter((ref): ref is string => ref !== null).slice(0, 4),
      sourceResultIdentity: null,
    },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function safeReturnTarget(value: unknown): StrategyReturnTarget {
  return value === "/dashboard/analysis" ? "/dashboard/analysis" : "/dashboard";
}

/** Keeps arbitrary browser history state from becoming a strategy source claim. */
export function readStrategyNavigationState(value: unknown): StrategyNavigationState | null {
  if (!isRecord(value) || !isRecord(value.strategySource) || value.strategySource.source !== "dashboard") return null;
  const raw = value.strategySource;
  const source: StrategySourceContext = {
    source: "dashboard",
    returnTo: safeReturnTarget(raw.returnTo),
    returnLabel: nonEmpty(typeof raw.returnLabel === "string" ? raw.returnLabel : null) ?? returnLabelFor(safeReturnTarget(raw.returnTo)),
    label: nonEmpty(typeof raw.label === "string" ? raw.label : null) ?? "首页来源",
    reportType: nonEmpty(typeof raw.reportType === "string" ? raw.reportType : null),
    tradeDate: normalizeDate(typeof raw.tradeDate === "string" ? raw.tradeDate : null),
    asOf: nonEmpty(typeof raw.asOf === "string" ? raw.asOf : null),
    runId: nonEmpty(typeof raw.runId === "string" ? raw.runId : null),
    snapshotId: nonEmpty(typeof raw.snapshotId === "string" ? raw.snapshotId : null),
    reportId: nonEmpty(typeof raw.reportId === "string" ? raw.reportId : null),
    authority: nonEmpty(typeof raw.authority === "string" ? raw.authority : null),
    publishAllowed: typeof raw.publishAllowed === "boolean" ? raw.publishAllowed : null,
    sourceRefs: Array.isArray(raw.sourceRefs) ? raw.sourceRefs.filter((item): item is string => typeof item === "string").slice(0, 4) : [],
    sourceResultIdentity: isRecord(raw.sourceResultIdentity) ? raw.sourceResultIdentity as unknown as ResultIdentity : null,
  };
  return {
    strategySource: source,
    dashboardResult: isRecord(value.dashboardResult) ? value.dashboardResult as unknown as DashboardDataResponse : undefined,
  };
}

interface IdentityComparison {
  label: string;
  tone: FAStatusTone;
  detail: string;
}

export function compareStrategySourceIdentity(source: StrategySourceContext, current: ResultIdentity | null | undefined): IdentityComparison {
  if (!source.sourceResultIdentity) {
    return {
      label: "无法核验",
      tone: "warn",
      detail: "首页来源只提供日期或研究 run；后端未提供可与当前策略直接比较的正式结果身份。",
    };
  }
  if (!current) {
    return {
      label: "无法核验",
      tone: "warn",
      detail: "当前策略尚未返回正式结果身份，暂不能判断是否沿用首页结果。",
    };
  }
  if (!isKnownResultIdentity(source.sourceResultIdentity) || !isKnownResultIdentity(current)) {
    return {
      label: "无法核验",
      tone: "warn",
      detail: "来源或当前结果身份 schema 未知，页面不会根据日期或单个字段推断一致性。",
    };
  }

  const sourceSubject = source.sourceResultIdentity.subject;
  const currentSubject = current.subject;
  const sourceResultId = nonEmpty(sourceSubject.result_id);
  const currentResultId = nonEmpty(currentSubject.result_id);
  if (sourceResultId && currentResultId) {
    return sourceResultId === currentResultId
      ? { label: "身份一致", tone: "up", detail: "后端正式结果 ID 与首页来源一致。" }
      : { label: "不同结果", tone: "warn", detail: "后端正式结果 ID 与首页来源不同，当前页面不能沿用首页结论。" };
  }

  const sameKind = nonEmpty(sourceSubject.kind) && sourceSubject.kind === nonEmpty(currentSubject.kind);
  const sourceRunId = nonEmpty(sourceSubject.run_id);
  const currentRunId = nonEmpty(currentSubject.run_id);
  if (sameKind && sourceRunId && currentRunId) {
    return sourceRunId === currentRunId
      ? { label: "身份一致", tone: "up", detail: "后端同类正式结果 run ID 与首页来源一致。" }
      : { label: "不同结果", tone: "warn", detail: "后端同类正式结果 run ID 与首页来源不同。" };
  }
  return {
    label: "无法核验",
    tone: "warn",
    detail: "正式结果缺少可比较的结果 ID 或同类 run ID，页面不会把日期相同当作身份一致。",
  };
}
