import { Calendar, Loader2 } from "lucide-react";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import { FATabBar } from "@/components/shared/FATabBar";
import { getLatestTradeDate, isWeekend } from "@/lib/date";
import type { MarketMonitorMockFile, MarketMonitorStatus } from "@/types/market-monitor";

type MarketMonitorTab = "overview" | "pricing-chain" | "cross-asset" | "calendar";

export function MarketMonitorLoadingPanel() {
  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        padding: 16,
      }}
    >
      <div className="flex items-center gap-3">
        <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--brand)" }} />
        <div>
          <div style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 13, color: "var(--fg-2)" }}>
            正在加载市场监控数据
          </div>
          <div style={{ fontFamily: "var(--font-sans)", fontSize: 11, color: "var(--fg-4)", marginTop: 4 }}>
            优先请求 API，失败后回退到 mock / unavailable 外壳。
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 8, marginTop: 20 }}>
        {Array.from({ length: 6 }).map((_, index) => (
          <div
            key={`loading-card-${index}`}
            className="animate-pulse"
            style={{
              height: 96,
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--border)",
              background: "var(--bg-card)",
            }}
          />
        ))}
      </div>
    </div>
  );
}

export function MarketMonitorPageHeader({
  pageStatusLabel,
  sourceLabel,
  latestDate,
  realtimeRegime,
  primaryDriver,
  history,
  activeTab,
  tabOptions,
  onTabChange,
}: {
  pageStatusLabel: string;
  sourceLabel: string;
  latestDate: string;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
  history: MarketMonitorHistoryResponse | null;
  activeTab: MarketMonitorTab;
  tabOptions: Array<{ value: MarketMonitorTab; label: string }>;
  onTabChange: (value: MarketMonitorTab) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 12,
        background: "linear-gradient(135deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)",
        border: "1px solid var(--border-faint)",
        borderRadius: 10,
        padding: "8px 14px",
      }}
    >
      <div className="min-w-0">
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--fg-1)", letterSpacing: "-0.01em" }}>
          市场监控
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-4 gap-y-0.5">
          <span className="text-[10px] text-[var(--fg-4)]">
            阶段：<span style={{ color: "var(--fg-2)", fontWeight: 600 }}>{pageStatusLabel}</span>
          </span>
          <span className="text-[10px] text-[var(--fg-4)]">
            来源：<span style={{ color: "var(--fg-2)" }}>{sourceLabel}</span>
          </span>
          <span className="text-[10px] text-[var(--fg-4)]">
            日期：<span style={{ color: "var(--fg-2)" }}>{latestDate}</span>
          </span>
          {realtimeRegime?.regime ? (
            <span className="text-[10px]" style={{ color: "var(--brand)" }}>
              {realtimeRegime.regime} ({(realtimeRegime.confidence * 100).toFixed(0)}%)
            </span>
          ) : null}
          {primaryDriver?.driver ? (
            <span className="text-[10px] text-[var(--fg-4)]">
              · {primaryDriver.driver}
            </span>
          ) : null}
          {history ? (
            <span className="text-[10px] text-[var(--fg-5)]">
              {history.available_points} 数据点
              {history.degraded ? " · 降级" : ""}
            </span>
          ) : null}
        </div>
      </div>
      <FATabBar value={activeTab} tabs={tabOptions} onChange={(value) => onTabChange(value as MarketMonitorTab)} ariaLabel="市场监控视图切换" />
    </div>
  );
}

export function MarketMonitorWeekendBanner() {
  if (!isWeekend()) {
    return null;
  }

  return (
    <div
      className="flex items-center gap-2 rounded-[var(--radius-sm)] px-3 py-1.5"
      style={{ background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)" }}
    >
      <Calendar size={12} color="#3b82f6" />
      <span className="text-[10px] font-medium text-[#3b82f6]">
        周末模式 — 市场数据展示最近交易日（{getLatestTradeDate()}），新闻事件实时更新
      </span>
    </div>
  );
}

export type { MarketMonitorTab, MarketMonitorStatus };
