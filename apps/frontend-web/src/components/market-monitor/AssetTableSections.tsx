import { BarChart3 } from "lucide-react";
import type { MarketMonitorMetric, MarketMonitorMetricGroup } from "@/types/market-monitor";
import { findMetric } from "./format";
import { AssetTableRow, type AssetRow } from "./AssetTableRow";

export const ASSET_ROWS: AssetRow[] = [
  { key: "XAUUSD", symbol: "XAU", name: "现货黄金", group: "metals" },
  { key: "XAGUSD", symbol: "XAG", name: "现货白银", group: "metals" },
  { key: "DXY", symbol: "DXY", name: "美元指数", group: "dollar" },
  { key: "USDX_N", symbol: "USDX", name: "美元指数(名义)", group: "dollar" },
  { key: "US10Y", symbol: "US10Y", name: "10Y 国债", group: "rates" },
  { key: "US02Y", symbol: "US02Y", name: "2Y 国债", group: "rates" },
  { key: "REAL_10Y", symbol: "TIPS", name: "10Y 实际利率", group: "rates" },
  { key: "T10YIE", symbol: "T10YIE", name: "通胀预期", group: "rates" },
  { key: "YIELD_SPREAD_2Y_3M", symbol: "2Y-3M", name: "短端利差", group: "rates" },
  { key: "TGA", symbol: "TGA", name: "财政现金账户", group: "liquidity" },
  { key: "REPO", symbol: "REPO", name: "逆回购", group: "liquidity" },
  { key: "FED_BS", symbol: "FedBS", name: "联储资产负债表", group: "liquidity" },
  { key: "SPX", symbol: "SPX", name: "标普500", group: "funding" },
  { key: "VIX", symbol: "VIX", name: "波动率指数", group: "funding" },
  { key: "BTC", symbol: "BTC", name: "比特币", group: "funding" },
];

export const GROUP_META: Record<MarketMonitorMetricGroup, { label: string; icon: string; color: string }> = {
  metals: { label: "贵金属", icon: "Au", color: "#fbbf24" },
  dollar: { label: "美元体系", icon: "$", color: "#60a5fa" },
  rates: { label: "利率矩阵", icon: "R", color: "#f05252" },
  liquidity: { label: "流动性", icon: "L", color: "#34d399" },
  funding: { label: "风险资产", icon: "F", color: "#a78bfa" },
};

export const GROUP_ORDER: MarketMonitorMetricGroup[] = ["metals", "dollar", "rates", "liquidity", "funding"];
export const COLUMN_GRID = "68px 1fr 72px 70px 50px 58px 1fr";

export function AssetTableHeader({ metricCount }: { metricCount: number }) {
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
        <BarChart3 size={13} style={{ color: "var(--brand-hover)" }} />
        <div>
          <div style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 10, color: "var(--fg-2)", lineHeight: 1 }}>
            核心资产分组监控
          </div>
          <div style={{ fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--fg-5)", marginTop: 2 }}>
            {ASSET_ROWS.length} 个资产 · {GROUP_ORDER.length} 个分组
          </div>
        </div>
      </div>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          padding: "2px 6px",
          borderRadius: 3,
          border: "1px solid var(--border-faint)",
          color: "var(--fg-5)",
          background: "var(--bg-card-inner)",
        }}
      >
        {metricCount} loaded
      </span>
    </div>
  );
}

export function AssetTableColumns() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: COLUMN_GRID,
        padding: "5px 12px",
        background: "rgba(255,255,255,0.02)",
        borderBottom: "1px solid var(--border-faint)",
        fontFamily: "var(--font-sans)",
        fontWeight: 500,
        fontSize: 8,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--fg-5)",
      }}
    >
      <span>Symbol</span>
      <span>Name</span>
      <span style={{ textAlign: "right" }}>Price</span>
      <span style={{ textAlign: "right" }}>Change%</span>
      <span style={{ textAlign: "right" }}>Delta</span>
      <span style={{ textAlign: "right" }}>Impact</span>
      <span>Note</span>
    </div>
  );
}

export function AssetGroupSection({
  group,
  metrics,
}: {
  group: MarketMonitorMetricGroup;
  metrics: MarketMonitorMetric[];
}) {
  const meta = GROUP_META[group];
  const rows = ASSET_ROWS.filter((row) => row.group === group);

  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: COLUMN_GRID,
          padding: "5px 12px",
          background: "rgba(255,255,255,0.015)",
          borderTop: "1px solid var(--border-faint)",
          alignItems: "center",
        }}
      >
        <div className="flex items-center gap-2" style={{ gridColumn: "1 / -1" }}>
          <div
            style={{
              width: 16,
              height: 16,
              borderRadius: 3,
              background: `${meta.color}1a`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-mono)",
              fontWeight: 700,
              fontSize: 8,
              color: meta.color,
            }}
          >
            {meta.icon}
          </div>
          <span
            style={{
              fontFamily: "var(--font-sans)",
              fontWeight: 600,
              fontSize: 9,
              lineHeight: 1,
              color: meta.color,
            }}
          >
            {meta.label}
          </span>
        </div>
      </div>

      {rows.map((row) => {
        const metric = findMetric(metrics, row.key);

        return (
          <AssetTableRow key={row.key} row={row} metric={metric} />
        );
      })}
    </div>
  );
}
