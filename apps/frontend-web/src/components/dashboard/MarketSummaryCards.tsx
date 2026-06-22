import type { DashboardSummary } from "@/types/dashboard";
import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";

interface MarketSummaryCardsProps {
  marketSummary: DashboardSummary["market_summary"];
}

function metricTone(trend: DashboardSummary["market_summary"]["XAUUSD"]["trend"]): "up" | "down" | "flat" {
  if (trend === "up" || trend === "down") return trend;
  return "flat";
}

export function MarketSummaryCards({ marketSummary }: MarketSummaryCardsProps) {
  const metrics = Object.values(marketSummary);

  return (
    <FACard title="市场快照" eyebrow="关键读数" accent="info" bodyClassName="space-y-4">
      <FASectionHeader
        title="关键市场读数"
        description="黄金、美元、利率、通胀与实际利率的高密度摘要。"
      />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        {metrics.map((metric) => (
          <FAMetricCard
            key={metric.label}
            label={metric.label}
            value={metric.value ?? "—"}
            unit={metric.unit}
            delta={metric.change ?? undefined}
            trend={metricTone(metric.trend)}
            hint={metric.note ?? undefined}
            status={metric.status ?? undefined}
            statusTone={
              metric.status === "ok"
                ? "up"
                : metric.status === "warn"
                  ? "warn"
                  : metric.status === "error"
                    ? "down"
                    : metric.status === "info"
                      ? "info"
                      : "dim"
            }
          />
        ))}
      </div>
    </FACard>
  );
}
