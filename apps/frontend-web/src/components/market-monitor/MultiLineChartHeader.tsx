import { TrendingUp } from "lucide-react";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import { TIMEFRAMES, timeframeLabel } from "@/components/market-monitor/marketMonitorChart";

interface MultiLineChartHeaderProps {
  activeTimeframe: MarketMonitorHistoryTimeframe;
  syntheticFallback: boolean;
  onSelectTimeframe: (timeframe: MarketMonitorHistoryTimeframe) => void;
}

export function MultiLineChartHeader({ activeTimeframe, syntheticFallback, onSelectTimeframe }: MultiLineChartHeaderProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 12px",
        borderBottom: "1px solid var(--border-faint)",
      }}
    >
      <div className="flex items-center gap-2">
        <TrendingUp size={13} style={{ color: "var(--brand-hover)" }} />
        <div>
          <div style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 10, color: "var(--fg-2)", lineHeight: 1 }}>
            XAUUSD Candles
          </div>
          <div style={{ fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--fg-5)", marginTop: 2 }}>
            {timeframeLabel(activeTimeframe)}
            {["15M", "30M", "1H", "4H", "1D"].includes(activeTimeframe) ? " · DXY 日线 only" : ""}
            {syntheticFallback ? " · 历史接口失败，降级展示实时曲线" : ""}
          </div>
        </div>
      </div>

      <div
        className="flex gap-1"
        style={{
          padding: 2,
          border: "1px solid var(--border-faint)",
          borderRadius: 6,
          background: "rgba(255,255,255,0.02)",
        }}
      >
        {TIMEFRAMES.map((timeframe) => {
          const isActive = timeframe === activeTimeframe;
          return (
            <button
              key={timeframe}
              onClick={() => onSelectTimeframe(timeframe)}
              style={{
                minWidth: 34,
                padding: "5px 7px",
                borderRadius: 4,
                fontSize: 9,
                fontWeight: 600,
                fontFamily: "var(--font-sans)",
                cursor: "pointer",
                transition: "all 120ms ease",
                ...(isActive
                  ? {
                      background: "rgba(59,130,246,0.15)",
                      border: "0",
                      color: "#60a5fa",
                    }
                  : {
                      background: "transparent",
                      border: "0",
                      color: "var(--fg-5)",
                    }),
              }}
            >
              {timeframe}
            </button>
          );
        })}
      </div>
    </div>
  );
}
