import type { DashboardSummary, WallLevel } from "@/types/dashboard";
import { Layers3 } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";

interface CMEOptionsPanelProps {
  options: DashboardSummary["cme_options"];
}

function WallList({ title, walls, tone }: { title: string; walls: WallLevel[]; tone: "bullish" | "bearish" }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{title}</span>
        <FAStatusPill tone={tone === "bullish" ? "up" : "down"}>{tone === "bullish" ? "支撑" : "阻力"}</FAStatusPill>
      </div>
      <div className="mt-3 space-y-2">
        {walls.length > 0 ? (
          walls.map((wall) => (
            <div key={`${title}-${wall.strike}`} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-2">
              <div className="flex items-center justify-between gap-2 text-[11px]">
                <span className={`font-mono font-semibold ${tone === "bullish" ? "text-[var(--up)]" : "text-[var(--down)]"}`}>
                  {wall.strike.toLocaleString("en-US")}
                </span>
                <span className="fa-num text-[var(--fg-4)]">{wall.score.toFixed(2)}</span>
              </div>
              <div className="mt-1 text-[10px] text-[var(--fg-5)]">距离 {wall.distance_pct.toFixed(2)}%</div>
            </div>
          ))
        ) : (
          <div className="text-[11px] text-[var(--fg-5)]">不可用</div>
        )}
      </div>
    </div>
  );
}

export function CMEOptionsPanel({ options }: CMEOptionsPanelProps) {
  return (
    <FACard
      title="CME 期权"
      eyebrow="Options Structure"
      accent="warn"
      bodyClassName="space-y-4"
      action={<Layers3 size={13} className="text-[var(--warn)]" />}
    >
      <div className="flex flex-wrap gap-2">
        <FAStatusPill tone="dim">{options.product}</FAStatusPill>
        <FAStatusPill tone="neutral">{`账期 ${options.trade_date || "—"}`}</FAStatusPill>
        <FAStatusPill tone="info">{`市场状态 ${options.market_regime}`}</FAStatusPill>
      </div>
      <div className="text-[11px] text-[var(--fg-4)]">到期月：{options.expiries.join(", ") || "—"}</div>

      <div className="grid gap-3 sm:grid-cols-2">
        <FAMetricCard label="pin_level" value={options.pin_level ?? "—"} hint="Pin 位" />
        <FAMetricCard label="net_gex" value={options.net_gex ?? "—"} hint="净 GEX" />
        <FAMetricCard label="wall_score" value={options.wall_score ?? "—"} hint="WallScore" />
        <FAMetricCard label="gamma_zero" value={options.gamma_zero ?? "—"} hint="Gamma 零点" />
      </div>

      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5 text-[11px] text-[var(--fg-4)]">
        意图：<span className="text-[var(--fg-2)]">{options.intent}</span> · 评分 {(options.intent_score * 100).toFixed(0)}%
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <WallList title="上方阻力墙" walls={options.upper_resistance_walls} tone="bearish" />
        <WallList title="下方支撑墙" walls={options.lower_support_walls} tone="bullish" />
      </div>
    </FACard>
  );
}
