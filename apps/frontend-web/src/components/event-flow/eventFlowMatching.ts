import type { EventFlowTimelineItem, Jin10ArticleBrief } from "@/types/event-flow";

function normalizeText(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, " ").trim();
}

function tokenize(value: string): string[] {
  return normalizeText(value)
    .split(/\s+/)
    .filter((item) => item.length >= 2);
}

function eventTokenSet(event: EventFlowTimelineItem): Set<string> {
  return new Set(
    tokenize([
      event.title,
      event.desc,
      event.source ?? "",
      event.assets ?? "",
      event.raw_event_type ?? "",
      event.event_kind ?? "",
    ].join(" ")),
  );
}

export function matchBriefScore(eventTokens: Set<string>, brief: Jin10ArticleBrief): number {
  const haystack = tokenize([
    brief.headline,
    brief.original_excerpt,
    brief.analysis_summary,
    ...brief.key_points,
    ...brief.asset_tags,
    ...brief.topic_tags,
  ].join(" "));

  let score = 0;
  for (const token of haystack) {
    if (eventTokens.has(token)) score += 1;
  }
  if ((brief.display_bucket || "").includes("快讯")) score += 1;
  if (brief.access_status === "readable") score += 1;
  return score;
}

export function findRelatedBriefs(
  event: EventFlowTimelineItem | null,
  briefs: Jin10ArticleBrief[] | null | undefined,
): Jin10ArticleBrief[] {
  if (!event) return [];
  if (!briefs?.length) return [];
  const tokens = eventTokenSet(event);
  const scored = briefs
    .map((brief) => ({ brief, score: matchBriefScore(tokens, brief) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score);
  return (scored.length > 0 ? scored.map((item) => item.brief) : briefs).slice(0, 4);
}

export function findBestEventIdForBrief(
  brief: Jin10ArticleBrief,
  events: EventFlowTimelineItem[],
): string | null {
  if (!events.length) return null;

  const scored = events
    .map((event) => ({
      eventId: event.id,
      score: matchBriefScore(eventTokenSet(event), brief),
    }))
    .sort((a, b) => b.score - a.score);

  if (scored[0] && scored[0].score > 0) return scored[0].eventId;
  return null;
}
