import { useEffect } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, GitBranch, RefreshCw } from "lucide-react";

import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { GoldTopicOverviewCard, GoldTopicStatusBar } from "@/components/gold-mainlines/GoldMainlinePageFrame";
import {
  GOLD_MAINLINE_META,
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatGoldPricingLayerLabel,
  formatTransmissionPathLabel,
  formatGoldVerificationStatusLabel,
  goldNetBiasTone,
  goldVerificationStatusTone,
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import { useGoldMainlines } from "@/hooks/useGoldMainlines";
import type { AppShellOutletContext } from "@/components/AppShell";
import type {
  GoldMacroOverview,
  GoldMainline,
  GoldMainlineEventLink,
  GoldMainlineRanking,
  VerificationItem,
} from "@/types/gold-mainlines";
import type { SourceRef } from "@/types/common";

const RATE_MAINLINES: GoldMainline[] = ["fed_policy_path", "real_rates_usd"];
const RATE_PATHS = ["inflation_to_real_rates", "usd_pressure"];
const RATE_CHAIN_STEPS = [
  { id: "macro_inputs", label: "通胀 / 就业 / FOMC", mainlineId: "fed_policy_path" as GoldMainline },
  { id: "fed_path", label: "Fed path", mainlineId: "fed_policy_path" as GoldMainline },
  { id: "nominal_rates", label: "名义利率", mainlineId: "fed_policy_path" as GoldMainline },
  { id: "real_rates", label: "实际利率", mainlineId: "real_rates_usd" as GoldMainline },
  { id: "usd_pressure", label: "DXY / 美元压力", mainlineId: "real_rates_usd" as GoldMainline },
  { id: "gold_response", label: "黄金价格确认", mainlineId: "real_rates_usd" as GoldMainline },
];

function scoreLabel(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

function warningLabel(value: string): string {
  const exact: Record<string, string> = {
    "gold_macro_overview artifact unavailable": "黄金主线总览产物暂不可用",
    "gold_event_mainlines artifact unavailable": "黄金事件主线产物暂不可用",
  };
  return exact[value] ?? value;
}

function warningText(values: string[]): string {
  return values.map(warningLabel).join("；");
}

function statusTone(value: string | null | undefined): FAStatusTone {
  if (value === "available" || value === "ok" || value === "confirmed" || value === "official_confirmed" || value === "multi_source") return "up";
  if (value === "partial" || value === "stale" || value === "pending" || value === "single_source" || value === "report_derived") return "warn";
  if (value === "unavailable" || value === "failed" || value === "error") return "down";
  if (value === "unknown") return "dim";
  return "neutral";
}

function rankingMainlineId(item: GoldMainlineRanking | null | undefined): GoldMainline | null {
  return normalizeGoldMainlineId(item?.mainline_id ?? item?.mainline);
}

function eventMainlineIds(event: GoldMainlineEventLink): GoldMainline[] {
  const ids = [...(event.mainline_ids ?? []), event.primary_mainline ?? null]
    .map((value) => normalizeGoldMainlineId(value))
    .filter((value): value is GoldMainline => Boolean(value));
  return [...new Set(ids)];
}

function topicRankings(overview: GoldMacroOverview): GoldMainlineRanking[] {
  return [...(overview.theme_rankings ?? [])]
    .filter((item) => {
      const mainlineId = rankingMainlineId(item);
      return mainlineId ? RATE_MAINLINES.includes(mainlineId) : false;
    })
    .sort((left, right) => left.rank - right.rank);
}

interface TopicMainlineRow {
  id: GoldMainline;
  ranking: GoldMainlineRanking | null;
  verificationItems: VerificationItem[];
  status: "covered" | "pending" | "missing";
}

function topicRows(overview: GoldMacroOverview): TopicMainlineRow[] {
  const rankingById = new Map(
    topicRankings(overview)
      .map((item) => [rankingMainlineId(item), item] as const)
      .filter((entry): entry is readonly [GoldMainline, GoldMainlineRanking] => Boolean(entry[0])),
  );
  return RATE_MAINLINES.map((id) => {
    const ranking = rankingById.get(id) ?? null;
    const verificationItems = overview.verification_matrix.filter((item) => item.mainline_id === id);
    const hasPendingVerification = verificationItems.some((item) => item.status === "pending" || item.status === "unavailable");
    return {
      id,
      ranking,
      verificationItems,
      status: ranking ? (hasPendingVerification || ranking.verification_status === "single_source" ? "pending" : "covered") : "missing",
    };
  });
}

function coverageStatusLabel(value: TopicMainlineRow["status"]): string {
  if (value === "covered") return "已覆盖";
  if (value === "pending") return "待验证";
  return "待接入";
}

function coverageStatusTone(value: TopicMainlineRow["status"]): FAStatusTone {
  if (value === "covered") return "up";
  if (value === "pending") return "warn";
  return "dim";
}

function topicEvents(events: GoldMainlineEventLink[]): GoldMainlineEventLink[] {
  return events
    .filter((event) => eventMainlineIds(event).some((id) => RATE_MAINLINES.includes(id)) || event.transmission_path_ids.some((id) => RATE_PATHS.includes(id)))
    .slice(0, 8);
}

function topicVerification(overview: GoldMacroOverview): VerificationItem[] {
  return overview.verification_matrix
    .filter((item) => {
      const mainlineId = normalizeGoldMainlineId(item.mainline_id);
      return mainlineId ? RATE_MAINLINES.includes(mainlineId) : false;
    })
    .slice(0, 8);
}

function sourceKey(ref: SourceRef, index: number): string {
  return `${ref.source_ref}:${ref.snapshot_id ?? ""}:${index}`;
}

function collectSources(overview: GoldMacroOverview, rankings: GoldMainlineRanking[]): SourceRef[] {
  const refs = [
    ...rankings.flatMap((item) => item.source_refs ?? []),
    ...(overview.source_refs ?? []),
  ];
  const seen = new Set<string>();
  const unique: SourceRef[] = [];
  refs.forEach((ref, index) => {
    const key = sourceKey(ref, index);
    const stable = `${ref.source_ref}:${ref.snapshot_id ?? ""}:${ref.status ?? ""}`;
    if (seen.has(stable)) return;
    seen.add(stable);
    unique.push(ref);
  });
  return unique.slice(0, 8);
}

function RatesHeader({ overview, rows }: { overview: GoldMacroOverview; rows: TopicMainlineRow[] }) {
  const leading = rows.find((row) => row.ranking)?.ranking ?? null;
  const coveredCount = rows.filter((row) => row.ranking).length;

  return (
    <GoldTopicOverviewCard
      title="利率与美元"
      eyebrow="Rate / Dollar"
      description={leading?.summary || overview.one_line_conclusion || "等待后端主线总览返回利率与美元摘要。"}
      accent="info"
      metrics={[
        { label: "专题覆盖", value: `${coveredCount}/2`, meta: "Fed path / Real rates", tone: coveredCount === 2 ? "up" : "warn" },
        {
          label: "主导主线",
          value: formatGoldMainlineLabel(rankingMainlineId(leading) ?? overview.dominant_mainline),
          meta: leading ? formatGoldPricingLayerLabel(leading.pricing_layer) : "dominant",
        },
        { label: "主线分数", value: scoreLabel(leading?.theme_score ?? leading?.score), meta: "Theme score", tone: goldNetBiasTone(leading?.direction ?? overview.net_bias) },
        { label: "置信度", value: scoreLabel(leading?.confidence_score ?? leading?.confidence), meta: leading?.verification_status ?? "confidence" },
      ]}
    />
  );
}

function MainlineGrid({ rows }: { rows: TopicMainlineRow[] }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {rows.map((row) => {
        const item = row.ranking;
        const meta = GOLD_MAINLINE_META[row.id];
        const verificationStatus = item?.verification_status ?? (row.status === "missing" ? "unverified" : "pending");

        return (
        <FACard
          key={row.id}
          title={item?.label || meta.label}
          eyebrow={item ? `Rank #${item.rank}` : formatGoldPricingLayerLabel(meta.pricingLayer)}
          accent={row.id === "fed_policy_path" ? "info" : "brand"}
          className="shrink-0"
          action={<FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{coverageStatusLabel(row.status)}</FAStatusPill>}
        >
          <div className="grid gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-1.5">
                <FAStatusPill tone={goldNetBiasTone(item?.direction ?? "unknown")} dot={false}>{formatGoldNetBiasLabel(item?.direction ?? "unknown")}</FAStatusPill>
                <FAStatusPill tone={goldVerificationStatusTone(verificationStatus)} dot={false}>{formatGoldVerificationStatusLabel(verificationStatus)}</FAStatusPill>
              </div>
              <p className="mt-2 text-[12px] leading-5 text-[var(--fg-3)]">{item?.summary || meta.description}</p>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="text-[10px] text-[var(--fg-5)]">Score</div>
                <div className="fa-num mt-1 text-[14px] font-semibold text-[var(--fg-2)]">{scoreLabel(item?.score)}</div>
              </div>
              <div className="rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="text-[10px] text-[var(--fg-5)]">Confidence</div>
                <div className="fa-num mt-1 text-[14px] font-semibold text-[var(--fg-2)]">{scoreLabel(item?.confidence)}</div>
              </div>
              <div className="rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="text-[10px] text-[var(--fg-5)]">Events</div>
                <div className="fa-num mt-1 text-[14px] font-semibold text-[var(--fg-2)]">{item?.event_ids.length ?? 0}</div>
              </div>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              <div>
                <div className="text-[10px] font-semibold text-[var(--fg-5)]">利多驱动</div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {((item?.bullish_drivers.length ? item.bullish_drivers : [])).map((driver) => (
                    <FAStatusPill key={driver} tone="up" dot={false}>{formatGoldDriverLabel(driver)}</FAStatusPill>
                  ))}
                  {!item?.bullish_drivers.length ? <span className="text-[11px] text-[var(--fg-4)]">未形成后端驱动拆解</span> : null}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-semibold text-[var(--fg-5)]">利空驱动</div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {((item?.bearish_drivers.length ? item.bearish_drivers : [])).map((driver) => (
                    <FAStatusPill key={driver} tone="down" dot={false}>{formatGoldDriverLabel(driver)}</FAStatusPill>
                  ))}
                  {!item?.bearish_drivers.length ? <span className="text-[11px] text-[var(--fg-4)]">未形成后端驱动拆解</span> : null}
                </div>
              </div>
            </div>
            <div>
              <div className="text-[10px] font-semibold text-[var(--fg-5)]">需要证据</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {meta.evidenceTargets.map((target) => (
                  <FAStatusPill key={target} tone={row.status === "missing" ? "dim" : "neutral"} dot={false}>{target}</FAStatusPill>
                ))}
              </div>
            </div>
          </div>
        </FACard>
        );
      })}
    </div>
  );
}

function chainStepStatus(row: TopicMainlineRow | undefined, hasEvents: boolean): { label: string; tone: FAStatusTone } {
  if (!row) return { label: "待接入", tone: "dim" };
  if (row.status === "missing") return { label: "待接入", tone: "dim" };
  if (row.status === "pending") return { label: "待验证", tone: "warn" };
  if (hasEvents) return { label: "已归因", tone: "up" };
  return { label: "已覆盖", tone: "up" };
}

function TransmissionCard({ rows, events }: { rows: TopicMainlineRow[]; events: GoldMainlineEventLink[] }) {
  const rowById = new Map(rows.map((row) => [row.id, row]));
  const hasEvents = events.length > 0;

  return (
    <FACard title="利率链 / 美元链" eyebrow="Transmission" accent="none" className="shrink-0">
      <div className="grid gap-1.5">
        {RATE_CHAIN_STEPS.map((step, index) => {
          const status = chainStepStatus(rowById.get(step.mainlineId), hasEvents);
          return (
            <div key={step.id} className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[11px]">
              <GitBranch size={11} className="text-[var(--info)]" />
              <span className="fa-num text-[10px] text-[var(--fg-5)]">{String(index + 1).padStart(2, "0")}</span>
              <span className="min-w-0 flex-1 truncate font-semibold text-[var(--fg-2)]">{step.label}</span>
              <FAStatusPill tone={status.tone} dot={false}>{status.label}</FAStatusPill>
            </div>
          );
        })}
      </div>
    </FACard>
  );
}

function EvidencePanel({ events }: { events: GoldMainlineEventLink[] }) {
  return (
    <FACard title="事件证据" eyebrow="Event Evidence" accent="none" className="shrink-0">
      {events.length ? (
        <div className="grid gap-2">
          {events.map((event) => (
            <div key={event.event_id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="fa-num min-w-0 truncate text-[11px] font-semibold text-[var(--fg-2)]">{event.event_id}</div>
                <FAStatusPill tone={goldNetBiasTone(event.direction_by_asset?.XAUUSD ?? "unknown")} dot={false}>
                  {formatGoldNetBiasLabel(event.direction_by_asset?.XAUUSD ?? "unknown")}
                </FAStatusPill>
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {eventMainlineIds(event).map((id) => (
                  <FAStatusPill key={id} tone="neutral" dot={false}>{formatGoldMainlineLabel(id)}</FAStatusPill>
                ))}
                {event.transmission_path_ids.map((id) => (
                  <FAStatusPill key={id} tone="dim" dot={false}>{formatTransmissionPathLabel(id)}</FAStatusPill>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-[var(--fg-4)]">当前主线产物未返回利率与美元相关事件链接。</div>
      )}
    </FACard>
  );
}

function VerificationPanel({ items }: { items: VerificationItem[] }) {
  return (
    <FACard title="待验证" eyebrow="Verification" accent="info" className="shrink-0">
      {items.length ? (
        <div className="grid gap-2">
          {items.map((item) => (
            <div key={item.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-[11px] font-semibold text-[var(--fg-2)]">{item.label || item.reason || item.required_source || item.id}</div>
                <FAStatusPill tone={statusTone(item.status)} dot={false}>{item.status}</FAStatusPill>
              </div>
              <div className="mt-1 text-[10px] text-[var(--fg-5)]">{item.required_source || formatGoldMainlineLabel(item.mainline_id)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-[var(--fg-4)]">当前主线总览未返回利率与美元待验证项。</div>
      )}
    </FACard>
  );
}

function SourcesPanel({ refs }: { refs: SourceRef[] }) {
  if (!refs.length) return null;
  return (
    <FACard title="证据来源" eyebrow="Source Trace" accent="none" className="shrink-0">
      <div className="flex flex-wrap gap-1.5">
        {refs.map((ref, index) => (
          <FASourceTraceBadge key={sourceKey(ref, index)} source={ref.label || ref.source_ref} status={ref.status ?? "trace"} snapshotId={ref.snapshot_id} />
        ))}
      </div>
    </FACard>
  );
}

export function RatesDollarPage() {
  const { data, isLoading, isError, error, refetch } = useGoldMainlines();
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    shell.setHeaderContent(
      <HeaderBreadcrumb
        title="利率与美元"
        meta={
          <>
            <span className="dashboard-header-summary-item">Fed path</span>
            <span className="dashboard-header-summary-item">实际利率</span>
            <span className="dashboard-header-summary-item">DXY</span>
          </>
        }
      />,
    );
    return () => shell.setHeaderContent(null);
  }, [shell]);

  if (isLoading) {
    return <div className="finance-page-shell"><LoadingSkeleton variant="page" /></div>;
  }

  if (isError || !data) {
    return <div className="finance-page-shell"><ErrorState message={error?.message ?? "利率与美元数据加载失败"} onRetry={refetch} /></div>;
  }

  const overview = data.gold_macro_overview;

  if (!overview) {
    return (
      <FAPageScaffold>
        <FAEmptyState
          title="利率与美元专题未生成"
          description={warningText(data.warnings) || "当前没有可用的黄金主线总览。"}
          action={(
            <div className="flex flex-wrap justify-center gap-2">
              <button type="button" onClick={refetch} className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]">
                <RefreshCw size={12} />
                刷新
              </button>
              <Link to="/gold-mainlines" className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]">
                黄金主线
                <ArrowRight size={12} />
              </Link>
            </div>
          )}
        />
        {data.warnings.length ? <FAWarningBanner title="数据状态" description={warningText(data.warnings)} tone="info" /> : null}
      </FAPageScaffold>
    );
  }

  const rankings = topicRankings(overview);
  const rows = topicRows(overview);
  const events = topicEvents(data.gold_mainlines.event_links ?? []);
  const verification = topicVerification(overview);
  const sources = collectSources(overview, rankings);

  return (
    <FAPageScaffold
      toolbar={(
        <GoldTopicStatusBar status={data.status} date={data.date || overview.as_of?.slice(0, 10)} runId={data.run_id} netBias={overview.net_bias} phase={overview.phase} riskScore={overview.risk_score} onRefresh={refetch} />
      )}
    >
      {data.warnings.length ? <FAWarningBanner title="降级提示" description={warningText(data.warnings)} tone="info" /> : null}
      <RatesHeader overview={overview} rows={rows} />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <div className="grid content-start gap-3">
          <MainlineGrid rows={rows} />
        </div>
        <div className="grid content-start gap-3">
          <TransmissionCard rows={rows} events={events} />
          <EvidencePanel events={events} />
          <VerificationPanel items={verification} />
          <SourcesPanel refs={sources} />
        </div>
      </div>
    </FAPageScaffold>
  );
}

export default RatesDollarPage;
