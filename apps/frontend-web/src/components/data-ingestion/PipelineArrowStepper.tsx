import type { PipelineLayerStatus } from "@/types/data-ingestion";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusTone } from "@/components/shared/statusMeta";
import { Database, FileText, RefreshCw, Zap } from "lucide-react";

interface PipelineArrowStepperProps {
  layers: PipelineLayerStatus[];
}

const layerLabels: Record<string, string> = {
  configured: "配置",
  raw_ingested: "原始接入",
  parsed: "解析",
  analysis_ready: "分析就绪",
};

const layerIcons: Record<string, typeof Database> = {
  configured: Database,
  raw_ingested: RefreshCw,
  parsed: FileText,
  analysis_ready: Zap,
};

function toneForStatus(status: string): FAStatusTone {
  return getStatusTone(status, "step");
}

export function PipelineArrowStepper({ layers }: PipelineArrowStepperProps) {
  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-2)]">
          采集流水线
        </span>
        <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
          Pipeline Status
        </span>
      </div>
      <div className="flex items-center gap-0">
        {layers.map((layer, index) => {
          const Icon = layerIcons[layer.id] || Database;
          const ratio = layer.total_count > 0 ? layer.completed_count / layer.total_count : 0;
          const lc = toneForStatus(layer.status);
          const lcColor =
            lc === "up" ? "var(--up)" : lc === "warn" ? "var(--warn)" : lc === "down" ? "var(--down)" : "var(--fg-6)";

          return (
            <div key={layer.id} className="flex items-center flex-1 min-w-0">
              <div
                className="flex flex-col items-center gap-1.5 rounded-[var(--radius-md)] border px-3 py-2.5 min-w-0"
                style={{
                  borderColor: `color-mix(in srgb, ${lcColor} 30%, transparent)`,
                  background: `color-mix(in srgb, ${lcColor} 5%, transparent)`,
                  flex: 1,
                }}
              >
                <Icon size={13} style={{ color: lcColor }} />
                <span className="text-[9px] font-semibold text-[var(--fg-3)] text-center leading-tight">
                  {layerLabels[layer.id] ?? layer.id}
                </span>
                <div className="w-full h-[3px] rounded-[1.5px] bg-[var(--bg-terminal)] overflow-hidden">
                  <div
                    className="h-full rounded-[1.5px] transition-[width] duration-300"
                    style={{
                      width: `${Math.min(100, ratio * 100)}%`,
                      background: lcColor,
                    }}
                  />
                </div>
                <span
                  className="fa-num text-[10px] font-bold"
                  style={{ color: lcColor }}
                >
                  {layer.completed_count}/{layer.total_count}
                </span>
                <FAStatusPill tone={lc} dot={false}>
                  {ratio >= 1 ? "done" : ratio > 0 ? "running" : "pending"}
                </FAStatusPill>
              </div>
              {index < layers.length - 1 ? (
                <div className="flex items-center px-0.5 shrink-0">
                  <div
                    className="h-[2px] w-4"
                    style={{
                      background: `linear-gradient(90deg, ${lcColor}, var(--border))`,
                    }}
                  />
                  <svg width="8" height="10" viewBox="0 0 8 10" className="shrink-0 -ml-px">
                    <path
                      d="M0 1 L6 5 L0 9"
                      fill="none"
                      stroke="var(--border)"
                      strokeWidth="1.5"
                    />
                  </svg>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
