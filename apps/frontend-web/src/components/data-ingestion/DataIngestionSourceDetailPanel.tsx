import { useEffect, useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";
import { triggerIngestionSourceTest } from "@/adapters/dataIngestion";
import type { DataSourceStatusViewModel, DataSourceTestResponse } from "@/types/data-ingestion";
import { DataIngestionFeishuMessagesBlock } from "./DataIngestionFeishuMessagesBlock";
import {
  EvidencePathRow,
  SourceArtifactEvidenceBlock,
  SourceDetailMetricsGrid,
  SourceDrilldownBlockWithLinks,
  SourceIssueBlock,
  SourceLatestRawBlock,
  SourceModulesBlock,
  SourceNewsFeatureArtifactsBlock,
  SourceNewsRuntimeBlock,
  SourceNewsSummaryBlock,
  SourceRawAndStageRefsBlock,
  SourceRefsBlock,
  SourceStoragePollingBlock,
  SourceStagesBlock,
} from "./DataIngestionDetailBlocks";

const TESTABLE_SOURCE_IDS = new Set([
  "jin10_mcp_flash",
  "jin10_mcp_calendar",
  "jin10_mcp_market",
  "jin10_xnews_public",
  "jin10_datacenter_reports",
  "jin10_svip_reports",
]);

function normalizeMonitorDate(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  const ymd = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
  if (ymd) return ymd[1];
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return null;
  const yyyy = String(parsed.getFullYear());
  const mm = String(parsed.getMonth() + 1).padStart(2, "0");
  const dd = String(parsed.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function SourceDetailPanel({
  source,
  onRetry,
}: {
  source: DataSourceStatusViewModel | null;
  onRetry: (source: DataSourceStatusViewModel) => void;
}) {
  if (!source) {
    return <SourceDetailEmptyState />;
  }

  return <SourceDetailSelectedState source={source} onRetry={onRetry} />;
}

function SourceDetailEmptyState() {
  return (
    <div
      className="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)]"
      style={{ maxHeight: "min(78vh, 860px)" }}
    >
      <div className="border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-2)]">数据源详情</div>
        <div className="mt-0.5 text-[9px] text-[var(--fg-5)]">点击左侧任一数据源查看运行与溯源</div>
      </div>
      <div className="p-3 text-[10px] leading-5 text-[var(--fg-5)]">
        当前未选中数据源。点击左侧矩阵中的数据源行查看采集、解析、快照等详细信息。
      </div>
    </div>
  );
}

function SourceDetailSelectedState({
  source,
  onRetry,
}: {
  source: DataSourceStatusViewModel;
  onRetry: (source: DataSourceStatusViewModel) => void;
}) {
  return (
    <div
      className="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)]"
      style={{ maxHeight: "min(78vh, 860px)" }}
    >
      <SourceDetailHeader source={source} />

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <SourceDetailSections source={source} onRetry={onRetry} />
      </div>
    </div>
  );
}

function SourceDetailHeader({ source }: { source: DataSourceStatusViewModel }) {
  const statusLabel = source.status === "available" ? "可用" : source.status === "partial" ? "部分可用" : source.status === "error" ? "错误" : "不可用";
  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-2)]">数据源详情</div>
          <div className="mt-0.5 truncate text-[11px] font-semibold text-[var(--fg-1)]">{source.label}</div>
        </div>
        <span
          className="shrink-0 rounded-full px-1.5 py-px text-[9px] font-bold"
          style={{
            background: source.status === "available" ? "var(--up-soft)" : source.status === "partial" ? "var(--warn-soft)" : "var(--down-soft)",
            color: source.status === "available" ? "var(--up)" : source.status === "partial" ? "var(--warn)" : "var(--down)",
          }}
        >
          {statusLabel}
        </span>
      </div>
    </div>
  );
}

function SourceDetailSections({
  source,
  onRetry,
}: {
  source: DataSourceStatusViewModel;
  onRetry: (source: DataSourceStatusViewModel) => void;
}) {
  const [testResult, setTestResult] = useState<{ sourceId: string; result: DataSourceTestResponse } | null>(null);
  const [testError, setTestError] = useState<{ sourceId: string; error: Error } | null>(null);
  const [testingSourceId, setTestingSourceId] = useState<string | null>(null);
  const health = source.pipeline_health;
  const latestSuccess = source.latest_parsed_time ?? source.latest_raw_time ?? null;
  const latestUpdate = source.latest_update_time ?? latestSuccess;
  const issue = source.error_message ?? source.status_reason ?? (source.configured ? null : "source not configured");
  const affectedModules = health.affectedModules;
  const sourceRefs = source.source_refs.slice(0, 4);
  const artifactEvidence = source.artifact_evidence;
  const newsSummary = artifactEvidence?.news_feature_summary ?? null;
  const newsRuntime = source.news_runtime;
  const feishuPreferredDate = source.latest_parsed_time ?? source.latest_raw_time ?? null;
  const stages = Object.entries(health.stages);
  const stageRefs = stages
    .flatMap(([key, stage]) => [
      stage.inputRef ? { key: `${key}-input`, label: `${key}.input`, value: stage.inputRef } : null,
      stage.outputRef ? { key: `${key}-output`, label: `${key}.output`, value: stage.outputRef } : null,
    ])
    .filter((item): item is { key: string; label: string; value: string } => item !== null)
    .slice(0, 6);
  const canRunSourceTest = TESTABLE_SOURCE_IDS.has(source.id);
  const monitorHref = source.id === "jin10_feishu"
    ? (() => {
        const date = normalizeMonitorDate(source.latest_parsed_time ?? source.latest_raw_time ?? source.latest_update_time ?? null);
        return date ? `/feishu-monitor?date=${encodeURIComponent(date)}` : "/feishu-monitor";
      })()
    : null;

  useEffect(() => {
    setTestResult(null);
    setTestError(null);
    setTestingSourceId(null);
  }, [source.id]);

  async function handleSourceTest() {
    setTestingSourceId(source.id);
    setTestError(null);
    try {
      const result = await triggerIngestionSourceTest(source.id, {
        actor: "frontend",
        reason: `从数据源详情即时测试 ${source.label}`,
        limit: 5,
      });
      setTestResult({ sourceId: source.id, result });
    } catch (cause) {
      setTestResult(null);
      setTestError({ sourceId: source.id, error: cause instanceof Error ? cause : new Error("即时测试失败") });
    } finally {
      setTestingSourceId((current) => (current === source.id ? null : current));
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <SourceDetailMetricsGrid
        configured={source.configured}
        downstreamStatus={health.downstreamStatus}
        analysisReady={source.analysis_ready}
        lastRunId={source.last_run_id}
        latestSuccess={latestSuccess}
        latestUpdate={latestUpdate}
        snapshotId={source.snapshot_id}
        rowCount={source.row_count}
      />

      <SourceIssueBlock issue={issue ?? "当前未返回失败或降级原因。"} />
      <SourceModulesBlock modules={affectedModules} />
      <SourceStagesBlock stages={stages} />
      <SourceLatestRawBlock rawRef={source.latest_raw_ref} />
      <SourceStoragePollingBlock
        databaseTables={source.database_tables}
        artifactLayers={source.artifact_layers}
        polling={source.polling_strategy}
        pressure={source.pressure_profile}
      />

      {artifactEvidence ? (
        <SourceArtifactEvidenceBlock
          preferred={artifactEvidence.preferred_artifact_path}
          collectorRaw={artifactEvidence.collector_raw_artifact_path}
          collectorParsed={artifactEvidence.collector_parsed_artifact_path}
        />
      ) : null}

      {source.group === "news" && newsRuntime ? (
        <SourceNewsRuntimeBlock
          latestCollectionStatus={newsRuntime.latest_collection_status}
          latestSourceRefCount={newsRuntime.latest_source_ref_count}
          latestReasonCodes={newsRuntime.latest_reason_codes}
          latestCollectorStatus={newsRuntime.latest_collector_runtime?.status}
          diagnosticsArtifactPath={newsRuntime.collection_diagnostics_artifact_path}
          latestSourceRefStatuses={newsRuntime.latest_source_ref_statuses}
          latestCollectionWarnings={newsRuntime.latest_collection_warnings}
          latestCollectorError={newsRuntime.latest_collector_runtime?.error}
        />
      ) : null}

      {source.group === "news" && newsSummary ? (
        <>
          <SourceNewsSummaryBlock
            headline={newsSummary.market_mainline_headline}
            latestFeatureDate={newsSummary.latest_feature_date}
            latestFeatureRunId={newsSummary.latest_feature_run_id}
            confirmedEventCount={newsSummary.confirmed_event_count}
            candidateEventCount={newsSummary.candidate_event_count}
            unconfirmedRiskCount={newsSummary.unconfirmed_risk_count}
            calendarEventCount={newsSummary.calendar_event_count}
          />
          <SourceNewsFeatureArtifactsBlock
            briefArtifactPath={newsSummary.brief_artifact_path}
            eventCandidatesArtifactPath={newsSummary.event_candidates_artifact_path}
            impactAssessmentsArtifactPath={newsSummary.impact_assessments_artifact_path}
            marketReactionsArtifactPath={newsSummary.market_reactions_artifact_path}
            reportEventsArtifactPath={newsSummary.report_events_artifact_path}
          />
        </>
      ) : null}

      {source.id === "jin10_feishu" ? <DataIngestionFeishuMessagesBlock preferredDate={feishuPreferredDate} /> : null}

      <SourceDrilldownBlockWithLinks lastRunId={source.last_run_id} monitorHref={monitorHref} />
      <SourceRawAndStageRefsBlock rawArtifactRef={health.rawArtifactRef} stageRefs={stageRefs} />
      <SourceRefsBlock sourceRefs={sourceRefs} />
      {canRunSourceTest ? (
        <SourceTestPreviewBlock
          isLoading={testingSourceId === source.id}
          result={testResult?.sourceId === source.id ? testResult.result : null}
          error={testError?.sourceId === source.id ? testError.error : null}
          onTest={() => {
            void handleSourceTest();
          }}
        />
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onRetry(source)}
          className="rounded-full border border-[var(--border)] px-3 py-1.5 text-[10px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)]"
        >
          登记重试任务
        </button>
      </div>
    </div>
  );
}

function SourceTestPreviewBlock({
  isLoading,
  result,
  error,
  onTest,
}: {
  isLoading: boolean;
  result: DataSourceTestResponse | null;
  error: Error | null;
  onTest: () => void;
}) {
  const summaryRows = result ? Object.entries(result.summary).filter(([, value]) => isPreviewPrimitive(value)).slice(0, 8) : [];
  const statusTone = result ? sourceTestStatusTone(result.status, result.data_status) : null;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">即时测试</div>
          <div className="mt-1 text-[9px] leading-4 text-[var(--fg-5)]">轻量探测，只写临时产物和任务审计。</div>
        </div>
        <button
          type="button"
          onClick={onTest}
          disabled={isLoading}
          className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[var(--border)] px-2 py-1 text-[9px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoading ? <Loader2 size={10} className="animate-spin" /> : <PlayCircle size={10} />}
          {isLoading ? "测试中" : "立即测试"}
        </button>
      </div>

      {error ? (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-2 py-1.5 text-[9px] leading-4 text-[var(--down)]">
          {error.message}
        </div>
      ) : null}

      {result ? (
        <div className="mt-2 flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-1.5">
            <SourceTestMetric label="状态" value={result.status} tone={statusTone ?? undefined} />
            <SourceTestMetric label="数据" value={result.data_status ?? "—"} />
            <SourceTestMetric label="耗时" value={`${result.duration_ms}ms`} mono />
            <SourceTestMetric label="样本数" value={String(result.preview.length)} mono />
          </div>

          <div className="flex flex-col gap-1">
            {result.run_id ? <EvidencePathRow label="运行" value={result.run_id} /> : null}
            {result.artifacts.raw_path ? <EvidencePathRow label="原始" value={result.artifacts.raw_path} /> : null}
            {result.artifacts.parsed_path ? <EvidencePathRow label="解析" value={result.artifacts.parsed_path} /> : null}
          </div>

          {summaryRows.length ? (
            <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2">
              <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">摘要</div>
              <div className="mt-1 flex flex-col gap-1">
                {summaryRows.map(([key, value]) => (
                  <EvidencePathRow key={key} label={key} value={formatPreviewValue(value)} />
                ))}
              </div>
            </div>
          ) : null}

          <SourceTestPreviewRows rows={result.preview} />
        </div>
      ) : !error && !isLoading ? (
        <div className="mt-2 text-[9px] leading-4 text-[var(--fg-5)]">点击运行查看最新样本、数据结构状态和临时产物路径。</div>
      ) : null}
    </div>
  );
}

function SourceTestMetric({
  label,
  value,
  mono = false,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "ok" | "warn" | "error";
}) {
  return (
    <div className="min-w-0 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-1">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">{label}</div>
      <div
        className={`mt-0.5 truncate text-[9px] font-semibold ${mono ? "font-mono" : ""}`}
        style={{
          color:
            tone === "ok"
              ? "var(--up)"
              : tone === "warn"
                ? "var(--warn)"
                : tone === "error"
                  ? "var(--down)"
                  : "var(--fg-3)",
        }}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function SourceTestPreviewRows({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2 text-[9px] text-[var(--fg-5)]">
        预览为空，查看摘要和产物判断是否需要登录、结构修复或后续解析。
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">预览</div>
      <div className="mt-1 flex flex-col gap-1.5">
        {rows.slice(0, 5).map((row, index) => (
          <div key={index} className="rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1">
            {Object.entries(row).slice(0, 5).map(([key, value]) => (
              <EvidencePathRow key={key} label={key} value={formatPreviewValue(value)} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function sourceTestStatusTone(status: string, dataStatus?: string | null): "ok" | "warn" | "error" {
  if (status === "ok" || dataStatus === "live") return "ok";
  if (status === "failed" || dataStatus === "unavailable") return "error";
  return "warn";
}

function isPreviewPrimitive(value: unknown): boolean {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function formatPreviewValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
