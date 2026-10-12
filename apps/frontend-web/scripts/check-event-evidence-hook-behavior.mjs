import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import ts from "typescript";

const source = (relativePath) => readFileSync(join(process.cwd(), relativePath), "utf8");

function loadTranspiledModule(relativePath, dependencies = {}) {
  const output = ts.transpileModule(source(relativePath), {
    fileName: relativePath,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, {
    module,
    exports: module.exports,
    require: (name) => {
      if (dependencies[name]) return dependencies[name];
      throw new Error(`Unexpected runtime dependency in ${relativePath}: ${name}`);
    },
    console,
    Error,
    Promise,
    Number,
    String,
    Object,
    Array,
  }, { filename: relativePath });
  return module.exports;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function createRequests() {
  const impact = new Map();
  const reaction = new Map();
  return {
    impact,
    reaction,
    fetchImpact: (eventId) => {
      const pending = deferred();
      impact.set(eventId, pending);
      return pending.promise;
    },
    fetchReaction: (eventId) => {
      const pending = deferred();
      reaction.set(eventId, pending);
      return pending.promise;
    },
  };
}

function createHookRunner() {
  const stateSlots = [];
  const effectSlots = [];
  const pendingEffectIndexes = [];
  let stateCursor = 0;
  let effectCursor = 0;
  let currentEventId = null;
  let result = null;

  const fakeReact = {
    useState(initialValue) {
      const index = stateCursor;
      stateCursor += 1;
      if (!(index in stateSlots)) stateSlots[index] = initialValue;
      return [stateSlots[index], (nextValue) => {
        stateSlots[index] = typeof nextValue === "function" ? nextValue(stateSlots[index]) : nextValue;
      }];
    },
    useEffect(effect, dependencies) {
      const index = effectCursor;
      effectCursor += 1;
      const previous = effectSlots[index];
      const changed = !previous
        || dependencies.length !== previous.dependencies.length
        || dependencies.some((value, dependencyIndex) => value !== previous.dependencies[dependencyIndex]);
      if (!changed) return;
      if (previous?.pending) {
        previous.dependencies = [...dependencies];
        previous.effect = effect;
        return;
      }
      effectSlots[index] = {
        dependencies: [...dependencies],
        effect,
        cleanup: previous?.cleanup,
        pending: true,
      };
      pendingEffectIndexes.push(index);
    },
  };

  return {
    fakeReact,
    bind(hook) {
      this.hook = hook;
    },
    render(eventId) {
      currentEventId = eventId;
      stateCursor = 0;
      effectCursor = 0;
      result = this.hook(eventId);
      return result;
    },
    flushEffects() {
      while (pendingEffectIndexes.length > 0) {
        const index = pendingEffectIndexes.shift();
        const slot = effectSlots[index];
        if (!slot || !slot.pending) continue;
        slot.cleanup?.();
        const cleanup = slot.effect();
        slot.cleanup = typeof cleanup === "function" ? cleanup : undefined;
        slot.pending = false;
      }
    },
    currentEventId: () => currentEventId,
    result: () => result,
  };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function makeImpact(eventId) {
  return { event_id: eventId, status: "available", summary: "supplied impact" };
}

function makeReaction(eventId) {
  return { event_id: eventId, status: "available", windows: {} };
}

function createTestHook(requests) {
  const runner = createHookRunner();
  const concreteHookModule = loadTranspiledModule("src/hooks/useEventFlowEventEvidence.ts", {
    react: runner.fakeReact,
    "@/adapters/eventFlow": {
      fetchEventFlowEventImpact: requests.fetchImpact,
      fetchEventFlowMarketReaction: requests.fetchReaction,
    },
    "@/types/event-flow": {},
    "@/components/event-flow/eventEvidenceFormat": {
      resolveEventEvidenceIdentity: (routeEventId, modelEventId) => {
        if (typeof modelEventId !== "string" || !modelEventId.trim()) return "unverified";
        return routeEventId === modelEventId ? "verified" : "mismatch";
      },
    },
  });
  runner.bind(concreteHookModule.useEventFlowEventEvidence);
  return runner;
}

// One endpoint may finish while the other remains pending. The completed
// read model must be visible immediately and loading must remain scoped to the
// pending endpoint.
{
  const requests = createRequests();
  const runner = createTestHook(requests);
  runner.render("evt-a");
  runner.flushEffects();
  requests.impact.get("evt-a").resolve(makeImpact("evt-a"));
  await flushPromises();
  runner.render("evt-a");
  assert.equal(runner.result().impact.event_id, "evt-a", "impact should render before market reaction resolves");
  assert.equal(runner.result().marketReaction, null, "pending reaction must not be represented as success");
  assert.equal(runner.result().impactIdentity, "verified");
  assert.equal(runner.result().impactLoading, false, "impact loading ends when the impact endpoint settles");
  assert.equal(runner.result().marketReactionLoading, true, "reaction loading remains scoped to the pending endpoint");
  assert.equal(runner.result().isLoading, true, "loading stays true while the second endpoint is pending");

  requests.reaction.get("evt-a").resolve(makeReaction("evt-a"));
  await flushPromises();
  runner.render("evt-a");
  assert.equal(runner.result().marketReaction.event_id, "evt-a");
  assert.equal(runner.result().marketReactionLoading, false);
  assert.equal(runner.result().isLoading, false, "loading ends only after both endpoints settle");
}

// A successful HTTP response with another event identity must remain an
// explicit mismatch and must never populate the routed event's evidence.
{
  const requests = createRequests();
  const runner = createTestHook(requests);
  runner.render("evt-route");
  runner.flushEffects();
  requests.impact.get("evt-route").resolve(makeImpact("evt-other"));
  await flushPromises();
  runner.render("evt-route");
  assert.equal(runner.result().impact, null, "mismatched impact must not populate the routed event");
  assert.equal(runner.result().impactIdentity, "mismatch");
  assert.match(runner.result().impactError.message, /event_id/);

  requests.reaction.get("evt-route").reject(new Error("HTTP 503"));
  await flushPromises();
  runner.render("evt-route");
  assert.equal(runner.result().isLoading, false);
  assert.match(runner.result().marketReactionError.message, /HTTP 503/);
}

// A refetch creates a new request key even when the routed event ID is the
// same. The previous result is hidden before the new effect starts.
{
  const requests = createRequests();
  const runner = createTestHook(requests);
  runner.render("evt-refresh");
  runner.flushEffects();
  requests.impact.get("evt-refresh").resolve(makeImpact("evt-refresh"));
  requests.reaction.get("evt-refresh").resolve(makeReaction("evt-refresh"));
  await flushPromises();
  runner.render("evt-refresh");
  assert.equal(runner.result().impact.event_id, "evt-refresh");

  runner.result().refetch();
  runner.render("evt-refresh");
  assert.equal(runner.result().impact, null, "refetch must hide the prior impact before its effect flushes");
  assert.equal(runner.result().marketReaction, null, "refetch must hide the prior reaction before its effect flushes");
  assert.equal(runner.result().impactIdentity, "unverified");
  assert.equal(runner.result().marketReactionIdentity, "unverified");
  assert.equal(runner.result().isLoading, true);
  runner.flushEffects();
  runner.render("evt-refresh");
  requests.impact.get("evt-refresh").resolve(makeImpact("evt-refresh"));
  requests.reaction.get("evt-refresh").resolve(makeReaction("evt-refresh"));
  await flushPromises();
  runner.render("evt-refresh");
  assert.equal(runner.result().impactIdentity, "verified");
  assert.equal(runner.result().marketReactionIdentity, "verified");
}

// Route changes synchronously hide the old result before the new effect is
// flushed. After the effect runs, late old responses cannot overwrite the new
// event's cleared state or its identities.
{
  const requests = createRequests();
  const runner = createTestHook(requests);
  runner.render("evt-old");
  runner.flushEffects();
  requests.impact.get("evt-old").resolve(makeImpact("evt-old"));
  requests.reaction.get("evt-old").resolve(makeReaction("evt-old"));
  await flushPromises();
  runner.render("evt-old");
  assert.equal(runner.result().impact.event_id, "evt-old");

  runner.render("evt-new");
  assert.equal(runner.result().impact, null);
  assert.equal(runner.result().marketReaction, null);
  assert.equal(runner.result().impactIdentity, "unverified", "old verified identity must be hidden before the new effect flushes");
  assert.equal(runner.result().marketReactionIdentity, "unverified", "old verified identity must be hidden before the new effect flushes");
  assert.equal(runner.result().impactLoading, true);
  assert.equal(runner.result().marketReactionLoading, true);
  assert.equal(runner.result().isLoading, true);
  assert.equal(requests.impact.has("evt-new"), false, "new request starts only when the effect is flushed");

  runner.flushEffects();
  runner.render("evt-new");
  assert.equal(runner.result().impact, null);
  assert.equal(runner.result().marketReaction, null);
  await flushPromises();
  assert.equal(runner.result().impact, null, "old impact must remain isolated after route change");
  assert.equal(runner.result().marketReaction, null, "old reaction must remain isolated after route change");
  assert.equal(runner.result().impactIdentity, "unverified");
  assert.equal(runner.result().marketReactionIdentity, "unverified");
  assert.equal(runner.result().impactLoading, true);
  assert.equal(runner.result().marketReactionLoading, true);
  assert.equal(runner.result().isLoading, true, "new route remains pending until its own endpoints settle");

  requests.impact.get("evt-new").resolve(makeImpact("evt-new"));
  requests.reaction.get("evt-new").resolve(makeReaction("evt-new"));
  await flushPromises();
  runner.render("evt-new");
  assert.equal(runner.result().impact.event_id, "evt-new");
  assert.equal(runner.result().marketReaction.event_id, "evt-new");
  assert.equal(runner.result().impactIdentity, "verified");
  assert.equal(runner.result().marketReactionIdentity, "verified");
}

console.log("Event evidence hook behavior OK: independent endpoint visibility, identity mismatch isolation and route-switch cancellation.");
