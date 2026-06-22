import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { ReportAnalysisInputsView } from "@/types/reports";
import {
  ReportAnalysisDeterministicInputsSection,
  ReportAnalysisOutputSection,
  ReportAnalysisSummaryCards,
} from "./ReportAnalysisInputSections";

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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2 text-[10px] text-[var(--fg-4)]">
        <span className="text-[11px] font-semibold text-[var(--fg-2)]">分析输入</span>
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-0.5">
          家族 {model.family ?? "-"}
        </span>
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-0.5">
          资产 {model.asset ?? "-"}
        </span>
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-0.5">
          日期 {model.trade_date ?? "-"}
        </span>
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
