import type { ReactNode } from "react";
import { CheckCircle2, CircleDashed, Clock3, XCircle } from "lucide-react";
import { FAStatusPill, type FAStatusTone } from "./FAStatusPill";

export type FAPipelineStageStatus = "done" | "running" | "queued" | "error" | "unavailable";

export interface FAPipelineStage {
  id: string;
  label: ReactNode;
  description?: ReactNode;
  status: FAPipelineStageStatus;
}

interface FAPipelineStepperProps {
  stages: FAPipelineStage[];
  className?: string;
}

const toneByStatus: Record<FAPipelineStageStatus, FAStatusTone> = {
  done: "up",
  running: "info",
  queued: "warn",
  error: "down",
  unavailable: "dim",
};

function iconForStatus(status: FAPipelineStageStatus) {
  if (status === "done") return <CheckCircle2 size={12} />;
  if (status === "running") return <Clock3 size={12} />;
  if (status === "error") return <XCircle size={12} />;
  return <CircleDashed size={12} />;
}

export function FAPipelineStepper({ stages, className = "" }: FAPipelineStepperProps) {
  return (
    <div className={`grid gap-2 md:grid-cols-3 xl:grid-cols-6 ${className}`}>
      {stages.map((stage, index) => (
        <div key={stage.id} className="relative rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-2">
          {index > 0 ? <div className="absolute -left-2 top-1/2 hidden h-px w-2 bg-[var(--border)] xl:block" /> : null}
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5 text-[var(--fg-3)]">
              {iconForStatus(stage.status)}
              <span className="truncate text-[10px] font-semibold">{stage.label}</span>
            </div>
            <FAStatusPill tone={toneByStatus[stage.status]} dot={false}>
              {stage.status}
            </FAStatusPill>
          </div>
          {stage.description ? <div className="mt-1 truncate text-[10px] text-[var(--fg-5)]">{stage.description}</div> : null}
        </div>
      ))}
    </div>
  );
}
