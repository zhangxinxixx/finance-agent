import type { MarketMonitorMetric } from "@/types/market-monitor";
import { FACard } from "@/components/shared/FACard";
import { findMetric, formatMetricChange, formatMetricValue, marketMonitorMetricLabel, marketMonitorUnitLabel } from "./format";

const ASSET_KEYS = ["XAUUSD", "DXY", "US10Y", "REAL_10Y", "T10YIE", "YIELD_SPREAD_2Y_3M", "TGA"] as const;
const ASSET_LABELS: Record<string, string> = {
  XAUUSD: "现货黄金（XAUUSD）",
  DXY: "美元指数（DXY）",
  US10Y: "10年名义利率（US10Y）",
  REAL_10Y: "10年实际利率（REAL_10Y）",
  T10YIE: "10年通胀预期（T10YIE）",
  YIELD_SPREAD_2Y_3M: "2年-3个月利差（2Y3M）",
  TGA: "财政账户（TGA）",
};

/** Compare supplied observations; correlation needs a synchronized backend result. */
export function CorrelationMatrix({ metrics }: { metrics: MarketMonitorMetric[] }) {
  return (
    <FACard title="跨资产变化对照" eyebrow="跨资产观测" accent="info" bodyClassName="overflow-x-auto">
      <p className="fa-muted-text mb-3">
        对照后端已有周/月变化，查看不同资产是否同时变化。各指标单位和观测日不同，变化幅度不可直接比较；
        尚未提供同步历史样本的相关性结果，不能据此确认相关系数或因果关系。缺失变化显示 —。
      </p>
      <table className="fa-table">
        <thead><tr><th>指标</th><th>观测日期</th><th>观测值 / 单位</th><th>周变化（原始口径）</th><th>月变化（原始口径）</th></tr></thead>
        <tbody>
          {ASSET_KEYS.map((key) => {
            const metric = findMetric(metrics, key);
            return (
              <tr key={key}>
                <td><span className="font-semibold">{marketMonitorMetricLabel(key, ASSET_LABELS[key] ?? metric?.label)}</span></td>
                <td>{metric?.latest_date || "未提供"}</td>
                <td className="tabular-nums">{metric ? formatMetricValue(metric.latest_value, 4) : "—"} {metric?.unit ? marketMonitorUnitLabel(metric.unit) : "单位未提供"}</td>
                <td className="tabular-nums">{formatMetricChange(metric?.one_week_change ?? null)}</td>
                <td className="tabular-nums">{formatMetricChange(metric?.one_month_change ?? null)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </FACard>
  );
}

export default CorrelationMatrix;
