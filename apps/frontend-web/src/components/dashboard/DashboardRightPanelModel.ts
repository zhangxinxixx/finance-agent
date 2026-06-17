import type { Jin10CalendarEvent } from "@/hooks/useJin10Calendar";
import type { Jin10FlashItem } from "@/hooks/useJin10Flash";

interface DashboardRightPanelInput {
  calendarEvents: Jin10CalendarEvent[];
  flashItems: Jin10FlashItem[];
}

export interface DashboardRightPanelModel {
  sortedEvents: Jin10CalendarEvent[];
  visibleEvents: Jin10CalendarEvent[];
  visibleFlash: Jin10FlashItem[];
  flashOverflowCount: number;
  eventOverflowCount: number;
}

function getTodayCalendarDateKey(date = new Date()): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function sortDashboardCalendarEvents(
  events: Jin10CalendarEvent[],
  todayStr = getTodayCalendarDateKey(),
): Jin10CalendarEvent[] {
  return [...events].sort((a, b) => {
    const da = a.pub_time?.slice(0, 10) ?? "";
    const db = b.pub_time?.slice(0, 10) ?? "";
    const aFuture = da >= todayStr;
    const bFuture = db >= todayStr;
    if (aFuture && !bFuture) return -1;
    if (!aFuture && bFuture) return 1;
    return da < db ? 1 : da > db ? -1 : 0;
  });
}

function isKeyFlashItem(item: Jin10FlashItem): boolean {
  return item.is_key_event === true;
}

function filterKeyFlashItems(items: Jin10FlashItem[]): Jin10FlashItem[] {
  return items.filter(isKeyFlashItem);
}

export function buildDashboardRightPanelModel({
  calendarEvents,
  flashItems,
}: DashboardRightPanelInput): DashboardRightPanelModel {
  const highImpactEvents = calendarEvents.filter((event) => (event.star ?? 0) >= 3);
  const sortedEvents = sortDashboardCalendarEvents(highImpactEvents);
  const visibleEvents = sortedEvents.slice(0, 3);
  const filteredFlashItems = filterKeyFlashItems(flashItems);
  const visibleFlash = filteredFlashItems.slice(0, 3);

  return {
    sortedEvents,
    visibleEvents,
    visibleFlash,
    flashOverflowCount: Math.max(0, filteredFlashItems.length - visibleFlash.length),
    eventOverflowCount: Math.max(0, sortedEvents.length - visibleEvents.length),
  };
}
