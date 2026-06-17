import type { DashboardSummary, DashboardViewModel, SignalDirection } from "@/types/dashboard";
import { Activity, ChevronDown, ChevronUp, Minus, Target } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAConvictionBar } from "@/components/shared/FAConvictionBar";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { translateText } from "./judgmentFormat";

interface MarketStateOverviewProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
}

function directionLabel(direction: SignalDirection) {
  if (direction === "bullish") return "偏多";
  if (direction === "bearish") return "偏空";
  return "中性";
}

function directionHeadline(direction: SignalDirection) {
  if (direction === "bullish") return "看多";
  if (direction === "bearish") return "看空";
  return "中性";
}

function directionTone(direction: SignalDirection): "up" | "down" | "neutral" {
  if (direction === "bullish") return "up";
  if (direction === "bearish") return "down";
  return "neutral";
}

function metricValue(value: number | string | null | undefined, unit?: string) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return `${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}${unit ?? ""}`;
  }
  return `${value}${unit ?? ""}`;
}

function ListBlock({
  title,
  items,
  kind,
}: {
  title: string;
  items: string[];
  kind: "up" | "down" | "neutral";
}) {
  const Icon = kind === "up" ? ChevronUp : kind === "down" ? ChevronDown : Minus;
  const iconClass = kind === "up" ? "text-[var(--up)]" : kind === "down" ? "text-[var(--down)]" : "text-[var(--fg-5)]";
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="mb-2 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{title}</div>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item} className="flex items-start gap-2 text-[11px] text-[var(--fg-3)]">
            <Icon size={11} className={`mt-0.5 shrink-0 ${iconClass}`} />
            <span>{item}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function KeyLevelBlock({ levels }: { levels: DashboardSummary["strategy"]["key_levels"] }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="mb-2 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">关键价位</div>
      <div className="space-y-2">
        {levels.resistance.map((level, index) => (
          <div key={`res-${level}-${index}`} className="flex items-center gap-2">
            <span className="h-4 w-[3px] rounded-[var(--radius-xs)] bg-[var(--down)]" />
            <span className="font-mono text-[11px] font-semibold text-[var(--down)]">{level.toLocaleString("en-US")}</span>
            <span className="text-[10px] text-[var(--fg-5)]">阻力</span>
          </div>
        ))}
        {levels.support.map((level, index) => (
          <div key={`sup-${level}-${index}`} className="flex items-center gap-2">
            <span className="h-4 w-[3px] rounded-[var(--radius-xs)] bg-[var(--up)]" />
            <span className="font-mono text-[11px] font-semibold text-[var(--up)]">{level.toLocaleString("en-US")}</span>
            <span className="text-[10px] text-[var(--fg-5)]">支撑</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MarketStateOverview({ summary, viewModel }: MarketStateOverviewProps) {
  const { conclusion, market_summary: market, strategy } = summary;
  const marketState = viewModel?.market_state;
  const direction = marketState?.bias === "bullish" || marketState?.bias === "bearish" || marketState?.bias === "neutral"
    ? marketState.bias
    : conclusion.direction;
  const confidence = marketState?.confidence ?? conclusion.confidence ?? strategy.confidence ?? null;
  const primaryMetrics = [market.XAUUSD, market.DXY, market.US10Y, market.REAL_10Y].filter(Boolean);

  return (
    <FACard title="今日综合判断卡" eyebrow="Judgment Banner" accent="warn" bodyClassName="space-y-4">
      <div className="grid gap-3 xl:grid-cols-[1.5fr_1fr_1fr_1.15fr]">
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <div className="grid gap-2">
            <div className="grid grid-cols-[72px_1fr] gap-2">
              <div className="text-[10px] text-[var(--fg-5)]">市场阶段</div>
              <div className="text-[14px] font-bold text-[var(--warn)]">{translateText(strategy.macro_phase)}</div>
            </div>
            <div className="grid grid-cols-[72px_1fr] gap-2">
              <div className="text-[10px] text-[var(--fg-5)]">黄金状态</div>
              <div className="text-[14px] font-bold text-[var(--fg-2)]">{translateText(marketState?.label || conclusion.bias || "等待后端综合结论")}</div>
            </div>
            <div className="grid grid-cols-[72px_1fr] gap-2">
              <div className="text-[10px] text-[var(--fg-5)]">交易方向</div>
              <div className={`text-[14px] font-bold ${direction === "bullish" ? "text-[var(--up)]" : direction === "bearish" ? "text-[var(--down)]" : "text-[var(--fg-3)]"}`}>
                {directionHeadline(direction)}
              </div>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <FAStatusPill tone="warn">{translateText(strategy.macro_phase)}</FAStatusPill>
            <FAStatusPill tone={direction === "bullish" ? "up" : direction === "bearish" ? "down" : "neutral"}>{directionLabel(direction)}</FAStatusPill>
          </div>

          <div className="mt-3 text-[11px] leading-6 text-[var(--fg-4)]">
            {translateText(marketState?.summary || conclusion.options_summary)}
          </div>
        </div>

        <ListBlock title="主导因子" items={strategy.triggers.slice(0, 3)} kind="up" />
        <ListBlock title="压制因子" items={strategy.invalid_conditions.slice(0, 3)} kind="down" />
        <KeyLevelBlock levels={strategy.key_levels} />
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {primaryMetrics.map((metric) => (
            <FAMetricCard
              key={metric.label}
              label={metric.label}
              value={metricValue(metric.value, metric.unit)}
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

        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <div className="mb-3 flex items-center gap-2">
            <Activity size={12} className="text-[var(--brand-hover)]" />
            <div className="text-[10px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">确信度</div>
          </div>
          <FAConvictionBar value={(confidence ?? 0) * 100} tone="warn" />
        </div>
      </div>

      <FAWarningBanner title="改判条件" description={strategy.risk_points[0] || summary.risk_alerts[0] || "等待后端补充改判条件。"} tone="warn" />
    </FACard>
  );
}
