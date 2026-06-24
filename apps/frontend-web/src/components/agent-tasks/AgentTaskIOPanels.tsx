import { ArrowDownToLine, ArrowUpFromLine, FileSearch } from "lucide-react";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { AgentInspectionViewModel, TaskStepViewModel } from "@/types/agent-task";
import { AgentInspectionPanel } from "./AgentInspectionPanel";
import { RefList } from "./AgentTaskDisplayBlocks";
import { taskStatusLabel, taskStatusTone } from "./agentTaskMeta";

export function IOGrid({ steps, agentInspection }: { steps: TaskStepViewModel[]; agentInspection?: AgentInspectionViewModel | null }) {
  if (steps.length === 0 && (!agentInspection || agentInspection.agents.length === 0)) {
    return <FAEmptyState title="暂无输入输出" description="当前任务没有返回步骤级引用。" className="p-6" />;
  }

  return (
    <div className="space-y-4">
      <AgentInspectionPanel inspection={agentInspection} />
      {steps.map((step) => (
        <div key={step.id} className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="mb-4 flex items-center justify-between gap-2">
            <div>
              <div className="text-[14px] font-semibold text-[var(--fg-1)]">{step.label}</div>
              <div className="mt-1 text-[11px] text-[var(--fg-4)]">{step.stage || "未标注阶段"}</div>
            </div>
            <FAStatusPill tone={taskStatusTone(step.status)}>{taskStatusLabel(step.status)}</FAStatusPill>
          </div>
          <div className="grid gap-3 xl:grid-cols-3">
            <RefList title="输入" icon={<ArrowDownToLine size={12} className="text-[var(--brand)]" />} items={step.input_refs} emptyText="当前步骤未返回输入引用。" />
            <RefList title="输出" icon={<ArrowUpFromLine size={12} className="text-[var(--up)]" />} items={step.output_refs} emptyText="当前步骤未返回输出引用。" />
            <RefList title="溯源" icon={<FileSearch size={12} className="text-[var(--warn)]" />} items={step.source_refs} emptyText="当前步骤未返回来源引用。" />
          </div>
        </div>
      ))}
    </div>
  );
}
