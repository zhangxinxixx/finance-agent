import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function source(relativePath) {
  return readFileSync(join(__dirname, "..", relativePath), "utf8");
}

const adapter = source("src/adapters/agentTasks.ts");
const orchestrationAdapter = source("src/adapters/orchestration.ts");
const systemEvolutionAdapter = source("src/adapters/systemEvolution.ts");
const promptEvolutionAdapter = source("src/adapters/promptEvolution.ts");
const promptEvolutionTypes = source("src/types/prompt-evolution.ts");
const hook = source("src/hooks/useReviewCenter.ts");
const orchestrationHook = source("src/hooks/useOrchestrationManualReview.ts");
const systemEvolutionHook = source("src/hooks/useSystemEvolutionReview.ts");
const promptEvolutionHook = source("src/hooks/usePromptEvolutionReview.ts");
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

assert.match(orchestrationAdapter, /\/api\/orchestration\/manual-review/, "orchestration adapter must read manual-review items");
assert.match(orchestrationAdapter, /\/api\/orchestration\/manual-review\/action/, "orchestration adapter must post manual-review actions");
for (const action of ["acknowledged", "resolved", "dismissed"]) {
  assert.match(orchestrationAdapter, new RegExp(action), `orchestration adapter missing ${action} action`);
}
assert.match(orchestrationHook, /submitAction:/, "orchestration manual-review hook must expose submitAction");
assert.match(sections, /OrchestrationManualReviewCard/, "Review Center sections must render orchestration manual-review cards");
assert.match(sections, /确认关注/, "orchestration card must render acknowledged action");
assert.match(sections, /标记解决/, "orchestration card must render resolved action");
assert.match(sections, /忽略/, "orchestration card must render dismissed action");
assert.match(page, /useOrchestrationManualReview/, "ReviewCenterPage must load orchestration manual-review items");
assert.match(page, /OrchestrationManualReviewCard/, "ReviewCenterPage must render orchestration manual-review cards");

assert.match(systemEvolutionAdapter, /\/api\/governance\/system-evolution\/latest/, "system evolution adapter must read latest governance review");
assert.match(systemEvolutionAdapter, /\/api\/governance\/system-evolution\/proposal\/action/, "system evolution adapter must post proposal actions");
assert.match(systemEvolutionAdapter, /export async function fetchSystemEvolutionReview/, "system evolution adapter must export fetchSystemEvolutionReview");
assert.match(systemEvolutionAdapter, /export async function submitSystemEvolutionProposalAction/, "system evolution adapter must export submitSystemEvolutionProposalAction");
for (const action of ["approve", "reject", "link_issue", "link_pr", "mark_implemented", "mark_rolled_back"]) {
  assert.match(systemEvolutionAdapter, new RegExp(action), `system evolution adapter missing ${action} action`);
}
assert.match(systemEvolutionHook, /fetchSystemEvolutionReview/, "system evolution hook must load latest governance review");
assert.match(systemEvolutionHook, /useSystemEvolutionReview/, "system evolution hook must export useSystemEvolutionReview");
assert.match(systemEvolutionHook, /submitProposalAction:/, "system evolution hook must expose submitProposalAction");
assert.match(sections, /SystemEvolutionProposalCard/, "Review Center sections must render SystemEvolution proposals");
assert.match(sections, /SystemEvolution 提案/, "SystemEvolution card must label governance proposals");
assert.match(sections, /批准/, "SystemEvolution card must render approve action");
assert.match(sections, /拒绝/, "SystemEvolution card must render reject action");
assert.match(sections, /关联 Issue/, "SystemEvolution card must render link issue action");
assert.match(sections, /关联 PR/, "SystemEvolution card must render link PR action");
assert.match(sections, /标记已实施/, "SystemEvolution card must render implemented action");
assert.match(sections, /标记回滚/, "SystemEvolution card must render rolled back action");
assert.match(page, /useSystemEvolutionReview/, "ReviewCenterPage must load SystemEvolution governance review");
assert.match(page, /SystemEvolutionProposalCard/, "ReviewCenterPage must render SystemEvolution governance proposals");
assert.match(page, /onProposalAction={systemEvolution\.submitProposalAction}/, "ReviewCenterPage must pass SystemEvolution proposal action handler");

assert.match(promptEvolutionAdapter, /\/api\/governance\/prompt-evolution\/latest/, "prompt evolution adapter must read latest validation artifacts");
assert.match(promptEvolutionAdapter, /\/api\/governance\/prompt-evolution\/release\/action/, "prompt evolution adapter must post release actions");
assert.match(promptEvolutionAdapter, /export async function fetchPromptEvolutionReview/, "prompt evolution adapter must export fetchPromptEvolutionReview");
assert.match(promptEvolutionAdapter, /export async function submitPromptEvolutionReleaseAction/, "prompt evolution adapter must export submitPromptEvolutionReleaseAction");
assert.match(promptEvolutionHook, /fetchPromptEvolutionReview/, "prompt evolution hook must load validation artifacts");
assert.match(promptEvolutionHook, /usePromptEvolutionReview/, "prompt evolution hook must export usePromptEvolutionReview");
assert.match(promptEvolutionHook, /submitReleaseAction:/, "prompt evolution hook must expose submitReleaseAction");
assert.match(promptEvolutionHook, /release_readiness/, "prompt evolution hook must consume release_readiness");
assert.match(promptEvolutionTypes, /rolled_back_from\??:/, "prompt evolution release record type must include rolled_back_from");
assert.match(promptEvolutionTypes, /rolled_back_to\??:/, "prompt evolution release record type must include rolled_back_to");
assert.match(promptEvolutionTypes, /affected_agents\??:/, "prompt evolution release record type must include affected_agents");
assert.match(sections, /PromptEvolutionValidationCard/, "Review Center sections must render PromptEvolution validation artifacts");
assert.match(sections, /A\/B 验证/, "PromptEvolution validation card must label A/B validation");
assert.match(sections, /发布状态/, "PromptEvolution validation card must render release readiness status");
assert.match(sections, /can_request_release_approval/, "PromptEvolution validation card must gate release approval by readiness");
assert.match(sections, /can_record_rollback/, "PromptEvolution validation card must gate rollback by readiness");
assert.match(sections, /发布记录/, "PromptEvolution validation card must render release records");
assert.match(sections, /rolled_back_from/, "PromptEvolution validation card must render rollback source prompt");
assert.match(sections, /rolled_back_to/, "PromptEvolution validation card must render rollback target prompt");
assert.match(sections, /affected_agents/, "PromptEvolution validation card must render affected agents");
assert.match(sections, /记录发布批准/, "PromptEvolution validation card must render release approval action");
assert.match(sections, /记录回滚/, "PromptEvolution validation card must render rollback action");
assert.match(page, /usePromptEvolutionReview/, "ReviewCenterPage must load PromptEvolution validation artifacts");
assert.match(page, /PromptEvolutionValidationCard/, "ReviewCenterPage must render PromptEvolution validation artifacts");
assert.match(page, /onReleaseAction={promptEvolutionReview\.submitReleaseAction}/, "ReviewCenterPage must pass PromptEvolution release action handler");

console.log("Review Center action contract OK");
