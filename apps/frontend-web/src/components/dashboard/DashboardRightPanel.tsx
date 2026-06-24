import type { DashboardSummary } from "@/types/dashboard";
import { ContextPanelShell } from "@/components/shared/ContextPanel";
import { useJin10Calendar } from "@/hooks/useJin10Calendar";
import { useEventFlowLiveFlash } from "@/hooks/useEventFlowLiveFlash";
import { buildDashboardRightPanelModel } from "./DashboardRightPanelModel";
import { EconomicCalendarSection, RealtimeFlashSection } from "./DashboardRightPanelSections";

interface DashboardRightPanelProps {
  summary: DashboardSummary;
}

export function DashboardRightPanel({ summary: _summary }: DashboardRightPanelProps) {
  const calendar = useJin10Calendar();
  const flash = useEventFlowLiveFlash(50);

  const { sortedEvents, visibleEvents, calendarMode, visibleFlash, flashOverflowCount, eventOverflowCount } =
    buildDashboardRightPanelModel({
      calendarEvents: calendar.data,
      flashItems: flash.data,
    });

  return (
    <ContextPanelShell>
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
    </ContextPanelShell>
  );
}
