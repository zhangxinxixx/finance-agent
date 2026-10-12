import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";
import { assertPageRequestAllowed, classifyPageRequest, summarizeEvidenceRecord } from "../src/adapters/pageDataBoundary.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const allowedCases = [
  ["/api/market/candles?asset=XAUUSD&timeframe=1h", "dws"],
  ["/api/options/decision?date=2026-10-09", "dws"],
  ["/api/reports/report-1/analysis", "output"],
  ["/api/final-report/latest", "output"],
  ["/api/data-sources/status?view=ads", "ads"],
  ["/api/runs/run-1?view=ads", "ads"],
  ["/api/processing/trace/trace-1?view=ads", "ads"],
  ["/api/tasks/premarket/preflight", "ads"],
];

for (const [path, layer] of allowedCases) {
  const result = assertPageRequestAllowed(path);
  assert.equal(result.layer, layer, `${path} should be classified as ${layer}`);
}

const blockedCases = [
  "/api/raw/news/1",
  "/api/parsed/cme/1",
  "/api/ods/options",
  "/api/reports/report-1/%72aw/input",
  "/api/reports-internal/rows",
  "/api/reports/%E0%A4%A",
  "/api/dwd/candles",
  "/api/runs/run-1/artifacts",
  "/api/runs/run-1/logs",
  "/api/reports/report-1/analysis-inputs",
  "/api/source-trace/by-artifact/a-1",
  "/api/jin10/flash?limit=10",
  "/api/jin10/calendar",
  "/api/news/feishu-jin10/messages/latest",
  "/api/data-sources/status",
  "/api/processing/overview",
  "https://example.com/api/data.json",
  "https://www.tradingview.com/widgetembed/?symbol=OANDA%3AXAUUSD",
  "https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD",
  "/api/unclassified/internal",
];

for (const path of blockedCases) {
  assert.equal(classifyPageRequest(path).allowed, false, `${path} must be blocked`);
  assert.throws(() => assertPageRequestAllowed(path), { name: "PageDataBoundaryError" });
}

const evidenceSummary = summarizeEvidenceRecord({
  source_name: "CME",
  status: "available",
  source_url: "https://www.cmegroup.com/markets/metals/precious/gold.html",
  raw_path: "storage/raw/cme/bulletin.pdf",
  parsed_path: "storage/parsed/cme/bulletin.json",
  artifact_path: "storage/features/cme/features.json",
  payload: { secret: "raw response" },
});
assert.deepEqual(evidenceSummary, {
  source_name: "CME",
  status: "available",
  source_url: "https://www.cmegroup.com/markets/metals/precious/gold.html",
});
assert.equal(summarizeEvidenceRecord("storage/raw/cme/bulletin.pdf"), null, "standalone lower-layer paths must not be copied");

const apiClient = await readFile(resolve(root, "src/adapters/apiClient.ts"), "utf8");
const configuredDagster = "http://127.0.0.1:5300/graphql";
const clientSource = apiClient
  .replaceAll('"@/adapters/pageDataBoundary.mjs"', JSON.stringify(pathToFileURL(resolve(root, "src/adapters/pageDataBoundary.mjs")).href))
  .replaceAll("import.meta.env", JSON.stringify({ VITE_DAGSTER_GRAPHQL_URL: configuredDagster }));
const compiledClient = ts.transpileModule(clientSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const client = await import(`data:text/javascript;base64,${Buffer.from(compiledClient).toString("base64")}`);
const originalFetch = globalThis.fetch;
const requests = [];
globalThis.fetch = async (url) => {
  requests.push(url);
  return new Response(JSON.stringify({ status: "available" }), { status: 200 });
};
try {
  for (const path of blockedCases) {
    await assert.rejects(client.fetchJson(path), { name: "PageDataBoundaryError" });
  }
  assert.equal(requests.length, 0, "blocked requests must never reach fetch");
  assert.equal((await client.fetchJson("/api/events/calendar-summary")).status, "available");
  await client.fetchJson(configuredDagster);
  assert.deepEqual(requests, ["/api/events/calendar-summary", configuredDagster]);
} finally {
  globalThis.fetch = originalFetch;
}

const directFetchFiles = [
  "src/components/charts/TradingViewChart.tsx",
  "src/adapters/eventFlow.ts",
  "src/adapters/knowledge.ts",
  "src/adapters/dagster.ts",
];
for (const relativePath of directFetchFiles) {
  const source = await readFile(resolve(root, relativePath), "utf8");
  assert.doesNotMatch(source, /\bfetch\s*\(/, `${relativePath} must use the shared page request client`);
}

console.log("page data boundary behavior checks passed");
