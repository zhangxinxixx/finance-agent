import { useEffect } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, GitBranch, RefreshCw, ShieldAlert } from "lucide-react";

import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { getStatusLabel } from "@/components/shared/statusMeta";
import {
  GOLD_MAINLINE_META,
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatGoldPhaseLabel,
  formatGoldPricingLayerLabel,
  formatTransmissionPathLabel,
  formatGoldVerificationStatusLabel,
  goldConflictTone,
  goldNetBiasTone,
  goldVerificationStatusTone,
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import { useGoldMainlines } from "@/hooks/useGoldMainlines";
import type { AppShellOutletContext } from "@/components/AppShell";
import type {
  DriverConflict,
  GoldMacroOverview,
  GoldMainline,
  GoldMainlineEventLink,
  GoldMainlineRanking,
  TransmissionChainSummary,
  VerificationItem,
} from "@/types/gold-mainlines";
import type { SourceRef } from "@/types/common";

const OIL_MAINLINES: GoldMainline[] = ["oil_prices", "geopolitical_war_risk"];
const OIL_PATHS = ["geopolitics_to_oil_to_rates", "haven_bid"];
const OIL_CHAIN_STEPS = [
  { id: "geopolitical_event", label: "地缘事件", mainlineId: "geopolitical_war_risk" as GoldMainline },
  { id: "supply_risk", label: "原油供应风险", mainlineId: "geopolitical_war_risk" as GoldMainline },
  { id: "oil_price", label: "WTI / Brent", mainlineId: "oil_prices" as GoldMainline },
  { id: "inflation_expectation", label: "通胀预期", mainlineId: "oil_prices" as GoldMainline },
  { id: "fed_path", label: "Fed path", mainlineId: "oil_prices" as GoldMainline },
  { id: "rates_usd", label: "实际利率 / 美元", mainlineId: "oil_prices" as GoldMainline },
  { id: "gold_response", label: "黄金方向确认", mainlineId: "geopolitical_war_risk" as GoldMainline },
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

function rankingMainlineId(item: GoldMainlineRanking): GoldMainline | null {
  return normalizeGoldMainlineId(item.mainline_id ?? item.mainline);
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
      return mainlineId ? OIL_MAINLINES.includes(mainlineId) : false;
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
  return OIL_MAINLINES.map((id) => {
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
    .filter((event) => eventMainlineIds(event).some((id) => OIL_MAINLINES.includes(id)) || event.transmission_path_ids.some((id) => OIL_PATHS.includes(id)))
    .slice(0, 8);
}

function topicVerification(overview: GoldMacroOverview): VerificationItem[] {
  return overview.verification_matrix
    .filter((item) => {
      const mainlineId = normalizeGoldMainlineId(item.mainline_id);
      return mainlineId ? OIL_MAINLINES.includes(mainlineId) : false;
    })
    .slice(0, 8);
}

function sourceKey(ref: SourceRef, index: number): string {
  return `${ref.source_ref}:${ref.snapshot_id ?? ""}:${index}`;
}

function collectSources(overview: GoldMacroOverview, rankings: GoldMainlineRanking[], chain: TransmissionChainSummary | null): SourceRef[] {
  const refs = [
    ...rankings.flatMap((item) => item.source_refs ?? []),
    ...(chain?.source_refs ?? []),
    ...(overview.source_refs ?? []),
  ];
  const seen = new Set<string>();
  const unique: SourceRef[] = [];
  refs.forEach((ref) => {
    const stable = `${ref.source_ref}:${ref.snapshot_id ?? ""}:${ref.status ?? ""}`;
    if (seen.has(stable)) return;
    seen.add(stable);
    unique.push(ref);
  });
  return unique.slice(0, 8);
}

function OilHeader({ overview, rows }: { overview: GoldMacroOverview; rows: TopicMainlineRow[] }) {
  const leading = rows.find((row) => row.ranking)?.ranking ?? null;
  const chain = overview.war_oil_rate_chain;
  const coveredCount = rows.filter((row) => row.ranking).length;

  return (
    <FACard
      title="石油与地缘"
      eyebrow="Oil / Geopolitics"
      description={chain?.summary || leading?.summary || overview.one_line_conclusion || "等待后端主线总览返回石油与地缘摘要。"}
      accent="warn"
      className="shrink-0"
      action={(
        <div className="flex flex-wrap justify-end gap-1.5">
          <FAStatusPill tone={goldNetBiasTone(chain?.net_effect ?? leading?.direction ?? overview.net_bias)} dot={false}>
            {formatGoldNetBiasLabel(chain?.net_effect ?? leading?.direction ?? overview.net_bias)}
          </FAStatusPill>
          <FAStatusPill tone="neutral" dot={false}>{formatGoldPhaseLabel(overview.phase)}</FAStatusPill>
          <FAStatusPill tone="dim" dot={false}>{overview.as_of?.slice(0, 16).replace("T", " ") || "时间未知"}</FAStatusPill>
        </div>
      )}
    >
      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">专题覆盖</div>
          <div className="fa-num mt-2 text-[18px] font-semibold text-[var(--fg-2)]">{coveredCount}/2</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">风险链</div>
          <div className="mt-2 text-[13px] font-semibold text-[var(--fg-2)]">{formatTransmissionPathLabel(chain?.path_id)}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">主导驱动</div>
          <div className="mt-2 text-[13px] font-semibold text-[var(--fg-2)]">{formatGoldDriverLabel(chain?.dominant_driver ?? overview.driver_conflict?.dominant_driver)}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">风险分</div>
          <div className="fa-num mt-2 text-[18px] font-semibold text-[var(--fg-2)]">{scoreLabel(overview.risk_score)}/100</div>
        </div>
      </div>
    </FACard>
  );
}

function chainStepStatus(row: TopicMainlineRow | undefined, hasChain: boolean, hasEvents: boolean): { label: string; tone: FAStatusTone } {
  if (hasChain) return { label: "已返回", tone: "up" };
  if (!row || row.status === "missing") return { label: "待接入", tone: "dim" };
  if (row.status === "pending") return { label: "待验证", tone: "warn" };
  if (hasEvents) return { label: "已归因", tone: "up" };
  return { label: "已覆盖", tone: "up" };
}

function ChainBoard({ chain, rows, events }: { chain: TransmissionChainSummary | null; rows: TopicMainlineRow[]; events: GoldMainlineEventLink[] }) {
  const rowById = new Map(rows.map((row) => [row.id, row]));
  const hasEvents = events.length > 0;
  const fallbackSteps = OIL_CHAIN_STEPS.map((step) => {
    const status = chainStepStatus(rowById.get(step.mainlineId), false, hasEvents);
    return {
      id: step.id,
      label: step.label,
      status: status.label,
      tone: status.tone,
    };
  });

  return (
    <FACard
      title={chain ? formatTransmissionPathLabel(chain.path_id) : "战争-石油-利率链"}
      eyebrow="Chain Board"
      accent="warn"
      className="shrink-0"
      action={chain ? <FAStatusPill tone={goldNetBiasTone(chain.net_effect)} dot={false}>{formatGoldNetBiasLabel(chain.net_effect)}</FAStatusPill> : null}
    >
      {chain ? (
        <div className="grid gap-3">
          <p className="text-[12px] leading-5 text-[var(--fg-3)]">{chain.summary}</p>
          <div className="grid gap-1.5">
            {chain.steps.map((step, index) => (
              <div key={step.id} className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[11px]">
                <GitBranch size={11} className="text-[var(--warn)]" />
                <span className="fa-num text-[10px] text-[var(--fg-5)]">{String(index + 1).padStart(2, "0")}</span>
                <span className="min-w-0 flex-1 truncate font-semibold text-[var(--fg-2)]">{step.label}</span>
                <FAStatusPill tone={statusTone(step.status ?? chain.status)} dot={false}>{step.status ?? chain.status}</FAStatusPill>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid gap-3">
          <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2 text-[11px] leading-5 text-[var(--fg-4)]">
            当前 artifact 未返回完整战争-石油-利率传导链，以下显示专题应覆盖的链条节点和数据接入状态。
          </div>
          <div className="grid gap-1.5">
            {fallbackSteps.map((step, index) => (
              <div key={step.id} className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[11px]">
                <GitBranch size={11} className="text-[var(--warn)]" />
                <span className="fa-num text-[10px] text-[var(--fg-5)]">{String(index + 1).padStart(2, "0")}</span>
                <span className="min-w-0 flex-1 truncate font-semibold text-[var(--fg-2)]">{step.label}</span>
                <FAStatusPill tone={step.tone} dot={false}>{step.status}</FAStatusPill>
              </div>
            ))}
          </div>
        </div>
      )}
    </FACard>
  );
}

function ConflictSplit({ conflict }: { conflict: DriverConflict | null }) {
  return (
    <FACard
      title="多空冲突拆解"
      eyebrow="Conflict Split"
      accent={conflict?.status === "aligned" ? "up" : "warn"}
      className="shrink-0"
      action={<FAStatusPill tone={goldConflictTone(conflict?.status)} dot={false}>{conflict?.status ?? "unknown"}</FAStatusPill>}
    >
      {conflict ? (
        <div className="grid gap-3">
          {conflict.explanation ? <p className="text-[12px] leading-5 text-[var(--fg-3)]">{conflict.explanation}</p> : null}
          <div className="grid gap-2 md:grid-cols-2">
            <div>
              <div className="text-[10px] font-semibold text-[var(--fg-5)]">避险利多</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(conflict.bullish_drivers.length ? conflict.bullish_drivers : ["暂无"]).map((driver) => (
                  <FAStatusPill key={driver} tone="up" dot={false}>{formatGoldDriverLabel(driver)}</FAStatusPill>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-semibold text-[var(--fg-5)]">通胀/利率利空</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(conflict.bearish_drivers.length ? conflict.bearish_drivers : ["暂无"]).map((driver) => (
                  <FAStatusPill key={driver} tone="down" dot={false}>{formatGoldDriverLabel(driver)}</FAStatusPill>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-[11px] text-[var(--fg-4)]">当前主线总览未返回多空冲突拆解。</div>
      )}
    </FACard>
  );
}

function MainlineRows({ rows }: { rows: TopicMainlineRow[] }) {
  return (
    <FACard title="地缘 / 石油主线" eyebrow="Theme Rows" accent="brand" bodyClassName="!p-0" className="shrink-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] table-fixed text-left text-[11px]">
          <colgroup>
            <col className="w-[62px]" />
            <col className="w-[150px]" />
            <col className="w-[92px]" />
            <col className="w-[82px]" />
            <col className="w-[76px]" />
            <col className="w-[110px]" />
            <col />
          </colgroup>
          <thead className="border-b border-[var(--border-faint)] bg-[var(--bg-card-inner)] text-[var(--fg-5)]">
            <tr>
              <th className="px-3 py-2 font-semibold">Rank</th>
              <th className="px-3 py-2 font-semibold">主线</th>
              <th className="px-3 py-2 font-semibold">覆盖</th>
              <th className="px-3 py-2 font-semibold">方向</th>
              <th className="px-3 py-2 font-semibold">Score</th>
              <th className="px-3 py-2 font-semibold">验证</th>
              <th className="px-3 py-2 font-semibold">摘要 / 证据</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const item = row.ranking;
              const meta = GOLD_MAINLINE_META[row.id];
              const verificationStatus = item?.verification_status ?? (row.status === "missing" ? "unverified" : "pending");
              return (
                <tr key={row.id} className="border-b border-[var(--border-faint)] last:border-0">
                  <td className="fa-num px-3 py-2 font-semibold text-[var(--fg-2)]">{item ? `#${item.rank}` : "—"}</td>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-[var(--fg-2)]">{item?.label || meta.label}</div>
                    <div className="mt-0.5 text-[10px] text-[var(--fg-5)]">{formatGoldPricingLayerLabel(meta.pricingLayer)}</div>
                  </td>
                  <td className="px-3 py-2"><FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{coverageStatusLabel(row.status)}</FAStatusPill></td>
                  <td className="px-3 py-2"><FAStatusPill tone={goldNetBiasTone(item?.direction ?? "unknown")} dot={false}>{formatGoldNetBiasLabel(item?.direction ?? "unknown")}</FAStatusPill></td>
                  <td className="fa-num px-3 py-2 font-semibold text-[var(--fg-2)]">{scoreLabel(item?.score)}</td>
                  <td className="px-3 py-2"><FAStatusPill tone={goldVerificationStatusTone(verificationStatus)} dot={false}>{formatGoldVerificationStatusLabel(verificationStatus)}</FAStatusPill></td>
                  <td className="px-3 py-2 text-[var(--fg-3)]">
                    <div className="line-clamp-2 leading-5">{item?.summary || meta.description}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {meta.evidenceTargets.slice(0, 4).map((target) => (
                        <span key={target} className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-1.5 py-0.5 text-[10px] text-[var(--fg-5)]">{target}</span>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </FACard>
  );
}

function VerificationRail({ overview, items }: { overview: GoldMacroOverview; items: VerificationItem[] }) {
  const conflictChecks = overview.driver_conflict?.verification_needed ?? [];

  return (
    <FACard title="验证清单" eyebrow="Verification Rail" accent="info" className="shrink-0">
      {items.length || conflictChecks.length ? (
        <div className="grid gap-2">
          {conflictChecks.map((item) => (
            <div key={`conflict-${item}`} className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <ShieldAlert size={12} className="mt-0.5 shrink-0 text-[var(--warn)]" />
              <div className="min-w-0 flex-1 text-[11px] leading-5 text-[var(--fg-3)]">{formatGoldDriverLabel(item)}</div>
            </div>
          ))}
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
        <div className="text-[11px] text-[var(--fg-4)]">当前主线总览未返回地缘/石油待验证项。</div>
      )}
    </FACard>
  );
}

function EventEvidence({ events }: { events: GoldMainlineEventLink[] }) {
  return (
    <FACard title="相关事件" eyebrow="Event Evidence" accent="none" className="shrink-0">
      {events.length ? (
        <div className="grid gap-2">
          {events.map((event) => (
            <div key={event.event_id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="fa-num min-w-0 truncate text-[11px] font-semibold text-[var(--fg-2)]">{event.event_id}</div>
                {event.changed_dominant_theme ? <FAStatusPill tone="warn" dot={false}>改变主线</FAStatusPill> : null}
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {eventMainlineIds(event).map((id) => <FAStatusPill key={id} tone="neutral" dot={false}>{formatGoldMainlineLabel(id)}</FAStatusPill>)}
                {event.transmission_path_ids.map((id) => <FAStatusPill key={id} tone="dim" dot={false}>{formatTransmissionPathLabel(id)}</FAStatusPill>)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-[var(--fg-4)]">当前主线产物未返回石油与地缘相关事件链接。</div>
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

export function OilGeopoliticsPage() {
  const { data, isLoading, isError, error, refetch } = useGoldMainlines();
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    shell.setHeaderContent(
      <div className="dashboard-header-summary dashboard-header-summary--stacked">
        <div className="dashboard-header-summary-title">石油与地缘</div>
        <div className="dashboard-header-summary-meta">
          <span className="dashboard-header-summary-item">战争风险</span>
          <span className="dashboard-header-summary-item">油价冲击</span>
          <span className="dashboard-header-summary-item">利率传导</span>
        </div>
      </div>,
    );
    return () => shell.setHeaderContent(null);
  }, [shell]);

  if (isLoading) {
    return <div className="finance-page-shell"><LoadingSkeleton variant="page" /></div>;
  }

  if (isError || !data) {
    return <div className="finance-page-shell"><ErrorState message={error?.message ?? "石油与地缘数据加载失败"} onRetry={refetch} /></div>;
  }

  const overview = data.gold_macro_overview;

  if (!overview) {
    return (
      <FAPageScaffold>
        <FAEmptyState
          title="石油与地缘专题未生成"
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
  const chain = overview.war_oil_rate_chain;
  const verification = topicVerification(overview);
  const events = topicEvents(data.gold_mainlines.event_links ?? []);
  const sources = collectSources(overview, rankings, chain);

  return (
    <FAPageScaffold
      toolbar={(
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <FAStatusPill tone={statusTone(data.status)} dot={false}>{getStatusLabel(data.status)}</FAStatusPill>
            <FAStatusPill tone="neutral" dot={false}>{data.date || overview.as_of?.slice(0, 10) || "日期未知"}</FAStatusPill>
            {data.run_id ? <FAStatusPill tone="dim" dot={false}>{data.run_id}</FAStatusPill> : null}
          </div>
          <button type="button" onClick={refetch} className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]">
            <RefreshCw size={12} />
            刷新
          </button>
        </div>
      )}
    >
      {data.warnings.length ? <FAWarningBanner title="降级提示" description={warningText(data.warnings)} tone="info" /> : null}
      <OilHeader overview={overview} rows={rows} />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <div className="grid content-start gap-3">
          <ChainBoard chain={chain} rows={rows} events={events} />
          <MainlineRows rows={rows} />
          <ConflictSplit conflict={overview.driver_conflict} />
        </div>
        <div className="grid content-start gap-3">
          <VerificationRail overview={overview} items={verification} />
          <EventEvidence events={events} />
          <SourcesPanel refs={sources} />
        </div>
      </div>
    </FAPageScaffold>
  );
}

export default OilGeopoliticsPage;
