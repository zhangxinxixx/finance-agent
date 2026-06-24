import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function ReviewCenterLoadingState() {
  return (
    <div className="finance-page-shell">
      <LoadingSkeleton variant="page" />
    </div>
  );
}

export function ReviewCenterErrorBanner({ message }: { message: string }) {
  return <FAWarningBanner title="复核接口不可用" description={message} tone="down" />;
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
