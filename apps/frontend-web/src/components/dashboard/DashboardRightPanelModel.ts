import type { Jin10CalendarEvent } from "@/hooks/useJin10Calendar";
import type { EventFlowLiveFlashItem } from "@/hooks/useEventFlowLiveFlash";

interface DashboardRightPanelInput {
  calendarEvents: Jin10CalendarEvent[];
  flashItems: EventFlowLiveFlashItem[];
}

const RIGHT_PANEL_TOP_LIMIT = 5;
const CALENDAR_LOOKAHEAD_DAYS = 7;

export interface DashboardRightPanelModel {
  sortedEvents: Jin10CalendarEvent[];
  visibleEvents: Jin10CalendarEvent[];
  calendarMode: "upcoming" | "recent";
  visibleFlash: EventFlowLiveFlashItem[];
  flashOverflowCount: number;
  eventOverflowCount: number;
}

function getTodayCalendarDateKey(date = new Date()): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function addDays(dateKey: string, days: number): string {
  const date = new Date(`${dateKey}T00:00:00`);
  if (Number.isNaN(date.getTime())) return dateKey;
  date.setDate(date.getDate() + days);
  return getTodayCalendarDateKey(date);
}

function eventDateKey(event: Jin10CalendarEvent): string {
  return event.pub_time?.slice(0, 10) ?? "";
}

function eventTimestamp(event: Jin10CalendarEvent): number {
  const value = event.pub_time ? new Date(event.pub_time).getTime() : Number.NaN;
  return Number.isNaN(value) ? 0 : value;
}

function macroPriorityScore(event: Jin10CalendarEvent): number {
  const title = (event.title ?? "").toLowerCase();

  if (title.includes("美联储利率决定") || title.includes("央行利率决定")) return 100;
  if (title.includes("非农")) return 95;
  if (title.includes("核心pce") || title.includes("pce")) return 92;
  if (title.includes("cpi")) return 90;
  if (title.includes("初请失业金")) return 86;
  if (title.includes("失业率")) return 82;
  if (title.includes("零售销售")) return 78;
  if (title.includes("制造业") || title.includes("pmi")) return 72;
  if (title.includes("eia原油库存")) return 58;
  if (title.includes("api原油库存")) return 52;
  if (title.includes("原油库存")) return 50;
  return event.is_high_impact ? 40 : Math.min(event.star ?? 0, 5) * 6;
}

function isFutureWindowEvent(event: Jin10CalendarEvent, todayStr: string, maxDateStr: string): boolean {
  const dateKey = eventDateKey(event);
  return dateKey >= todayStr && dateKey <= maxDateStr;
}

export function sortDashboardCalendarEvents(
  events: Jin10CalendarEvent[],
  todayStr = getTodayCalendarDateKey(),
): Jin10CalendarEvent[] {
  const maxDateStr = addDays(todayStr, CALENDAR_LOOKAHEAD_DAYS);
  return [...events].sort((a, b) => {
    const da = eventDateKey(a);
    const db = eventDateKey(b);
    const aInWindow = isFutureWindowEvent(a, todayStr, maxDateStr);
    const bInWindow = isFutureWindowEvent(b, todayStr, maxDateStr);
    if (aInWindow && !bInWindow) return -1;
    if (!aInWindow && bInWindow) return 1;

    const aFuture = da >= todayStr;
    const bFuture = db >= todayStr;
    if (aFuture && !bFuture) return -1;
    if (!aFuture && bFuture) return 1;

    if (aFuture && bFuture) {
      const scoreDelta = macroPriorityScore(b) - macroPriorityScore(a);
      if (scoreDelta !== 0) return scoreDelta;
      const timeDelta = eventTimestamp(a) - eventTimestamp(b);
      if (timeDelta !== 0) return timeDelta;
    } else {
      const scoreDelta = macroPriorityScore(b) - macroPriorityScore(a);
      if (scoreDelta !== 0) return scoreDelta;
      const timeDelta = eventTimestamp(b) - eventTimestamp(a);
      if (timeDelta !== 0) return timeDelta;
    }

    return (b.star ?? 0) - (a.star ?? 0);
  });
}

function filterPriorityCalendarEvents(
  events: Jin10CalendarEvent[],
  todayStr = getTodayCalendarDateKey(),
): Jin10CalendarEvent[] {
  const maxDateStr = addDays(todayStr, CALENDAR_LOOKAHEAD_DAYS);
  const highImpactEvents = events.filter((event) => (event.is_high_impact === true) || (event.star ?? 0) >= 4);
  const upcomingEvents = highImpactEvents.filter((event) => isFutureWindowEvent(event, todayStr, maxDateStr));
  if (upcomingEvents.length > 0) {
    return upcomingEvents;
  }
  return highImpactEvents;
}

function isKeyFlashItem(item: EventFlowLiveFlashItem): boolean {
  const importance = String(item.importance ?? "").trim().toLowerCase();
  return item.is_key_event === true && (importance === "high" || importance === "高");
}

function filterKeyFlashItems(items: EventFlowLiveFlashItem[]): EventFlowLiveFlashItem[] {
  return items.filter(isKeyFlashItem);
}

export function buildDashboardRightPanelModel({
  calendarEvents,
  flashItems,
}: DashboardRightPanelInput): DashboardRightPanelModel {
  const priorityEvents = filterPriorityCalendarEvents(calendarEvents);
  const sortedEvents = sortDashboardCalendarEvents(priorityEvents);
  const visibleEvents = sortedEvents.slice(0, RIGHT_PANEL_TOP_LIMIT);
  const calendarMode = visibleEvents.some((event) => event.release_state === "upcoming") ? "upcoming" : "recent";
  const filteredFlashItems = filterKeyFlashItems(flashItems);
  const visibleFlash = filteredFlashItems.slice(0, RIGHT_PANEL_TOP_LIMIT);

  return {
    sortedEvents,
    visibleEvents,
    calendarMode,
    visibleFlash,
    flashOverflowCount: Math.max(0, filteredFlashItems.length - visibleFlash.length),
    eventOverflowCount: Math.max(0, sortedEvents.length - visibleEvents.length),
  };
}
