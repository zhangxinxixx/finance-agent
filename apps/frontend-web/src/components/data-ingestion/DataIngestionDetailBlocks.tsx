import { formatDateTime } from "@/lib/date";
import type { DataSourcePollingStrategy, DataSourcePressureProfile, DataSourceRawRef } from "@/types/data-ingestion";
import { DetailMetric, EvidencePathRow } from "./DataIngestionDetailBlocks.shared";
export { DetailMetric, EvidencePathRow } from "./DataIngestionDetailBlocks.shared";

export function SourceDetailMetricsGrid({
  configured,
  downstreamStatus,
  analysisReady,
  lastRunId,
  latestSuccess,
  latestUpdate,
  snapshotId,
  rowCount,
}: {
  configured: boolean;
  downstreamStatus: string | undefined;
  analysisReady: boolean;
  lastRunId: string | null | undefined;
  latestSuccess: string | null | undefined;
  latestUpdate: string | null | undefined;
  snapshotId: string | null | undefined;
  rowCount: number;
}) {
  const cfgLabel = configured ? "已配置" : "未配置";
  const dsLabel = downstreamStatus === "BLOCKED" ? "阻塞" : downstreamStatus === "DEGRADED" ? "降级" : analysisReady ? "就绪" : "阻塞";
  const latestSuccessLabel = latestSuccess ? formatDateTime(latestSuccess) : "无记录";
  const latestUpdateLabel = latestUpdate ? formatDateTime(latestUpdate) : "无记录";
  const snapshotLabel = snapshotId ?? "无快照";
  const rowCountLabel = rowCount ? rowCount.toLocaleString() : "—";
  return (
    <div className="grid grid-cols-2 gap-2">
      <DetailMetric label="配置状态" value={cfgLabel} />
      <DetailMetric label="下游状态" value={dsLabel} />
      <DetailMetric label="最近运行" value={lastRunId ?? "—"} mono />
      <DetailMetric label="最近更新" value={latestUpdateLabel} mono />
      <DetailMetric label="最近成功" value={latestSuccessLabel} mono />
      <DetailMetric label="快照 ID" value={snapshotLabel} mono />
      <DetailMetric label="数据行数" value={rowCountLabel} mono />
    </div>
  );
}

export function SourceLatestRawBlock({ rawRef }: { rawRef: DataSourceRawRef | null | undefined }) {
  if (!rawRef || (!rawRef.url && !rawRef.raw_path && !rawRef.parsed_path && !rawRef.source_ref)) {
    return (
      <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
        <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">最新原始数据</div>
        <div className="mt-1 text-[9px] text-[var(--fg-5)]">当前 source 未返回原文链接或 raw artifact。</div>
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">最新原始数据</div>
        {rawRef.published_at ? <span className="font-mono text-[8px] text-[var(--fg-5)]">{formatDateTime(rawRef.published_at)}</span> : null}
      </div>
      <div className="mt-1 flex flex-col gap-1">
        {rawRef.label ? <EvidencePathRow label="标签" value={rawRef.label} /> : null}
        {rawRef.url ? (
          <div className="flex items-start justify-between gap-2">
            <span className="shrink-0 text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">链接</span>
            <a
              href={rawRef.url}
              target="_blank"
              rel="noreferrer"
              className="truncate text-right font-mono text-[8px] text-[var(--brand-hover)] hover:underline"
              title={rawRef.url}
            >
              {rawRef.url}
            </a>
          </div>
        ) : null}
        {rawRef.raw_path ? <EvidencePathRow label="原始文件" value={rawRef.raw_path} /> : null}
        {rawRef.parsed_path ? <EvidencePathRow label="解析文件" value={rawRef.parsed_path} /> : null}
        {rawRef.source_ref ? <EvidencePathRow label="引用来源" value={rawRef.source_ref} /> : null}
      </div>
    </div>
  );
}

export function SourceStoragePollingBlock({
  databaseTables,
  artifactLayers,
  polling,
  pressure,
}: {
  databaseTables: string[];
  artifactLayers: string[];
  polling: DataSourcePollingStrategy | null | undefined;
  pressure: DataSourcePressureProfile | null | undefined;
}) {
  const pressureLevel = pressure?.level === "low" ? "低负载" : pressure?.level === "medium" ? "中等负载" : pressure?.level === "high" ? "高负载" : "未知";
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">存储 / 轮询 / 压力</div>
      <div className="mt-1 flex flex-col gap-1">
        <EvidencePathRow label="数据库表" value={databaseTables.length ? databaseTables.join(" / ") : "—"} />
        <EvidencePathRow label="产物层" value={artifactLayers.length ? artifactLayers.join(" / ") : "—"} />
        <EvidencePathRow label="采集模式" value={[polling?.mode, polling?.cadence].filter(Boolean).join(" · ") || "—"} />
        <EvidencePathRow label="查询策略" value={polling?.query ?? "—"} />
        <EvidencePathRow
          label="负载压力"
          value={`${pressureLevel}${pressure?.upgrade_required ? " · 建议升级" : ""}`}
        />
        {pressure?.recommendation ? (
          <div className="pt-1 text-[9px] leading-4 text-[var(--fg-4)]">{pressure.recommendation}</div>
        ) : null}
      </div>
    </div>
  );
}

export function SourceIssueBlock({ issue }: { issue: string }) {
  const readableIssue = translateIssue(issue);
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">失败 / 降级原因</div>
      <div className="mt-1 text-[10px] leading-5 text-[var(--fg-3)]">{readableIssue}</div>
    </div>
  );
}

function translateIssue(issue: string): string {
  const map: Record<string, string> = {
    "source not configured": "数据源未配置（缺少 API 密钥或账号）",
    "Source not configured": "数据源未配置（缺少 API 密钥或账号）",
    "API key missing": "缺少 API 密钥",
    "api key not set": "未设置 API 密钥",
    "connection refused": "连接被拒绝（目标服务不可达）",
    "Connection refused": "连接被拒绝（目标服务不可达）",
    "timeout": "请求超时",
    "not connected": "未连接",
    "Not connected": "未连接",
    "rate limited": "请求受限（触发频率限制）",
    "Rate limited": "请求受限（触发频率限制）",
    "no data available": "无可用数据",
    "No data available": "无可用数据",
    "partial data": "部分数据可用",
    "Partial data": "部分数据可用",
    "maintenance": "维护中",
    "Maintenance": "维护中",
    "unknown error": "未知错误",
    "Unknown error": "未知错误",
  };
  return map[issue] ?? issue;
}

export function SourceModulesBlock({ modules }: { modules: string[] }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">影响模块</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {modules.map((module) => (
          <span key={module} className="rounded border border-[var(--border-faint)] bg-[var(--bg-panel)] px-1.5 py-px text-[8px] text-[var(--fg-4)]">
            {module}
          </span>
        ))}
      </div>
    </div>
  );
}

export function SourceStagesBlock({
  stages,
}: {
  stages: Array<[string, { status: string }]>;
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">阶段链路</div>
      <div className="mt-1 flex flex-col gap-1">
        {stages.length === 0 ? (
          <div className="text-[9px] text-[var(--fg-5)]">暂无阶段健康数据。</div>
        ) : (
          stages.map(([key, stage]) => (
            <div key={key} className="flex items-center justify-between gap-2">
              <span className="truncate text-[9px] text-[var(--fg-4)]">{key}</span>
              <span className="shrink-0 font-mono text-[8px] text-[var(--fg-5)]">{stage.status}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export { SourceArtifactEvidenceBlock, SourceDrilldownBlock, SourceRawAndStageRefsBlock, SourceRefsBlock } from "./DataIngestionRefBlocks";
export {
  SourceNewsFeatureArtifactsBlock,
  SourceNewsRuntimeBlock,
  SourceNewsSummaryBlock,
} from "./DataIngestionNewsBlocks";
