import type { DashboardStrategyCardViewModel, StrategyCardData } from "@/types/dashboard";
import { FileText, Zap } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAConvictionBar } from "@/components/shared/FAConvictionBar";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";

interface StrategyPanelProps {
  strategy: StrategyCardData;
  strategyViewModel?: DashboardStrategyCardViewModel | null;
}

function directionLabel(direction: StrategyCardData["direction"]) {
  if (direction === "bullish") return "看多";
  if (direction === "bearish") return "看空";
  return "中性";
}

function SummaryList({ title, items, icon }: { title: string; items: string[]; icon: "zap" | "file" }) {
  const Icon = icon === "zap" ? Zap : FileText;
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
        <Icon size={11} className="text-[var(--brand-hover)]" />
        <span>{title}</span>
      </div>
      {items.length > 0 ? (
        <div className="space-y-2">
          {items.slice(0, 3).map((item) => (
            <div key={item} className="flex gap-2 text-[11px] leading-5 text-[var(--fg-3)]">
              <span className="mt-[0.45rem] h-1 w-1 shrink-0 rounded-full bg-[var(--brand-hover)]" />
              <span>{item}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-[var(--fg-5)]">后端未提供该字段，当前保持为空。</div>
      )}
    </div>
  );
}

export function StrategyPanel({ strategy, strategyViewModel }: StrategyPanelProps) {
  const direction = strategyViewModel?.direction && strategyViewModel.direction !== "unknown"
    ? strategyViewModel.direction
    : strategy.direction;
  const confidence = strategyViewModel?.confidence ?? strategy.confidence ?? null;
  const summaryText = strategyViewModel?.scenario_summary || strategy.bias;
  const triggers = strategyViewModel?.trigger_conditions ?? strategy.triggers;
  const invalidConditions = strategyViewModel?.invalid_conditions.length ? strategyViewModel.invalid_conditions : strategy.invalid_conditions;
  const riskPoints = strategyViewModel?.risk_points.length ? strategyViewModel.risk_points : strategy.risk_points;
  const watchlist = strategyViewModel?.watchlist.length ? strategyViewModel.watchlist : [];
  const runId = strategyViewModel?.run_id ?? strategy.run_id;
  const snapshotId = strategyViewModel?.snapshot_id ?? strategy.snapshot_id;
  const leadTrigger = triggers[0] ?? "等待触发条件";
  const leadInvalid = invalidConditions[0] ?? "等待失效条件";
  const leadRisk = riskPoints[0] ?? watchlist[0] ?? "详情页查看风险点与观察列表";

  return (
    <FACard title="今日综合分析摘要" eyebrow="Daily Composite" accent="brand" bodyClassName="space-y-4">
      <FASectionHeader
        title="综合结论"
        description={summaryText}
        action={<FAStatusPill tone={direction === "bullish" ? "up" : direction === "bearish" ? "down" : "neutral"}>{directionLabel(direction)}</FAStatusPill>}
      />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_110px]">
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3 text-[11px] leading-6 text-[var(--fg-3)]">
          {summaryText}
        </div>
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <FAConvictionBar value={(confidence ?? 0) * 100} tone="warn" />
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Lead Trigger</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{leadTrigger}</div>
          <div className="mt-2 text-[10px] text-[var(--fg-4)]">
            目标位 {strategy.key_levels.resistance[0] != null ? strategy.key_levels.resistance[0].toLocaleString("en-US") : "—"}
          </div>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Invalidation</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{leadInvalid}</div>
          <div className="mt-2 text-[10px] text-[var(--fg-4)]">
            支撑位 {strategy.key_levels.support[0] != null ? strategy.key_levels.support[0].toLocaleString("en-US") : "—"}
          </div>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Risk Hint</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{leadRisk}</div>
          <div className="mt-2 text-[10px] text-[var(--fg-4)]">首页仅保留结论、关键触发和风险提示</div>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <SummaryList title="触发条件摘要" items={triggers} icon="zap" />
        <SummaryList title="失效条件摘要" items={invalidConditions.length ? invalidConditions : riskPoints} icon="file" />
      </div>

      {(runId || snapshotId) && (
        <div className="flex flex-wrap gap-2">
          {runId ? <FASourceTraceBadge source={runId} status="run" tone="info" /> : null}
          {snapshotId ? <FASourceTraceBadge source={snapshotId} status="snapshot" tone="info" snapshotId={snapshotId} /> : null}
        </div>
      )}
    </FACard>
  );
}
