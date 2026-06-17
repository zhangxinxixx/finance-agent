import type { EventImpact } from "@/types/event-flow";

export function getImpactLabel(impact: EventImpact): string {
  if (impact === "利多黄金") return "利多";
  if (impact === "利空黄金") return "利空";
  return impact;
}
