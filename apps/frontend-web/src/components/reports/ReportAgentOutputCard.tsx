import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getDataStatusLabel } from "@/lib/status";
import type { ReportAnalysisAgentOutputView } from "@/types/reports";
import { ReportTraceDrilldown } from "./ReportTraceDrilldown";
import { biasLabel, factReviewLabel, factReviewTone, generationModeLabel, isSynthesisOutput, statusTone } from "./reportDetailMeta";
import { ReportAgentOutputFeedbackForm } from "./ReportAgentOutputFeedbackForm";

export function ReportAgentOutputCard({ item }: { item: ReportAnalysisAgentOutputView }) {
  const modelLabel = item.llm_model ?? null;

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-[var(--fg-1)]">{item.display_name}</div>
          <div className="mt-1 text-[11px] text-[var(--fg-4)]">{modelLabel ? `模型：${modelLabel}` : "智能体输出"}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <FAStatusPill tone={statusTone(item.status)}>{getDataStatusLabel(item.status)}</FAStatusPill>
          {item.fact_review_status ? (
            <FAStatusPill tone={factReviewTone(item.fact_review_status)}>{factReviewLabel(item.fact_review_status)}</FAStatusPill>
          ) : null}
          <FAStatusPill tone="neutral">{biasLabel(item.bias)}</FAStatusPill>
          <FAStatusPill tone="info">置信度 {item.confidence.toFixed(2)}</FAStatusPill>
        </div>
      </div>

      <div className="mt-3 text-[12px] leading-6 text-[var(--fg-2)]">{item.summary_zh || item.summary || "-"}</div>

      <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-[var(--fg-4)]">
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
          结论 {item.claim_count}
        </span>
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
          来源 {item.source_refs.length}
        </span>
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
          产物 {item.artifact_refs.length}
        </span>
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
          {generationModeLabel(item.generated_by)}
        </span>
        {item.created_at ? (
          <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
            {item.created_at}
          </span>
        ) : null}
      </div>

      {item.key_findings.length > 0 ? (
        <div className="mt-3 space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">关键结论</div>
          <div className="space-y-1.5">
            {item.key_findings.slice(0, 3).map((finding) => (
              <div
                key={finding}
                className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2.5 py-2 text-[11px] leading-5 text-[var(--fg-3)]"
              >
                {finding}
              </div>
            ))}
          </div>
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
        payloadTitle="技术载荷"
      />

      <details className="mt-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)]">
        <summary className="cursor-pointer list-none px-3 py-2 text-[11px] font-semibold text-[var(--fg-3)]">反馈记录</summary>
        <div className="border-t border-[var(--border-faint)] px-3 py-3">
          <ReportAgentOutputFeedbackForm item={item} />
        </div>
      </details>

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
