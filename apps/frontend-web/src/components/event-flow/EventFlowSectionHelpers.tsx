import type { Jin10ArticleBrief } from "@/types/event-flow";

export function FilterDropdown({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</span>
      <div className="flex h-[28px] min-w-[80px] cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 transition-colors hover:border-[var(--border-strong)]">
        <span className="flex-1 whitespace-nowrap text-[11px] text-[var(--fg-2)]">{value}</span>
        <span className="text-[8px] text-[var(--fg-5)]">&#9662;</span>
      </div>
    </div>
  );
}

export function CountMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 fa-num text-[16px] font-semibold text-[var(--fg-1)]">{value}</div>
    </div>
  );
}

export function articleBriefTone(brief: Jin10ArticleBrief) {
  if (brief.display_bucket === "重点分析") return "warn";
  if (brief.display_bucket === "VIP预览" || brief.display_bucket === "待渲染") return "info";
  if (brief.display_bucket === "快讯") return "neutral";
  return "dim";
}
