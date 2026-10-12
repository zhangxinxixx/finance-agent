import assert from "node:assert/strict";

// Run with Node 22+ so the test exercises the TypeScript presentation helper
// that the StrategyPage and LiveStrategyWorkspace both import:
// node --experimental-strip-types scripts/check-strategy-trust.mjs
const {
  getDisplayLiveStrategyStatus,
  getLiveStrategyTrustState,
  isLiveStrategyMarketUsable,
  liveStrategyTrustLabel,
  liveStrategyTrustMessage,
  liveStrategyScenarioStatusLabel,
} = await import("../src/components/strategy/liveStrategyTrust.ts");

const availableTriggered = {
  status: "TRIGGERED",
  availability: "available",
  dataReady: true,
  market: { status: "available", price: 4000 },
  goldBaselineVerified: true,
};

assert.equal(
  getLiveStrategyTrustState({ isLoading: false, error: null }),
  "current",
  "a completed request should be current",
);
assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, trustState: "current" }),
  "TRIGGERED",
  "a verified available result may retain its backend status",
);

assert.equal(
  getLiveStrategyTrustState({ isLoading: true, error: null }),
  "refreshing",
  "an in-flight refresh must be distinguishable from a current result",
);
assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, trustState: "refreshing" }),
  "SUSPENDED_DATA",
  "an old triggered result must be blocked while refresh is in flight",
);
assert.match(liveStrategyTrustLabel("refreshing"), /无法核验/);
assert.match(liveStrategyTrustMessage("refreshing"), /上次成功结果供复盘/);

assert.equal(
  getLiveStrategyTrustState({ isLoading: false, error: new Error("503") }),
  "unavailable",
  "a failed refresh must be unavailable",
);
assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, trustState: "unavailable" }),
  "SUSPENDED_DATA",
  "a failed refresh must not expose the old triggered status",
);
assert.match(liveStrategyTrustLabel("unavailable"), /刷新失败/);
assert.equal(liveStrategyTrustLabel("current"), "本次读取成功");
assert.match(liveStrategyTrustMessage("current"), /行情、分析与参考资格须分别核对/);
assert.equal(liveStrategyScenarioStatusLabel("ready"), "条件已就绪");
assert.equal(liveStrategyScenarioStatusLabel("blocked"), "数据阻断");
assert.equal(liveStrategyScenarioStatusLabel("unknown_backend_status"), "状态未知");

assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, availability: "partial", trustState: "current" }),
  "SUSPENDED_DATA",
  "a partial backend result must not be presented as an executable status",
);
assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, availability: "unavailable", trustState: "current" }),
  "SUSPENDED_DATA",
  "an unavailable market result must not expose the backend triggered status",
);
assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, dataReady: false, trustState: "current" }),
  "SUSPENDED_DATA",
  "a backend data_ready=false result must not expose the backend triggered status",
);
assert.equal(
  isLiveStrategyMarketUsable({ status: "unavailable", price: 4000 }),
  false,
  "an unavailable live market must fail the shared market gate",
);
assert.equal(
  getDisplayLiveStrategyStatus({
    ...availableTriggered,
    market: { status: "unavailable", price: 4000 },
    trustState: "current",
  }),
  "SUSPENDED_DATA",
  "TRIGGERED plus unavailable market data must stay unavailable in the UI",
);
assert.equal(
  isLiveStrategyMarketUsable({ status: "available", price: null }),
  false,
  "a null market price must fail the shared market gate",
);
assert.equal(
  getDisplayLiveStrategyStatus({
    ...availableTriggered,
    market: { status: "available", price: null },
    trustState: "current",
  }),
  "SUSPENDED_DATA",
  "TRIGGERED plus a null market price must stay unavailable in the UI",
);
for (const price of [Number.NaN, Number.POSITIVE_INFINITY]) {
  assert.equal(
    isLiveStrategyMarketUsable({ status: "available", price }),
    false,
    `a non-finite market price (${String(price)}) must fail the shared market gate`,
  );
  assert.equal(
    getDisplayLiveStrategyStatus({ ...availableTriggered, market: { status: "available", price }, trustState: "current" }),
    "SUSPENDED_DATA",
    `TRIGGERED plus a non-finite market price (${String(price)}) must stay unavailable in the UI`,
  );
}
assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, status: "INVALID_STATUS", trustState: "current" }),
  "SUSPENDED_DATA",
  "an invalid backend strategy status must fail closed in the presentation gate",
);
const backendStatus = { ...availableTriggered };
const displayedStatus = getDisplayLiveStrategyStatus({ ...backendStatus, dataReady: false, trustState: "current" });
assert.equal(displayedStatus, "SUSPENDED_DATA");
assert.deepEqual(backendStatus, availableTriggered, "the presentation gate must not write back to backend result data");
assert.equal(
  getDisplayLiveStrategyStatus({ ...availableTriggered, goldBaselineVerified: false, trustState: "current" }),
  "WAITING",
  "an unverified Gold baseline must remain fail-closed without inventing a direction",
);

console.log("Strategy trust state behavior OK");
