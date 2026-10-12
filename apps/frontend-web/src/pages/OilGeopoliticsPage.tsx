import { useEffect } from "react";
import { readableWarning } from "@/lib/researchReading";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, RefreshCw } from "lucide-react";

import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { GoldTopicPage } from "@/components/gold-workspace/GoldTopicPage";
import {
  GoldReadTimeSourceHealthBanner,
  GoldTopicOverviewCard,
  GoldTopicStatusBar,
  goldDecisionTrustLabel,
  goldDecisionTrustNote,
} from "@/components/gold-mainlines/GoldMainlinePageFrame";
import { OilGeoEvidenceTimeline } from "@/components/oil-geopolitics/OilGeoEvidenceTimeline";
import { OilGeoMainlineRows } from "@/components/oil-geopolitics/OilGeoMainlineRows";
import { OilGeoVerificationCard } from "@/components/oil-geopolitics/OilGeoVerificationCard";
import { SafeHavenVsInflationSplit } from "@/components/oil-geopolitics/SafeHavenVsInflationSplit";
import { WarOilRateChainPanel } from "@/components/oil-geopolitics/WarOilRateChainPanel";
import {
  collectSources,
  rankingMainlineId,
  scoreLabel,
  topicEvents,
  topicRankings,
  topicRows,
  topicVerification,
  type TopicMainlineRow,
} from "@/components/oil-geopolitics/oilGeopoliticsModel";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatTransmissionPathLabel,
  goldNetBiasTone,
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
  return exact[value] ?? readableWarning(value);
}

function warningText(values: string[]): string {
  return values.map(warningLabel).join("；");
}

function OilHeader({
  overview,
  rows,
  decisionTrustLabel,
  decisionTrustNote,
}: {
  overview: GoldMacroOverview;
  rows: TopicMainlineRow[];
  decisionTrustLabel: string;
  decisionTrustNote: string | null;
}) {
  const leading = rows.find((row) => row.ranking)?.ranking ?? null;
  const chain = overview.war_oil_rate_chain;
  const coveredCount = rows.filter((row) => row.ranking).length;

  return (
    <GoldTopicOverviewCard
      title="石油与地缘"
      eyebrow="石油与地缘主题"
      decisionTrustLabel={decisionTrustLabel}
      decisionTrustNote={decisionTrustNote}
      description={readableWarning(chain?.summary || leading?.summary || overview.one_line_conclusion || "等待后端主线总览返回石油与地缘摘要。")}
      accent="warn"
      metrics={[
        { label: "已登记主线", value: `${coveredCount}/2`, meta: "有排序记录，不等同可靠覆盖", tone: coveredCount ? "info" : "warn" },
        { label: "风险链", value: chain ? formatTransmissionPathLabel(chain.path_id) : "未提供", meta: chain?.conclusion_label ? `${chain.conclusion_label} · 传导链` : "传导路径待确认" },
        {
          label: "主导驱动",
          value: formatGoldDriverLabel(chain?.dominant_driver ?? overview.driver_conflict?.dominant_driver),
          meta: formatGoldMainlineLabel(rankingMainlineId(leading) ?? overview.dominant_mainline),
          tone: goldNetBiasTone(chain?.net_effect ?? leading?.direction ?? overview.net_bias),
        },
        { label: "风险分", value: scoreLabel(overview.risk_score) === "—" ? "—" : `${scoreLabel(overview.risk_score)}/100`, meta: "研究风险评分", tone: "warn" },
      ]}
    />
  );
}

function OilGeopoliticsEvidenceDetails({ embedded = false }: { embedded?: boolean }) {
  const {
    data,
    isLoading,
    isRefreshing,
    isError,
    error,
    lastSuccessfulAt,
    refetch,
  } = useGoldMainlines();
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    if (embedded) return;
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
  }, [shell, embedded]);

  if (isLoading && !data) {
    return <div className="finance-page-shell"><LoadingSkeleton variant="page" /></div>;
  }

  if (isError && !data) {
    return <div className="finance-page-shell"><ErrorState message={error?.message ?? "石油与地缘数据加载失败"} onRetry={refetch} /></div>;
  }

  if (!data) return null;

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
  const refreshError = isError ? error?.message : null;
  const decisionTrustLabel = goldDecisionTrustLabel(data.read_time_source_health, { isRefreshing, refreshError });
  const decisionTrustNote = goldDecisionTrustNote(data.read_time_source_health, { isRefreshing, refreshError });

  return (
    <FAPageScaffold
      toolbar={(
        <GoldTopicStatusBar
          status={data.status}
          date={data.date || overview.as_of?.slice(0, 10)}
          runId={data.run_id}
          netBias={overview.net_bias}
          phase={overview.phase}
          riskScore={overview.risk_score}
          sourceHealth={data.read_time_source_health}
          isRefreshing={isRefreshing}
          refreshError={refreshError}
          lastSuccessfulAt={lastSuccessfulAt}
          onRefresh={refetch}
        />
      )}
    >
      {data.warnings.length ? <FAWarningBanner title="降级提示" description={warningText(data.warnings)} tone="info" /> : null}
      <GoldReadTimeSourceHealthBanner
        health={data.read_time_source_health}
        warnings={data.read_time_warnings}
      />
      <OilHeader
        overview={overview}
        rows={rows}
        decisionTrustLabel={decisionTrustLabel}
        decisionTrustNote={decisionTrustNote}
      />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <div className="grid content-start gap-3">
          <WarOilRateChainPanel chain={chain} rows={rows} events={events} />
          <OilGeoMainlineRows rows={rows} />
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

export function OilGeopoliticsPage() {
  return <GoldTopicPage title="能源、地缘与资金" group="funds"
    description="原油与成品油、避险和通胀传导、央行与ETF配置、CFTC仓位及融资环境"
    evidence={<OilGeopoliticsEvidenceDetails embedded />} />;
}

export default OilGeopoliticsPage;
