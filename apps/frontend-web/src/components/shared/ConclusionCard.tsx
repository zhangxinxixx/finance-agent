import type { DashboardSummary } from "@/types/dashboard";
import { FACard } from "./FACard";
import { FAMetricCard } from "./FAMetricCard";
import { FAStatusPill } from "./FAStatusPill";
import { getStatusMeta } from "./statusMeta";

interface ConclusionCardProps {
  summary: DashboardSummary["conclusion"];
  isLoading?: boolean;
}

function directionLabel(direction: DashboardSummary["conclusion"]["direction"]) {
  if (direction === "bullish") return "看多";
  if (direction === "bearish") return "看空";
  return "中性";
}

function directionStatus(direction: DashboardSummary["conclusion"]["direction"]) {
  if (direction === "bullish") return "ok";
  if (direction === "bearish") return "error";
  return "neutral";
}

export function ConclusionCard({ summary, isLoading = false }: ConclusionCardProps) {
  const badgeStatus = directionStatus(summary.direction);
  const badgeMeta = getStatusMeta(badgeStatus, { label: directionLabel(summary.direction) });

  return (
    <section className="finance-panel p-0">
      <div className="finance-panel-header">
        <div>
          <div className="finance-panel-title">策略结论</div>
          <div className="finance-panel-subtitle">只读摘要层，统一收口 Dashboard 的方向与风险信号</div>
        </div>
      </div>

      <div className="p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <FAStatusPill status={badgeStatus} tone={badgeMeta.tone} label={badgeMeta.label} className="whitespace-nowrap px-2 py-1">
                {badgeMeta.label}
              </FAStatusPill>
              <span className="text-[11px] text-finance-text-muted">{summary.macro_phase}</span>
            </div>
            <h2 className="text-[18px] font-bold text-finance-text-primary">
              {isLoading ? "加载中..." : summary.bias}
            </h2>
            <p className="max-w-4xl text-[12px] leading-6 text-finance-text-secondary">
              {isLoading ? "正在从 mock 数据源加载 Dashboard 摘要。" : summary.options_summary}
            </p>
          </div>

          <div className="grid min-w-[260px] grid-cols-2 gap-2">
            <FAMetricCard label="Pin 位" value={summary.pin_level ?? "—"} />
            <FAMetricCard label="WallScore" value={summary.wall_score ?? "—"} />
            <FAMetricCard label="净 GEX" value={summary.net_gex ?? "—"} />
            <FAMetricCard
              label="置信度"
              value={(summary.direction ? (summary.confidence * 100).toFixed(0) : "—") + "%"}
            />
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <FACard title="Resistance" bodyClassName="space-y-2">
            <div className="flex flex-wrap gap-2">
              {summary.resistance_levels.length > 0 ? (
                summary.resistance_levels.map((level, index) => (
                  <span
                    key={`resistance-${level}-${index}`}
                    className="rounded border border-finance-bearish/20 bg-finance-bearish/10 px-2 py-1 text-[11px] font-mono text-finance-bearish"
                  >
                    {level.toLocaleString("en-US")}
                  </span>
                ))
              ) : (
                <span className="text-[11px] text-finance-text-muted">不可用</span>
              )}
            </div>
          </FACard>

          <FACard title="Support" bodyClassName="space-y-2">
            <div className="flex flex-wrap gap-2">
              {summary.support_levels.length > 0 ? (
                summary.support_levels.map((level, index) => (
                  <span
                    key={`support-${level}-${index}`}
                    className="rounded border border-finance-bullish/20 bg-finance-bullish/10 px-2 py-1 text-[11px] font-mono text-finance-bullish"
                  >
                    {level.toLocaleString("en-US")}
                  </span>
                ))
              ) : (
                <span className="text-[11px] text-finance-text-muted">不可用</span>
              )}
            </div>
          </FACard>
        </div>
      </div>
    </section>
  );
}
