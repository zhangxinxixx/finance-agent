import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type {
  ReportAnalysisAgentOutputView,
  ReportAnalysisInputItemView,
  ReportAnalysisInputsView,
} from "@/types/reports";
import { ReportAnalysisDeterministicCard } from "./ReportAnalysisDeterministicCard";
import { ReportAgentOutputCard } from "./ReportAgentOutputCard";

export function ReportAnalysisSummaryCards({ model }: { model: ReportAnalysisInputsView }) {
  const metrics = [
    { label: "确定性输入", value: model.deterministic_inputs.length },
    { label: "智能体输出", value: model.agent_outputs.length },
    { label: "事实审查", value: model.fact_reviews.length },
    { label: "综合输出", value: model.synthesis_outputs.length },
    { label: "血缘明细", value: model.source_refs.length },
    { label: "顶层产物", value: model.artifact_refs.length },
  ];

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
      <div className="grid gap-x-3 gap-y-2 sm:grid-cols-2 xl:grid-cols-6">
        {metrics.map((metric) => (
          <div key={metric.label} className="min-w-0 border-l border-[var(--border-faint)] pl-2 first:border-l-0 first:pl-0">
            <div className="text-[9px] text-[var(--fg-5)]">{metric.label}</div>
            <div className="mt-0.5 text-[16px] font-semibold leading-none text-[var(--fg-1)]">{metric.value}</div>
          </div>
        ))}
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
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[12px] font-semibold text-[var(--fg-2)]">确定性输入</div>
        <div className="text-[10px] text-[var(--fg-5)]">{items.length} 项</div>
      </div>
      {items.length > 0 ? (
        <div className="grid gap-2 xl:grid-cols-2">
          {items.map((item) => (
            <ReportAnalysisInputItem key={item.input_id} item={item} />
          ))}
        </div>
      ) : (
        <FAEmptyState title="暂无确定性输入" description="当前报告没有返回分析快照，或没有可回退的输入载荷。" />
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
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[12px] font-semibold text-[var(--fg-2)]">{title}</div>
        <div className="text-[10px] text-[var(--fg-5)]">{items.length} 项</div>
      </div>
      {items.length > 0 ? (
        <div className="grid gap-2 xl:grid-cols-2">
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
