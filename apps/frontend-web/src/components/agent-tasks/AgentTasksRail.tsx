import { RotateCcw } from "lucide-react";
import type { TaskRunSummaryViewModel } from "@/types/agent-task";
import { CATEGORY_META, inferCategory, type AgentCategoryKey } from "./agentTaskMeta";

export type AgentTaskStatusFilter = "all" | "running" | "needs_review" | "success" | "failed";

interface AgentTasksRailProps {
  runs: TaskRunSummaryViewModel[];
  activeCategory: AgentCategoryKey | "all";
  onCategoryChange: (category: AgentCategoryKey | "all") => void;
}

function countByCategory(runs: TaskRunSummaryViewModel[], category: AgentCategoryKey): number {
  return runs.filter((run) => inferCategory(run) === category).length;
}

export function AgentTasksRail({
  runs,
  activeCategory,
  onCategoryChange,
}: AgentTasksRailProps) {
  const hasActiveFilters = activeCategory !== "all";

  return (
    <aside className="rounded-[18px] border border-[var(--border)] bg-[var(--bg-panel)] p-3 xl:sticky xl:top-0">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div>
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">筛选</div>
          <div className="mt-1 text-[10px] text-[var(--fg-5)]">按 Agent 分类与运行状态定位任务。</div>
        </div>
        {hasActiveFilters ? (
          <button
            type="button"
            onClick={() => onCategoryChange("all")}
            className="inline-flex items-center gap-1 text-[10px] font-semibold text-[var(--brand-hover)] transition-colors hover:text-[var(--brand)]"
          >
            <RotateCcw size={10} />
            重置
          </button>
        ) : null}
      </div>

      <div className="space-y-5">
        <section>
          <div className="mb-2 text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">Agent 分类</div>
          <div className="space-y-1.5">
            <button
              type="button"
              onClick={() => onCategoryChange("all")}
              className={`w-full rounded-[12px] border px-3 py-2.5 text-left transition-colors ${
                activeCategory === "all"
                  ? "border-[var(--brand)] bg-[var(--brand-dim)]"
                  : "border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[12px] font-semibold text-[var(--fg-2)]">全部 Agent</div>
                  <div className="mt-1 text-[10px] text-[var(--fg-5)]">查看所有任务分组</div>
                </div>
                <span className="fa-num text-[11px] text-[var(--fg-4)]">{runs.length}</span>
              </div>
            </button>

            {(Object.keys(CATEGORY_META) as AgentCategoryKey[]).map((key) => {
              const meta = CATEGORY_META[key];
              const count = countByCategory(runs, key);
              const active = activeCategory === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => onCategoryChange(key)}
                  className={`w-full rounded-[12px] border px-3 py-2.5 text-left transition-colors ${
                    active
                      ? "border-[var(--border-strong)] bg-[var(--bg-card)]"
                      : "border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
                  }`}
                  style={{ boxShadow: active ? `inset 3px 0 0 ${meta.accent}` : undefined }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[12px] font-semibold text-[var(--fg-2)]">{meta.label}</div>
                      <div className="mt-1 text-[10px] text-[var(--fg-5)]">{meta.description}</div>
                    </div>
                    <span className="rounded-full px-2 py-1 text-[10px] font-semibold" style={{ color: meta.accent, background: `${meta.accent}18` }}>
                      {count}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </aside>
  );
}
