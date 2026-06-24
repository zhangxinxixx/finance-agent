import type { PipelineStatus, PipelineStageStatus } from "@/types/dashboard";
import { FACard } from "./FACard";
import { FAPipelineStepper, type FAPipelineStage } from "./FAPipelineStepper";

const stages: Array<{ key: keyof PipelineStatus; label: string; description: string }> = [
  { key: "raw", label: "采集", description: "原始数据" },
  { key: "parsed", label: "解析", description: "结构化" },
  { key: "features", label: "特征", description: "特征计算" },
  { key: "agent", label: "分析", description: "策略分析" },
  { key: "report", label: "报告", description: "渲染输出" },
  { key: "knowledge", label: "同步", description: "知识归档" },
];

function normalizeStatus(status: PipelineStageStatus): FAPipelineStage["status"] {
  switch (status) {
    case "done":
      return "done";
    case "running":
      return "running";
    case "pending":
      return "queued";
    case "unavailable":
    default:
      return "unavailable";
  }
}

interface PipelineStepperProps {
  pipeline: PipelineStatus;
}

export function PipelineStepper({ pipeline }: PipelineStepperProps) {
  const pipelineStages = stages.map((stage) => ({
    id: stage.key,
    label: stage.label,
    description: stage.description,
    status: normalizeStatus(pipeline[stage.key]),
  }));

  return (
    <FACard
      title="流水线"
      eyebrow="Research Pipeline"
      accent="brand"
      bodyClassName="space-y-4"
    >
      <div className="text-[11px] text-[var(--fg-4)]">采集 → 解析 → 特征 → 分析 → 报告 → 同步</div>
      <FAPipelineStepper stages={pipelineStages} />
    </FACard>
  );
}
