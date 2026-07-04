import { useState } from "react";
import { triggerIngestionRetry } from "@/adapters/dataIngestion";
import type { DataSourceActionResponse, DataSourceStatusViewModel } from "@/types/data-ingestion";
import { IngestionActionList } from "./DataIngestionActionList";

export { BlockingIssuesPanel } from "./DataIngestionBlockingIssuesPanel";
export { SourceDetailPanel } from "./DataIngestionSourceDetailPanel";

export function IngestionActionsPanel({
  sources,
  onActionComplete,
  onActionError,
}: {
  sources: DataSourceStatusViewModel[];
  onActionComplete: (result: DataSourceActionResponse) => void;
  onActionError: (error: Error) => void;
}) {
  const actionableSources = sources.filter((source) => source.status !== "available").slice(0, 4);
  const [runningSource, setRunningSource] = useState<string | null>(null);

  async function handleRetry(source: DataSourceStatusViewModel) {
    setRunningSource(source.id);
    try {
      const result = await triggerIngestionRetry(source.id, {
        actor: "frontend",
        reason: `从数据接入页请求重试 ${source.label}`,
      });
      onActionComplete(result);
    } catch (cause) {
      onActionError(cause instanceof Error ? cause : new Error("重试登记失败"));
    } finally {
      setRunningSource(null);
    }
  }

  return (
    <div
      className="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)]"
      style={{ maxHeight: "min(36vh, 360px)" }}
    >
      <div className="border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2">
        <div className="text-[12px] font-semibold text-[var(--fg-1)]">操作入口</div>
        <div className="mt-0.5 text-[11px] text-[var(--fg-4)]">重试只创建 task_run，页面不本地改数据状态</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <IngestionActionList actionableSources={actionableSources} runningSource={runningSource} onRetry={handleRetry} />
      </div>
    </div>
  );
}
