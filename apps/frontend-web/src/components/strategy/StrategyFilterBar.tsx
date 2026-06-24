import { RefreshCw } from "lucide-react";
import { FAFilterBar } from "@/components/shared/FAFilterBar";
import { FATabBar, type FATabOption } from "@/components/shared/FATabBar";
import { STRATEGY_WINDOW_TABS, type StrategyWindowKey } from "@/hooks/useStrategyPageState";

interface StrategyFilterBarProps {
  assetTabs: FATabOption<string>[];
  selectedAsset: string;
  onAssetChange: (value: string) => void;
  selectedWindow: StrategyWindowKey;
  onWindowChange: (value: StrategyWindowKey) => void;
  regimeTabs: FATabOption<string>[];
  activeRegime: string;
  onRegimeChange: (value: string) => void;
  onRefresh: () => void;
}

export function StrategyFilterBar({
  assetTabs,
  selectedAsset,
  onAssetChange,
  selectedWindow,
  onWindowChange,
  regimeTabs,
  activeRegime,
  onRegimeChange,
  onRefresh,
}: StrategyFilterBarProps) {
  return (
    <FAFilterBar
      left={
        <>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">资产</span>
            <FATabBar tabs={assetTabs} value={selectedAsset} onChange={onAssetChange} ariaLabel="策略资产筛选" />
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">窗口</span>
            <FATabBar tabs={STRATEGY_WINDOW_TABS} value={selectedWindow} onChange={onWindowChange} ariaLabel="策略历史窗口筛选" />
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">市场状态</span>
            <FATabBar tabs={regimeTabs} value={activeRegime} onChange={onRegimeChange} ariaLabel="策略市场状态筛选" />
          </div>
        </>
      }
      right={
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex h-[26px] items-center gap-1 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-[10px] text-[10px] font-semibold text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
        >
          <RefreshCw size={10} />
          刷新
        </button>
      }
    />
  );
}
