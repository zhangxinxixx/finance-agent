import { useEffect, useState } from "react";
import { BarChart3, RefreshCw } from "lucide-react";

import { fetchCMEOptionsDates } from "../adapters/cmeOptions";
import { CMEOptionsKpiStrip } from "../components/cme-options/CMEOptionsKpiStrip";
import { CMEOptionsDecisionWorkspace } from "../components/cme-options/CMEOptionsDecisionWorkspace";
import { CMEOptionsOverviewGrid } from "../components/cme-options/CMEOptionsOverviewGrid";
import {
  CMEOptionsIntentSummary,
  CMEOptionsLoadingShell,
  type CMEOptionsTab,
  renderCMEOptionsTabContent,
  reportStatusLabel,
  reviewStatusLabel,
  sourceLabel,
  sourceTone,
} from "../components/cme-options/CMEOptionsPageSections";
import { FACard } from "../components/shared/FACard";
import { FAEmptyState } from "../components/shared/FAEmptyState";
import { FAFilterBar } from "../components/shared/FAFilterBar";
import { FAPageScaffold } from "../components/shared/FAPageScaffold";
import { FAStatusPill } from "../components/shared/FAStatusPill";
import { FAWorkspaceHeader } from "../components/shared/FAWorkspaceHeader";
import { ErrorState } from "../components/shared/ErrorState";
import { useCMEOptions } from "../hooks/useCMEOptions";
import { useCMEOptionsDecision } from "../hooks/useCMEOptionsDecision";
import type { CMEOptionsResponse } from "../types/cme-options";

/* ── Main Page ──────────────────────────────────────── */

export function CMEOptionsPage() {
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | undefined>(undefined);
  const [selectedExpiry, setSelectedExpiry] = useState<string | undefined>(undefined);
  const [activeTab, setActiveTab] = useState<CMEOptionsTab>("overview");
  const [isDatesLoading, setIsDatesLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function loadDates() {
      setIsDatesLoading(true);
      try {
        const dates = await fetchCMEOptionsDates();
        if (!cancelled) {
          setAvailableDates(dates);
          setSelectedDate((current) => {
            if (dates.length === 0) return undefined;
            if (current && dates.includes(current)) return current;
            return dates[0];
          });
        }
      } catch {
        if (!cancelled) {
          setAvailableDates([]);
          setSelectedDate(undefined);
        }
      } finally {
        if (!cancelled) setIsDatesLoading(false);
      }
    }
    void loadDates();
    return () => { cancelled = true; };
  }, []);

  const shouldLoadSnapshot = !isDatesLoading && (availableDates.length === 0 || selectedDate !== undefined);
  const { data, isLoading, isError, error, refetch } = useCMEOptions(selectedDate, shouldLoadSnapshot);
  const decisionState = useCMEOptionsDecision(selectedDate, shouldLoadSnapshot);
  const snapshot = data as CMEOptionsResponse | null;
  const source = snapshot?.source ?? "unavailable";
  const hasData = snapshot?.has_data !== false;
  const wallScores = snapshot?.wall_scores ?? [];
  const hasRequiredSections = Boolean(snapshot?.data_source && snapshot?.gex?.netgex_aggregate && snapshot?.support_resistance);
  const isEmpty = !snapshot || !hasData || wallScores.length === 0 || !hasRequiredSections;
  const status = snapshot?.data_source?.status;
  const factReviewStatus = snapshot?.analysis?.fact_review_status;
  const expiryList = snapshot?.data_source?.expiries ?? [];
  const tabOptions = [
    { value: "overview", label: "总览" },
    { value: "gex-gamma", label: "伽马敞口" },
    { value: "wall-map", label: "墙位地图" },
    { value: "scenario", label: "情景推演" },
    { value: "data-trace", label: "数据溯源" },
  ] satisfies Array<{ value: CMEOptionsTab; label: string }>;
  const pageShellClass = "finance-page-shell cme-options-page-shell";

  // Reset expiry when date changes or expiry list updates
  useEffect(() => {
    if (expiryList.length > 0 && (!selectedExpiry || !expiryList.includes(selectedExpiry))) {
      setSelectedExpiry(expiryList[0]);
    }
  }, [expiryList, selectedExpiry]);

  if (isLoading && !snapshot && !isError) {
    return <div className={pageShellClass}><CMEOptionsLoadingShell /></div>;
  }

  if (isError) {
    return (
      <div className={pageShellClass}>
        <FACard title="期权结构" eyebrow="期权" accent="brand">
          <div className="flex items-center gap-1.5">
            <FAStatusPill tone={sourceTone(source)}>{sourceLabel(source)}</FAStatusPill>
          </div>
        </FACard>
        <ErrorState title="加载期权结构失败" message={error?.message || "未知错误。请重试。"} onRetry={refetch} retryLabel="重试" />
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className={pageShellClass}>
        <FACard title="期权结构" eyebrow="期权" accent="brand">
          <div className="flex items-center gap-1.5">
            <FAStatusPill tone={sourceTone(source)}>{sourceLabel(source)}</FAStatusPill>
          </div>
        </FACard>
        <FAEmptyState title="该日期无期权数据" description="请切换日期，或检查预处理输出是否可用。" />
      </div>
    );
  }

  return (
    <FAPageScaffold
      className={pageShellClass}
      toolbar={(
        <div className="fa-page-stack">
          <FAWorkspaceHeader
            className="cme-options-workspace-header"
            icon={BarChart3}
            title="CME 期权结构"
            tabs={tabOptions}
            value={activeTab}
            onChange={(value) => setActiveTab(value as CMEOptionsTab)}
            ariaLabel="期权结构视图切换"
            actions={(
              <button type="button" onClick={() => { refetch(); decisionState.refetch(); }} className="fa-workspace-toolbar-button" title="刷新 CME 期权结构">
                <RefreshCw size={12} />
                刷新
              </button>
            )}
            primaryLabel="数据状态"
            primaryItems={[
              { label: "来源", value: sourceLabel(source) },
              ...(status ? [{ label: "公告", value: reportStatusLabel(status) }] : []),
              ...(factReviewStatus ? [{ label: "复核", value: reviewStatusLabel(factReviewStatus) }] : []),
              ...(decisionState.data ? [{ label: "决策", value: decisionState.data.status === "available" ? "可用" : decisionState.data.status === "partial" ? "部分可用" : "不可用" }] : []),
            ]}
            secondaryLabel="合约"
            secondaryItems={[
              ...(selectedDate ? [{ label: "日期", value: selectedDate }] : []),
              ...(selectedExpiry ? [{ label: "到期", value: selectedExpiry }] : []),
              { label: "行数", value: snapshot.data_source?.row_count?.toLocaleString("en-US") ?? "0" },
            ]}
          />

          <FAFilterBar
            className="cme-options-control-bar"
            left={
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                <CMEOptionsIntentSummary snapshot={snapshot} />
                <CMEOptionsKpiStrip snapshot={snapshot} />
              </div>
            }
            right={
              <>
                <div className="event-flow-filter-item">
                  <span className="event-flow-filter-label">日期</span>
                  <select
                    value={selectedDate ?? ""}
                    onChange={(e) => setSelectedDate(e.target.value || undefined)}
                    className="event-flow-filter-box cme-options-filter-box min-w-[104px]"
                  >
                    {availableDates.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <div className="event-flow-filter-item">
                  <span className="event-flow-filter-label">到期日</span>
                  <select
                    value={selectedExpiry ?? ""}
                    onChange={(e) => setSelectedExpiry(e.target.value || undefined)}
                    className="event-flow-filter-box cme-options-filter-box min-w-[120px]"
                  >
                    {expiryList.map((ex) => (
                      <option key={ex} value={ex}>{ex}</option>
                    ))}
                  </select>
                </div>
              </>
            }
          />
        </div>
      )}
      bodyClassName="fa-page-stack"
    >
      <div className="px-1 pb-4">
        {snapshot && activeTab === "overview" ? (
          <div className="fa-page-stack">
            <CMEOptionsDecisionWorkspace decision={decisionState.data} isLoading={decisionState.isLoading} error={decisionState.error} />
            <section className="cme-decision-snapshot-analysis" aria-label="完整结构分析">
              <div className="cme-decision-snapshot-heading">
                <div><span>Snapshot Deep Analysis</span><strong>完整结构分析</strong></div>
                <p>保留原始 CME snapshot 的完整结构、风险与溯源阅读路径。</p>
              </div>
              <CMEOptionsOverviewGrid snapshot={snapshot} wallScores={wallScores} />
            </section>
          </div>
        ) : snapshot ? renderCMEOptionsTabContent({ snapshot, activeTab, wallScores, selectedExpiry }) : null}
      </div>
    </FAPageScaffold>
  );
}
