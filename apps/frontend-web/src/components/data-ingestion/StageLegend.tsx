import { StageNode } from "./StageNode";
import type { PipelineStageStatus } from "@/types/data-ingestion";

const LEGEND_ITEMS: Array<{ status: PipelineStageStatus; label: string }> = [
  { status: "OK",          label: "正常" },
  { status: "READY",       label: "就绪" },
  { status: "WARN",        label: "警告" },
  { status: "ERROR",       label: "异常" },
  { status: "BLOCKED",     label: "阻塞" },
  { status: "WAITING",     label: "等待" },
  { status: "NO_DATA",     label: "无数据" },
  { status: "NO_SNAPSHOT", label: "无快照" },
];

export function StageLegend() {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {LEGEND_ITEMS.map(({ status, label }) => (
        <div key={status} className="inline-flex items-center gap-1">
          <StageNode status={status} compact />
          <span className="text-[8px] text-[var(--fg-6)]">{label}</span>
        </div>
      ))}
    </div>
  );
}
