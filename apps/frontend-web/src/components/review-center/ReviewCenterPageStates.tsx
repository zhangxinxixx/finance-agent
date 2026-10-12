import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { readerValue } from "@/lib/readerLabels";

export function ReviewCenterLoadingState() {
  return (
    <div className="finance-page-shell">
      <LoadingSkeleton variant="page" />
    </div>
  );
}

export function ReviewCenterErrorBanner({ message, record }: { message: string; record?: unknown }) {
  return (
    <div className="space-y-2">
      <FAWarningBanner title="复核接口不可用" description={readerValue(message, "复核数据暂时无法读取，请稍后重试。")} tone="down" />
      {record !== undefined ? <EvidenceRecordActions record={record} label="复核错误依据" /> : null}
    </div>
  );
}

export function ReviewCenterEmptyState() {
  return (
    <FAEmptyState
      title="没有匹配的复核项"
      description="当前过滤条件下没有复核项；这是有效空状态，不会使用 mock 伪装 live。"
      className="p-8"
    />
  );
}
