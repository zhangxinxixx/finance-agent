interface AgentPromptFeedbackFormProps {
  rating: string;
  category: string;
  comment: string;
  isSubmitting: boolean;
  onRatingChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
  onCommentChange: (value: string) => void;
  onSubmit: () => void;
}

export function AgentPromptFeedbackForm({
  rating,
  category,
  comment,
  isSubmitting,
  onRatingChange,
  onCategoryChange,
  onCommentChange,
  onSubmit,
}: AgentPromptFeedbackFormProps) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2.5">
      <div className="text-[12px] font-semibold text-[var(--fg-2)]">人工反馈</div>
      <div className="mt-0.5 text-[11px] text-[var(--fg-4)]">反馈会追加到 Prompt Feedback；严重类别会进入 Review Center。</div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <label className="block">
          <div className="mb-1 text-[10px] text-[var(--fg-5)]">评分</div>
          <select
            value={rating}
            onChange={(event) => onRatingChange(event.target.value)}
            className="h-8 w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[11px] text-[var(--fg-2)] outline-none"
          >
            {["5", "4", "3", "2", "1"].map((value) => (
              <option key={value} value={value} className="bg-[var(--bg-card)] text-[var(--fg-2)]">
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <div className="mb-1 text-[10px] text-[var(--fg-5)]">类别</div>
          <select
            value={category}
            onChange={(event) => onCategoryChange(event.target.value)}
            className="h-8 w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[11px] text-[var(--fg-2)] outline-none"
          >
            <option value="prompt_quality" className="bg-[var(--bg-card)] text-[var(--fg-2)]">prompt_quality</option>
            <option value="analysis_error" className="bg-[var(--bg-card)] text-[var(--fg-2)]">analysis_error</option>
            <option value="missing_context" className="bg-[var(--bg-card)] text-[var(--fg-2)]">missing_context</option>
          </select>
        </label>
      </div>
      <textarea
        value={comment}
        onChange={(event) => onCommentChange(event.target.value)}
        rows={3}
        placeholder="记录 Prompt 或输出需要调整的具体问题"
        className="mt-2 w-full resize-none rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 py-2 text-[11px] leading-5 text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
      />
      <div className="mt-2 flex justify-end">
        <button
          type="button"
          disabled={isSubmitting}
          onClick={onSubmit}
          className="inline-flex h-8 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "提交中..." : "提交反馈"}
        </button>
      </div>
    </div>
  );
}
