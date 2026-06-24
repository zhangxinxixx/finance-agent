import { SourceTracePanelFrame } from "@/components/shared/SourceTracePanelFrame";
import type { SourceRef } from "@/types/common";
import type { CMEOptionsSourceTraceItem } from "@/types/cme-options";

interface SourceTracePanelProps {
  sourceTrace?: CMEOptionsSourceTraceItem[];
  sourceRefs?: SourceRef[];
}

export function SourceTracePanel({ sourceTrace = [], sourceRefs = [] }: SourceTracePanelProps) {
  return (
    <SourceTracePanelFrame
      title="数据来源与溯源"
      eyebrow="溯源"
      accent="info"
      sourceTrace={sourceTrace}
      sourceRefs={sourceRefs}
      description="展示当前页面使用的来源记录、状态与可追溯引用。"
      emptyDescription="当前日期没有可展示的溯源记录。"
    />
  );
}
