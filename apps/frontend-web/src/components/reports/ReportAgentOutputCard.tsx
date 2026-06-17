import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getDataStatusLabel } from "@/lib/status";
import type { ReportAnalysisAgentOutputView } from "@/types/reports";
import { ReportTraceDrilldown } from "./ReportTraceDrilldown";
import { factReviewLabel, factReviewTone, isSynthesisOutput, statusTone } from "./reportDetailMeta";
import { ReportAgentOutputFeedbackForm } from "./ReportAgentOutputFeedbackForm";

export function ReportAgentOutputCard({ item }: { item: ReportAnalysisAgentOutputView }) {
  const modelLabel = item.llm_model ?? (item.generated_by === "rule" ? "rule-based" : null);

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-[var(--fg-1)]">{item.display_name}</div>
          <div className="mt-1 text-[11px] text-[var(--fg-4)]">
            {item.registry_id ?? item.agent_name} · {item.role} · {item.generated_by ?? "rule"}
          </div>
          <div className="mt-1 text-[11px] text-[var(--fg-4)]">
            分析 Agent：{item.agent_name}
            {modelLabel ? ` · 模型：${modelLabel}` : ""}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <FAStatusPill tone={statusTone(item.status)}>{getDataStatusLabel(item.status)}</FAStatusPill>
          {item.fact_review_status ? (
            <FAStatusPill tone={factReviewTone(item.fact_review_status)}>{factReviewLabel(item.fact_review_status)}</FAStatusPill>
          ) : null}
          <FAStatusPill tone="neutral">{item.bias || "neutral"}</FAStatusPill>
          <FAStatusPill tone="info">置信 {item.confidence.toFixed(2)}</FAStatusPill>
        </div>
      </div>

      <div className="mt-3 text-[12px] leading-6 text-[var(--fg-2)]">{item.summary_zh || item.summary || "-"}</div>

      <div className="mt-3 grid gap-2 text-[11px] text-[var(--fg-4)] sm:grid-cols-2 xl:grid-cols-4">
        <div>claims：{item.claim_count}</div>
        <div>prompt：{item.prompt_version ?? "-"}</div>
        <div>sources：{item.source_refs.length}</div>
        <div>artifacts：{item.artifact_refs.length}</div>
      </div>

      <div className="mt-2 grid gap-2 text-[11px] text-[var(--fg-4)] sm:grid-cols-2 xl:grid-cols-4">
        <div>run：{item.run_id ?? "-"}</div>
        <div>snapshot：{item.snapshot_id ?? "-"}</div>
        <div>module：{item.module}</div>
        <div>created_at：{item.created_at ?? "-"}</div>
      </div>

      {item.key_findings.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.key_findings.slice(0, 4).map((finding) => (
            <span
              key={finding}
              className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-terminal)] px-2 py-1 text-[11px] text-[var(--fg-3)]"
            >
              {finding}
            </span>
          ))}
        </div>
      ) : null}

      <ReportTraceDrilldown
        sourceRefs={item.source_refs}
        artifactRefs={item.artifact_refs}
        payload={{
          summary: item.summary,
          summary_zh: item.summary_zh,
          key_findings: item.key_findings,
          risk_points: item.risk_points,
          watchlist: item.watchlist,
          invalid_conditions: item.invalid_conditions,
          fact_review_status: item.fact_review_status ?? null,
          prompt_version: item.prompt_version ?? null,
          llm_model: item.llm_model ?? null,
          generated_by: item.generated_by ?? null,
        }}
      />

      <ReportAgentOutputFeedbackForm item={item} />

      {isSynthesisOutput(item) && item.risk_points.length > 0 ? (
        <div className="mt-3 space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">待复核与降权说明</div>
          <div className="space-y-2">
            {item.risk_points.slice(0, 3).map((riskPoint) => (
              <div
                key={riskPoint}
                className="rounded-[var(--radius-md)] border border-[rgba(245,158,11,0.18)] bg-[rgba(245,158,11,0.06)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-3)]"
              >
                {riskPoint}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {isSynthesisOutput(item) && item.invalid_conditions.length > 0 ? (
        <div className="mt-3 space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">被排除或冲突的结论</div>
          <div className="flex flex-wrap gap-2">
            {item.invalid_conditions.slice(0, 4).map((entry) => (
              <span
                key={entry}
                className="rounded-[var(--radius-md)] border border-[rgba(245,158,11,0.18)] bg-[rgba(245,158,11,0.06)] px-2 py-1 text-[11px] text-[var(--fg-3)]"
              >
                {entry}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {isSynthesisOutput(item) && item.watchlist.length > 0 ? (
        <div className="mt-3 space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">建议阅读顺序</div>
          <div className="flex flex-wrap gap-2">
            {item.watchlist.slice(0, 4).map((entry) => (
              <span
                key={entry}
                className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-terminal)] px-2 py-1 text-[11px] text-[var(--fg-3)]"
              >
                {entry}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
