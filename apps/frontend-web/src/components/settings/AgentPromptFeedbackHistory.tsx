import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import type { PromptFeedbackItem } from "@/types/agent-registry";
import { formatSettingsTime } from "./settingsFormat";
import { feedbackCategoryLabel, feedbackStatusLabel } from "./settingsFormat";

interface AgentPromptFeedbackHistoryProps {
  feedbackHistory: PromptFeedbackItem[];
  isLoading: boolean;
  error: string | null;
}

export function AgentPromptFeedbackHistory({ feedbackHistory, isLoading, error }: AgentPromptFeedbackHistoryProps) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)]">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--border-faint)] px-2.5 py-2">
        <div>
          <div className="text-[12px] font-semibold text-[var(--fg-2)]">反馈历史</div>
          <div className="mt-0.5 text-[11px] text-[var(--fg-4)]">最近 8 条提示词反馈，只读展示，不改写历史输出。</div>
        </div>
        <FAStatusPill tone="dim" dot={false} className="fa-num">
          {feedbackHistory.length}
        </FAStatusPill>
      </div>
      <div className="space-y-2 p-2.5">
        {error ? <div className="text-[11px] text-[var(--down)]">{error}</div> : null}
        {!error && isLoading ? <div className="text-[11px] text-[var(--fg-4)]">加载反馈历史...</div> : null}
        {!error && !isLoading && feedbackHistory.length === 0 ? (
          <div className="text-[11px] text-[var(--fg-4)]">暂无反馈记录。</div>
        ) : null}
        {feedbackHistory.map((item) => (
          <div key={item.feedback_id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <FAStatusPill tone={item.status === "open" ? "warn" : "dim"} className="text-[12px]">
                    {feedbackStatusLabel(item.status)}
                  </FAStatusPill>
                  <FAStatusPill tone={item.category === "analysis_error" || item.category === "missing_context" ? "down" : "neutral"} className="text-[12px]">
                    {feedbackCategoryLabel(item.category)}
                  </FAStatusPill>
                  {item.rating ? (
                    <span className="fa-num text-[10px] text-[var(--fg-4)]">评分 {item.rating}</span>
                  ) : null}
                </div>
                <div className="mt-1 line-clamp-2 text-[11px] leading-5 text-[var(--fg-2)]">
                  {item.comment || "未填写反馈内容"}
                </div>
              </div>
              <div className="shrink-0 text-right text-[10px] text-[var(--fg-5)]">
                <div className="fa-num">{formatSettingsTime(item.created_at ?? null)}</div>
                {item.review_item_id ? <details className="mt-1 text-[var(--warn)]"><summary className="cursor-pointer">查看复核记录</summary><EvidenceRecordActions label="脱敏复核记录" record={{ review_item_id: item.review_item_id }} /></details> : null}
              </div>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-5)]">
              {item.run_id || item.agent_output_id || item.prompt_version_id ? <details><summary className="cursor-pointer">查看关联记录</summary><EvidenceRecordActions label="脱敏关联记录" record={{ run_id: item.run_id, agent_output_id: item.agent_output_id, prompt_version_id: item.prompt_version_id }} /></details> : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
