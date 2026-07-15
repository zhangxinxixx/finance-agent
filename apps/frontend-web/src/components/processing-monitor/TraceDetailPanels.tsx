import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type {
  ProcessingFallbackOutput,
  ProcessingTracePathNode,
  ProcessingTraceResponse,
} from "@/types/processing-monitor";

function statusTone(value: string | null | undefined): FAStatusTone {
  const normalized = (value ?? "").toLowerCase();
  if (["matched", "covered", "pass", "success", "accepted", "primary", "fallback"].includes(normalized)) return "up";
  if (["needs_review", "degraded", "stale", "observe_wait", "partial"].includes(normalized)) return "warn";
  if (["blocked", "failed", "missing", "not_found", "none"].includes(normalized)) return "down";
  return "neutral";
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function PayloadRows({ payload, emptyLabel = "后端未返回此输出" }: { payload: Record<string, unknown>; emptyLabel?: string }) {
  const entries = Object.entries(payload);
  if (!entries.length) {
    return <div className="fa-faint-text">{emptyLabel}</div>;
  }
  return (
    <dl className="grid gap-2">
      {entries.map(([key, value]) => (
        <div key={key} className="grid gap-1 sm:grid-cols-[132px_minmax(0,1fr)]">
          <dt className="fa-label break-all">{key}</dt>
          <dd className="fa-body-text break-all">{displayValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function PrimaryOutputPanel({ trace }: { trace: ProcessingTraceResponse }) {
  const output = trace.primary_output;
  const payload: Record<string, unknown> = output
    ? {
        scope: output.scope,
        agent_name: output.agent_name,
        run_id: output.run_id,
        snapshot_id: output.snapshot_id,
        status: output.status,
        file_path: output.file_path,
        artifact_refs: output.artifact_refs,
      }
    : {};
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="fa-card-title">Primary</div>
        <FAStatusPill tone={statusTone(output?.status)} dot={false}>{output?.status ?? "missing"}</FAStatusPill>
      </div>
      <PayloadRows payload={payload} />
    </div>
  );
}

function FallbackOutputRows({ outputs }: { outputs: ProcessingFallbackOutput[] }) {
  if (!outputs.length) return <div className="fa-faint-text">后端未返回 Fallback 候选</div>;
  return (
    <div className="grid gap-2">
      {outputs.map((output, index) => (
        <div key={`${output.agent_name}-${output.snapshot_id ?? index}`} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="fa-card-title">{output.agent_name || "unknown agent"}</span>
            <span className="fa-num fa-muted-text">{output.confidence ?? "—"}</span>
          </div>
          <div className="mt-2 fa-body-text break-words">{output.summary ?? output.snapshot_id ?? "—"}</div>
          <div className="mt-1 fa-faint-text">bias: {output.bias ?? "—"}</div>
        </div>
      ))}
    </div>
  );
}

function FallbackOutputPanel({ trace }: { trace: ProcessingTraceResponse }) {
  const overrideAction = displayValue(trace.fallback_review.strategy_card_override.action);
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="fa-card-title">Fallback</div>
        <FAStatusPill tone={trace.fallback_review.fallback_used ? "warn" : "neutral"} dot={false}>
          {trace.fallback_review.fallback_used ? "used" : "not used"}
        </FAStatusPill>
      </div>
      <FallbackOutputRows outputs={trace.fallback_outputs} />
      {trace.fallback_review.no_strong_conclusion || overrideAction !== "—" ? (
        <div className="mt-3 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2">
          <div className="fa-label text-[var(--warn)]">Fallback review</div>
          <div className="mt-1 fa-body-text">
            no strong conclusion: {trace.fallback_review.no_strong_conclusion ? "是" : "否"}
            <span className="mx-2 text-[var(--fg-5)]">·</span>
            action: {overrideAction}
          </div>
        </div>
      ) : null}
      <div className="mt-3 grid gap-2">
        <div>
          <div className="fa-label">Reasons</div>
          <div className="mt-1 fa-body-text break-words">
            {trace.fallback_review.reasons.length ? trace.fallback_review.reasons.join(" / ") : "—"}
          </div>
        </div>
        <PayloadRows payload={{ fallback_tasks: trace.fallback_review.fallback_tasks }} />
        <PayloadRows payload={{ task_results: trace.fallback_review.task_results }} />
        <PayloadRows payload={{ fallback_quality_gate_decision: trace.fallback_review.fallback_quality_gate_decision }} />
        <PayloadRows payload={{ review_items: trace.fallback_review.review_items }} />
      </div>
    </div>
  );
}

function AcceptedOutputPanel({ trace }: { trace: ProcessingTraceResponse }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--important-border)] bg-[var(--important-soft)] p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="fa-card-title">Accepted</div>
        <FAStatusPill tone={statusTone(trace.accepted_output_source)} dot={false}>
          source: {trace.accepted_output_source}
        </FAStatusPill>
      </div>
      <PayloadRows payload={trace.accepted_output} emptyLabel="后端未采用任何输出" />
    </div>
  );
}

function StageAuditRow({ node }: { node: ProcessingTracePathNode }) {
  const visibleSourceRefs = node.source_refs.slice(0, 3);
  const visibleArtifactRefs = node.artifact_refs.slice(0, 3);
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="fa-card-title">{node.label || node.node_id}</div>
          <div className="mt-1 fa-faint-text">{node.stage} · scope: {node.scope}</div>
        </div>
        <FAStatusPill tone={statusTone(node.status)} dot={false}>{node.status}</FAStatusPill>
      </div>
      <div className="mt-2 grid gap-1 fa-muted-text">
        <div>
          <div>Source refs ({node.source_ref_count})</div>
          {visibleSourceRefs.length
            ? visibleSourceRefs.map((ref) => <div key={ref.source_ref} className="break-all">{ref.source_ref}</div>)
            : <div>—</div>}
          {node.source_refs.length > visibleSourceRefs.length
            ? <div className="fa-faint-text">另 {node.source_refs.length - visibleSourceRefs.length} 条</div>
            : null}
        </div>
        <div>
          <div>Artifact refs ({node.artifact_ref_count})</div>
          {visibleArtifactRefs.length
            ? visibleArtifactRefs.map((ref, index) => {
                const label = ref.path ?? ref.file_path ?? ref.artifact_id ?? "unknown";
                return <div key={`${label}-${index}`} className="break-all">{label}</div>;
              })
            : <div>—</div>}
          {node.artifact_refs.length > visibleArtifactRefs.length
            ? <div className="fa-faint-text">另 {node.artifact_refs.length - visibleArtifactRefs.length} 条</div>
            : null}
        </div>
        <div>Warnings: {node.warnings.length ? node.warnings.join(" / ") : "—"}</div>
        <div>Missing data: {node.missing_data.length ? node.missing_data.join(" / ") : "—"}</div>
        <div>
          Agent artifacts: {node.agent_artifact_refs.length
            ? node.agent_artifact_refs.map((ref) => `${ref.agent_name}:${ref.status}:${ref.file_path}`).join(" / ")
            : "—"}
        </div>
      </div>
    </div>
  );
}

export function TraceDetailPanels({ trace }: { trace: ProcessingTraceResponse }) {
  const header = trace.trace_header;
  return (
    <div className="grid gap-3">
      <FACard
        title="Trace Header"
        eyebrow="Backend Audit Header"
        accent={trace.status === "matched" ? "up" : "warn"}
        action={<FAStatusPill tone={statusTone(header.status)}>{header.status}</FAStatusPill>}
      >
        <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ["Trace ID", header.trace_id],
            ["Run ID", header.run_id],
            ["Entity", `${header.entity_type}:${header.entity_id ?? "—"}`],
            ["Review", header.review_status],
            ["Publish allowed", header.publish_allowed],
            ["As of", header.as_of],
            ["Artifact quality", trace.source_health.overall_status],
            ["Read-time quality", trace.read_time_source_health.overall_status],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-3 py-2">
              <dt className="fa-label">{String(label)}</dt>
              <dd className="mt-1 fa-num fa-body-text break-all">{displayValue(value)}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 grid gap-2 fa-muted-text">
          <div>Read-time generated at: {trace.read_time_generated_at ?? "—"}</div>
          <div>Read-time warnings: {trace.read_time_warnings.length ? trace.read_time_warnings.join(" / ") : "—"}</div>
          <div>Quality warnings: {trace.quality_gate.warnings.length ? trace.quality_gate.warnings.join(" / ") : "—"}</div>
        </div>
      </FACard>

      <FACard title="Agent 输出选择" eyebrow="Primary / Fallback / Accepted" accent="emphasis">
        <div className="grid gap-3 xl:grid-cols-3">
          <PrimaryOutputPanel trace={trace} />
          <FallbackOutputPanel trace={trace} />
          <AcceptedOutputPanel trace={trace} />
        </div>
      </FACard>

      <FACard title="Stage Audit" eyebrow="Backend-projected Metadata" accent="info">
        {trace.trace_path.length ? (
          <div className="grid gap-2 lg:grid-cols-2">
            {trace.trace_path.map((node) => <StageAuditRow key={node.node_id} node={node} />)}
          </div>
        ) : (
          <FAEmptyState title="暂无 Stage Audit" description="后端未返回 trace_path。" />
        )}
      </FACard>

      <FACard title="证据与影响视图" eyebrow="Trace Payload Only" accent="info">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div>
            <div className="fa-card-title">Input Snapshots</div>
            <div className="mt-2"><PayloadRows payload={trace.input_snapshot_ids} /></div>
          </div>
          <div>
            <div className="fa-card-title">Evidence Refs</div>
            <div className="mt-2"><PayloadRows payload={{ items: trace.evidence_refs }} /></div>
          </div>
          <div>
            <div className="fa-card-title">Evidence Items</div>
            <div className="mt-2"><PayloadRows payload={{ items: trace.evidence_items }} /></div>
          </div>
          <div>
            <div className="fa-card-title">Affected Views</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {trace.affected_views.length
                ? trace.affected_views.map((view) => <FAStatusPill key={view} tone="info" dot={false}>{view}</FAStatusPill>)
                : <span className="fa-faint-text">后端未返回影响视图</span>}
            </div>
          </div>
        </div>
      </FACard>
    </div>
  );
}
