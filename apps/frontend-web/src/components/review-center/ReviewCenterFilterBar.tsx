import { RefreshCw, Search } from "lucide-react";
import { FAFilterBar } from "@/components/shared/FAFilterBar";
import { REVIEW_STATUS_OPTIONS, getReviewStatusLabel } from "./reviewCenterPageModel";

interface ReviewCenterFilterBarProps {
  status: string;
  onStatusChange: (value: string) => void;
  sourceModule: string;
  modules: string[];
  onSourceModuleChange: (value: string) => void;
  query: string;
  onQueryChange: (value: string) => void;
  onRefresh: () => void;
}

export function ReviewCenterFilterBar({
  status,
  onStatusChange,
  sourceModule,
  modules,
  onSourceModuleChange,
  query,
  onQueryChange,
  onRefresh,
}: ReviewCenterFilterBarProps) {
  return (
    <FAFilterBar
      left={
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">复核状态</span>
          {(["all", ...REVIEW_STATUS_OPTIONS] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onStatusChange(option)}
              className={[
                "h-8 rounded-full border px-3 text-[11px] font-semibold",
                status === option
                  ? "border-[var(--brand)] bg-[var(--bg-active)] text-[var(--brand-hover)]"
                  : "border-[var(--border)] bg-[var(--bg-card)] text-[var(--fg-4)] hover:text-[var(--fg-2)]",
              ].join(" ")}
            >
              {getReviewStatusLabel(option)}
            </button>
          ))}
        </div>
      }
      right={
        <>
          <label className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">模块</span>
            <select
              value={sourceModule}
              onChange={(event) => onSourceModuleChange(event.target.value)}
              className="min-w-[130px] bg-transparent text-[11px] text-[var(--fg-2)] outline-none"
            >
              <option value="" className="bg-[var(--bg-card)] text-[var(--fg-2)]">全部模块</option>
              {modules.map((module) => (
                <option key={module} value={module} className="bg-[var(--bg-card)] text-[var(--fg-2)]">
                  {module}
                </option>
              ))}
            </select>
          </label>
          <label className="flex h-8 min-w-[220px] items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <Search size={12} />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索复核项 / run / 原因..."
              className="w-full bg-transparent text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
            />
          </label>
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3.5 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
          >
            <RefreshCw size={12} />
            刷新
          </button>
        </>
      }
    />
  );
}
