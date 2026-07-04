import { History } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import type { StrategyAssetSummaryViewModel, StrategyHistoryItemViewModel, StrategyViewModel } from "@/types/strategy";
import { biasTone, formatConfidence, formatDate, statusTone, strategyValueLabel } from "./strategyFormat";

export function StrategyHistoryListSection({
  items,
  selectedId,
  onSelect,
  isDetailLoading,
  sampleSize,
  windowLabel,
  regimeLabel,
}: {
  items: StrategyHistoryItemViewModel[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  isDetailLoading: boolean;
  sampleSize: number;
  windowLabel: string;
  regimeLabel: string;
}) {
  return (
    <FACard title="每日策略回看" eyebrow="按日策略卡" bodyClassName="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-5)]">
        <History size={12} />
        <span>
          {windowLabel} / {regimeLabel}
        </span>
        <span>
          可见 {items.length} / 总样本 {sampleSize}
        </span>
      </div>
      {items.length ? (
        <div className="overflow-x-auto">
          <div className="flex gap-2 pb-1">
            {items.map((item) => {
              const isSelected = selectedId === item.strategy_card_id;
              return (
                <button
                  key={item.strategy_card_id}
                  type="button"
                  disabled={isDetailLoading && isSelected}
                  onClick={() => onSelect(item.strategy_card_id)}
                  className={[
                    "shrink-0 rounded-[var(--radius-md)] border p-2.5 text-left transition-colors",
                    "min-w-[160px] max-w-[200px]",
                    isSelected
                      ? "border-[var(--brand)] bg-[var(--brand-soft)]"
                      : "border-[var(--border-faint)] bg-[var(--bg-card-inner)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]",
                  ].join(" ")}
                >
                  <div className="text-[10px] font-semibold text-[var(--fg-4)]">
                    {formatDate(item.trade_date)}
                  </div>
                  <div className="mt-1 flex items-center gap-1.5">
                    <FAStatusPill tone={biasTone(item.bias)} dot={false}>
                      {strategyValueLabel(item.bias)}
                    </FAStatusPill>
                    <span className="fa-num text-[10px] text-[var(--fg-3)]">
                      {formatConfidence(item.confidence)}
                    </span>
                  </div>
                  {item.market_regime ? (
                    <div className="mt-1 truncate text-[10px] text-[var(--fg-4)]" title={item.market_regime}>
                      {strategyValueLabel(item.market_regime)}
                    </div>
                  ) : null}
                  {item.run_id ? <div className="mt-0.5 text-[9px] text-[var(--fg-5)]">含溯源记录</div> : null}
                </button>
              );
            })}
          </div>
        </div>
      ) : (
        <FAEmptyState
          title="当前筛选没有样本"
          description="调整资产、时间窗口或市场状态后再看历史每日策略卡。"
        />
      )}
    </FACard>
  );
}

export function StrategyCalibrationPanel({
  asset,
  sampleSize,
  visibleCount,
  windowLabel,
  regimeLabel,
  regimeCounts,
  status,
  unavailableReason,
}: {
  asset: string;
  sampleSize: number;
  visibleCount: number;
  windowLabel: string;
  regimeLabel: string;
  regimeCounts: StrategyAssetSummaryViewModel["regime_counts"];
  status: StrategyViewModel["status"];
  unavailableReason: string | null;
}) {
  return (
    <FACard title="框架校准" eyebrow="历史样本" accent="info" bodyClassName="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">资产</div>
          <div className="mt-1 text-[13px] font-semibold text-[var(--fg-2)]">{asset}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">样本</div>
          <div className="mt-1 text-[13px] font-semibold text-[var(--fg-2)]">{sampleSize}</div>
          <div className="mt-0.5 text-[10px] text-[var(--fg-5)]">可见 {visibleCount}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">窗口</div>
          <div className="mt-1 text-[13px] font-semibold text-[var(--fg-2)]">{windowLabel}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">框架状态</div>
          <div className="mt-1 text-[13px] font-semibold text-[var(--fg-2)]">{strategyValueLabel(regimeLabel)}</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <FAStatusPill tone={statusTone(status)}>{strategyValueLabel(status)}</FAStatusPill>
        <FAStatusPill tone="info">{windowLabel}</FAStatusPill>
        <FAStatusPill tone="neutral">{strategyValueLabel(regimeLabel)}</FAStatusPill>
      </div>

      {regimeCounts.length ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">样本状态分布</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {regimeCounts.map((item) => (
              <FAStatusPill key={item.market_regime} tone="neutral">
                {strategyValueLabel(item.market_regime)} · {item.sample_size}
              </FAStatusPill>
            ))}
          </div>
        </div>
      ) : null}

      {unavailableReason ? (
        <FAWarningBanner
          title={status === "partial" ? "当前资产仅有历史样本" : "当前资产不可用"}
          description={unavailableReason}
          tone={status === "partial" ? "info" : "warn"}
        />
      ) : null}
    </FACard>
  );
}
