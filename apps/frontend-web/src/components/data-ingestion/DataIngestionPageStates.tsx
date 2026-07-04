import { Database } from "lucide-react";
import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import type { DataSourceActionResponse } from "@/types/data-ingestion";

export function DataIngestionLoadingState() {
  return (
    <div className="finance-page-shell">
      <div className="space-y-3">
        <LoadingSkeleton variant="page" />
        <div className="grid gap-3 xl:grid-cols-2 2xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <LoadingSkeleton key={index} variant="card" rows={5} />
          ))}
        </div>
      </div>
    </div>
  );
}

export function DataIngestionErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="finance-page-shell">
      <ErrorState
        title="数据接入不可用"
        message={message}
        onRetry={onRetry}
        retryLabel="重新拉取"
      />
    </div>
  );
}

export function DataIngestionEmptyState() {
  return (
    <div className="finance-page-shell flex flex-col gap-2.5">
      <div className="flex flex-col items-center justify-center rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-panel)] py-12">
        <Database size={24} className="mb-2 text-[var(--fg-6)]" />
        <div className="text-[12px] text-[var(--fg-4)]">未配置数据源</div>
        <div className="mt-1 text-[10px] text-[var(--fg-5)]">请检查 /api/data-sources/status 或 mock 回退配置。</div>
      </div>
    </div>
  );
}

export function DataIngestionActionFeedback({
  actionResult,
  actionError,
}: {
  actionResult: DataSourceActionResponse | null;
  actionError: Error | null;
}) {
  return (
    <>
      {actionResult ? (
        <div className="rounded-[var(--radius-lg)] border border-[var(--info-border)] bg-[var(--info-soft)] p-2.5 text-[10px] leading-5 text-[var(--info)]">
          已登记 {actionResult.action === "retry" ? "重试" : actionResult.action}：{actionResult.source_key} · run_id {actionResult.run_id ?? "不可用"} · {actionResult.status}
        </div>
      ) : null}
      {actionError ? (
        <div className="rounded-[var(--radius-lg)] border border-[var(--down-border)] bg-[var(--down-soft)] p-2.5 text-[10px] leading-5 text-[var(--down)]">
          操作失败：{actionError.message}
        </div>
      ) : null}
    </>
  );
}
