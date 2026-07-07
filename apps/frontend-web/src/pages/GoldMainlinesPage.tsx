import { useEffect } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, RefreshCw } from "lucide-react";

import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { GoldMainlineRequirementArchitecturePanel } from "@/components/gold-mainlines/GoldMainlineRequirementArchitecturePanel";
import { GoldTopicOverviewCard, GoldTopicStatusBar } from "@/components/gold-mainlines/GoldMainlinePageFrame";
import { MainlineDetailDrawer } from "@/components/gold-mainlines/MainlineDetailDrawer";
import { MainlineEvidenceList } from "@/components/gold-mainlines/MainlineEvidenceList";
import { MainlineRankingTable } from "@/components/gold-mainlines/MainlineRankingTable";
import { mainlineCoverageRows, type MainlineCoverageRow } from "@/components/gold-mainlines/goldMainlineCoverage";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNarrativeText,
} from "@/components/shared/goldMainlineFormat";
import { useGoldMainlines } from "@/hooks/useGoldMainlines";
import type { AppShellOutletContext } from "@/components/AppShell";
import type { GoldMacroOverview } from "@/types/gold-mainlines";

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
              <button type="button" onClick={refetch} className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">
                <RefreshCw size={12} />
                刷新
              </button>
              <Link to="/event-flow" className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-3 py-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">
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
      <MainlineRankingTable rows={coverageRows} />
      <GoldMainlineRequirementArchitecturePanel overview={overview} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.42fr)]">
        <MainlineDetailDrawer overview={overview} rows={coverageRows} />
        <MainlineEvidenceList overview={overview} rows={coverageRows} />
      </div>
    </FAPageScaffold>
  );
}

export default GoldMainlinesPage;
