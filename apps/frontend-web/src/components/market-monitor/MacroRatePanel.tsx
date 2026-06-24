import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { findMetric, formatMetricChange, formatMetricValue, statusTone } from "./format";

interface MacroRatePanelProps {
  metrics: MarketMonitorMetric[];
}

const FACTOR_GROUPS = [
  {
    title: "当前主导因子",
    colorClass: "border-l-[var(--up)]",
    metricKey: "DXY",
    fallbackTitle: "美元走弱",
    fallbackDescription: "美元回落通常为黄金提供顺风。",
  },
  {
    title: "次级因子",
    colorClass: "border-l-[var(--info)]",
    metricKey: "XAUUSD",
    fallbackTitle: "价格惯性",
    fallbackDescription: "价格与避险需求共振时，反弹更容易延续。",
  },
  {
    title: "压制因子",
    colorClass: "border-l-[var(--down)]",
    metricKey: "REAL_10Y",
    fallbackTitle: "实际利率高位",
    fallbackDescription: "实际利率维持高位时，会压制黄金估值扩张。",
  },
] as const;

export function MacroRatePanel({ metrics }: MacroRatePanelProps) {
  const divergenceMetric = findMetric(metrics, "REAL_10Y");

  return (
    <FACard title="驱动因子诊断" eyebrow="Factor Readout" accent="brand">
      <div className="space-y-2.5">
        {FACTOR_GROUPS.map(({ title, colorClass, metricKey, fallbackTitle, fallbackDescription }) => {
          const metric = findMetric(metrics, metricKey);

          return (
            <div
              key={metricKey}
              className={`rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-3 border-l-2 ${colorClass}`}
            >
              <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{title}</div>
              <div className="mt-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[12px] font-semibold text-[var(--fg-2)]">
                    {metric?.label || fallbackTitle}
                  </div>
                  <p className="mt-1 text-[10px] leading-5 text-[var(--fg-4)]">
                    {metric?.interpretation?.trim() || fallbackDescription}
                  </p>
                </div>
                <FAStatusPill tone={statusTone(metric?.status ?? "unavailable")}>
                  {metric?.status ?? "unavailable"}
                </FAStatusPill>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
                <span className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-terminal)] px-2 py-1 font-mono text-[var(--fg-2)]">
                  latest {metric ? formatMetricValue(metric.latest_value, 4) : "—"}
                  {metric?.unit ? ` ${metric.unit}` : ""}
                </span>
                <span className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-terminal)] px-2 py-1 font-mono text-[var(--fg-4)]">
                  1W {metric ? formatMetricChange(metric.one_week_change) : "—"}
                </span>
                <span className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-terminal)] px-2 py-1 font-mono text-[var(--fg-4)]">
                  1M {metric ? formatMetricChange(metric.one_month_change) : "—"}
                </span>
              </div>
            </div>
          );
        })}

        <div className="rounded-[var(--radius-md)] border border-[color:rgba(245,158,11,0.28)] bg-[color:rgba(245,158,11,0.08)] px-3 py-3">
          <div className="text-[10px] font-semibold text-[var(--warn)]">背离检测</div>
          <p className="mt-1.5 text-[10px] leading-5 text-[var(--fg-3)]">
            {divergenceMetric?.interpretation?.trim() || "黄金与关键利率因子之间若出现反向共振，应降低追价质量。"}
          </p>
        </div>
      </div>
    </FACard>
  );
}
