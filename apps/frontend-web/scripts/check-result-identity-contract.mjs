import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = (relativePath) => readFileSync(join(root, relativePath), "utf8");

const identityTypes = source("src/types/result-identity.ts");
const identityAdapter = source("src/adapters/resultIdentity.ts");
const identityBar = source("src/components/shared/ResultIdentityBar.tsx");
const reportsAdapter = source("src/adapters/reports.ts");
const goldAdapter = source("src/adapters/goldMainlines.ts");
const liveAdapter = source("src/adapters/liveStrategy.ts");
const reportPage = source("src/pages/ReportDetailPage.tsx");
const reportsPage = source("src/pages/ReportsPage.tsx");
const goldPage = source("src/pages/GoldMainlinesPage.tsx");
const strategyPage = source("src/pages/StrategyPage.tsx");
const liveTypes = source("src/types/live-strategy.ts");
const reportTypes = source("src/types/reports.ts");

function moduleUrl(relativePath) {
  const output = ts.transpileModule(source(relativePath), {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      verbatimModuleSyntax: false,
    },
  }).outputText;
  return `data:text/javascript;base64,${Buffer.from(output, "utf8").toString("base64")}`;
}

const [{ normalizeResultIdentity }, { isKnownResultIdentity }] = await Promise.all([
  import(moduleUrl("src/adapters/resultIdentity.ts")),
  import(moduleUrl("src/types/result-identity.ts")),
]);

const subject = {
  kind: "gold_daily_close_result",
  run_id: "run-result-01",
  premarket_snapshot_id: "premarket-01",
  feature_snapshot_id: "feature-01",
  result_id: "result-01",
  state_id: "state-01",
  strategy_id: "strategy-01",
  receipt_id: "receipt-01",
  bundle_ref: "bundle-01",
  verification_status: "verified",
  reason_code: null,
};
const normalized = normalizeResultIdentity({
  schema_version: "gold_result_identity.v1",
  subject,
  effective_baseline: {
    ...subject,
    result_id: "baseline-result-01",
    held: true,
    status: "accepted",
    authority_ready: true,
    quality_status: "verified",
    strategy_status: "NO_TRADE",
    decision_as_of: "2026-09-05T00:00:00Z",
  },
  relationship: { status: "same_effective_head", reason_code: null },
});
assert.equal(normalized.subject.result_id, "result-01", "subject result ID must be preserved");
assert.equal(normalized.effective_baseline.result_id, "baseline-result-01", "baseline result ID must remain a separate object");
assert.equal(normalized.effective_baseline.held, true, "HOLD must be preserved without rewriting status");
assert.equal(normalized.effective_baseline.status, "accepted", "HOLD must not rewrite the baseline status code");
assert.equal(normalized.effective_baseline.strategy_status, "NO_TRADE", "baseline strategy status must be preserved");
assert.equal(normalized.relationship.status, "same_effective_head", "known relationship status must be preserved");
assert.equal(normalizeResultIdentity(null), null, "missing identity must remain unavailable");
const unknownSchema = normalizeResultIdentity({
  schema_version: "gold_result_identity.v9",
  subject,
  effective_baseline: null,
  relationship: { status: "same_effective_head", reason_code: null },
});
assert.equal(isKnownResultIdentity(unknownSchema), false, "unknown identity schema must not be treated as verified");
assert.equal(isKnownResultIdentity(normalized), true, "known identity schema must be recognized");
const malformed = normalizeResultIdentity({
  schema_version: "gold_result_identity.v1",
  subject,
  effective_baseline: { ...subject, held: "true", authority_ready: 1 },
  relationship: { status: "future_status", reason_code: "unknown" },
});
assert.equal(malformed.effective_baseline.held, false, "malformed boolean must fail closed");
assert.equal(malformed.effective_baseline.authority_ready, false, "malformed authority flag must fail closed");
assert.equal(malformed.relationship.status, "unavailable", "unknown relationship must fail closed");

assert.match(identityTypes, /gold_result_identity\.v1/, "identity type must pin the Gold result identity schema");
for (const field of [
  "kind",
  "run_id",
  "premarket_snapshot_id",
  "feature_snapshot_id",
  "result_id",
  "state_id",
  "strategy_id",
  "receipt_id",
  "bundle_ref",
  "verification_status",
  "reason_code",
]) {
  assert.match(identityTypes, new RegExp(`${field}:`), `identity subject must retain ${field}`);
}
for (const field of ["status", "held", "authority_ready", "quality_status", "strategy_status", "decision_as_of"]) {
  assert.match(identityTypes, new RegExp(`${field}:`), `effective baseline must retain ${field}`);
}
for (const status of ["same_effective_head", "different_result", "unverified", "unavailable"]) {
  assert.match(identityTypes, new RegExp(`"${status}"`), `relationship must support ${status}`);
}

assert.match(identityAdapter, /normalizeResultIdentity/, "identity adapter must expose one normalizer");
assert.match(identityAdapter, /effective_baseline: normalizeEffectiveBaseline/, "identity adapter must preserve nullable effective baseline");
assert.match(identityAdapter, /schema_version: nullableString/, "identity adapter must preserve missing or unknown schema state");
assert.match(identityAdapter, /status: knownStatus/, "identity adapter must fail closed on unknown relationship status");

assert.match(reportTypes, /result_identity\?: ResultIdentity \| null/, "report detail API must preserve additive result_identity");
assert.match(reportsAdapter, /result_identity: normalizeResultIdentity\(detail\.result_identity\)/, "report adapter must normalize result_identity");
assert.match(goldAdapter, /result_identity: normalizeResultIdentity\(raw\.result_identity\)/, "Gold mainline adapter must normalize result_identity");
assert.match(liveTypes, /result_identity: ResultIdentity \| null/, "live strategy view model must expose result_identity");
assert.match(liveAdapter, /result_identity: normalizeResultIdentity\(raw\.result_identity\)/, "live strategy adapter must normalize result_identity");

assert.match(identityBar, /aria-label="正式结果身份"/, "identity bar must expose a stable DOM label");
assert.match(identityBar, /展开完整身份 ID/, "full machine IDs must remain available in a folded section");
assert.match(identityBar, /HOLD · 沿用/, "held baseline must be explicit in Chinese");
assert.match(identityBar, /无法核验当前有效基线/, "missing or unknown identity must fail closed in the UI");
assert.match(identityBar, /isKnownResultIdentity/, "identity bar must guard relationship display by schema version");
assert.match(identityBar, /const subject = known \? identity\?\.subject/, "unknown identity schema must not expose unverified subject fields");

assert.match(reportPage, /<ResultIdentityBar/, "report detail must show the formal result identity");
assert.match(goldPage, /<ResultIdentityBar/, "Gold mainlines must show the formal result identity");
assert.match(strategyPage, /identity=\{liveStrategy\.data\?\.result_identity\}/, "current strategy must use live result identity");
assert.match(strategyPage, /<LegacyStrategyIdentityNotice/, "legacy strategy views must state they are not baseline-qualified");
assert.match(reportsPage, /进入报告详情查看正式结果身份/, "reports index must direct users to formal identity details");

console.log("Result identity frontend contract OK");
