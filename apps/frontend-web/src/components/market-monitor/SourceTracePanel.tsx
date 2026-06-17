import { SourceTracePanelFrame } from "@/components/shared/SourceTracePanelFrame";
import type { SourceRef } from "@/types/common";
import type { MarketMonitorSourceTraceItem } from "@/types/market-monitor";

interface SourceTracePanelProps {
  sourceTrace?: MarketMonitorSourceTraceItem[];
  sourceRefs?: SourceRef[];
}

export function SourceTracePanel({ sourceTrace = [], sourceRefs = [] }: SourceTracePanelProps) {
  return (
    <SourceTracePanelFrame
      title="分析结果与溯源"
      eyebrow="Evidence Trail"
      accent="brand"
      sourceTrace={sourceTrace}
      sourceRefs={sourceRefs}
      compact
      emptyDescription="当前监控页没有返回 source trace 或 source refs。"
    />
  );
}
