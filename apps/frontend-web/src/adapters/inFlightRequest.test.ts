import { createInFlightRequest } from "./inFlightRequest.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (reason?: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function testSharesOnlyTheActiveRequest(): Promise<void> {
  let indexCalls = 0;
  let datesCalls = 0;
  const indexDeferred = deferred<{ reports: string[] }>();
  const datesDeferred = deferred<{ dates: string[] }>();
  const fetchIndex = createInFlightRequest(() => {
    indexCalls += 1;
    return indexDeferred.promise;
  });
  const fetchDates = createInFlightRequest(() => {
    datesCalls += 1;
    return datesDeferred.promise;
  });

  const firstIndex = fetchIndex();
  const secondIndex = fetchIndex();
  const firstDates = fetchDates();
  const secondDates = fetchDates();
  assert(firstIndex === secondIndex, "same reports URL should share the active Promise");
  assert(firstDates === secondDates, "same dates URL should share the active Promise");
  assert((firstIndex as Promise<unknown>) !== (firstDates as Promise<unknown>), "different URLs must keep independent in-flight Promises");
  assert(indexCalls === 1 && datesCalls === 1, "each URL should start only one request");

  indexDeferred.resolve({ reports: ["latest"] });
  datesDeferred.resolve({ dates: ["2026-09-29"] });
  assert((await firstIndex).reports[0] === "latest", "reports result should pass through unchanged");
  assert((await firstDates).dates[0] === "2026-09-29", "dates result should pass through unchanged");

  const nextIndex = fetchIndex();
  const nextDates = fetchDates();
  assert(nextIndex !== firstIndex && nextDates !== firstDates, "settled requests must be released immediately");
  assert((indexCalls as number) === 2 && (datesCalls as number) === 2, "a later call should fetch fresh data");
}

async function testRejectedRequestIsNotCachedOrSwallowed(): Promise<void> {
  let calls = 0;
  const firstDeferred = deferred<string>();
  const retryDeferred = deferred<string>();
  const fetchValue = createInFlightRequest(() => {
    calls += 1;
    return (calls === 1 ? firstDeferred : retryDeferred).promise;
  });

  const first = fetchValue();
  const duplicate = fetchValue();
  assert(first === duplicate, "a rejected request should still be shared while pending");
  firstDeferred.reject(new Error("temporary failure"));
  const rejected = await Promise.allSettled([first, duplicate]);
  assert(rejected.every((result) => result.status === "rejected"), "rejection must propagate to all waiters");

  const retry = fetchValue();
  assert(retry !== first && calls === 2, "rejection must release the in-flight slot without a TTL cache");
  retryDeferred.resolve("recovered");
  assert((await retry) === "recovered", "a later retry should resolve normally");
}

await testSharesOnlyTheActiveRequest();
await testRejectedRequestIsNotCachedOrSwallowed();
console.log("Reports request in-flight dedupe behavior OK");
