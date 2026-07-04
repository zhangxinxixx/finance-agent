import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Calendar, Database, FileText, Layers, Newspaper } from "lucide-react";
import { ContextPanelSectionHeader } from "@/components/shared/ContextPanel";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getStatusLabel } from "@/components/shared/statusMeta";
import type { DashboardSummary } from "@/types/dashboard";
import type { Jin10CalendarEvent } from "@/hooks/useJin10Calendar";
import type { EventFlowLiveFlashItem } from "@/hooks/useEventFlowLiveFlash";
import {
  DashboardPanelCard,
  DashboardPanelEmptyState,
  DashboardPanelStack,
  compactPanelText,
  formatPanelDate,
  formatPanelTime,
} from "./DashboardRightPanelPrimitives";

function SectionActionLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="dashboard-right-action"
    >
      <span>{children}</span>
      <ArrowRight size={10} />
    </Link>
  );
}

function eventSignalText(item: EventFlowLiveFlashItem): string | null {
  const tags = item.signal_tags?.filter(Boolean).slice(0, 2) ?? [];
  return tags.length > 0 ? tags.join(" / ") : null;
}

function traceDateLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length >= 10 ? value.slice(0, 10) : value;
}

export function RealtimeFlashSection({
  items,
  overflowCount,
  isLoading,
  isError,
}: {
  items: EventFlowLiveFlashItem[];
  overflowCount: number;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <div className="dashboard-right-section">
      <ContextPanelSectionHeader
        icon={Newspaper}
        title="今日事件"
        meta={items.length > 0 ? `当日 Top ${items.length}` : isLoading ? "加载中" : "暂无"}
        className="dashboard-right-section-header mb-2"
      />
      <div className="mb-2 flex items-center justify-end">
        <SectionActionLink to="/event-flow">{overflowCount > 0 ? "查看更多" : "进入事件流"}</SectionActionLink>
      </div>
      <DashboardPanelStack>
        {items.length > 0 ? (
          items.map((item, i) => {
            const timeStr = formatPanelTime(item.time);
            const signalText = eventSignalText(item);
            return (
              <DashboardPanelCard
                key={item.id || i}
                className={i === 0 ? "dashboard-panel-card--primary" : ""}
              >
                <div className="dashboard-flash-row">
                  <span className={`fa-num dashboard-flash-time ${i === 0 ? "dashboard-flash-time--primary" : ""}`}>{timeStr}</span>
                  <div className="dashboard-flash-content" title={item.content}>
                    {compactPanelText(item.content, 62)}
                  </div>
                </div>
                {signalText ? (
                  <div className="dashboard-flash-signal" title={signalText}>
                    {signalText}
                  </div>
                ) : null}
              </DashboardPanelCard>
            );
          })
        ) : (
          <DashboardPanelEmptyState>
            {isError ? "今日事件暂不可用" : isLoading ? "当日重点事件加载中" : "暂无当日重点事件"}
          </DashboardPanelEmptyState>
        )}
      </DashboardPanelStack>
    </div>
  );
}

export function EconomicCalendarSection({
  events,
  visibleEvents,
  mode,
  overflowCount,
  isLoading,
  isError,
}: {
  events: Jin10CalendarEvent[];
  visibleEvents: Jin10CalendarEvent[];
  mode: "upcoming" | "recent";
  overflowCount: number;
  isLoading: boolean;
  isError: boolean;
}) {
  const metaText = events.length > 0
    ? mode === "upcoming"
      ? `未来7天 ${visibleEvents.length} / ${events.length}`
      : `最近已公布 ${visibleEvents.length} / ${events.length}`
    : isLoading
      ? "加载中"
      : "暂无";

  return (
    <div className="dashboard-right-section">
      <ContextPanelSectionHeader
        icon={Calendar}
        title="宏观日历"
        meta={metaText}
        className="dashboard-right-section-header mb-2"
      />
      <div className="mb-2 flex items-center justify-end">
        <SectionActionLink to="/market-monitor?tab=calendar">{overflowCount > 0 ? `查看更多 ${overflowCount} 条` : "进入市场监控"}</SectionActionLink>
      </div>
      <DashboardPanelStack>
        {events.length > 0 ? (
          visibleEvents.map((ev, i) => {
            const hasReleasedValue = ev.actual !== null && ev.actual !== "";
            const isFuture = !hasReleasedValue;
            const stars = "★".repeat(Math.min(ev.star ?? 0, 4));
            const dateStr = formatPanelDate(ev.pub_time);
            const timeStr = formatPanelTime(ev.pub_time);
            const impactColor = ev.affect_txt === "利多" ? "var(--up)" : ev.affect_txt === "利空" ? "var(--down)" : "var(--fg-5)";
            const statusLabel = isFuture ? "未公布" : (ev.affect_txt || "已公布");
            const statusClass = isFuture ? "dashboard-calendar-status--future" : "";
            return (
              <DashboardPanelCard
                key={`${ev.pub_time}-${ev.title}-${i}`}
                className={isFuture ? "dashboard-panel-card--future" : ""}
              >
                <div className="dashboard-calendar-row">
                  <span className="fa-num dashboard-calendar-time">{dateStr} {timeStr}</span>
                  <span className={`dashboard-calendar-title ${isFuture ? "dashboard-calendar-title--future" : ""}`} title={ev.title}>
                    {stars} {ev.title}
                  </span>
                  <span className={`dashboard-calendar-status ${statusClass}`} style={{ color: isFuture ? undefined : impactColor }}>
                    {statusLabel}
                  </span>
                </div>
              </DashboardPanelCard>
            );
          })
        ) : (
          <DashboardPanelEmptyState className="dashboard-panel-empty-state--flat">
            {isError ? "宏观日历暂不可用" : isLoading ? "重点日历加载中" : "暂无重点宏观事件"}
          </DashboardPanelEmptyState>
        )}
      </DashboardPanelStack>
    </div>
  );
}

export function DataTraceSection({ sourceTrace }: { sourceTrace: DashboardSummary["source_trace"] }) {
  const visibleTrace = sourceTrace.slice(0, 4);
  if (visibleTrace.length === 0) return null;

  return (
    <div className="dashboard-right-section">
      <ContextPanelSectionHeader
        icon={Database}
        title="数据状态"
        meta={`${visibleTrace.length} / ${sourceTrace.length}`}
        className="dashboard-right-section-header mb-2"
      />
      <DashboardPanelStack>
        {visibleTrace.map((trace, i) => (
          <DashboardPanelCard key={`${trace.source_ref}-${trace.snapshot_id ?? i}`} className="dashboard-trace-card">
            <div className="dashboard-trace-row">
              <div className="min-w-0">
                <div className="dashboard-trace-name">{trace.name || trace.source_ref}</div>
                <div className="dashboard-trace-meta">
                  {traceDateLabel(trace.trade_date)}
                  {trace.snapshot_id ? <span>#{trace.snapshot_id.slice(0, 6)}</span> : null}
                </div>
              </div>
              <FAStatusPill status={trace.status} domain="source" dot={false} className="dashboard-trace-status">
                {getStatusLabel(trace.status, "source")}
              </FAStatusPill>
            </div>
          </DashboardPanelCard>
        ))}
      </DashboardPanelStack>
    </div>
  );
}

function isOptionsReport(report: DashboardSummary["latest_reports"][number]): boolean {
  const text = `${report.type ?? ""} ${report.family ?? ""} ${report.title ?? ""}`.toLowerCase();
  return text.includes("cme") || text.includes("option") || text.includes("期权");
}

function isIntegratedReport(report: DashboardSummary["latest_reports"][number]): boolean {
  if (isOptionsReport(report)) return false;
  const text = `${report.type ?? ""} ${report.family ?? ""} ${report.title ?? ""}`.toLowerCase();
  return text.includes("final_report") || text.includes("strategy") || text.includes("macro") || text.includes("综合") || text.includes("日报");
}

function reportHref(report: DashboardSummary["latest_reports"][number]): string {
  if (report.url) return report.url;
  if (report.report_id) return `/reports/${encodeURIComponent(report.report_id)}`;
  return "/reports";
}

function ReportRows({ reports }: { reports: DashboardSummary["latest_reports"] }) {
  return (
    <DashboardPanelStack>
      {reports.length > 0 ? (
        reports.map((report, index) => (
          <DashboardPanelCard key={`${report.family ?? report.type ?? "report"}-${report.trade_date}-${index}`}>
            <Link to={reportHref(report)} className="dashboard-report-row" title={report.title}>
              <span className="dashboard-report-title">{report.title}</span>
              <span className="fa-num dashboard-report-date">{report.trade_date}</span>
            </Link>
          </DashboardPanelCard>
        ))
      ) : (
        <DashboardPanelEmptyState className="dashboard-panel-empty-state--flat">
          暂无可读报告
        </DashboardPanelEmptyState>
      )}
    </DashboardPanelStack>
  );
}

export function LatestSupplementalReportSection({ report }: { report: DashboardSummary["latest_supplemental_report"] }) {
  if (!report) return null;
  const meta = report.anchor_trade_date ? `锚定 ${report.anchor_trade_date}` : "补充分析";

  return (
    <div className="dashboard-right-section">
      <ContextPanelSectionHeader
        icon={FileText}
        title="宏观事件补充"
        meta={meta}
        className="dashboard-right-section-header mb-2"
      />
      <DashboardPanelStack>
        <DashboardPanelCard>
          <Link to={reportHref(report)} className="dashboard-report-row" title={report.title}>
            <span className="dashboard-report-title">{report.title}</span>
            <span className="fa-num dashboard-report-date">{report.trade_date}</span>
          </Link>
          {report.summary ? (
            <div className="mt-1 text-[10px] leading-4 text-[var(--fg-5)]">
              {compactPanelText(report.summary, 80)}
            </div>
          ) : null}
        </DashboardPanelCard>
      </DashboardPanelStack>
    </div>
  );
}

export function LatestIntegratedReportSection({ reports }: { reports: DashboardSummary["latest_reports"] }) {
  const readyReports = reports.filter((report) => report.status === "ready" && isIntegratedReport(report)).slice(0, 2);

  return (
    <div className="dashboard-right-section">
      <ContextPanelSectionHeader
        icon={FileText}
        title="最新综合报告"
        meta={readyReports.length > 0 ? `${readyReports.length} 份可读` : "暂无"}
        className="dashboard-right-section-header mb-2"
      />
      <ReportRows reports={readyReports} />
    </div>
  );
}

export function LatestOptionsReportSection({ reports }: { reports: DashboardSummary["latest_reports"] }) {
  const readyReports = reports.filter((report) => report.status === "ready" && isOptionsReport(report)).slice(0, 2);

  return (
    <div className="dashboard-right-section">
      <ContextPanelSectionHeader
        icon={Layers}
        title="最新期权报告"
        meta={readyReports.length > 0 ? `${readyReports.length} 份可读` : "暂无"}
        className="dashboard-right-section-header mb-2"
      />
      <ReportRows reports={readyReports} />
    </div>
  );
}
