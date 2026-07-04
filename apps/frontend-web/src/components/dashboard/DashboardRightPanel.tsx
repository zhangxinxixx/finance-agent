import type { DashboardSummary } from "@/types/dashboard";
import { ContextPanelShell } from "@/components/shared/ContextPanel";
import { useJin10Calendar } from "@/hooks/useJin10Calendar";
import { useEventFlowLiveFlash } from "@/hooks/useEventFlowLiveFlash";
import { buildDashboardRightPanelModel } from "./DashboardRightPanelModel";
import {
  DataTraceSection,
  EconomicCalendarSection,
  LatestIntegratedReportSection,
  LatestOptionsReportSection,
  LatestSupplementalReportSection,
  RealtimeFlashSection,
} from "./DashboardRightPanelSections";
import { GoldMacroOverviewPanel } from "./GoldMacroOverviewPanel";

interface DashboardRightPanelProps {
  summary: DashboardSummary;
}

export function DashboardRightPanel({ summary }: DashboardRightPanelProps) {
  const calendar = useJin10Calendar();
  const flash = useEventFlowLiveFlash(50);

  const { sortedEvents, visibleEvents, calendarMode, visibleFlash, flashOverflowCount, eventOverflowCount } =
    buildDashboardRightPanelModel({
      calendarEvents: calendar.data,
      flashItems: flash.data,
    });

  return (
    <ContextPanelShell className="dashboard-right-panel">
      <div className="dashboard-right-panel-header">
        <div>
          <div className="dashboard-right-panel-title">研究上下文</div>
        </div>
        <div className="dashboard-right-panel-meta">{summary.source_trace.length} 条数据链路</div>
      </div>
      <GoldMacroOverviewPanel overview={summary.gold_macro_overview} />
      <RealtimeFlashSection
        items={visibleFlash}
        overflowCount={flashOverflowCount}
        isLoading={flash.isLoading}
        isError={flash.isError}
      />
      <EconomicCalendarSection
        events={sortedEvents}
        visibleEvents={visibleEvents}
        mode={calendarMode}
        overflowCount={eventOverflowCount}
        isLoading={calendar.isLoading}
        isError={calendar.isError}
      />
      <DataTraceSection sourceTrace={summary.source_trace} />
      <LatestSupplementalReportSection report={summary.latest_supplemental_report} />
      <LatestIntegratedReportSection reports={summary.latest_reports} />
      <LatestOptionsReportSection reports={summary.latest_reports} />
    </ContextPanelShell>
  );
}
