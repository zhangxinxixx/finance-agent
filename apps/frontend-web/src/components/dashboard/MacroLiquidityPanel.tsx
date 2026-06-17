import type { DashboardSummary } from "@/types/dashboard";
import { Droplets } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";

interface MacroLiquidityPanelProps {
  macroLiquidity: DashboardSummary["macro_liquidity"];
}

export function MacroLiquidityPanel({ macroLiquidity }: MacroLiquidityPanelProps) {
  const metrics = Object.values(macroLiquidity);
  const metricLabels = metrics.map((metric) => metric.label).join(" · ");

  return (
    <FACard
      title="宏观流动性"
      eyebrow="Macro Liquidity"
      accent="info"
      bodyClassName="space-y-4"
      action={<Droplets size={13} className="text-[var(--info)]" />}
    >
      <p className="text-[11px] text-[var(--fg-4)]">{metricLabels}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {metrics.map((metric) => (
          <FAMetricCard
            key={metric.label}
            label={metric.label}
            value={metric.value ?? "—"}
            unit={metric.unit}
            delta={metric.change ?? undefined}
            trend={metric.trend === "up" || metric.trend === "down" ? metric.trend : "flat"}
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
