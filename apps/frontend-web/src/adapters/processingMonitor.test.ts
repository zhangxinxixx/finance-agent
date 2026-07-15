import { fetchArtifactSourceTrace, normalizeArtifactSourceTrace, normalizeProcessingTrace } from "./processingMonitor";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function equal(actual: unknown, expected: unknown, message: string) {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  assert(actualJson === expectedJson, `${message}: expected ${expectedJson}, received ${actualJson}`);
}

const matched = normalizeProcessingTrace({
  status: "matched",
  date: "2026-07-18",
  run_id: "run-50",
  asset: "XAUUSD",
  query: { processing_trace_id: "trace-50" },
  matched_event: {
    event_id: "event-50",
    input_id: "input-50",
    primary_mainline: "oil_prices",
    processing_trace_id: "trace-50",
  },
  mainlines: ["oil_prices", null],
  transmission_chains: ["war_oil_rate_chain"],
  trace_header: {
    trace_id: "trace-50",
    run_id: "run-50",
    entity_type: "event",
    entity_id: "event-50",
    status: "matched",
    review_status: "blocked",
    publish_allowed: false,
    as_of: "2026-07-18T10:00:00Z",
  },
  trace_path: [
    {
      node_id: "review_gate",
      label: "Review Gate",
      stage: "validated",
      status: "blocked",
      source_ref_count: 2,
      artifact_ref_count: 1,
      warnings: ["manual_review_required", 7],
      missing_data: ["options_oi"],
      agent_artifact_refs: [{ agent_name: "report_render_agent", status: "success", file_path: "outputs/report.json" }],
      source_refs: [{ source_ref: "jin10:flash:50", provider: "jin10" }, { provider: "invalid" }],
      artifact_refs: [{ artifact_type: "quality_gate_result", path: "analysis/quality_gate_result.json" }, "invalid"],
      scope: "run",
    },
  ],
  source_health: {
    overall_status: "ready",
    as_of: "2026-07-18T09:59:00Z",
    source_freshness: { jin10: "fresh" },
    mainline_impact: { oil_prices: "covered" },
    can_emit_strong_conclusion: true,
    blocked_mainlines: [],
    degraded_mainlines: ["etf_flows"],
  },
  quality_gate: {
    status: "blocked",
    review_status: "blocked",
    publish_allowed: false,
    agent_loop_decision: { decision: "observe_only" },
    fallback_review: { no_strong_conclusion: true, strategy_card_override: { action: "observe_wait" } },
  },
  read_time_source_health: { overall_status: "degraded", p1_missing: ["fedwatch_ois"] },
  read_time_warnings: ["read_time_source_health_degraded", null],
  read_time_generated_at: "2026-07-18T10:01:00Z",
  source_refs: [{ source_ref: "jin10:flash:50", provider: "jin10" }],
  artifact_refs: [{ artifact_type: "final_report", path: "outputs/report.md" }],
  view_bindings: [{ view: "Dashboard", status: "bound" }],
  primary_output: {
    scope: "run",
    agent_name: "report_render_agent",
    run_id: "run-50",
    snapshot_id: "snapshot-primary",
    status: "success",
    file_path: "agent_outputs/report_render.json",
    artifact_refs: [{ artifact_type: "final_report", path: "outputs/report.md" }],
  },
  fallback_outputs: [{ agent_name: "fallback_synthesis_agent", bias: "neutral", confidence: 0.55, summary: "observe" }],
  accepted_output: {},
  accepted_output_source: "none",
  fallback_review: {
    status: "blocked",
    fallback_used: true,
    accepted_output: null,
    manual_review_required: true,
    primary_outputs: ["report_render_agent:snapshot-primary"],
    fallback_outputs: [{ agent_name: "fallback_synthesis_agent", confidence: 0.55 }],
    accepted_outputs: {},
    fallback_tasks: [{ task_type: "fallback_reanalyze" }],
    task_results: [{ task_type: "fallback_reanalyze", reason: "quality_gate", status: "rejected" }],
    reasons: ["unsupported_claim"],
    review_items: [{ review_id: "review-50" }],
    fallback_quality_gate_decision: { status: "blocked" },
    no_strong_conclusion: true,
    strategy_card_override: { bias: "neutral", action: "observe_wait" },
  },
  agent_envelopes: [
    {
      scope: "run",
      agent_name: "report_render_agent",
      run_id: "run-50",
      snapshot_id: "snapshot-primary",
      status: "success",
      confidence: 0.61,
      created_at: "2026-07-18T10:00:00Z",
      input_snapshot_ids: { analysis: "analysis-50" },
      source_refs: [{ source_ref: "jin10:flash:50" }],
      artifact_refs: [{ path: "outputs/report.md" }],
      evidence_refs: [{ evidence_ref: "evidence-50" }],
      evidence_items: [{ evidence_id: "evidence-item-50" }],
      data_quality: ["partial"],
      file_path: "agent_outputs/report_render.json",
    },
  ],
  input_snapshot_ids: { analysis: "analysis-50" },
  evidence_refs: [{ evidence_ref: "evidence-50" }],
  evidence_items: [{ evidence_id: "evidence-item-50", kind: "derived_feature" }],
  affected_views: ["Dashboard", "ProcessingMonitor", 9],
});

equal(matched.trace_header, {
  trace_id: "trace-50",
  run_id: "run-50",
  entity_type: "event",
  entity_id: "event-50",
  status: "matched",
  review_status: "blocked",
  publish_allowed: false,
  as_of: "2026-07-18T10:00:00Z",
}, "normalizes trace header");
equal(matched.trace_path[0].warnings, ["manual_review_required"], "filters stage warnings");
equal(matched.trace_path[0].missing_data, ["options_oi"], "normalizes stage missing data");
equal(matched.trace_path[0].agent_artifact_refs, [
  { agent_name: "report_render_agent", status: "success", file_path: "outputs/report.json" },
], "normalizes stage agent artifact refs");
equal(matched.trace_path[0].source_refs, [
  { source_ref: "jin10:flash:50", provider: "jin10" },
], "normalizes stage source refs from payload");
equal(matched.trace_path[0].artifact_refs, [
  { artifact_type: "quality_gate_result", path: "analysis/quality_gate_result.json" },
], "normalizes stage artifact refs from payload");
assert(matched.trace_path[0].scope === "run", "normalizes stage scope");
assert(matched.source_health.overall_status === "ready", "normalizes artifact-time source health");
assert(matched.source_health.can_emit_strong_conclusion, "normalizes strong-conclusion gate");
equal(matched.source_health.degraded_mainlines, ["etf_flows"], "normalizes source-health mainline impact");
assert(matched.read_time_source_health.overall_status === "degraded", "normalizes read-time source health");
equal(matched.read_time_warnings, ["read_time_source_health_degraded"], "normalizes read-time warnings");
assert(matched.quality_gate.publish_allowed === false, "normalizes trace quality gate");
assert(matched.quality_gate.agent_loop_decision.decision === "observe_only", "normalizes trace agent-loop decision");
assert(matched.primary_output?.agent_name === "report_render_agent", "normalizes primary output");
assert(matched.fallback_outputs[0].agent_name === "fallback_synthesis_agent", "normalizes fallback outputs");
assert(matched.accepted_output_source === "none", "does not infer accepted output source");
assert(Object.keys(matched.accepted_output).length === 0, "does not manufacture accepted output");
assert(matched.fallback_review.no_strong_conclusion, "preserves no strong conclusion");
assert(matched.fallback_review.strategy_card_override.action === "observe_wait", "preserves observe_wait override");
equal(matched.evidence_refs, [{ evidence_ref: "evidence-50" }], "preserves evidence refs from payload");
equal(matched.evidence_items, [{ evidence_id: "evidence-item-50", kind: "derived_feature" }], "preserves evidence items from payload");
equal(matched.affected_views, ["Dashboard", "ProcessingMonitor"], "filters affected views from payload");

const empty = normalizeProcessingTrace({
  status: "not_found",
  trace_header: { status: "not_found" },
  trace_path: [
    {
      node_id: "jin10_message_raw",
      source_refs: null,
      artifact_refs: null,
    },
  ],
});
assert(empty.status === "not_found", "preserves not-found status");
assert(empty.trace_header.status === "not_found", "preserves not-found header status");
assert(empty.trace_header.entity_type === "unknown", "defaults unknown entity type");
assert(empty.primary_output === null, "normalizes missing primary output to null");
assert(empty.accepted_output_source === "unknown", "does not infer missing accepted source");
equal(empty.evidence_items, [], "keeps empty evidence shape");
equal(empty.affected_views, [], "keeps empty affected views shape");
equal(empty.trace_path[0].source_refs, [], "keeps not-found stage source refs empty");
equal(empty.trace_path[0].artifact_refs, [], "keeps not-found stage artifact refs empty");

const artifactPayload = {
  run_id: "run-artifact-50",
  snapshot_id: "snapshot-artifact-50",
  data_status: "partial",
  source_refs: [{
    source_id: "src-50",
    source_name: "CME Daily Bulletin",
    source_type: "pdf",
    data_date: "2026-07-18",
    file_path: "storage/raw/cme/2026-07-18/bulletin.pdf",
    status: "available",
  }],
  artifact_refs: [{
    artifact_id: "artifact-50",
    artifact_type: "feature_json",
    file_path: "storage/features/cme/2026-07-18/rollup.json",
  }],
  snapshot: { snapshot_id: "snapshot-artifact-50", snapshot_type: "analysis", data_status: "partial" },
  input_snapshots: [{ snapshot_id: "input-50", snapshot_type: "macro", data_status: "live" }],
  related_artifacts: [{ artifact_id: "artifact-related-50", artifact_type: "raw_file", file_path: "storage/raw/cme/2026-07-18/bulletin.pdf" }],
  warnings: [{ code: "snapshot-drift", message: "snapshot differs" }],
};

const normalizedArtifactTrace = normalizeArtifactSourceTrace(artifactPayload);
assert(normalizedArtifactTrace.run_id === "run-artifact-50", "preserves artifact source trace run id");
assert(normalizedArtifactTrace.source_refs[0].source_id === "src-50", "preserves artifact source ref fields");
assert(normalizedArtifactTrace.artifact_refs[0].artifact_id === "artifact-50", "preserves artifact reference fields");
assert(normalizedArtifactTrace.input_snapshots[0].snapshot_id === "input-50", "preserves input snapshots");
assert(normalizedArtifactTrace.related_artifacts[0].artifact_id === "artifact-related-50", "preserves related artifacts");
assert(normalizedArtifactTrace.warnings[0].code === "snapshot-drift", "preserves backend lineage warnings without inventing a second field");

const originalFetch = globalThis.fetch;
const requestedPaths: string[] = [];
globalThis.fetch = async (input) => {
  requestedPaths.push(String(input));
  return new Response(JSON.stringify(artifactPayload), { status: 200, headers: { "Content-Type": "application/json" } });
};
const artifactMatch = await fetchArtifactSourceTrace("artifact/50");
assert(artifactMatch.status === "matched", "maps artifact source trace success to matched");
assert(requestedPaths[0] === "/api/source-trace/by-artifact/artifact%2F50", "uses the source trace artifact authority with encoded id");

globalThis.fetch = async () => new Response("not found", { status: 404 });
const artifactNotFound = await fetchArtifactSourceTrace("missing-artifact");
assert(artifactNotFound.status === "not_found", "maps artifact source trace 404 to not found");

globalThis.fetch = async () => new Response("service unavailable", { status: 503 });
let non404Error: unknown = null;
try {
  await fetchArtifactSourceTrace("broken-artifact");
} catch (error) {
  non404Error = error;
}
assert(non404Error instanceof Error, "preserves non-404 artifact source trace errors");
globalThis.fetch = originalFetch;
