import { useEffect } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, GitBranch, RefreshCw, ShieldAlert } from "lucide-react";

import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { GoldTopicOverviewCard, GoldTopicStatusBar } from "@/components/gold-mainlines/GoldMainlinePageFrame";
import {
  GOLD_MAINLINE_META,
  GOLD_MAINLINE_ORDER,
  formatGoldDriverLabel,
  formatGoldEventRefLabel,
  formatGoldMainlineLabel,
  formatGoldNarrativeText,
  formatGoldNetBiasLabel,
  formatGoldPricingLayerLabel,
  formatGoldSourceRefLabel,
  formatTransmissionPathLabel,
  formatGoldConflictStatusLabel,
  formatGoldVerificationReasonLabel,
  formatGoldVerificationStatusLabel,
  goldConflictTone,
  goldNetBiasTone,
  goldVerificationStatusTone,
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import { useGoldMainlines } from "@/hooks/useGoldMainlines";
import type { AppShellOutletContext } from "@/components/AppShell";
import type { GoldMacroOverview, GoldMainline, GoldMainlineRanking, MainlineRequirement, VerificationItem } from "@/types/gold-mainlines";

function scoreLabel(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

function scoreFormulaLabel(item: GoldMainlineRanking | null): string {
  if (!item) return "—";
  const direction = item.direction_score ?? 0;
  const impact = item.impact_score ?? 1;
  const confidence = item.confidence_score ?? 1;
  const freshness = item.freshness_score ?? 1;
  return `${direction}/${impact}/${confidence}/${freshness}`;
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

function statusTone(value: string | null | undefined) {
  if (value === "available" || value === "ok" || value === "confirmed") return "up";
  if (value === "partial" || value === "stale" || value === "pending") return "warn";
  if (value === "unavailable" || value === "failed" || value === "error") return "down";
  return "neutral";
}

type MainlineCoverageStatus = "covered" | "pending" | "missing";

interface MainlineCoverageRow {
  id: GoldMainline;
  ranking: GoldMainlineRanking | null;
  verificationItems: VerificationItem[];
  eventIds: string[];
  sourceCount: number;
  status: MainlineCoverageStatus;
}

function rankingMainlineId(item: GoldMainlineRanking): GoldMainline | null {
  return normalizeGoldMainlineId(item.mainline_id ?? item.mainline);
}

function mainlineCoverageRows(overview: GoldMacroOverview): MainlineCoverageRow[] {
  const rankings = new Map(
    (overview.theme_rankings ?? [])
      .map((item) => [rankingMainlineId(item), item] as const)
      .filter((entry): entry is readonly [GoldMainline, GoldMainlineRanking] => Boolean(entry[0])),
  );
  return GOLD_MAINLINE_ORDER.map((id) => {
    const ranking = rankings.get(id) ?? null;
    const verificationItems = overview.verification_matrix.filter((item) => item.mainline_id === id);
    const eventIds = ranking?.event_ids ?? [];
    const sourceKeys = new Set(
      [
        ...(ranking?.source_refs ?? []),
        ...verificationItems.flatMap((item) => item.source_refs ?? []),
      ].map((ref, index) => `${ref.source_ref ?? "source"}:${ref.snapshot_id ?? index}`),
    );
    const hasPendingVerification = verificationItems.some((item) => item.status === "pending" || item.status === "unavailable");
    const status: MainlineCoverageStatus = ranking ? (hasPendingVerification || ranking.verification_status === "single_source" ? "pending" : "covered") : "missing";

    return {
      id,
      ranking,
      verificationItems,
      eventIds,
      sourceCount: sourceKeys.size,
      status,
    };
  });
}

function coverageStatusLabel(value: MainlineCoverageStatus): string {
  if (value === "covered") return "已覆盖";
  if (value === "pending") return "待验证";
  return "待接入";
}

function coverageStatusTone(value: MainlineCoverageStatus) {
  if (value === "covered") return "up";
  if (value === "pending") return "warn";
  return "dim";
}

function readinessTone(value: string | null | undefined) {
  if (value === "ready") return "up";
  if (value === "partial") return "warn";
  if (value === "missing") return "down";
  return "neutral";
}

function readinessLabel(value: string | null | undefined): string {
  if (value === "ready") return "可分析";
  if (value === "partial") return "部分可分析";
  if (value === "missing") return "待开发";
  return value || "未知";
}

function verificationLabel(item: VerificationItem): string {
  return formatGoldVerificationReasonLabel(item.label || item.reason || item.required_source || item.id);
}

function formatEventCount(value: number): string {
  return `${value} 条事件`;
}

function GoldMainlineHero({ overview, rows }: { overview: GoldMacroOverview; rows: MainlineCoverageRow[] }) {
  const conflict = overview.driver_conflict;
  const covered = rows.filter((row) => row.ranking).length;
  const pending = rows.filter((row) => row.status === "pending").length;
  const missing = rows.filter((row) => row.status === "missing").length;
  const eventCount = new Set(rows.flatMap((row) => row.eventIds)).size || overview.key_events.length;

  return (
    <GoldTopicOverviewCard
      title="黄金主线归因"
      eyebrow="Attribution Layer"
      accent="emphasis"
      description={formatGoldNarrativeText(overview.one_line_conclusion || conflict?.explanation) || "主线引擎暂未返回摘要。"}
      metrics={[
        {
          label: "主导主线",
          value: formatGoldMainlineLabel(overview.dominant_mainline),
          meta: conflict?.dominant_driver ? formatGoldDriverLabel(conflict.dominant_driver) : "dominant",
          tone: conflict?.status === "conflicted" || conflict?.status === "mixed" ? "warn" : "info",
        },
        { label: "覆盖", value: `${covered}/9`, meta: `待接入 ${missing}` },
        { label: "待验证", value: pending, meta: "单源 / 缺关键数据", tone: pending ? "warn" : "up" },
        { label: "事件 / 验证", value: `${eventCount}E / ${overview.verification_matrix.length}V`, meta: overview.asset || "XAUUSD" },
      ]}
    />
  );
}

function RankingTable({ rows }: { rows: MainlineCoverageRow[] }) {
  return (
    <FACard title="九主线覆盖矩阵" eyebrow="Theme Coverage" accent="brand" bodyClassName="!p-0" className="shrink-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[940px] table-fixed text-left text-[11px]">
          <colgroup>
            <col className="w-[58px]" />
            <col className="w-[178px]" />
            <col className="w-[92px]" />
            <col className="w-[82px]" />
            <col className="w-[74px]" />
            <col className="w-[66px]" />
            <col className="w-[104px]" />
            <col className="w-[86px]" />
            <col />
          </colgroup>
          <thead className="border-b border-[var(--border-faint)] bg-[var(--bg-card-inner)] text-[var(--fg-5)]">
            <tr>
              <th className="px-3 py-2 font-semibold">Rank</th>
              <th className="px-3 py-2 font-semibold">主线</th>
              <th className="px-3 py-2 font-semibold">定价层</th>
              <th className="px-3 py-2 font-semibold">覆盖</th>
              <th className="px-3 py-2 font-semibold">方向</th>
              <th className="px-3 py-2 font-semibold">评分</th>
              <th className="px-3 py-2 font-semibold">验证</th>
              <th className="px-3 py-2 font-semibold">证据</th>
              <th className="px-3 py-2 font-semibold">摘要</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const meta = GOLD_MAINLINE_META[row.id];
              const item = row.ranking;
              const verificationStatus = item?.verification_status ?? (row.status === "missing" ? "unverified" : "pending");
              return (
              <tr key={row.id} className="border-b border-[var(--border-faint)] last:border-0">
                <td className="px-3 py-2 fa-num font-semibold text-[var(--fg-2)]">{item ? `#${item.rank}` : "—"}</td>
                <td className="px-3 py-2">
                  <div className="font-semibold text-[var(--fg-2)]">{item?.label || meta.label}</div>
                  <div className="mt-0.5 line-clamp-1 text-[10px] text-[var(--fg-5)]">{meta.headline}</div>
                </td>
                <td className="px-3 py-2 text-[var(--fg-3)]">{formatGoldPricingLayerLabel(item?.pricing_layer ?? meta.pricingLayer)}</td>
                <td className="px-3 py-2">
                  <FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{coverageStatusLabel(row.status)}</FAStatusPill>
                </td>
                <td className="px-3 py-2">
                  <FAStatusPill tone={goldNetBiasTone(item?.direction ?? "unknown")} dot={false}>{formatGoldNetBiasLabel(item?.direction ?? "unknown")}</FAStatusPill>
                </td>
                <td className="px-3 py-2">
                  <div className="fa-num font-semibold text-[var(--fg-2)]">{scoreLabel(item?.theme_score ?? item?.score)}</div>
                  <div className="mt-0.5 text-[9px] text-[var(--fg-5)]">D/I/C/F {scoreFormulaLabel(item)}</div>
                </td>
                <td className="px-3 py-2">
                  <FAStatusPill tone={goldVerificationStatusTone(verificationStatus)} dot={false}>{formatGoldVerificationStatusLabel(verificationStatus)}</FAStatusPill>
                </td>
                <td className="px-3 py-2">
                  <div className="fa-num text-[var(--fg-2)]">{row.eventIds.length}E / {row.sourceCount}S</div>
                </td>
                <td className="min-w-0 px-3 py-2 text-[var(--fg-3)]">
                  <div className="line-clamp-2 max-w-full break-words leading-5">
                    {item?.summary || `待接入：${meta.evidenceTargets.slice(0, 3).join(" / ")}`}
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

function MissingCoveragePanel({ rows }: { rows: MainlineCoverageRow[] }) {
  const missingRows = rows.filter((row) => row.status === "missing");
  const pendingRows = rows.filter((row) => row.status === "pending");

  return (
    <FACard title="覆盖缺口" eyebrow="Coverage Gaps" accent="warn" className="shrink-0">
      <div className="grid gap-3">
        <div>
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">未覆盖主线</div>
          {missingRows.length ? (
            <div className="mt-1.5 grid gap-2">
              {missingRows.map((row) => {
                const meta = GOLD_MAINLINE_META[row.id];
                return (
                  <div key={row.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[11px] font-semibold text-[var(--fg-2)]">{meta.label}</div>
                      <FAStatusPill tone="dim" dot={false}>{formatGoldPricingLayerLabel(meta.pricingLayer)}</FAStatusPill>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {meta.evidenceTargets.slice(0, 4).map((target) => (
                        <FAStatusPill key={target} tone="neutral" dot={false}>{target}</FAStatusPill>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="mt-1.5 text-[11px] text-[var(--fg-4)]">九条主线均已有后端覆盖。</div>
          )}
        </div>
        <div>
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">已覆盖但待验证</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(pendingRows.length ? pendingRows : []).map((row) => (
              <FAStatusPill key={row.id} tone="warn" dot={false}>{GOLD_MAINLINE_META[row.id].shortLabel}</FAStatusPill>
            ))}
            {!pendingRows.length ? <span className="text-[11px] text-[var(--fg-4)]">暂无单源待验证主线。</span> : null}
          </div>
        </div>
      </div>
    </FACard>
  );
}

function RequirementArchitecturePanel({ overview }: { overview: GoldMacroOverview }) {
  const requirements = overview.mainline_requirements ?? [];
  if (!requirements.length) return null;
  const readiness = overview.analysis_readiness;
  const gaps = overview.architecture_gaps ?? readiness?.next_gaps ?? [];

  return (
    <FACard
      title="分析能力架构"
      eyebrow="First Principles"
      accent="info"
      className="shrink-0"
      action={readiness ? (
        <FAStatusPill tone={readinessTone(readiness.status)} dot={false}>
          {readinessLabel(readiness.status)} {readiness.ready_count}/{readiness.total_count}
        </FAStatusPill>
      ) : null}
    >
      <div className="grid gap-3">
        <div className="grid gap-1.5 sm:grid-cols-4">
          {[
            { label: "完整", value: readiness?.ready_count ?? 0 },
            { label: "部分", value: readiness?.partial_count ?? 0 },
            { label: "待开发", value: readiness?.missing_count ?? 0 },
            { label: "覆盖率", value: `${Math.round((readiness?.coverage_ratio ?? 0) * 100)}%` },
          ].map((item) => (
            <div key={item.label} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5">
              <div className="text-[10px] font-semibold text-[var(--fg-5)]">{item.label}</div>
              <div className="fa-num mt-0.5 text-[14px] font-semibold text-[var(--fg-2)]">{item.value}</div>
            </div>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] table-fixed text-left text-[11px]">
            <colgroup>
              <col className="w-[160px]" />
              <col className="w-[98px]" />
              <col />
              <col className="w-[210px]" />
              <col className="w-[210px]" />
            </colgroup>
            <thead className="border-b border-[var(--border-faint)] text-[var(--fg-5)]">
              <tr>
                <th className="px-2.5 py-2 font-semibold">主线</th>
                <th className="px-2.5 py-2 font-semibold">能力</th>
                <th className="px-2.5 py-2 font-semibold">第一性原理</th>
                <th className="px-2.5 py-2 font-semibold">必需输入</th>
                <th className="px-2.5 py-2 font-semibold">缺口字段</th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((item: MainlineRequirement) => (
                <tr key={item.mainline_id} className="border-b border-[var(--border-faint)] last:border-0">
                  <td className="px-2.5 py-2">
                    <div className="font-semibold text-[var(--fg-2)]">{formatGoldMainlineLabel(item.mainline_id)}</div>
                    <div className="mt-0.5 text-[10px] text-[var(--fg-5)]">{formatGoldPricingLayerLabel(item.pricing_layer)}</div>
                  </td>
                  <td className="px-2.5 py-2">
                    <FAStatusPill tone={readinessTone(item.readiness_status)} dot={false}>{readinessLabel(item.readiness_status)}</FAStatusPill>
                  </td>
                  <td className="px-2.5 py-2 text-[var(--fg-3)]">
                    <div className="line-clamp-2 leading-5">{item.asset_principle}</div>
                    <div className="mt-1 truncate text-[10px] text-[var(--fg-5)]">{item.analysis_chain.slice(0, 5).join(" -> ")}</div>
                  </td>
                  <td className="px-2.5 py-2">
                    <div className="flex flex-wrap gap-1">
                      {item.required_sources.slice(0, 4).map((source) => (
                        <FAStatusPill key={source} tone={item.missing_sources.includes(source) ? "warn" : "up"} dot={false}>
                          {formatGoldDriverLabel(source)}
                        </FAStatusPill>
                      ))}
                    </div>
                  </td>
                  <td className="px-2.5 py-2 text-[var(--fg-4)]">
                    <div className="line-clamp-2 break-words leading-5">
                      {(item.missing_fields.length ? item.missing_fields : item.development_gaps).slice(0, 4).join(" / ") || "暂无"}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {gaps.length ? (
          <div className="grid gap-1.5">
            <div className="text-[10px] font-semibold text-[var(--fg-5)]">下一批架构缺口</div>
            {gaps.slice(0, 5).map((gap) => (
              <div key={gap} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[11px] leading-5 text-[var(--fg-3)]">
                {gap}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </FACard>
  );
}

function EventCoveragePanel({ rows }: { rows: MainlineCoverageRow[] }) {
  const eventRows = rows.filter((row) => row.eventIds.length > 0);

  return (
    <FACard title="事件归因索引" eyebrow="Event Links" accent="none" className="shrink-0">
      {eventRows.length ? (
        <div className="grid gap-2">
          {eventRows.map((row) => (
            <div key={row.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold text-[var(--fg-2)]">{GOLD_MAINLINE_META[row.id].label}</div>
                <FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{formatEventCount(row.eventIds.length)}</FAStatusPill>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {row.eventIds.slice(0, 4).map((eventId) => (
                  <span
                    key={eventId}
                    title={eventId.replace(/^event:/, "")}
                    className="fa-num max-w-full truncate rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5 text-[10px] text-[var(--fg-4)]"
                  >
                    {formatGoldEventRefLabel(eventId)}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-[var(--fg-4)]">当前主线总览未返回事件归因索引。</div>
      )}
    </FACard>
  );
}

function ConflictPanel({ overview }: { overview: GoldMacroOverview }) {
  const conflict = overview.driver_conflict;
  if (!conflict) return null;

  return (
    <FACard
      title="多空冲突"
      eyebrow="Driver Conflict"
      accent={conflict.status === "aligned" ? "up" : "warn"}
      className="shrink-0"
      action={<FAStatusPill tone={goldConflictTone(conflict.status)} dot={false}>{formatGoldConflictStatusLabel(conflict.status)}</FAStatusPill>}
    >
      <div className="grid gap-3">
        <div>
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">利多驱动</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(conflict.bullish_drivers.length ? conflict.bullish_drivers : ["暂无"]).map((item) => (
              <FAStatusPill key={item} tone="up" dot={false}>{formatGoldDriverLabel(item)}</FAStatusPill>
            ))}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-semibold text-[var(--fg-5)]">利空驱动</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(conflict.bearish_drivers.length ? conflict.bearish_drivers : ["暂无"]).map((item) => (
              <FAStatusPill key={item} tone="down" dot={false}>{formatGoldDriverLabel(item)}</FAStatusPill>
            ))}
          </div>
        </div>
      </div>
    </FACard>
  );
}

function ChainPanel({ overview }: { overview: GoldMacroOverview }) {
  const chain = overview.war_oil_rate_chain;
  if (!chain) return null;

  return (
    <FACard
      title={formatTransmissionPathLabel(chain.path_id)}
      eyebrow="Transmission Chain"
      accent="warn"
      className="shrink-0"
      action={<FAStatusPill tone={goldNetBiasTone(chain.net_effect)} dot={false}>{formatGoldNetBiasLabel(chain.net_effect)}</FAStatusPill>}
    >
      <p className="text-[12px] leading-5 text-[var(--fg-3)]">{formatGoldNarrativeText(chain.summary)}</p>
      {chain.steps.length ? (
        <div className="mt-3 grid gap-1.5">
          {chain.steps.map((step) => (
            <div key={step.id} className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[11px]">
              <GitBranch size={11} className="text-[var(--warn)]" />
              <span className="min-w-0 flex-1 truncate text-[var(--fg-2)]">{step.label}</span>
              <FAStatusPill tone={statusTone(step.status ?? "partial")} dot={false}>{step.status ?? "partial"}</FAStatusPill>
            </div>
          ))}
        </div>
      ) : null}
    </FACard>
  );
}

function VerificationPanel({ overview }: { overview: GoldMacroOverview }) {
  const verification = overview.verification_matrix.slice(0, 8);
  const conflictChecks = overview.driver_conflict?.verification_needed ?? [];

  return (
    <FACard title="待验证矩阵" eyebrow="Verification" accent="info" className="shrink-0">
      {verification.length || conflictChecks.length ? (
        <div className="grid gap-2">
          {conflictChecks.map((item) => (
            <div key={`conflict-${item}`} className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <ShieldAlert size={12} className="mt-0.5 shrink-0 text-[var(--warn)]" />
              <div className="min-w-0 flex-1 text-[11px] leading-5 text-[var(--fg-3)]">{formatGoldDriverLabel(item)}</div>
            </div>
          ))}
          {verification.map((item) => (
            <div key={item.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-[11px] font-semibold text-[var(--fg-2)]">{verificationLabel(item)}</div>
                <FAStatusPill tone={statusTone(item.status)} dot={false}>{formatGoldVerificationStatusLabel(item.status)}</FAStatusPill>
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-[var(--fg-5)]">
                {item.mainline_id ? <span>{formatGoldMainlineLabel(item.mainline_id)}</span> : null}
                {item.required_source ? <span>{formatGoldVerificationReasonLabel(item.required_source)}</span> : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-[var(--fg-4)]">当前主线总览未返回待验证项。</div>
      )}
    </FACard>
  );
}

function SourceRefsPanel({ overview }: { overview: GoldMacroOverview }) {
  const refs = overview.source_refs.slice(0, 8);
  if (!refs.length) return null;

  return (
    <FACard title="证据来源" eyebrow="Source Trace" accent="none" className="shrink-0">
      <div className="flex flex-wrap gap-1.5">
        {refs.map((ref, index) => (
          <FASourceTraceBadge
            key={`${ref.source_ref}-${ref.snapshot_id ?? index}`}
            source={formatGoldSourceRefLabel(ref, `来源 ${index + 1}`)}
            status={ref.status ?? "trace"}
            snapshotId={ref.snapshot_id}
          />
        ))}
      </div>
    </FACard>
  );
}

export function GoldMainlinesPage() {
  const { data, isLoading, isError, error, refetch } = useGoldMainlines();
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    shell.setHeaderContent(
      <HeaderBreadcrumb
        title="黄金主线归因"
        meta={
          <>
            <span className="dashboard-header-summary-item">九条主线排序</span>
            <span className="dashboard-header-summary-item">多空冲突</span>
            <span className="dashboard-header-summary-item">传导链验证</span>
          </>
        }
      />,
    );

    return () => shell.setHeaderContent(null);
  }, [shell]);

  if (isLoading) {
    return (
      <div className="finance-page-shell">
        <LoadingSkeleton variant="page" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="finance-page-shell">
        <ErrorState message={error?.message ?? "黄金主线数据加载失败"} onRetry={refetch} />
      </div>
    );
  }

  const overview = data.gold_macro_overview;

  if (!overview) {
    return (
      <FAPageScaffold>
        <FAEmptyState
          title="黄金主线总览未生成"
          description={warningText(data.warnings) || "当前没有可用的黄金主线总览。"}
          action={(
            <div className="flex flex-wrap justify-center gap-2">
              <button type="button" onClick={refetch} className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]">
                <RefreshCw size={12} />
                刷新
              </button>
              <Link to="/event-flow" className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]">
                事件证据
                <ArrowRight size={12} />
              </Link>
            </div>
          )}
        />
        {data.warnings.length ? (
          <FAWarningBanner title="数据状态" description={warningText(data.warnings)} tone="info" />
        ) : null}
      </FAPageScaffold>
    );
  }

  const coverageRows = mainlineCoverageRows(overview);

  return (
    <FAPageScaffold
      toolbar={(
        <GoldTopicStatusBar status={data.status} date={data.date || overview.as_of?.slice(0, 10)} runId={data.run_id} netBias={overview.net_bias} phase={overview.phase} riskScore={overview.risk_score} onRefresh={refetch} />
      )}
    >
      {data.warnings.length ? (
        <FAWarningBanner title="降级提示" description={warningText(data.warnings)} tone="info" />
      ) : null}

      <GoldMainlineHero overview={overview} rows={coverageRows} />
      <RankingTable rows={coverageRows} />
      <RequirementArchitecturePanel overview={overview} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.42fr)]">
        <div className="grid content-start gap-3">
          <MissingCoveragePanel rows={coverageRows} />
          <VerificationPanel overview={overview} />
          <EventCoveragePanel rows={coverageRows} />
        </div>
        <div className="grid content-start gap-3">
          <ConflictPanel overview={overview} />
          <ChainPanel overview={overview} />
          <SourceRefsPanel overview={overview} />
        </div>
      </div>
    </FAPageScaffold>
  );
}

export default GoldMainlinesPage;
