import { FACard } from "@/components/shared/FACard";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function KnowledgeBaseLoadingState() {
  return (
    <div className="finance-page-shell">
      <LoadingSkeleton variant="page" />
    </div>
  );
}

export function KnowledgeBaseErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="finance-page-shell">
      <FACard title="知识库不可用" eyebrow="加载异常" accent="down">
        <FAWarningBanner
          title="当前知识库工作台不可用"
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
