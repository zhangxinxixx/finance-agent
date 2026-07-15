import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const page = readFileSync(resolve("src/pages/EventFlowDetailPage.tsx"), "utf8");
const helper = readFileSync(resolve("src/components/event-flow/eventFlowDate.ts"), "utf8");

if (page.includes("2026-") || helper.includes("2026-")) {
  throw new Error("Event Flow date contract failed: date resolution contains a hardcoded calendar year");
}
for (const expected of ["fallbackDates", "sourceRefDateValues", "currentBusinessDate", "fullDateParts"]) {
  if (!helper.includes(expected)) {
    throw new Error(`Event Flow date contract failed: missing ${expected} fallback path`);
  }
}
if (!page.includes("data?.article_briefs?.date")) {
  throw new Error("Event Flow date contract failed: bundle date is not passed to report matching");
}
