import { useState } from "react";

import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { useAnalysisMemory } from "@/hooks/useAnalysisMemory";
import type { AnalysisStateScope, AnalysisStateView } from "@/types/analysis-memory";

const SCOPE_LABELS: Record<AnalysisStateScope, string> = {
  intraday: "日内",
  daily_close: "日收盘",
  weekly_fundamental: "周度基本面",
};

function shortId(value: string | null | undefined): string {
  return value ? (value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value) : "—";
}

function thesis(state: AnalysisStateView): string {
  return typeof state.payload.core_thesis === "string" ? state.payload.core_thesis : "未提供 core thesis";
}

function TransitionDiff({ state }: { state: AnalysisStateView }) {
  const changes = state.transition?.changes ?? [];
  return changes.length ? (
    <div className="mt-2 space-y-1">
      {changes.map((raw, index) => (
        <div key={`${state.state_id}-change-${index}`} className="grid gap-1 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5 md:grid-cols-[120px_90px_1fr]">
          <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-3)]">{String(raw.target ?? "unknown")}</span>
          <span className="text-[length:var(--type-caption)] font-semibold text-[var(--info)]">{String(raw.action ?? "unknown")}</span>
          <span className="text-[length:var(--type-caption)] text-[var(--fg-4)]">{String(raw.reason ?? "无说明")}</span>
        </div>
      ))}
    </div>
  ) : null;
}

export function AnalysisMemoryPanel({ allowReview = false }: { allowReview?: boolean }) {
  const [stateScope, setStateScope] = useState<AnalysisStateScope>("daily_close");
  const memory = useAnalysisMemory(stateScope);
  const [token, setToken] = useState("");
  const [actor, setActor] = useState("review-center");
  const [reason, setReason] = useState("");

  if (memory.isLoading && !memory.data) {
    return <FACard title="Analysis Memory" eyebrow="State observability" accent="info"><div className="fa-muted-text">正在读取状态链与 ContextBundle metadata…</div></FACard>;
  }
  if (!memory.data) {
    return <FACard title="Analysis Memory" eyebrow="State observability" accent="warn"><div className="fa-muted-text">当前无可用 canonical state：{memory.error?.message ?? "尚未初始化"}</div></FACard>;
  }

  const { canonical, candidates, bundles } = memory.data;
  const latestBundle = bundles.data[0];
  return (
    <FACard
      title="Analysis Memory 状态链"
      eyebrow="Accepted canonical / isolated candidates"
      description="正式状态只读取 accepted canonical；candidate 与 blocked 保持隔离，GET 不触发模型。"
      accent="info"
      bodyClassName="space-y-3"
    >
      {memory.error || memory.data.warnings.length ? <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-body-sm)] text-[var(--warn)]">{memory.error?.message ?? memory.data.warnings.join("；")}</div> : null}

      <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
        <div>
          <div className="fa-label">State scope</div>
          <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前仅观察 {SCOPE_LABELS[stateScope]}（{stateScope}）状态链。</div>
        </div>
        <select
          value={stateScope}
          onChange={(event) => setStateScope(event.target.value as AnalysisStateScope)}
          className="h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[length:var(--type-label)] text-[var(--fg-2)]"
          aria-label="Analysis Memory state scope"
        >
          {(Object.entries(SCOPE_LABELS) as Array<[AnalysisStateScope, string]>).map(([value, label]) => (
            <option key={value} value={value}>{label} · {value}</option>
          ))}
        </select>
      </div>

      {canonical ? <div className="rounded-[var(--radius-md)] border border-[var(--up-border)] bg-[var(--up-soft)] p-3">
        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill tone="up">正式 accepted canonical · {canonical.state_scope}</FAStatusPill>
          <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-4)]">head v{canonical.head_version} · {shortId(canonical.state.state_id)}</span>
        </div>
        <div className="mt-2 fa-card-title text-[var(--fg-1)]">{thesis(canonical.state)}</div>
        <div className="mt-2 grid gap-1 text-[length:var(--type-caption)] text-[var(--fg-3)] md:grid-cols-2">
          <span>run: <b className="fa-num">{shortId(canonical.state.lineage.run_id)}</b></span>
          <span>snapshot: <b className="fa-num">{shortId(canonical.state.lineage.accepted_output_snapshot_id)}</b></span>
          <span>sources: {canonical.state.lineage.source_refs.length}</span>
          <span>artifacts: {canonical.state.lineage.artifact_ids.length}</span>
        </div>
      </div> : <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] p-3 text-[length:var(--type-body-sm)] text-[var(--warn)]">尚无 accepted canonical；candidate 仅供查看，不能升级为正式状态。</div>}

      <div>
        <div className="fa-label mb-2">Canonical chain（新 → 旧）</div>
        <div className="flex flex-wrap gap-2">
          {canonical?.canonical_chain.map((state, index) => (
            <div key={state.state_id} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5 text-[length:var(--type-caption)] text-[var(--fg-3)]">
              <span className="fa-num">#{canonical.canonical_chain.length - index}</span> · {shortId(state.state_id)} · {state.quality_gate_action}
            </div>
          )) ?? <span className="fa-faint-text">canonical chain 尚未初始化。</span>}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between gap-2">
          <div className="fa-label">隔离候选（{candidates.pagination.total_items}）</div>
          <button type="button" onClick={() => void memory.refetch()} className="fa-workspace-toolbar-button">刷新状态</button>
        </div>
        <div className="mt-2 space-y-2">
          {candidates.data.length ? candidates.data.map((candidate) => (
            <div key={candidate.state_id} className={`rounded-[var(--radius-md)] border p-3 ${candidate.state_kind === "blocked" ? "border-[var(--down-border)] bg-[var(--down-soft)]" : "border-[var(--warn-border)] bg-[var(--warn-soft)]"}`}>
              <div className="flex flex-wrap items-center gap-2">
                <FAStatusPill tone={candidate.state_kind === "blocked" ? "down" : "warn"}>{candidate.state_kind === "blocked" ? "blocked / 不可采用" : "candidate / 待复核"} · {candidate.state_scope}</FAStatusPill>
                <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-4)]">{shortId(candidate.state_id)} · run {shortId(candidate.lineage.run_id)}</span>
              </div>
              <div className="mt-2 text-[length:var(--type-body)] text-[var(--fg-2)]">{thesis(candidate)}</div>
              <TransitionDiff state={candidate} />
              {allowReview && candidate.state_kind === "candidate" ? (
                <div className="mt-3 grid gap-2 md:grid-cols-[150px_1fr_1fr_auto]">
                  <input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="review actor" className="h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[length:var(--type-label)] text-[var(--fg-2)]" />
                  <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="复核依据（必填）" className="h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[length:var(--type-label)] text-[var(--fg-2)]" />
                  <input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="写权限 token" className="h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[length:var(--type-label)] text-[var(--fg-2)]" />
                  <button
                    type="button"
                    disabled={!canonical || !actor.trim() || !reason.trim() || !token.trim() || memory.actionCandidateId !== null}
                    onClick={() => void memory.acceptCandidate({ candidateId: candidate.state_id, actor, reason, token })}
                    className="fa-workspace-toolbar-button disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {memory.actionCandidateId === candidate.state_id ? "接受中" : "接受为新 canonical"}
                  </button>
                </div>
              ) : null}
            </div>
          )) : <div className="fa-faint-text">当前没有 candidate / blocked 状态。</div>}
        </div>
      </div>

      <div>
        <div className="fa-label mb-2">ContextBundle token composition</div>
        {latestBundle ? (
          <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <FAStatusPill tone={latestBundle.within_budget ? "up" : "down"}>{latestBundle.within_budget ? "预算内" : "超预算"}</FAStatusPill>
              <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-3)]">{latestBundle.estimated_tokens.toLocaleString()} / {latestBundle.budget_tokens.toLocaleString()} tokens</span>
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              {latestBundle.blocks.map((block) => (
                <div key={block.name} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] px-2 py-1.5">
                  <div className="fa-label">{block.name}</div>
                  <div className="mt-1 fa-num text-[length:var(--type-body-sm)] text-[var(--fg-2)]">{block.estimated_tokens.toLocaleString()} tokens</div>
                </div>
              ))}
            </div>
            <div className="mt-2 break-all text-[length:var(--type-caption)] text-[var(--fg-4)]">
              scope {latestBundle.state_scope} · run {shortId(latestBundle.run_id)} · canonical {shortId(latestBundle.canonical_state_id)} · sources {latestBundle.source_refs.length} · artifact {latestBundle.artifact_path}
            </div>
          </div>
        ) : <div className="fa-faint-text">暂无 ContextBundle metadata；不会从 GET 触发重新生成。</div>}
      </div>
    </FACard>
  );
}
