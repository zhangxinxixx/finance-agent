import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { Link } from "react-router-dom";
import { ExternalLink, FileText, Target } from "lucide-react";
import type { DashboardAgentCompactSummary, DashboardSummary, DashboardViewModel, SignalDirection } from "@/types/dashboard";
import type { DashboardDataResponse } from "@/types/dashboard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { buildDashboardStrategyNavigationState } from "@/components/strategy/StrategyEntryContext";
import { formatDateTime } from "@/lib/date";
import { buildIntegratedMacroSummary, dashboardResearchAsOf, dashboardResearchDate } from "./DashboardIntegratedMacroModel";
import { translateText } from "./judgmentFormat";

interface DashboardAnalysisPanelProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
  agentSynthesis?: DashboardAgentCompactSummary | null;
  dashboardResult?: DashboardDataResponse | null;
}

interface AnalysisSourceBadge {
  source: string;
  status?: string | null;
  snapshotId?: string | null;
}

function directionMeta(direction: SignalDirection | "unknown" | string | null | undefined): { label: string; tone: FAStatusTone } {
  const value = (direction || "").toLowerCase();
  if (value === "bullish" || value === "看多" || value === "偏多") return { label: "偏多", tone: "up" };
  if (value === "bearish" || value === "看空" || value === "偏空") return { label: "偏空", tone: "down" };
  if (value === "neutral-bullish") return { label: "中性偏多", tone: "up" };
  if (value === "neutral-bearish") return { label: "中性偏空", tone: "down" };
  if (value === "mixed") return { label: "混合", tone: "warn" };
  if (value === "unknown" || value === "unavailable") return { label: "待确认", tone: "dim" };
  return { label: value ? translateText(String(direction)) : "中性", tone: "neutral" };
}

function reviewMeta(status: string | null | undefined): { label: string; tone: FAStatusTone } {
  const value = (status || "").toLowerCase();
  if (value === "success" || value === "supported") return { label: "已核验", tone: "up" };
  if (value === "partial" || value === "partially_supported") return { label: "部分待补证", tone: "warn" };
  if (value === "needs_review" || value === "conflicted") return { label: "待复核", tone: "warn" };
  if (value === "unsupported" || value === "contradicted" || value === "unavailable") return { label: "审查有风险", tone: "down" };
  return { label: "未审查", tone: "dim" };
}

function uniqueList(items: Array<string | null | undefined>, fallback: string): string[] {
  const seen = new Set<string>();
  const values = items
    .map((item) => (item || "").trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false;
      seen.add(item);
      return true;
    });
  return values.length ? values : [fallback];
}

function sourceTone(status: string | null | undefined): FAStatusTone {
  const value = (status || "").toLowerCase();
  if (value === "ok" || value === "ready" || value === "success") return "up";
  if (value === "warn" || value === "warning" || value === "stale" || value === "fallback") return "warn";
  if (value === "error" || value === "failed") return "down";
  if (value === "unavailable" || value === "missing") return "dim";
  return "info";
}

function ReasoningSection({ title, children }: { title: string; children: string }) {
  return (
    <section className="dashboard-reasoning-section">
      <div className="dashboard-memo-subheading">{title}</div>
      <p>{translateText(children)}</p>
    </section>
  );
}

function ReasoningList({ title, items, tone }: { title: string; items: string[]; tone: "brand" | "warn" }) {
  return (
    <section className="dashboard-reasoning-section">
      <div className="dashboard-memo-subheading">{title}</div>
      <div className={`dashboard-reasoning-list dashboard-reasoning-list--${tone}`}>
        {items.map((item) => (
          <div key={item} className="dashboard-reasoning-list-row">
            <span aria-hidden="true" />
            <p>{translateText(item)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatConclusionTime(value: string | null | undefined, fallback: string): string {
  if (!value) return fallback;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return formatDateTime(value);
}

export function DashboardAnalysisPanel({ summary, viewModel, agentSynthesis, dashboardResult }: DashboardAnalysisPanelProps) {
  const strategyView = viewModel?.strategy_card ?? null;
  const research = summary.integrated_macro;
  const integrated = buildIntegratedMacroSummary(summary, viewModel);
  const isObservationOnly = summary.integrated_macro?.authority === "observation_only"
    || summary.integrated_macro?.publish_allowed === false;
  const dataDate = dashboardResearchDate(summary, viewModel);
  const conclusionTime = formatConclusionTime(
    dashboardResearchAsOf(summary, viewModel),
    dataDate,
  );
  const direction = integrated.direction;
  const directionBadge = directionMeta(direction);
  const reviewBadge = isObservationOnly
    ? { label: "研究观察/未迁移", tone: "warn" as FAStatusTone }
    : summary.integrated_macro
      ? { label: "核验状态未提供", tone: "dim" as FAStatusTone }
      : reviewMeta(agentSynthesis?.factReviewStatus ?? null);
  const confidence = summary.integrated_macro
    ? integrated.confidence
    : integrated.confidence ?? agentSynthesis?.confidence ?? strategyView?.confidence;
  const confidencePct = typeof confidence !== "number" || !Number.isFinite(confidence) ? null : Math.round(Math.max(0, Math.min(1, confidence)) * 100);
  const confidenceLabel = confidencePct == null ? "置信度未量化" : `置信度 ${confidencePct}/100`;
  const macroThread = integrated.macroExplanation;
  const liquidityThread = integrated.liquidityExplanation;
  const optionsThread = integrated.optionsMemo;
  const resonanceItems = uniqueList(
    research ? (research.trigger_upgrade ?? []) : [
      ...(strategyView?.trigger_conditions ?? []),
    ],
    isObservationOnly ? "本摘要未列共振条件，请查看完整研究报告。" : "后端暂未提供共振因素。",
  );
  const failureItems = uniqueList(
    research ? [
      ...(summary.integrated_macro?.trigger_downgrade ?? []),
      ...(summary.integrated_macro?.invalidation ?? []),
    ] : [
      ...(summary.integrated_macro?.trigger_downgrade ?? []),
      ...(agentSynthesis?.invalidConditions ?? []),
      ...(strategyView?.invalid_conditions ?? []),
      ...integrated.invalidation,
    ],
    isObservationOnly ? "本摘要未列失效条件，请查看完整研究报告。" : "后端暂未提供风险和失效条件。",
  );
  const riskItems = uniqueList(research ? research.risks ?? [] : [
    ...(agentSynthesis?.riskPoints ?? []), ...(strategyView?.risk_points ?? []), ...summary.risk.alerts,
  ], "本次结果未提供风险说明。");
  const missingInputs = research?.missing_inputs ?? [];
  const sourceRefs: AnalysisSourceBadge[] = [
    ...(research ? research.source_refs ?? [] : [...(strategyView?.source_refs ?? []), ...(viewModel?.source_refs ?? [])]),
  ]
    .map((ref) => ({
      source: "label" in ref ? ref.label ?? ref.source_ref : ref.source_ref,
      status: ref.status,
      snapshotId: ref.snapshot_id,
    }));
  const sourceTrace = research || sourceRefs.length
    ? sourceRefs
    : summary.source_trace.map((trace) => ({
        source: trace.source_ref,
        status: trace.status,
        snapshotId: trace.snapshot_id,
      }));
  const researchReport = research?.run_id && research.trade_date
    ? summary.latest_reports.find((report) => report.status === "ready" && report.run_id === research.run_id
      && report.trade_date === research.trade_date && report.family !== "macro_event_followup_supplement")
    : undefined;
  const researchReportId = researchReport?.report_id ?? research?.source_refs?.find(
    (ref) => research.run_id && ref.source_ref === `observation_report:${research.run_id}`,
  )?.source_ref;
  const reportTarget = researchReportId
    ? `/reports/${encodeURIComponent(researchReportId)}`
    : researchReport?.url?.startsWith("/reports/") ? researchReport.url : "/reports";
  const strategyNavigation = buildDashboardStrategyNavigationState({
    summary,
    viewModel,
    dashboardResult,
    researchDate: dataDate,
    researchAsOf: dashboardResearchAsOf(summary, viewModel),
    returnTo: "/dashboard/analysis",
    returnLabel: "返回判断与依据",
  });

  return (
    <section className="fa-card dashboard-memo-panel min-h-[276px]">
      <header className="fa-card-header dashboard-memo-header border-b border-[var(--border-faint)] !px-3 !py-2">
        <span className="h-3 w-[2px] rounded-[var(--radius-xs)] fa-important-bg" />
        <div className="dashboard-memo-heading-block">
          <div className="dashboard-memo-title">判断拆解</div>
          <div className="dashboard-memo-status-row">
            <FAStatusPill tone={directionBadge.tone}>{directionBadge.label}</FAStatusPill>
            <FAStatusPill tone={reviewBadge.tone}>{reviewBadge.label}</FAStatusPill>
            <span className="dashboard-memo-status-chip">{confidenceLabel}</span>
            <span className="dashboard-memo-status-chip dashboard-memo-status-chip--time">
              <span className="dashboard-memo-status-label">结论时间</span>
              <span className="fa-num">{conclusionTime}</span>
            </span>
          </div>
        </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            <Link to="/dashboard/analysis" state={dashboardResult ? { dashboardResult } : undefined} className="dashboard-memo-link-button">判断与依据</Link>
            <Link
              to={reportTarget}
              className="dashboard-memo-link-button"
            >
              <FileText size={11} />
              <span>{reportTarget === "/reports" ? "查找报告" : "本次报告"}</span>
              <ExternalLink size={9} className="text-[var(--fa-text-label)]" />
            </Link>
            {!isObservationOnly ? <Link
              to="/strategy"
              state={strategyNavigation}
              className="dashboard-memo-link-button"
            >
              <Target size={11} />
              <span className="hidden 2xl:inline">策略卡片</span>
              <span className="2xl:hidden">策略</span>
              <ExternalLink size={9} className="text-[var(--fa-text-label)]" />
            </Link> : null}
          </div>
      </header>

      <div className="fa-card-body dashboard-memo-body">
        <div className="dashboard-reasoning-body">
          <ReasoningSection title="宏观主线">{macroThread}</ReasoningSection>
          <ReasoningSection title="流动性状态">{liquidityThread}</ReasoningSection>
          <ReasoningSection title="期权配合度">{optionsThread}</ReasoningSection>
          <div className="dashboard-reasoning-grid">
            <ReasoningList title="共振因素" items={resonanceItems} tone="brand" />
            <ReasoningList title="失效条件" items={failureItems} tone="warn" />
          </div>
          <ReasoningList title="风险提醒" items={riskItems} tone="warn" />
          {missingInputs.length ? <ReasoningList title="本次研究缺失输入" items={missingInputs} tone="warn" /> : null}
        </div>

        {sourceTrace.length ? (
          <div className="dashboard-memo-divider" />
        ) : <p className="text-[length:var(--type-caption)] text-[var(--fg-4)]">本次研究未提供来源引用。</p>}

        {sourceTrace.length ? (
          <ResearchDetails label="查看研究依据记录">          <div className="dashboard-memo-source-block">
            <div className="dashboard-memo-subheading">数据来源</div>
            <div className="dashboard-memo-source-chips">
            {sourceTrace.map((ref) => (
              <FASourceTraceBadge
                key={`${ref.source}-${ref.snapshotId ?? ""}`}
                source={ref.source}
                status={ref.status ?? "trace"}
                tone={sourceTone(ref.status)}
                snapshotId={ref.snapshotId}
                className="dashboard-memo-source-badge"
              />
            ))}
            </div>
          </div>
</ResearchDetails>
        ) : null}
      </div>
    </section>
  );
}
