import type { DashboardSummary } from "@/types/dashboard";
import type { SourceRef } from "@/types/common";
import { SourceTracePanelFrame } from "@/components/shared/SourceTracePanelFrame";
import { FAStatusPill } from "@/components/shared/FAStatusPill";

interface SourceTracePanelProps {
  sourceTrace: DashboardSummary["source_trace"];
  dataSourceStatus: DashboardSummary["data_source_status"];
  sourceRefs?: SourceRef[];
}

export function SourceTracePanel({ sourceTrace, dataSourceStatus, sourceRefs = [] }: SourceTracePanelProps) {
  const statuses = Object.values(dataSourceStatus);

  return (
    <SourceTracePanelFrame
      title="数据溯源"
      eyebrow="数据溯源"
      accent="info"
      sourceTrace={sourceTrace}
      sourceRefs={sourceRefs}
      emptyTitle="暂无逐条 source trace"
      emptyDescription="当前已回退为数据源状态标签展示；后续接入完整 trace 后，这里继续作为审计视图。"
      action={<FAStatusPill tone="dim">{`${statuses.length} 数据源`}</FAStatusPill>}
    >
      <div className="flex flex-wrap gap-2">
        {statuses.map((item) => (
          <FAStatusPill
            key={item.label}
            tone={item.status === "ok" ? "up" : item.status === "warn" ? "warn" : item.status === "error" ? "down" : "dim"}
          >
            {item.label}
          </FAStatusPill>
        ))}
      </div>
    </SourceTracePanelFrame>
  );
}
