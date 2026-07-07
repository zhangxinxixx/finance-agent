import { useEffect } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, RefreshCw } from "lucide-react";

import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { GoldTopicOverviewCard, GoldTopicStatusBar } from "@/components/gold-mainlines/GoldMainlinePageFrame";
import { OilGeoEvidenceTimeline } from "@/components/oil-geopolitics/OilGeoEvidenceTimeline";
import { OilGeoVerificationCard } from "@/components/oil-geopolitics/OilGeoVerificationCard";
import { SafeHavenVsInflationSplit } from "@/components/oil-geopolitics/SafeHavenVsInflationSplit";
import { WarOilRateChainPanel } from "@/components/oil-geopolitics/WarOilRateChainPanel";
import {
  collectSources,
  coverageStatusLabel,
  coverageStatusTone,
  rankingMainlineId,
  scoreLabel,
  topicEvents,
  topicRankings,
  topicRows,
  topicVerification,
  type TopicMainlineRow,
} from "@/components/oil-geopolitics/oilGeopoliticsModel";
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
} from "@/components/shared/goldMainlineFormat";
import { useGoldMainlines } from "@/hooks/useGoldMainlines";
import type { AppShellOutletContext } from "@/components/AppShell";
import type {
  GoldMacroOverview,
} from "@/types/gold-mainlines";

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

function OilHeader({ overview, rows }: { overview: GoldMacroOverview; rows: TopicMainlineRow[] }) {
  const leading = rows.find((row) => row.ranking)?.ranking ?? null;
  const chain = overview.war_oil_rate_chain;
  const coveredCount = rows.filter((row) => row.ranking).length;

  return (
    <GoldTopicOverviewCard
      title="石油与地缘"
      eyebrow="Oil / Geopolitics"
      description={chain?.summary || leading?.summary || overview.one_line_conclusion || "等待后端主线总览返回石油与地缘摘要。"}
      accent="warn"
      metrics={[
        { label: "专题覆盖", value: `${coveredCount}/2`, meta: "Oil / Geopolitics", tone: coveredCount === 2 ? "up" : "warn" },
        { label: "风险链", value: formatTransmissionPathLabel(chain?.path_id), meta: chain?.conclusion_code ? `${chain.conclusion_code}. ${chain.conclusion_label ?? ""}` : "chain" },
        {
          label: "主导驱动",
          value: formatGoldDriverLabel(chain?.dominant_driver ?? overview.driver_conflict?.dominant_driver),
          meta: formatGoldMainlineLabel(rankingMainlineId(leading) ?? overview.dominant_mainline),
          tone: goldNetBiasTone(chain?.net_effect ?? leading?.direction ?? overview.net_bias),
        },
        { label: "风险分", value: `${scoreLabel(overview.risk_score)}/100`, meta: "risk score", tone: "warn" },
      ]}
    />
  );
}

function MainlineRows({ rows }: { rows: TopicMainlineRow[] }) {
  return (
    <FACard title="地缘 / 石油主线" eyebrow="Theme Rows" accent="brand" bodyClassName="!p-0" className="shrink-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] table-fixed text-left text-[length:var(--type-caption)]">
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
                    <div className="mt-0.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">{formatGoldPricingLayerLabel(meta.pricingLayer)}</div>
                  </td>
                  <td className="px-3 py-2"><FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{coverageStatusLabel(row.status)}</FAStatusPill></td>
                  <td className="px-3 py-2"><FAStatusPill tone={goldNetBiasTone(item?.direction ?? "unknown")} dot={false}>{formatGoldNetBiasLabel(item?.direction ?? "unknown")}</FAStatusPill></td>
                  <td className="fa-num px-3 py-2 font-semibold text-[var(--fg-2)]">{scoreLabel(item?.score)}</td>
                  <td className="px-3 py-2"><FAStatusPill tone={goldVerificationStatusTone(verificationStatus)} dot={false}>{formatGoldVerificationStatusLabel(verificationStatus)}</FAStatusPill></td>
                  <td className="px-3 py-2 text-[var(--fg-3)]">
                    <div className="line-clamp-2 leading-5">{item?.summary || meta.description}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {meta.evidenceTargets.slice(0, 4).map((target) => (
                        <span key={target} className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-1.5 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">{target}</span>
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

export function OilGeopoliticsPage() {
  const { data, isLoading, isError, error, refetch } = useGoldMainlines();
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    shell.setHeaderContent(
      <HeaderBreadcrumb
        title="石油与地缘"
        meta={
          <>
            <span className="dashboard-header-summary-item">战争风险</span>
            <span className="dashboard-header-summary-item">油价冲击</span>
            <span className="dashboard-header-summary-item">利率传导</span>
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
              <button type="button" onClick={refetch} className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">
                <RefreshCw size={12} />
                刷新
              </button>
              <Link to="/gold-mainlines" className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">
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
        <GoldTopicStatusBar status={data.status} date={data.date || overview.as_of?.slice(0, 10)} runId={data.run_id} netBias={overview.net_bias} phase={overview.phase} riskScore={overview.risk_score} onRefresh={refetch} />
      )}
    >
      {data.warnings.length ? <FAWarningBanner title="降级提示" description={warningText(data.warnings)} tone="info" /> : null}
      <OilHeader overview={overview} rows={rows} />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <div className="grid content-start gap-3">
          <WarOilRateChainPanel chain={chain} rows={rows} events={events} />
          <MainlineRows rows={rows} />
          <SafeHavenVsInflationSplit conflict={overview.driver_conflict} />
        </div>
        <div className="grid content-start gap-3">
          <OilGeoVerificationCard overview={overview} items={verification} />
          <OilGeoEvidenceTimeline events={events} sourceRefs={sources} />
        </div>
      </div>
    </FAPageScaffold>
  );
}

export default OilGeopoliticsPage;
