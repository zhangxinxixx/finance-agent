import { Loader2 } from "lucide-react";
import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function StrategyPageLoadingState() {
  return (
    <div className="finance-page-shell">
      <section className="finance-panel p-4">
        <div className="flex items-center gap-3">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--brand)]" />
          <div>
            <div className="text-[13px] font-semibold text-[var(--fg-2)]">正在加载策略数据</div>
            <div className="mt-1 text-[11px] text-[var(--fg-4)]">请稍候...</div>
          </div>
        </div>
        <LoadingSkeleton variant="page" className="mt-4" />
      </section>
    </div>
  );
}

export function StrategyPageErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="finance-page-shell">
      <ErrorState
        title="策略中心加载失败"
        message={message}
        onRetry={onRetry}
        retryLabel="重试"
      />
    </div>
  );
}
