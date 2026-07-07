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
import { MainlineDetailDrawer } from "@/components/gold-mainlines/MainlineDetailDrawer";
import { MainlineEvidenceList } from "@/components/gold-mainlines/MainlineEvidenceList";
import { MainlineRankingTable } from "@/components/gold-mainlines/MainlineRankingTable";
import { mainlineCoverageRows, type MainlineCoverageRow } from "@/components/gold-mainlines/goldMainlineCoverage";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNarrativeText,
  formatGoldPricingLayerLabel,
} from "@/components/shared/goldMainlineFormat";
import { useGoldMainlines } from "@/hooks/useGoldMainlines";
import type { AppShellOutletContext } from "@/components/AppShell";
import type { GoldMacroOverview, MainlineRequirement } from "@/types/gold-mainlines";

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
              <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">{item.label}</div>
              <div className="fa-num mt-0.5 text-[length:var(--type-card-title)] font-semibold text-[var(--fg-2)]">{item.value}</div>
            </div>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] table-fixed text-left text-[length:var(--type-caption)]">
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
                    <div className="mt-0.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">{formatGoldPricingLayerLabel(item.pricing_layer)}</div>
                  </td>
                  <td className="px-2.5 py-2">
                    <FAStatusPill tone={readinessTone(item.readiness_status)} dot={false}>{readinessLabel(item.readiness_status)}</FAStatusPill>
                  </td>
                  <td className="px-2.5 py-2 text-[var(--fg-3)]">
                    <div className="line-clamp-2 leading-5">{item.asset_principle}</div>
                    <div className="mt-1 truncate text-[length:var(--type-caption)] text-[var(--fg-5)]">{item.analysis_chain.slice(0, 5).join(" -> ")}</div>
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
            <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">下一批架构缺口</div>
            {gaps.slice(0, 5).map((gap) => (
              <div key={gap} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">
                {gap}
              </div>
            ))}
          </div>
        ) : null}
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
      <RequirementArchitecturePanel overview={overview} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.42fr)]">
        <MainlineDetailDrawer overview={overview} rows={coverageRows} />
        <MainlineEvidenceList overview={overview} rows={coverageRows} />
      </div>
    </FAPageScaffold>
  );
}

export default GoldMainlinesPage;
