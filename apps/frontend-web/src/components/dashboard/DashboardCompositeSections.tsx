import { useNavigate } from "react-router-dom";
import { ExternalLink, FileText, Layers as LayersIcon, Newspaper, Star, Target } from "lucide-react";

import {
  DashboardCompositeResonanceTable,
  DashboardCompositeRevisionBlock,
  DashboardCompositeSummaryBlock,
} from "./DashboardCompositeAnalysisBlocks";
import { translateText } from "./judgmentFormat";

interface DashboardCompositeHeaderProps {
  dataDate: string;
  hasFullReport: boolean;
  sourceTrace: Array<{
    source_ref: string;
    status?: string | null;
  }>;
}

interface DashboardCompositeBodyProps {
  compositeSummary: string;
  revision: string;
  confidencePct: number | null;
  resonanceItems: Array<{
    px: string;
    macro: string;
    options: string;
    verdict: string;
    kind: "support" | "pivot" | "resist" | "risk";
    core: boolean;
  }>;
}

export function DashboardCompositeHeader({ dataDate, hasFullReport, sourceTrace }: DashboardCompositeHeaderProps) {
  const navigate = useNavigate();

  return (
    <div className="fa-card-header gap-2">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--fa-important-border)] bg-[var(--fa-important-soft)]">
        <Star size={13} color="var(--fa-important)" fill="var(--fa-important)" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="fa-compact-label">
          今日综合分析摘要
        </div>
        <div className="truncate text-[12px] font-semibold leading-none text-[var(--fg-2)]">
          综合分析
        </div>
      </div>
      <span className="fa-num shrink-0 rounded border border-[var(--brand-dim)] bg-[var(--brand-dim)] px-2 py-0.5 text-[11px] font-bold text-[var(--brand)]">
        {dataDate}
      </span>
      <span className="fa-compact-label shrink-0 rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-1.5 py-0.5">
        Summary Only
      </span>
      {sourceTrace.length > 0 && (
        <div className="hidden shrink-0 items-center gap-1 xl:flex">
          {sourceTrace.map((trace) => (
            <span
              key={trace.source_ref}
              className="fa-num inline-flex items-center gap-1 rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-1.5 py-0.5 text-[10px] text-[var(--fa-text-muted)]"
            >
              <span
                className="h-[4px] w-[4px] rounded-full"
                style={{
                  background:
                    trace.status === "ok" ? "var(--up)" : trace.status === "warn" ? "var(--warn)" : trace.status === "error" ? "var(--down)" : "var(--fg-6)",
                }}
              />
              {translateText(trace.source_ref)}
            </span>
          ))}
        </div>
      )}
      <div className="flex shrink-0 items-center gap-1">
        {[
          { label: "综合日报", icon: FileText, path: "/reports", color: "var(--brand-hover)", disabled: !hasFullReport },
          { label: "CME期权", icon: LayersIcon, path: "/cme-options", color: "var(--chart-5)", disabled: false },
          { label: "事件流", icon: Newspaper, path: "/event-flow", color: "var(--info)", disabled: false },
          { label: "策略决策", icon: Target, path: "/strategy", color: "var(--warn)", disabled: false },
        ].map((btn) => {
          const Icon = btn.icon;
          return (
            <button
              key={btn.label}
              onClick={() => navigate(btn.path)}
              disabled={btn.disabled}
              className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-2 py-1 text-[9px] font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-40"
              style={{
                borderColor: `color-mix(in srgb, ${btn.color} 30%, transparent)`,
                background: `color-mix(in srgb, ${btn.color} 6%, transparent)`,
                color: btn.disabled ? "var(--fg-5)" : btn.color,
              }}
              onMouseEnter={(e) => {
                if (!btn.disabled) e.currentTarget.style.background = `color-mix(in srgb, ${btn.color} 14%, transparent)`;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = `color-mix(in srgb, ${btn.color} 6%, transparent)`;
              }}
            >
              <Icon size={10} />
              {btn.label}
              <ExternalLink size={7} className="opacity-50" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DashboardCompositeBody({
  compositeSummary,
  revision,
  confidencePct,
  resonanceItems,
}: DashboardCompositeBodyProps) {
  return (
    <div className="fa-card-body flex flex-col gap-3 px-3 py-2.5">
      <DashboardCompositeSummaryBlock compositeSummary={compositeSummary} confidencePct={confidencePct} />
      <DashboardCompositeResonanceTable items={resonanceItems} />
      <DashboardCompositeRevisionBlock revision={revision} />
    </div>
  );
}
