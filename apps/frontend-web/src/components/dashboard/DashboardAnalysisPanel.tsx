import { Link } from "react-router-dom";
import { AlertTriangle, ExternalLink, FileText, ListChecks, Target } from "lucide-react";
import type { DashboardAgentCompactSummary, DashboardSummary, DashboardViewModel, SignalDirection } from "@/types/dashboard";
import { FAConvictionBar } from "@/components/shared/FAConvictionBar";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { translateText } from "./judgmentFormat";

interface DashboardAnalysisPanelProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
  agentSynthesis?: DashboardAgentCompactSummary | null;
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

function AnalysisList({ title, icon, items, tone }: { title: string; icon: "check" | "risk"; items: string[]; tone: "brand" | "warn" }) {
  const Icon = icon === "check" ? ListChecks : AlertTriangle;
  const accent = tone === "warn" ? "var(--warn)" : "var(--brand-hover)";

  return (
    <div className="min-h-[112px] rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
        <Icon size={12} style={{ color: accent }} />
        <span>{title}</span>
      </div>
      <div className="space-y-2">
        {items.slice(0, 3).map((item) => (
          <div key={item} className="flex gap-2 text-[11px] leading-5 text-[var(--fg-3)]">
            <span className="mt-[0.45rem] h-1 w-1 shrink-0 rounded-full" style={{ background: accent }} />
            <span className="line-clamp-2">{translateText(item)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function dashboardReportTarget(url: string | null | undefined): string {
  return url?.startsWith("/reports") ? url : "/reports";
}

export function DashboardAnalysisPanel({ summary, viewModel, agentSynthesis }: DashboardAnalysisPanelProps) {
  const strategyView = viewModel?.strategy_card ?? null;
  const dataDate = viewModel?.trade_date ?? summary.cme_options.trade_date ?? summary.generated_at?.slice(0, 10) ?? "—";
  const direction = agentSynthesis?.bias ?? strategyView?.direction ?? summary.strategy.direction;
  const directionBadge = directionMeta(direction);
  const reviewBadge = reviewMeta(agentSynthesis?.factReviewStatus ?? null);
  const confidence = agentSynthesis?.confidence ?? strategyView?.confidence ?? summary.strategy.confidence ?? null;
  const confidencePct = confidence == null ? null : Math.round(Math.max(0, Math.min(1, confidence)) * 100);
  const summaryText = translateText(
    agentSynthesis?.summary ||
      strategyView?.scenario_summary ||
      summary.strategy.bias ||
      summary.conclusion.options_summary ||
      "等待后端生成综合分析摘要。",
  );
  const findings = uniqueList(
    [
      ...(agentSynthesis?.keyFindings ?? []),
      ...(strategyView?.trigger_conditions ?? []),
      ...summary.strategy.triggers,
    ],
    "后端暂未提供关键触发摘要。",
  );
  const risks = uniqueList(
    [
      ...(agentSynthesis?.riskPoints ?? []),
      ...(agentSynthesis?.invalidConditions ?? []),
      ...(strategyView?.risk_points ?? []),
      ...(strategyView?.invalid_conditions ?? []),
      ...summary.risk.alerts,
      ...summary.strategy.invalid_conditions,
    ],
    "后端暂未提供风险和失效条件。",
  );
  const sourceRefs: AnalysisSourceBadge[] = [
    ...(strategyView?.source_refs ?? []),
    ...(viewModel?.source_refs ?? []),
  ]
    .map((ref) => ({
      source: ref.label ?? ref.source_ref,
      status: ref.status,
      snapshotId: ref.snapshot_id,
    }))
    .slice(0, 3);
  const sourceTrace = sourceRefs.length
    ? sourceRefs
    : summary.source_trace.slice(0, 3).map((trace) => ({
        source: trace.source_ref,
        status: trace.status,
        snapshotId: trace.snapshot_id,
      }));
  const readyReport = summary.latest_reports.find((report) => report.status === "ready" && report.url);
  const reportTarget = dashboardReportTarget(readyReport?.url);

  return (
    <section className="fa-card min-h-[302px] border-[var(--border-faint)] shadow-none">
      <header className="fa-card-header border-b border-[var(--border-faint)]">
        <span className="h-3 w-[2px] rounded-[var(--radius-xs)] bg-[var(--warn)]" />
        <div className="min-w-0 flex-1">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">综合摘要</div>
          <div className="truncate text-[11px] font-semibold leading-tight text-[var(--fg-2)]">综合分析</div>
        </div>
        <div className="hidden items-center gap-1 lg:flex">
          <FAStatusPill tone={directionBadge.tone}>{directionBadge.label}</FAStatusPill>
          <FAStatusPill tone={reviewBadge.tone}>{reviewBadge.label}</FAStatusPill>
        </div>
        <span className="fa-num shrink-0 rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[10px] font-semibold text-[var(--fg-3)]">
          {dataDate}
        </span>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
          <Link
            to={reportTarget}
            className="inline-flex h-6 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[9px] font-semibold text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
          >
            <FileText size={11} />
            <span className="hidden 2xl:inline">完整报告</span>
            <span className="2xl:hidden">报告</span>
            <ExternalLink size={9} className="text-[var(--fg-5)]" />
          </Link>
          <Link
            to="/strategy"
            className="inline-flex h-6 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[9px] font-semibold text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
          >
            <Target size={11} />
            <span className="hidden 2xl:inline">策略卡片</span>
            <span className="2xl:hidden">策略</span>
            <ExternalLink size={9} className="text-[var(--fg-5)]" />
          </Link>
        </div>
      </header>

      <div className="fa-card-body space-y-3">
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_128px]">
          <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3.5 shadow-[0_0_0_1px_rgba(245,158,11,0.04)]">
            <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              <Target size={12} className="text-[var(--brand-hover)]" />
              <span>综合结论</span>
            </div>
            <p className="line-clamp-3 text-[12px] leading-6 text-[var(--fg-1)]">{summaryText}</p>
          </div>
          <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
            <FAConvictionBar value={confidencePct ?? 0} tone="warn" label="确信度" ariaLabel="综合分析确信度" />
            <div className="mt-3 text-[10px] leading-5 text-[var(--fg-5)]">
              {confidencePct == null ? "后端未提供确信度。" : "来自总览摘要模型的综合分析确信度。"}
            </div>
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <AnalysisList title="关键依据" icon="check" items={findings} tone="brand" />
          <AnalysisList title="风险 / 失效" icon="risk" items={risks} tone="warn" />
        </div>

        {sourceTrace.length ? (
          <div className="flex flex-wrap gap-2">
            {sourceTrace.map((ref) => (
              <FASourceTraceBadge
                key={`${ref.source}-${ref.snapshotId ?? ""}`}
                source={ref.source}
                status={ref.status ?? "trace"}
                tone={sourceTone(ref.status)}
                snapshotId={ref.snapshotId}
              />
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
