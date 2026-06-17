import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type {
  ReportAnalysisAgentOutputView,
  ReportAnalysisInputItemView,
  ReportAnalysisInputsView,
} from "@/types/reports";
import { ReportAnalysisDeterministicCard } from "./ReportAnalysisDeterministicCard";
import { ReportAgentOutputCard } from "./ReportAgentOutputCard";

export function ReportAnalysisSummaryCards({ model }: { model: ReportAnalysisInputsView }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <div className="text-[11px] text-[var(--fg-4)]">确定性输入</div>
        <div className="mt-1 text-[22px] font-semibold text-[var(--fg-1)]">{model.deterministic_inputs.length}</div>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <div className="text-[11px] text-[var(--fg-4)]">Agent 输出</div>
        <div className="mt-1 text-[22px] font-semibold text-[var(--fg-1)]">{model.agent_outputs.length}</div>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <div className="text-[11px] text-[var(--fg-4)]">事实审查</div>
        <div className="mt-1 text-[22px] font-semibold text-[var(--fg-1)]">{model.fact_reviews.length}</div>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <div className="text-[11px] text-[var(--fg-4)]">综合输出</div>
        <div className="mt-1 text-[22px] font-semibold text-[var(--fg-1)]">{model.synthesis_outputs.length}</div>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <div className="text-[11px] text-[var(--fg-4)]">顶层来源</div>
        <div className="mt-1 text-[22px] font-semibold text-[var(--fg-1)]">{model.source_refs.length}</div>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <div className="text-[11px] text-[var(--fg-4)]">顶层产物</div>
        <div className="mt-1 text-[22px] font-semibold text-[var(--fg-1)]">{model.artifact_refs.length}</div>
      </div>
    </div>
  );
}

function ReportAnalysisInputItem({ item }: { item: ReportAnalysisInputItemView }) {
  return <ReportAnalysisDeterministicCard item={item} />;
}

export function ReportAgentOutputItem({ item }: { item: ReportAnalysisAgentOutputView }) {
  return <ReportAgentOutputCard item={item} />;
}

export function ReportAnalysisDeterministicInputsSection({ items }: { items: ReportAnalysisInputItemView[] }) {
  return (
    <div className="space-y-3">
      <div className="text-[12px] font-semibold text-[var(--fg-2)]">确定性输入</div>
      {items.length > 0 ? (
        <div className="grid gap-3 xl:grid-cols-2">
          {items.map((item) => (
            <ReportAnalysisInputItem key={item.input_id} item={item} />
          ))}
        </div>
      ) : (
        <FAEmptyState title="暂无确定性输入" description="当前报告没有返回 analysis snapshot 或可回退的 agent input payload。" />
      )}
    </div>
  );
}

export function ReportAnalysisOutputSection({
  title,
  items,
  emptyTitle,
  emptyDescription,
}: {
  title: string;
  items: ReportAnalysisAgentOutputView[];
  emptyTitle: string;
  emptyDescription: string;
}) {
  return (
    <div className="space-y-3">
      <div className="text-[12px] font-semibold text-[var(--fg-2)]">{title}</div>
      {items.length > 0 ? (
        <div className="grid gap-3 xl:grid-cols-2">
          {items.map((item) => (
            <ReportAgentOutputItem key={item.agent_output_id} item={item} />
          ))}
        </div>
      ) : (
        <FAEmptyState title={emptyTitle} description={emptyDescription} />
      )}
    </div>
  );
}
