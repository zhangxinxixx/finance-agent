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
import { EvidenceRecordActions } from "../components/shared/EvidenceRecordActions";
import { useCMEOptions } from "../hooks/useCMEOptions";
import { useCMEOptionsDecision } from "../hooks/useCMEOptionsDecision";
import type { CMEOptionsResponse } from "../types/cme-options";
import { collectCMESnapshotIds, resolveCMEDecisionIdentity, resolveCMETradeDateIdentity } from "../components/cme-options/cmeDecisionIdentity";
import { formatCMEExpiryLabel } from "../components/cme-options/cmeOptionsFormat";

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
  const hasRequiredSections = Boolean(snapshot?.data_source && (snapshot?.gex?.netgex_aggregate || snapshot?.support_resistance || decisionState.data));
  const isEmpty = !snapshot || !hasData || !hasRequiredSections;
  const status = snapshot?.data_source?.status;
  const factReviewStatus = snapshot?.analysis?.fact_review_status;
  const expiryList = snapshot?.data_source?.expiries ?? [];
  const snapshotReportDate = snapshot?.data_source?.report_date && snapshot.data_source.report_date !== "unavailable"
    ? snapshot.data_source.report_date
    : null;
  const snapshotTradeDate = snapshot?.trade_date && snapshot.trade_date !== "unavailable" ? snapshot.trade_date : null;
  const decisionTradeDate = decisionState.data?.meta.current_trade_date ?? null;
  const tradeDateIdentity = resolveCMETradeDateIdentity(selectedDate, snapshotTradeDate, decisionTradeDate);
  const dateIdentityMismatch = tradeDateIdentity.status === "mismatch";
  const dateIdentityUnverified = Boolean(
    !dateIdentityMismatch
      && ((snapshot && !snapshotTradeDate) || (decisionState.data && !decisionTradeDate)),
  );
  const snapshotIdentityIds = collectCMESnapshotIds(
    snapshot?.snapshot_id,
    snapshot?.data_source?.input_snapshot_ids ?? [],
    snapshot?.source_trace?.map((item) => item.snapshot_id) ?? [],
  );
  const decisionIdentityIds = collectCMESnapshotIds(
    null,
    [],
    decisionState.data?.source_refs?.map((item) => item.snapshot_id) ?? [],
  );
  const decisionRevisionIdentity = resolveCMEDecisionIdentity(snapshotIdentityIds, decisionIdentityIds);
  const decisionRevisionMismatch = Boolean(decisionState.data && decisionRevisionIdentity.status === "mismatch");
  const decisionRevisionUnverified = Boolean(decisionState.data && decisionRevisionIdentity.status === "unverified");
  const alignedDecision = dateIdentityMismatch || dateIdentityUnverified || decisionRevisionMismatch || decisionRevisionUnverified
    ? null
    : decisionState.data;
  const dateIdentityMessage = dateIdentityMismatch
    ? "所选日期、结构数据与研究判断日期不一致，暂不能合并参考。"
    : dateIdentityUnverified
      ? "结构数据或研究判断缺少日期，暂不能确认对应同一交易日。"
      : null;
  const decisionRevisionMessage = decisionRevisionMismatch
    ? "研究判断与当前CME结构数据不对应，暂不能合并参考。"
    : decisionRevisionUnverified
      ? "尚无法核验研究判断与结构数据的对应关系，暂不能合并参考。"
      : null;
  const decisionIdentityError = dateIdentityMessage
    ? new Error(dateIdentityMessage)
    : decisionRevisionMessage
      ? new Error(decisionRevisionMessage)
    : decisionState.error;
  const refreshCME = () => {
    refetch();
    decisionState.refetch();
  };
  const emptyStateControls = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {availableDates.length > 0 ? (
        <label className="event-flow-filter-item">
          <span className="event-flow-filter-label">日期</span>
          <select
            aria-label="选择期权交易日"
            value={selectedDate ?? ""}
            onChange={(event) => setSelectedDate(event.target.value || undefined)}
            className="event-flow-filter-box cme-options-filter-box min-w-[104px]"
          >
            {availableDates.map((date) => <option key={date} value={date}>{date}</option>)}
          </select>
        </label>
      ) : null}
      <button type="button" onClick={refreshCME} className="fa-workspace-toolbar-button" title="重新读取 CME 期权结构">
        <RefreshCw size={12} />
        刷新
      </button>
    </div>
  );
  const tabOptions = [
    { value: "overview", label: "决策总览" },
    { value: "snapshot-overview", label: "结构总览" },
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
        <FACard title="期权结构" eyebrow="期权" accent="brand" action={emptyStateControls}>
          <div className="flex items-center gap-1.5">
            <FAStatusPill tone={sourceTone(source)}>{sourceLabel(source)}</FAStatusPill>
          </div>
        </FACard>
        <ErrorState title="加载期权结构失败" message={error?.message || "未知错误。请重试。"} onRetry={refetch} retryLabel="重试" />
      </div>
    );
  }

  if (isEmpty) {
    const unavailable = source === "unavailable";
    return (
      <div className={pageShellClass}>
        <FACard title="期权结构" eyebrow="期权" accent="brand" action={emptyStateControls}>
          <div className="flex items-center gap-1.5">
            <FAStatusPill tone={sourceTone(source)}>{sourceLabel(source)}</FAStatusPill>
          </div>
        </FACard>
        <FAEmptyState
          title={unavailable ? "期权数据接口不可用" : "该日期无期权数据"}
          description={snapshot?.error_reason || (unavailable ? "本次请求没有可展示的可信快照；页面未使用占位数据。" : "请切换日期，或检查预处理输出是否可用。")}
        />
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
              <button type="button" onClick={refreshCME} className="fa-workspace-toolbar-button" title="刷新 CME 期权结构">
                <RefreshCw size={12} />
                刷新
              </button>
            )}
            primaryLabel="数据状态"
            primaryItems={[

              { label: "请求日期", value: selectedDate ?? "最新" },
              { label: "CME报告日", value: snapshotReportDate ?? "—" },
              { label: "结构数据日期", value: snapshotTradeDate ?? "—" },
              { label: "决策交易日", value: decisionTradeDate ?? "—" },
              { label: "数据对应关系", value: decisionRevisionIdentity.status === "aligned" ? "来源已匹配" : decisionRevisionIdentity.status === "mismatch" ? "不一致" : "未核验" },
              ...(status ? [{ label: "公告", value: reportStatusLabel(status) }] : []),
              ...(factReviewStatus ? [{ label: "复核", value: reviewStatusLabel(factReviewStatus) }] : []),
              ...(alignedDecision ? [{ label: "决策", value: alignedDecision.status === "available" ? "可用" : alignedDecision.status === "partial" ? "部分可用" : "不可用" }] : dateIdentityMismatch ? [{ label: "决策", value: "日期不一致" }] : decisionRevisionMismatch ? [{ label: "决策", value: "快照不一致" }] : dateIdentityUnverified || decisionRevisionUnverified ? [{ label: "决策", value: "身份未核验" }] : []),
            ]}
            secondaryLabel="合约"
            secondaryItems={[
              { label: "行数", value: snapshot.data_source?.row_count?.toLocaleString("en-US") ?? "—" },
            ]}
          />

          {decisionState.data && decisionRevisionIdentity.status === "aligned" ? (
            <p className="text-[length:var(--type-body-sm)] leading-relaxed text-[var(--warn)]">
              已匹配来源记录；判断主快照身份未单独提供，完整版本一致性尚未确认。
            </p>
          ) : null}
          <details className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-3 py-2 text-[length:var(--type-caption)] text-[var(--fg-4)]">
            <summary className="cursor-pointer">查看快照身份与匹配依据</summary>
            <div className="mt-2 space-y-1 break-all">
              <p>结构数据身份：{snapshotIdentityIds.length > 0 ? "已登记，可核验" : "未提供"}</p>
              <p>研究判断来源：{decisionRevisionIdentity.decisionSnapshotIds.length > 0 ? "已登记，可核对" : "未提供"}</p>
              <p>判断主快照：后端未单独提供判断主快照身份。</p>
              <p>当前匹配结果：{decisionRevisionIdentity.status === "aligned" ? "当前仅核对来源记录，不能证明完整版本一致" : decisionRevisionIdentity.status === "mismatch" ? "版本不一致" : "尚无法核验"}</p>
              <EvidenceRecordActions
                label="快照与判断身份依据"
                record={{
                  structure_snapshot_id: snapshot?.snapshot_id ?? null,
                  structure_input_snapshot_ids: snapshot?.data_source?.input_snapshot_ids ?? [],
                  decision_source_snapshot_ids: decisionState.data?.source_refs?.map((item) => item.snapshot_id).filter(Boolean) ?? [],
                  trade_date: snapshotTradeDate,
                  report_date: snapshotReportDate,
                }}
              />
            </div>
          </details>

          <FAFilterBar
            className="cme-options-control-bar"
            left={
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                <CMEOptionsIntentSummary snapshot={snapshot} />
                {activeTab === "overview" ? null : <CMEOptionsKpiStrip snapshot={snapshot} decision={alignedDecision} />}
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
                      <option key={ex} value={ex}>{formatCMEExpiryLabel(ex)}</option>
                    ))}
                  </select>
                </div>
              </>
            }
          />
          {dateIdentityMessage || decisionRevisionMessage ? (
            <div className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-2)]">
              {dateIdentityMessage ? <div>{dateIdentityMessage}</div> : null}
              {decisionRevisionMessage ? <div>{decisionRevisionMessage}</div> : null}
            </div>
          ) : null}
        </div>
      )}
      bodyClassName="fa-page-stack"
    >
      <div className="px-1 pb-4">
        {snapshot && activeTab === "overview" ? (
          <div className="fa-page-stack">
            {decisionState.data ? <CMEOptionsDecisionWorkspace decision={alignedDecision} isLoading={decisionState.isLoading} error={decisionIdentityError} /> : <CMEOptionsDecisionWorkspace decision={null} isLoading={decisionState.isLoading} error={decisionIdentityError} />}
            {!alignedDecision ? <CMEOptionsOverviewGrid snapshot={snapshot} wallScores={wallScores} decision={alignedDecision} selectedExpiry={selectedExpiry} /> : null}
          </div>
        ) : snapshot ? renderCMEOptionsTabContent({ snapshot, activeTab, wallScores, selectedExpiry, decision: alignedDecision }) : null}
      </div>
    </FAPageScaffold>
  );
}
