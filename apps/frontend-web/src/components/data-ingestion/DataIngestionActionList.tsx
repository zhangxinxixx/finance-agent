import type { DataSourceStatusViewModel } from "@/types/data-ingestion";

export function IngestionActionList({
  actionableSources,
  runningSource,
  onRetry,
}: {
  actionableSources: DataSourceStatusViewModel[];
  runningSource: string | null;
  onRetry: (source: DataSourceStatusViewModel) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      {actionableSources.length === 0 ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3 text-[11px] text-[var(--fg-4)]">
          当前没有需要重试的数据源。
        </div>
      ) : (
        actionableSources.map((source) => (
          <IngestionRetryItem key={source.id} source={source} runningSource={runningSource} onRetry={onRetry} />
        ))
      )}
    </div>
  );
}

function IngestionRetryItem({
  source,
  runningSource,
  onRetry,
}: {
  source: DataSourceStatusViewModel;
  runningSource: string | null;
  onRetry: (source: DataSourceStatusViewModel) => void;
}) {
  const isRunning = runningSource === source.id;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold leading-snug text-[var(--fg-2)]" title={source.label}>{source.label}</div>
          <div className="mt-1 line-clamp-2 text-[11px] leading-snug text-[var(--fg-4)]">{source.status_reason ?? source.status}</div>
        </div>
        <button
          type="button"
          disabled={isRunning}
          onClick={() => onRetry(source)}
          className="shrink-0 rounded-full border border-[var(--info-border)] bg-[var(--info-soft)] px-3 py-1 text-[11px] font-semibold text-[var(--info)] transition-colors hover:border-[var(--info)] disabled:cursor-wait disabled:opacity-60"
        >
          {isRunning ? "登记中" : "重试"}
        </button>
      </div>
    </div>
  );
}
