import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { findMetric, formatMetricChange, formatMetricValue, marketMonitorMetricLabel, marketMonitorStatusLabel, marketMonitorUnitLabel } from "./format";

export interface RealRatePanelProps {
  metrics: MarketMonitorMetric[];
}

const TARGET_KEY = "REAL_10Y";
const STAT_BOX_CLASS_NAME = "rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2.5";

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className={STAT_BOX_CLASS_NAME}>
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 font-mono text-[13px] text-[var(--fg-2)]">{value}</div>
    </div>
  );
}

export function RealRatePanel({ metrics }: RealRatePanelProps) {
  const metric = findMetric(metrics, TARGET_KEY);
  const companionKeys = ["US10Y", "T10YIE", "YIELD_SPREAD_2Y_3M", "DXY"] as const;

  return (
    <FACard
      title="利率结构约束"
      eyebrow="利率结构"
      accent={metric?.status === "warn" || metric?.status === "error" ? "down" : "info"}
      action={<FAStatusPill tone={metric?.status === "ok" ? "up" : metric?.status === "warn" ? "warn" : metric?.status === "error" ? "down" : "neutral"}>{marketMonitorStatusLabel(metric?.status)}</FAStatusPill>}
    >
      {metric ? (
        <div className="space-y-3">
          <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{marketMonitorMetricLabel(TARGET_KEY, metric.label)}</div>
            <div className="mt-2 flex items-end gap-2">
              <div className="fa-num text-[28px] font-bold leading-none text-[var(--fg-1)]">
                {formatMetricValue(metric.latest_value, 4)}
              </div>
              {metric.unit ? <div className="pb-0.5 text-[11px] text-[var(--fg-4)]">{marketMonitorUnitLabel(metric.unit)}</div> : null}
            </div>
          </div>

          <div className="grid gap-2 md:grid-cols-3">
            <StatBox label="最新观测日" value={metric.latest_date || "—"} />
            <StatBox label="周变化" value={formatMetricChange(metric.one_week_change)} />
            <StatBox label="月变化" value={formatMetricChange(metric.one_month_change)} />
          </div>

          <div className="grid gap-2">
            {companionKeys.map((key) => {
              const companion = findMetric(metrics, key);
              return (
                <div
                  key={key}
                  className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-[10px] font-semibold text-[var(--fg-3)]">{marketMonitorMetricLabel(key, companion?.label)}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-[var(--fg-5)]">{companion?.latest_date ?? "—"}</div>
                  </div>
                  <div className="font-mono text-[11px] text-[var(--fg-2)]">
                    {companion ? formatMetricValue(companion.latest_value, 4) : "—"}
                  </div>
                  <div className="font-mono text-[10px] text-[var(--fg-4)]">
                    {companion ? formatMetricChange(companion.one_week_change) : "—"}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-terminal)] px-3 py-3">
            <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">市场读数</div>
            <p className="mt-2 text-[11px] leading-5 text-[var(--fg-3)]">
              {metric.interpretation || "暂无利率结构诊断。"}
            </p>
          </div>
        </div>
      ) : (
        <FAEmptyState
          title="暂无 REAL_10Y 数据"
          description="当前快照缺少利率结构主导指标；相关判断暂不可用。"
        />
      )}
    </FACard>
  );
}

export default RealRatePanel;
