import { useState } from "react";
import { Database, ExternalLink, RefreshCw, RotateCcw } from "lucide-react";

import { triggerIngestionRetry } from "@/adapters/dataIngestion";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { useDataIngestion } from "@/hooks/useDataIngestion";
import { formatDateTime } from "@/lib/date";
import type { DataSourceStatusViewModel } from "@/types/data-ingestion";

function statusTone(status: DataSourceStatusViewModel["status"]): FAStatusTone {
  if (status === "available") return "up";
  if (status === "partial") return "warn";
  if (status === "error") return "down";
  return "dim";
}

function statusLabel(status: DataSourceStatusViewModel["status"]): string {
  if (status === "available") return "可用";
  if (status === "partial") return "部分可用";
  if (status === "error") return "异常";
  return "不可用";
}

function officialSourceUrl(source: DataSourceStatusViewModel): string | null {
  const candidate = source.source_refs.find((ref) => ref.source_url)?.source_url ?? null;
  if (!candidate) return null;
  try {
    const url = new URL(candidate);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function SourceSummaryCard({ source, retrying, onRetry }: {
  source: DataSourceStatusViewModel;
  retrying: boolean;
  onRetry: (source: DataSourceStatusViewModel) => void;
}) {
  const officialUrl = officialSourceUrl(source);
  const downstream = source.pipeline_health.downstreamStatus;
  const downstreamLabel = downstream === "READY" ? "输入可用" : downstream === "DEGRADED" ? "输入降级" : "输入阻断";

  return (
    <FACard
      title={source.label}
      eyebrow={source.group}
      accent={statusTone(source.status) === "up" ? "up" : statusTone(source.status) === "down" ? "down" : "warn"}
      action={<FAStatusPill tone={statusTone(source.status)}>{statusLabel(source.status)}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <div className="grid gap-2 sm:grid-cols-3">
        <div className="rounded-[var(--radius-sm)] bg-[var(--bg-panel)] px-3 py-2">
          <div className="fa-label text-[var(--fg-5)]">分析输入</div>
          <div className="mt-1 fa-body-text">{source.analysis_ready ? "输入已就绪" : "输入尚未就绪"}</div>
        </div>
        <div className="rounded-[var(--radius-sm)] bg-[var(--bg-panel)] px-3 py-2">
          <div className="fa-label text-[var(--fg-5)]">消费状态</div>
          <div className="mt-1 fa-body-text">{downstreamLabel}</div>
        </div>
        <div className="rounded-[var(--radius-sm)] bg-[var(--bg-panel)] px-3 py-2">
          <div className="fa-label text-[var(--fg-5)]">更新时间</div>
          <div className="mt-1 fa-body-text">{formatDateTime(source.latest_update_time)}</div>
        </div>
      </div>
      {(source.freshness_reason || source.status_reason || source.error_message) ? (
        <p className="fa-muted-text">{source.error_message || source.freshness_reason || source.status_reason}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {officialUrl ? (
          <a href={officialUrl} target="_blank" rel="noreferrer" className="fa-label inline-flex items-center gap-1 text-[var(--brand)] underline">
            来源网站 <ExternalLink size={11} />
          </a>
        ) : <span className="fa-faint-text">未提供来源链接</span>}
        {source.status !== "available" ? (
          <button type="button" disabled={retrying} onClick={() => onRetry(source)} className="fa-workspace-toolbar-button">
            <RotateCcw size={11} />{retrying ? "已登记…" : "登记重试"}
          </button>
        ) : null}
      </div>
    </FACard>
  );
}

export function DataIngestionPage() {
  const ingestion = useDataIngestion();
  const [retryingSource, setRetryingSource] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleRetry(source: DataSourceStatusViewModel) {
    setRetryingSource(source.id);
    setActionMessage(null);
    setActionError(null);
    try {
      const result = await triggerIngestionRetry(source.id, { actor: "frontend", reason: `从数据可用性摘要登记重试 ${source.label}` });
      setActionMessage(`${source.label}：${result.status === "accepted" ? "重试已登记" : result.status}`);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : "重试登记失败");
    } finally {
      setRetryingSource(null);
    }
  }

  if (ingestion.isLoading && !ingestion.data) return <FAPageScaffold><LoadingSkeleton variant="page" /></FAPageScaffold>;

  if (ingestion.isError || !ingestion.data) {
    return <FAPageScaffold><FAWarningBanner title="数据可用性摘要不可用" description={ingestion.error?.message ?? "运行摘要暂时无法读取。"} tone="down" action={<button type="button" onClick={ingestion.refetch} className="fa-workspace-toolbar-button">重试</button>} /></FAPageScaffold>;
  }

  const { view_model: viewModel } = ingestion.data;
  const sources = viewModel.sources;
  const availableCount = sources.filter((source) => source.status === "available").length;
  const blockedCount = sources.filter((source) => source.pipeline_health.downstreamStatus === "BLOCKED").length;

  return (
    <FAPageScaffold
      toolbar={<FAWorkspaceHeader icon={Database} title="数据可用性" actions={<button type="button" onClick={ingestion.refetch} className="fa-workspace-toolbar-button"><RefreshCw size={12} />刷新</button>} primaryLabel="输入概况" primaryItems={[{ label: "可用", value: `${availableCount}/${sources.length}` }, { label: "阻断", value: blockedCount }]} secondaryLabel="运行摘要" secondaryItems={viewModel.system_status?.latest_run_created_at ? [{ label: "最近运行", value: formatDateTime(viewModel.system_status.latest_run_created_at) }] : []} />}
      bodyClassName="fa-page-stack"
    >
      <p className="fa-muted-text">查看数据时点、质量与分析输入状态。研究是否可用，以对应报告的验证结果为准。</p>
      {actionMessage ? <FAWarningBanner title="操作已登记" description={actionMessage} tone="info" /> : null}
      {actionError ? <FAWarningBanner title="操作失败" description={actionError} tone="down" /> : null}
      {sources.length > 0 ? (
        <div className="grid gap-3 xl:grid-cols-2">
          {sources.map((source) => <SourceSummaryCard key={source.id} source={source} retrying={retryingSource === source.id} onRetry={(item) => { void handleRetry(item); }} />)}
        </div>
      ) : <FAEmptyState title="暂无可用性摘要" description="尚未取得数据源运行状态。" />}
    </FAPageScaffold>
  );
}

export default DataIngestionPage;
