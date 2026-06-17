import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import type { ReportAnalysisInputsView } from "@/types/reports";
import {
  ReportAnalysisDeterministicInputsSection,
  ReportAnalysisOutputSection,
  ReportAnalysisSummaryCards,
} from "./ReportAnalysisInputSections";
import { ReportTraceDrilldown } from "./ReportTraceDrilldown";

export function ReportAnalysisInputsPanel({ model }: { model: ReportAnalysisInputsView | null }) {
  if (!model) {
    return (
      <FAEmptyState
        title="当前报告暂无分析输入视图"
        description="后端尚未返回分析输入数据，或当前报告仍停留在旧链路。"
      />
    );
  }

  return (
    <div className="max-h-[calc(100vh-260px)] min-h-0 space-y-4 overflow-y-auto overflow-x-hidden pr-1">
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[12px] font-semibold text-[var(--fg-2)]">分析输入总览</div>
            <div className="mt-1 text-[11px] text-[var(--fg-4)]">
              当前视图聚合 analysis snapshot、deterministic inputs 与各阶段 agent output 的溯源信息。
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px] text-[var(--fg-4)]">
            {model.source_endpoint ? <FASourceTraceBadge source={model.source_endpoint} status="api" tone="info" /> : null}
            <FASourceTraceBadge source={model.run_id ?? "无 run_id"} status="run" tone="dim" />
            <FASourceTraceBadge source={model.snapshot_id ?? "无 snapshot_id"} status="snapshot" tone="dim" />
          </div>
        </div>
        <div className="mt-3 grid gap-2 text-[11px] text-[var(--fg-4)] md:grid-cols-2 xl:grid-cols-4">
          <div>family：{model.family ?? "-"}</div>
          <div>asset：{model.asset ?? "-"}</div>
          <div>trade_date：{model.trade_date ?? "-"}</div>
          <div>report_id：{model.report_id}</div>
        </div>
        <ReportTraceDrilldown
          sourceRefs={model.source_refs}
          artifactRefs={model.artifact_refs}
          showPayload={false}
          sourceTitle="本报告分析输入顶层数据源"
          artifactTitle="本报告分析输入顶层产物"
        />
      </div>

      <ReportAnalysisSummaryCards model={model} />
      <ReportAnalysisDeterministicInputsSection items={model.deterministic_inputs} />
      <ReportAnalysisOutputSection
        title="引用智能体输出"
        items={model.agent_outputs}
        emptyTitle="暂无智能体输出"
        emptyDescription="后端没有找到与该报告绑定的已持久化智能体输出。"
      />
      {model.fact_reviews.length > 0 ? (
        <ReportAnalysisOutputSection
          title="事实审查输出"
          items={model.fact_reviews}
          emptyTitle="暂无事实审查输出"
          emptyDescription="后端没有找到与该报告绑定的事实审查结果。"
        />
      ) : null}
      {model.synthesis_outputs.length > 0 ? (
        <ReportAnalysisOutputSection
          title="综合分析输出"
          items={model.synthesis_outputs}
          emptyTitle="暂无综合分析输出"
          emptyDescription="后端没有找到与该报告绑定的综合分析结果。"
        />
      ) : null}
    </div>
  );
}
