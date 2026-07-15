import {
  classifyMarketCandleCoverage,
  mergeKlineCandles,
  type MarketCandleCoverage,
} from "./klineCoverageModel.js";

function expect(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function coverage(overrides: Partial<MarketCandleCoverage> = {}): MarketCandleCoverage {
  return {
    returned: 120,
    first_time: "2026-07-06T00:00:00+00:00",
    last_time: "2026-07-06T01:59:00+00:00",
    expected_interval_seconds: 60,
    gap_count: 0,
    max_gap_seconds: null,
    degraded: false,
    reason: null,
    ...overrides,
  };
}

function testClassifiesCoverageStates(): void {
  expect(
    classifyMarketCandleCoverage({ timeframe: "5m", coverage: coverage() }).status === "available",
    "healthy coverage should be available",
  );
  expect(
    classifyMarketCandleCoverage({ timeframe: "5m", coverage: coverage({ gap_count: 2, degraded: true }) }).status === "degraded",
    "gapped coverage should be degraded",
  );
  expect(
    classifyMarketCandleCoverage({ timeframe: "1D", coverage: coverage({ returned: 1 }) }).status === "unavailable",
    "single-row coverage should be unavailable",
  );
  expect(
    classifyMarketCandleCoverage({ timeframe: "5m", error: "HTTP 500" }).reason === "HTTP 500",
    "error should become unavailable reason",
  );
}

function testMergesKlineCandlesByTimestamp(): void {
  const merged = mergeKlineCandles(
    [
      { time: "2026-07-06T00:00:00Z", close: 3300 },
      { time: "2026-07-06T00:01:00Z", close: 3301 },
    ],
    [
      { time: "2026-07-06T00:01:00Z", close: 3302 },
      { time: "2026-07-06T00:02:00Z", close: 3303 },
    ],
    3,
  );

  expect(merged.length === 3, "merged candles should keep unique timestamps");
  expect(merged[1]?.close === 3302, "incoming candle should update the latest duplicate timestamp");
  expect(merged[2]?.time === "2026-07-06T00:02:00Z", "new candle should be appended in time order");
}

function testMergesWithinLimit(): void {
  const merged = mergeKlineCandles(
    [
      { time: "2026-07-06T00:00:00Z" },
      { time: "2026-07-06T00:01:00Z" },
      { time: "2026-07-06T00:02:00Z" },
    ],
    [{ time: "2026-07-06T00:03:00Z" }],
    2,
  );

  expect(merged.map((item) => item.time).join(",") === "2026-07-06T00:02:00Z,2026-07-06T00:03:00Z", "merge should trim to latest limit");
}

testClassifiesCoverageStates();
testMergesKlineCandlesByTimestamp();
testMergesWithinLimit();
