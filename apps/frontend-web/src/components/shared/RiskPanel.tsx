import type { RiskItem } from "@/types/dashboard";
import { ShieldAlert } from "lucide-react";
import { FACard } from "./FACard";
import { FAMetricCard } from "./FAMetricCard";
import { FAWarningBanner } from "./FAWarningBanner";

interface RiskPanelProps {
  items: RiskItem[];
  alerts: string[];
}

function riskTone(status: RiskItem["status"]): "up" | "warn" | "down" | "info" | "dim" {
  switch (status) {
    case "ok":
      return "up";
    case "warn":
      return "warn";
    case "error":
      return "down";
    case "info":
      return "info";
    case "unavailable":
    default:
      return "dim";
  }
}

export function RiskPanel({ items, alerts }: RiskPanelProps) {
  return (
    <FACard
      title="风险面板"
      eyebrow="Risk Monitor"
      accent="warn"
      bodyClassName="space-y-3"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item, index) => (
          <FAMetricCard
            key={`${item.label}-${index}`}
            label={item.label}
            value={item.value}
            hint={item.note ?? "—"}
            status={item.status}
            statusTone={riskTone(item.status)}
          />
        ))}
      </div>

      <div className="space-y-2">
        {alerts.length > 0 ? (
          alerts.map((alert) => (
            <FAWarningBanner key={alert} title="风险告警" description={alert} tone="warn" />
          ))
        ) : (
          <div className="flex items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5 text-[11px] text-[var(--fg-4)]">
            <ShieldAlert size={12} className="text-[var(--fg-5)]" />
            <span>暂无活跃风险告警。</span>
          </div>
        )}
      </div>
    </FACard>
  );
}
