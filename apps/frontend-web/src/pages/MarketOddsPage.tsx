import { useEffect, useState } from "react";
import { BarChart3, RefreshCw, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { fetchLatestExternalMarketOdds } from "@/adapters/marketMonitor";
import { MarketOddsMatrix } from "@/components/reports/ReportMarketOddsMatrix";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { buildMarketMonitorTabOptions, type MarketMonitorTab } from "@/components/market-monitor/marketMonitorPageModel";
import type { MarketOddsEvidenceViewModel } from "@/types/reports";

export function MarketOddsPage() {
  const navigate = useNavigate();
  const [evidence, setEvidence] = useState<MarketOddsEvidenceViewModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadEvidence() {
      setIsLoading(true);
      setError(null);
      try {
        const result = await fetchLatestExternalMarketOdds();
        if (!cancelled) setEvidence(result);
      } catch (cause) {
        if (!cancelled) {
          setEvidence(null);
          setError(cause instanceof Error ? cause : new Error("加载市场赔率失败"));
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void loadEvidence();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const itemCount = evidence?.groups.reduce((count, group) => count + group.items.length, 0) ?? 0;
  const dataDate = evidence?.trade_date ?? evidence?.as_of.slice(0, 10) ?? "—";

  function handleTabChange(tab: MarketMonitorTab) {
    if (tab === "odds") return;
    navigate(tab === "overview" ? "/market-monitor" : `/market-monitor?tab=${tab}`);
  }

  return (
    <FAPageScaffold
      className="market-monitor-page-shell"
      toolbar={(
        <FAWorkspaceHeader
          icon={BarChart3}
          title="市场监控"
          tabs={buildMarketMonitorTabOptions()}
          value="odds"
          onChange={handleTabChange}
          ariaLabel="市场监控视图切换"
          actions={(
            <button type="button" onClick={() => setReloadToken((value) => value + 1)} className="fa-workspace-toolbar-button">
              <RefreshCw size={12} />
              刷新
            </button>
          )}
          primaryLabel="数据状态"
          primaryItems={evidence ? [
            { label: "日期", value: dataDate },
            { label: "面板", value: evidence.panel_count },
            { label: "赔率项", value: itemCount },
            { label: "识别", value: evidence.extraction_status === "accepted" ? "通过" : "待复核" },
          ] : []}
          secondaryLabel="用途"
          secondaryItems={[{ label: "定位", value: "单源辅助证据" }]}
        />
      )}
      bodyClassName="fa-page-stack"
    >
      {isLoading ? <LoadingSkeleton variant="page" /> : null}

      {!isLoading && error ? (
        <ErrorState
          title="市场赔率加载失败"
          message={error.message}
          onRetry={() => setReloadToken((value) => value + 1)}
        />
      ) : null}

      {!isLoading && !error && !evidence ? (
        <FAEmptyState
          title="暂无市场赔率"
          description="当前接口没有返回可展示的外部市场赔率证据。"
        />
      ) : null}

      {!isLoading && evidence ? (
        <>
          <section className="flex items-start gap-3 border-l-2 border-[var(--warn)] bg-[var(--warn-soft)] px-3 py-2.5">
            <ShieldCheck size={16} className="mt-0.5 shrink-0 text-[var(--warn)]" />
            <div className="min-w-0">
              <h1 className="fa-section-title">外部事件定价</h1>
              <p className="mt-0.5 fa-muted-text">
                赔率反映外部市场对事件结果的定价，只作为研究辅助证据；点击任一条目可核对原图、OCR 和来源锚点。
              </p>
            </div>
          </section>
          <MarketOddsMatrix
            evidence={evidence}
            reportDetailPath={evidence.article_id ? `/reports/${evidence.article_id}` : null}
          />
        </>
      ) : null}
    </FAPageScaffold>
  );
}

export default MarketOddsPage;
