import type { EventFlowTimelineItem } from "@/types/event-flow";

const FULL_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T\s])/;
const MONTH_DAY_PATTERN = /^(\d{2})-(\d{2})$/;

function currentBusinessDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function fullDateParts(value: string): { date: string; year: string } | null {
  const match = value.trim().match(FULL_DATE_PATTERN);
  if (!match) return null;
  return { date: `${match[1]}-${match[2]}-${match[3]}`, year: match[1] };
}

function monthDayParts(value: string): { month: string; day: string } | null {
  const match = value.trim().match(MONTH_DAY_PATTERN);
  if (!match) return null;
  return { month: match[1], day: match[2] };
}

function sourceRefDateValues(event: EventFlowTimelineItem): string[] {
  return (event.source_refs ?? []).flatMap((ref) => [ref.trade_date, ref.dataDate, ref.asOf, ref.generated_at])
    .filter((value): value is string => Boolean(value));
}

/**
 * Return report-matching dates without inventing a calendar year.
 *
 * Explicit event dates win. For an MM-DD event, use the year from the event's
 * own full date first, then source/bundle dates supplied by the caller, and
 * finally the browser's current business date as the last-resort fallback.
 */
export function normalizeEventDateCandidates(
  event: EventFlowTimelineItem,
  fallbackDates: readonly string[] = [],
): string[] {
  const eventValues = [event.date, event.time].filter((item): item is string => Boolean(item)).map((item) => item.trim());
  const explicitDates = eventValues.map(fullDateParts).filter((item): item is { date: string; year: string } => Boolean(item));
  const fallbackValues = [...fallbackDates, ...sourceRefDateValues(event)];
  const fallbackDatesWithYears = fallbackValues.map(fullDateParts).filter((item): item is { date: string; year: string } => Boolean(item));
  const years = Array.from(new Set((explicitDates.length > 0 ? explicitDates : fallbackDatesWithYears).map((item) => item.year)));
  if (years.length === 0) {
    years.push(fullDateParts(currentBusinessDate())?.year ?? String(new Date().getFullYear()));
  }

  const result = new Set(explicitDates.map((item) => item.date));
  for (const value of eventValues) {
    const monthDay = monthDayParts(value);
    if (!monthDay) continue;
    for (const year of years) result.add(`${year}-${monthDay.month}-${monthDay.day}`);
  }
  return Array.from(result);
}
