import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function source(relativePath) {
  return readFileSync(join(__dirname, "..", relativePath), "utf8");
}

const adapter = source("src/adapters/agentTasks.ts");
const hook = source("src/hooks/useReviewCenter.ts");
const sections = source("src/components/review-center/ReviewCenterSections.tsx");
const page = source("src/pages/ReviewCenterPage.tsx");

for (const action of ["approve", "reject", "rerun", "use-fallback"]) {
  assert.match(adapter, new RegExp(`${action}: "${action}"|"${action}": "${action}"`), `adapter missing ${action} endpoint mapping`);
}

assert.match(adapter, /export type ReviewActionKind/, "adapter must export ReviewActionKind");
assert.match(adapter, /export async function resolveReviewCenterReview/, "adapter must export resolveReviewCenterReview");
assert.match(adapter, /method: "POST"/, "adapter review action must POST");
assert.match(hook, /resolveReview:/, "hook must expose resolveReview");
assert.match(hook, /actionReviewId:/, "hook must expose actionReviewId");
assert.match(hook, /actionError:/, "hook must expose actionError");
assert.match(sections, /onAction\??:/, "ReviewCard must accept an onAction callback");
assert.match(sections, /采用备用结果/, "ReviewCard must render a use-fallback action");
assert.match(sections, /重新运行/, "ReviewCard must render a rerun action");
assert.match(sections, /通过/, "ReviewCard must render an approve action");
assert.match(sections, /驳回/, "ReviewCard must render a reject action");
assert.match(page, /onAction={reviewCenter\.resolveReview}/, "ReviewCenterPage must pass resolveReview into ReviewCard");

console.log("Review Center action contract OK");
