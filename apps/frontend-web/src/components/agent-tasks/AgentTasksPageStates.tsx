import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function AgentTasksLoadingState() {
  return (
    <div className="finance-page-shell">
      <LoadingSkeleton variant="page" />
    </div>
  );
}

export function AgentTasksErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="finance-page-shell">
      <FACard title="任务列表不可用" eyebrow="错误" accent="down">
        <FAWarningBanner
          title="当前页面不可用"
          description={message}
          tone="down"
          action={
            <button
              type="button"
              onClick={onRetry}
              className="rounded-[var(--radius-md)] border border-[var(--down-border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--down)]"
            >
              重试
            </button>
          }
        />
      </FACard>
    </div>
  );
}

export function AgentTasksEmptyState() {
  return (
    <div className="finance-page-shell">
      <FAEmptyState title="暂无任务运行" description="`/api/runs` 当前为空，这属于有效空状态，不代表页面异常。" />
    </div>
  );
}

export function AgentTasksDetailWarning({ message }: { message?: string | null }) {
  if (!message) return null;
  return <FAWarningBanner title="运行详情降级" description={message} tone="warn" />;
}
