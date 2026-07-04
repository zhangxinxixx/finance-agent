import { AlertTriangle, Layers, Target } from "lucide-react";

interface ResonanceItem {
  px: string;
  macro: string;
  options: string;
  verdict: string;
  kind: "support" | "pivot" | "resist" | "risk";
  core: boolean;
}

export function DashboardCompositeSummaryBlock({
  compositeSummary,
  confidencePct,
}: {
  compositeSummary: string;
  confidencePct: number | null;
}) {
  return (
    <div className="relative overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="pointer-events-none absolute inset-y-0 left-0 w-[3px] bg-[var(--fa-important)]" />
      <div className="flex gap-3 pl-1">
        <Target size={14} className="mt-0.5 shrink-0 text-[var(--brand-hover)]" />
        <div className="min-w-0 flex-1">
          <div className="fa-compact-label mb-1">
            综合结论
          </div>
          <div className="text-[13px] leading-[1.6] text-[var(--fg-2)]">{compositeSummary}</div>
        </div>
        <div className="flex w-[118px] shrink-0 flex-col justify-center gap-1 border-l border-[var(--border)] pl-3">
          <span className="fa-compact-label">确信度</span>
          <div className="flex items-end gap-1">
            <span className="fa-num text-[24px] font-bold leading-none text-[var(--fa-important)]">
              {confidencePct ?? "—"}
            </span>
            <span className="pb-0.5 text-[10px] text-[var(--fa-text-muted)]">/100</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-[var(--border-faint)]">
            <div className="h-full rounded-full bg-[var(--fa-important)]" style={{ width: `${Math.max(0, Math.min(100, confidencePct ?? 0))}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}

export function DashboardCompositeResonanceTable({ items }: { items: ResonanceItem[] }) {
  if (!items.length) {
    return null;
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5">
        <Layers size={12} className="text-[var(--brand-hover)]" />
        <span className="text-[12px] font-semibold leading-none text-[var(--fg-2)]">关键位速览</span>
        <span className="fa-compact-meta">基于当前期权结构与综合结论</span>
      </div>
      <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)]">
        <div className="fa-compact-label grid grid-cols-[112px_1.1fr_1.3fr_1fr] border-b border-[var(--border)] bg-[var(--bg-section)] px-3 py-2">
          <span>价位</span>
          <span>宏观含义</span>
          <span>期权含义</span>
          <span>综合判断</span>
        </div>
        {items.map((r, i) => {
          const pxColor = r.kind === "support" ? "var(--up)" : r.kind === "resist" ? "var(--down)" : r.kind === "risk" ? "var(--warn)" : "var(--brand-hover)";
          return (
            <div
              key={`${r.kind}-${r.px}-${i}`}
              className={`grid grid-cols-[112px_1.1fr_1.3fr_1fr] items-center px-3 py-2.5 text-[11px] leading-[1.5] transition-colors hover:bg-[var(--bg-hover)] ${i === items.length - 1 ? "" : "border-b border-[var(--border)]"}`}
            >
              <div className="flex items-center gap-1.5">
                <span className="h-[14px] w-[3px] rounded-[1px]" style={{ background: pxColor }} />
                <span className="fa-num text-[12px] font-bold" style={{ color: pxColor }}>
                  {r.px}
                </span>
              </div>
              <span className="text-[var(--fg-3)]">{r.macro}</span>
              <span className="text-[var(--fg-3)]">{r.options}</span>
              <span className={r.core ? "font-semibold text-[var(--fg-2)]" : "text-[var(--fg-3)]"}>{r.verdict}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DashboardCompositeRevisionBlock({ revision }: { revision: string }) {
  return (
    <div className="flex items-start gap-2 rounded-[var(--radius-lg)] border border-[var(--warn-border)] bg-[var(--warn-soft)] p-3">
      <AlertTriangle size={12} className="mt-px shrink-0 text-[var(--warn)]" />
      <div className="flex-1">
        <span className="fa-compact-label mr-2 text-[var(--warn)]">改判条件</span>
        <span className="text-[11px] leading-[1.6] text-[var(--fg-3)]">{revision}</span>
      </div>
    </div>
  );
}
