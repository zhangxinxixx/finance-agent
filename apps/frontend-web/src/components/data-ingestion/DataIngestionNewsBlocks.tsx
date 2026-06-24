import { EvidencePathRow, DetailMetric } from "./DataIngestionDetailBlocks.shared";

export function SourceNewsRuntimeBlock({
  latestCollectionStatus,
  latestSourceRefCount,
  latestReasonCodes,
  latestCollectorStatus,
  diagnosticsArtifactPath,
  latestSourceRefStatuses,
  latestCollectionWarnings,
  latestCollectorError,
}: {
  latestCollectionStatus: string | null | undefined;
  latestSourceRefCount: number | null | undefined;
  latestReasonCodes: string[];
  latestCollectorStatus: string | null | undefined;
  diagnosticsArtifactPath: string | null | undefined;
  latestSourceRefStatuses: string[];
  latestCollectionWarnings: string[];
  latestCollectorError: string | null | undefined;
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">运行时诊断</div>
      <div className="mt-1 grid grid-cols-2 gap-2">
        <DetailMetric label="collect status" value={latestCollectionStatus ?? "—"} />
        <DetailMetric
          label="source refs"
          value={latestSourceRefCount !== null && latestSourceRefCount !== undefined ? String(latestSourceRefCount) : "—"}
          mono
        />
        <DetailMetric label="reason codes" value={latestReasonCodes.length > 0 ? latestReasonCodes.join(", ") : "—"} mono />
        <DetailMetric label="collector" value={latestCollectorStatus ?? "—"} mono />
      </div>
      <div className="mt-2 flex flex-col gap-1.5">
        {diagnosticsArtifactPath ? <EvidencePathRow label="diagnostics" value={diagnosticsArtifactPath} /> : null}
        {latestSourceRefStatuses.length > 0 ? (
          <div className="flex items-start justify-between gap-2">
            <span className="shrink-0 text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">ref status</span>
            <span
              className="truncate text-right font-mono text-[8px] text-[var(--fg-4)]"
              title={latestSourceRefStatuses.join(", ")}
            >
              {latestSourceRefStatuses.join(", ")}
            </span>
          </div>
        ) : null}
        {latestCollectionWarnings.length > 0 ? (
          <div className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2 py-1.5">
            <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--warn)]">warnings</div>
            <div className="mt-1 flex flex-col gap-1">
              {latestCollectionWarnings.slice(0, 2).map((warning, index) => (
                <div key={`${warning}-${index}`} className="text-[9px] leading-4 text-[var(--fg-3)]">
                  {warning}
                </div>
              ))}
            </div>
          </div>
        ) : null}
        {latestCollectorError ? (
          <div className="rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-2 py-1.5 text-[9px] leading-4 text-[var(--fg-3)]">
            {latestCollectorError}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function SourceNewsSummaryBlock({
  headline,
  latestFeatureDate,
  latestFeatureRunId,
  confirmedEventCount,
  candidateEventCount,
  unconfirmedRiskCount,
  calendarEventCount,
}: {
  headline: string | null | undefined;
  latestFeatureDate: string | null | undefined;
  latestFeatureRunId: string | null | undefined;
  confirmedEventCount: number;
  candidateEventCount: number;
  unconfirmedRiskCount: number;
  calendarEventCount: number;
}) {
  return (
    <>
      <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
        <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">新闻主线</div>
        <div className="mt-1 text-[10px] leading-5 text-[var(--fg-3)]">{headline ?? "daily_market_brief 已生成，但当前没有 headline。"}</div>
        <div className="mt-1 font-mono text-[8px] text-[var(--fg-5)]">
          feature_date {latestFeatureDate ?? "—"} · run {latestFeatureRunId ?? "—"}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <DetailMetric label="confirmed" value={String(confirmedEventCount)} mono />
        <DetailMetric label="candidate" value={String(candidateEventCount)} mono />
        <DetailMetric label="risk" value={String(unconfirmedRiskCount)} mono />
        <DetailMetric label="calendar" value={String(calendarEventCount)} mono />
      </div>
    </>
  );
}

export function SourceNewsFeatureArtifactsBlock({
  briefArtifactPath,
  eventCandidatesArtifactPath,
  impactAssessmentsArtifactPath,
  marketReactionsArtifactPath,
  reportEventsArtifactPath,
}: {
  briefArtifactPath: string | null | undefined;
  eventCandidatesArtifactPath: string | null | undefined;
  impactAssessmentsArtifactPath: string | null | undefined;
  marketReactionsArtifactPath: string | null | undefined;
  reportEventsArtifactPath: string | null | undefined;
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">新闻特征工件</div>
      <div className="mt-1 flex flex-col gap-1.5">
        {briefArtifactPath ? <EvidencePathRow label="brief" value={briefArtifactPath} /> : null}
        {eventCandidatesArtifactPath ? <EvidencePathRow label="candidates" value={eventCandidatesArtifactPath} /> : null}
        {impactAssessmentsArtifactPath ? <EvidencePathRow label="impact" value={impactAssessmentsArtifactPath} /> : null}
        {marketReactionsArtifactPath ? <EvidencePathRow label="reaction" value={marketReactionsArtifactPath} /> : null}
        {reportEventsArtifactPath ? <EvidencePathRow label="report" value={reportEventsArtifactPath} /> : null}
        {!briefArtifactPath &&
        !eventCandidatesArtifactPath &&
        !impactAssessmentsArtifactPath &&
        !marketReactionsArtifactPath &&
        !reportEventsArtifactPath ? (
          <div className="text-[9px] text-[var(--fg-5)]">暂无 news feature 工件路径。</div>
        ) : null}
      </div>
    </div>
  );
}
