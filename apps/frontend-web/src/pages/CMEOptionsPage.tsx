import { useEffect, useState } from "react";

import { fetchCMEOptionsDates } from "../adapters/cmeOptions";
import { CMEOptionsKpiStrip } from "../components/cme-options/CMEOptionsKpiStrip";
import {
  CMEOptionsIntentSummary,
  CMEOptionsLoadingShell,
  type CMEOptionsTab,
  renderCMEOptionsTabContent,
  reportStatusLabel,
  reportStatusTone,
  reviewStatusLabel,
  reviewStatusTone,
  sourceLabel,
  sourceTone,
} from "../components/cme-options/CMEOptionsPageSections";
import { FACard } from "../components/shared/FACard";
import { FAEmptyState } from "../components/shared/FAEmptyState";
import { FAFilterBar } from "../components/shared/FAFilterBar";
import { FAPageScaffold } from "../components/shared/FAPageScaffold";
import { FAStatusPill } from "../components/shared/FAStatusPill";
import { FATabBar } from "../components/shared/FATabBar";
import { ErrorState } from "../components/shared/ErrorState";
import { useCMEOptions } from "../hooks/useCMEOptions";
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
        <FAFilterBar
          left={
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <FAStatusPill tone={sourceTone(source)}>{sourceLabel(source)}</FAStatusPill>
              {status ? <FAStatusPill tone={reportStatusTone(status)}>{reportStatusLabel(status)}</FAStatusPill> : null}
              {factReviewStatus ? (
                <FAStatusPill tone={reviewStatusTone(factReviewStatus)}>{reviewStatusLabel(factReviewStatus)}</FAStatusPill>
              ) : null}
              <CMEOptionsIntentSummary snapshot={snapshot} />
              <CMEOptionsKpiStrip snapshot={snapshot} />
            </div>
          }
          right={
            <>
              <div className="flex flex-col gap-0.5">
                <span className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">日期</span>
                <select
                  value={selectedDate ?? ""}
                  onChange={(e) => setSelectedDate(e.target.value || undefined)}
                  className="flex h-[28px] min-w-[100px] cursor-pointer items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 text-[11px] text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)]"
                >
                  {availableDates.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">到期日</span>
                <select
                  value={selectedExpiry ?? ""}
                  onChange={(e) => setSelectedExpiry(e.target.value || undefined)}
                  className="flex h-[28px] min-w-[120px] cursor-pointer items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 text-[11px] text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)]"
                >
                  {expiryList.map((ex) => (
                    <option key={ex} value={ex}>{ex}</option>
                  ))}
                </select>
              </div>
            </>
          }
        />
      )}
      bodyClassName="fa-page-stack"
    >
      <div className="shrink-0 px-1">
        <FATabBar value={activeTab} tabs={tabOptions} onChange={(value) => setActiveTab(value as CMEOptionsTab)} ariaLabel="期权结构视图切换" />
      </div>

      <div className="px-1 pb-4">
        {snapshot ? renderCMEOptionsTabContent({ snapshot, activeTab, wallScores, selectedExpiry }) : null}
      </div>
    </FAPageScaffold>
  );
}
