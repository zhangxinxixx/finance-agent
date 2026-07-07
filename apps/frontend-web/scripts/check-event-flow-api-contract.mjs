import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve("src/adapters/eventFlow.ts"), "utf8");

const assertions = [
  [
    "successful overview responses use the API view model directly",
    "return _mapApiToViewModel(rawOverview);",
  ],
  ["API view models leave unsupported transmission chains empty", "chain: [],"],
  ["API view models leave unsupported sentiment empty", "sentiment: [],"],
  ["API view models leave unsupported risk radar empty", "radar: [],"],
  ["API view models leave unsupported reports empty", "reports: [],"],
  ["mock fallback is explicitly unavailable", 'status: "unavailable",'],
  ["mock fallback has an explicit source label", 'source: "mock_fallback",'],
];

for (const [description, expected] of assertions) {
  if (!source.includes(expected)) {
    throw new Error(`Event Flow API contract failed: ${description}`);
  }
}

if (source.includes("return _mergeApiIntoCurated(curated, rawOverview);")) {
  throw new Error("Event Flow API contract failed: successful responses retain curated mock content");
}
