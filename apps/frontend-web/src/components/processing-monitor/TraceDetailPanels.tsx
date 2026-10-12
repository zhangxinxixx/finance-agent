import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import type {
  ProcessingFallbackOutput,
  ProcessingTracePathNode,
  ProcessingTraceResponse,
} from "@/types/processing-monitor";
import { operationEntityLabel, operationFieldLabel, operationReadableLabel, operationReasonLabel, operationStageLabel, operationStatusLabel } from "@/components/operations/operationsLabels";

function statusTone(value: string | null | undefined): FAStatusTone {
  const normalized = (value ?? "").toLowerCase();
  if (["matched", "covered", "pass", "success", "accepted", "primary", "fallback"].includes(normalized)) return "up";
  if (["needs_review", "degraded", "stale", "observe_wait", "partial"].includes(normalized)) return "warn";
  if (["blocked", "failed", "missing", "not_found", "none"].includes(normalized)) return "down";
  return "neutral";
}

function displayValue(value: unknown, key?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string" && ["status", "review_status", "accepted_output_source", "severity", "mode"].includes(key ?? "")) {
    return operationStatusLabel(value);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (/[\u3400-\u9fff]/.test(trimmed)) return trimmed;
    if (trimmed.includes("_") || trimmed.includes("://") || trimmed.includes("/") || ["fixture", "mock", "raw", "parsed"].includes(trimmed.toLowerCase())) {
      return operationReadableLabel(trimmed);
    }
    return trimmed;
  }
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return `${value.length} 项记录`;
  return "记录已登记";
}

function isTechnicalField(key: string): boolean {
  return /(^|_)(id|ids|ref|refs|path|url|endpoint)$/.test(key) || ["run_id", "snapshot_id", "file_path"].includes(key);
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
          <dt className="fa-label break-all">{operationFieldLabel(key)}</dt>
          <dd className="fa-body-text break-all">
            {isTechnicalField(key) || (typeof value === "object" && value !== null) ? (
              <div>
                <div>{displayValue(value, key)}</div>
                <div className="mt-2"><EvidenceRecordActions record={value} label={`${operationFieldLabel(key)}依据`} /></div>
              </div>
            ) : displayValue(value, key)}
          </dd>
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
        <div className="fa-card-title">主结果</div>
        <FAStatusPill tone={statusTone(output?.status)} dot={false}>{operationStatusLabel(output?.status ?? "missing")}</FAStatusPill>
      </div>
      <PayloadRows payload={payload} />
    </div>
  );
}

function FallbackOutputRows({ outputs }: { outputs: ProcessingFallbackOutput[] }) {
  if (!outputs.length) return <div className="fa-faint-text">后端未返回回退候选</div>;
  return (
    <div className="grid gap-2">
      {outputs.map((output, index) => (
        <div key={`${output.agent_name}-${output.snapshot_id ?? index}`} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="fa-card-title">{output.agent_name || "代理名称待确认"}</span>
            <span className="fa-num fa-muted-text">{output.confidence ?? "—"}</span>
          </div>
          <div className="mt-2 fa-body-text break-words">{output.summary ?? (output.snapshot_id ? "回退结果已登记" : "—")}</div>
          <div className="mt-1 fa-faint-text">偏向：{output.bias ?? "未返回"}</div>
          <div className="mt-2"><EvidenceRecordActions record={output} label="回退结果依据" /></div>
        </div>
      ))}
    </div>
  );
}

function FallbackOutputPanel({ trace }: { trace: ProcessingTraceResponse }) {
  const overrideAction = displayValue(trace.fallback_review.strategy_card_override.action, "status");
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="fa-card-title">回退结果</div>
        <FAStatusPill tone={trace.fallback_review.fallback_used ? "warn" : "neutral"} dot={false}>
          {trace.fallback_review.fallback_used ? "已使用" : "未使用"}
        </FAStatusPill>
      </div>
      <FallbackOutputRows outputs={trace.fallback_outputs} />
      {trace.fallback_review.no_strong_conclusion || overrideAction !== "—" ? (
        <div className="mt-3 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2">
          <div className="fa-label text-[var(--warn)]">回退复核</div>
          <div className="mt-1 fa-body-text">
            当前不可下强结论：{trace.fallback_review.no_strong_conclusion ? "是" : "否"}
            <span className="mx-2 text-[var(--fg-5)]">·</span>
            处理：{overrideAction}
          </div>
        </div>
      ) : null}
      <div className="mt-3 grid gap-2">
        <div>
          <div className="fa-label">原因</div>
          <div className="mt-1 fa-body-text break-words">
            {trace.fallback_review.reasons.length ? trace.fallback_review.reasons.map(operationReasonLabel).join(" / ") : "—"}
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
        <div className="fa-card-title">最终采用</div>
        <FAStatusPill tone={statusTone(trace.accepted_output_source)} dot={false}>
          来源：{operationStatusLabel(trace.accepted_output_source)}
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
          <div className="fa-card-title">{node.label || "阶段节点待确认"}</div>
          <div className="mt-1 fa-faint-text">{operationStageLabel(node.stage)} · 范围：{node.scope === "run" ? "本次运行" : node.scope === "event" ? "事件" : "待确认"}</div>
        </div>
        <FAStatusPill tone={statusTone(node.status)} dot={false}>{operationStatusLabel(node.status)}</FAStatusPill>
      </div>
      <div className="mt-2 grid gap-1 fa-muted-text">
        <div>
          <div>来源引用（{node.source_ref_count}）</div>
          {visibleSourceRefs.length
            ? visibleSourceRefs.map((ref) => <div key={ref.source_ref} className="mt-2"><EvidenceRecordActions record={ref} label="来源依据" /></div>)
            : <div>—</div>}
          {node.source_refs.length > visibleSourceRefs.length
            ? <div className="fa-faint-text">另 {node.source_refs.length - visibleSourceRefs.length} 条</div>
            : null}
        </div>
        <div>
          <div>产物引用（{node.artifact_ref_count}）</div>
          {visibleArtifactRefs.length
            ? visibleArtifactRefs.map((ref, index) => {
                return <div key={`${ref.path ?? ref.file_path ?? ref.artifact_id ?? "artifact"}-${index}`} className="mt-2"><EvidenceRecordActions record={ref} label="产物依据" /></div>;
              })
            : <div>—</div>}
          {node.artifact_refs.length > visibleArtifactRefs.length
            ? <div className="fa-faint-text">另 {node.artifact_refs.length - visibleArtifactRefs.length} 条</div>
            : null}
        </div>
        <div className="space-y-2">
          <div>提醒：{node.warnings.length ? `${node.warnings.length} 项提醒已登记` : "无"}</div>
          {node.warnings.length ? <EvidenceRecordActions record={node.warnings} label="阶段提醒依据" /> : null}
        </div>
        <div className="space-y-2">
          <div>缺失数据：{node.missing_data.length ? `${node.missing_data.length} 项缺口已登记` : "无"}</div>
          {node.missing_data.length ? <EvidenceRecordActions record={node.missing_data} label="缺失数据依据" /> : null}
        </div>
        <div>
          分析产物：{node.agent_artifact_refs.length
            ? <div><div>{node.agent_artifact_refs.length} 条分析产物已登记</div>{node.agent_artifact_refs.map((ref) => <div key={`${ref.agent_name}-${ref.file_path}`} className="mt-2"><EvidenceRecordActions record={ref} label="分析产物依据" /></div>)}</div>
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
        title="链路摘要"
        eyebrow="审计信息"
        accent={trace.status === "matched" ? "up" : "warn"}
        action={<FAStatusPill tone={statusTone(header.status)}>{operationStatusLabel(header.status)}</FAStatusPill>}
      >
        <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            { label: "加工链路标识", value: header.trace_id, technical: true },
            { label: "运行标识", value: header.run_id, technical: true },
            { label: "关联对象", value: operationEntityLabel(header.entity_type), technical: false },
            { label: "复核状态", value: header.review_status, technical: false },
            { label: "发布权限", value: header.publish_allowed, technical: false },
            { label: "数据截至", value: header.as_of, technical: false },
            { label: "产物质量", value: trace.source_health.overall_status, technical: false },
            { label: "读取时质量", value: trace.read_time_source_health.overall_status, technical: false },
          ].map(({ label, value, technical }) => (
            <div key={String(label)} className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-3 py-2">
              <dt className="fa-label">{String(label)}</dt>
              <dd className="mt-1 fa-num fa-body-text break-all">
                {technical ? <EvidenceRecordActions record={value} label={`${label}依据`} /> : displayValue(value, label === "复核状态" || label === "产物质量" || label === "读取时质量" ? "status" : undefined)}
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 grid gap-2 fa-muted-text">
          <div>页面读取时间：{trace.read_time_generated_at ?? "—"}</div>
          <div className="space-y-2">读取提醒：{trace.read_time_warnings.length ? `${trace.read_time_warnings.length} 项提醒已登记` : "无"}{trace.read_time_warnings.length ? <EvidenceRecordActions record={trace.read_time_warnings} label="读取提醒依据" /> : null}</div>
          <div className="space-y-2">质量提醒：{trace.quality_gate.warnings.length ? `${trace.quality_gate.warnings.length} 项提醒已登记` : "无"}{trace.quality_gate.warnings.length ? <EvidenceRecordActions record={trace.quality_gate.warnings} label="质量提醒依据" /> : null}</div>
        </div>
      </FACard>

      <FACard title="分析输出选择" eyebrow="主结果 / 回退结果 / 最终采用" accent="emphasis">
        <div className="grid gap-3 xl:grid-cols-3">
          <PrimaryOutputPanel trace={trace} />
          <FallbackOutputPanel trace={trace} />
          <AcceptedOutputPanel trace={trace} />
        </div>
      </FACard>

      <FACard title="阶段审计" eyebrow="后端返回的阶段信息" accent="info">
        {trace.trace_path.length ? (
          <div className="grid gap-2 lg:grid-cols-2">
            {trace.trace_path.map((node) => <StageAuditRow key={node.node_id} node={node} />)}
          </div>
        ) : (
          <FAEmptyState title="暂无阶段审计" description="后端未返回链路阶段。" />
        )}
      </FACard>

      <FACard title="证据与影响视图" eyebrow="详细证据字段" accent="info">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div>
            <div className="fa-card-title">输入快照</div>
            <div className="mt-2"><PayloadRows payload={trace.input_snapshot_ids} /></div>
          </div>
          <div>
            <div className="fa-card-title">证据引用</div>
            <div className="mt-2"><PayloadRows payload={{ items: trace.evidence_refs }} /></div>
          </div>
          <div>
            <div className="fa-card-title">证据条目</div>
            <div className="mt-2"><PayloadRows payload={{ items: trace.evidence_items }} /></div>
          </div>
          <div>
            <div className="fa-card-title">受影响视图</div>
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
