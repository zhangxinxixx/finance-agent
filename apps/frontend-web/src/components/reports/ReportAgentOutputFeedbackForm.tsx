import { useState } from "react";
import { createAgentPromptFeedback } from "@/adapters/agentRegistry";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { ReportAnalysisAgentOutputView } from "@/types/reports";

export function ReportAgentOutputFeedbackForm({ item }: { item: ReportAnalysisAgentOutputView }) {
  const [feedbackRating, setFeedbackRating] = useState("3");
  const [feedbackCategory, setFeedbackCategory] = useState("prompt_quality");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [feedbackMessage, setFeedbackMessage] = useState<{ tone: "info" | "down"; text: string } | null>(null);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);

  async function handleSubmitFeedback() {
    const comment = feedbackComment.trim();
    if (!comment) {
      setFeedbackMessage({ tone: "down", text: "请填写需要复核或修正的具体问题。" });
      return;
    }
    setIsSubmittingFeedback(true);
    setFeedbackMessage(null);
    try {
      await createAgentPromptFeedback({
        agent_id: item.registry_id || item.agent_name,
        agent_output_id: item.agent_output_id,
        run_id: item.run_id ?? undefined,
        rating: Number(feedbackRating),
        category: feedbackCategory,
        comment,
        submitted_by: "codex",
        request_id: `report-feedback-${item.agent_output_id}-${Date.now()}`,
      });
      setFeedbackComment("");
      setFeedbackMessage({ tone: "info", text: "反馈已追加，不会修改历史 AgentOutput。" });
    } catch (cause) {
      setFeedbackMessage({
        tone: "down",
        text: cause instanceof Error ? cause.message : "反馈提交失败。",
      });
    } finally {
      setIsSubmittingFeedback(false);
    }
  }

  return (
    <div className="mt-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[11px] font-semibold text-[var(--fg-2)]">Prompt / 输出反馈</div>
          <div className="mt-1 text-[10px] text-[var(--fg-5)]">针对本报告引用的 AgentOutput 追加反馈。</div>
        </div>
        {feedbackMessage ? (
          <FAStatusPill tone={feedbackMessage.tone === "info" ? "info" : "down"} className="text-[12px]">
            {feedbackMessage.text}
          </FAStatusPill>
        ) : null}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[90px_150px_minmax(0,1fr)_auto]">
        <select
          value={feedbackRating}
          onChange={(event) => setFeedbackRating(event.target.value)}
          className="h-8 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[11px] text-[var(--fg-2)] outline-none"
          aria-label="反馈评分"
        >
          {["5", "4", "3", "2", "1"].map((value) => (
            <option key={value} value={value} className="bg-[var(--bg-card)] text-[var(--fg-2)]">
              {value}
            </option>
          ))}
        </select>
        <select
          value={feedbackCategory}
          onChange={(event) => setFeedbackCategory(event.target.value)}
          className="h-8 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[11px] text-[var(--fg-2)] outline-none"
          aria-label="反馈类别"
        >
          <option value="prompt_quality" className="bg-[var(--bg-card)] text-[var(--fg-2)]">
            prompt_quality
          </option>
          <option value="analysis_error" className="bg-[var(--bg-card)] text-[var(--fg-2)]">
            analysis_error
          </option>
          <option value="missing_context" className="bg-[var(--bg-card)] text-[var(--fg-2)]">
            missing_context
          </option>
        </select>
        <input
          value={feedbackComment}
          onChange={(event) => setFeedbackComment(event.target.value)}
          placeholder="记录本报告 Agent 输出需要复核的问题"
          className="h-8 min-w-0 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
        />
        <button
          type="button"
          disabled={isSubmittingFeedback}
          onClick={handleSubmitFeedback}
          className="inline-flex h-8 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmittingFeedback ? "提交中..." : "提交"}
        </button>
      </div>
    </div>
  );
}
