import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { readableWarning } from "@/lib/researchReading";
import { historyObservationSegments } from "./historyObservationModel";
import { formatHistoryTimeframe, marketMonitorUnitLabel } from "./format";

const SERIES = [
  { key: "XAUUSD", label: "黄金现货", unit: "美元 / 盎司" },
  { key: "DXY", label: "美元指数", unit: "指数点" },
  { key: "REAL_10Y", label: "10 年实际利率", unit: "%" },
  { key: "T10YIE", label: "10 年通胀预期", unit: "%" },
];
const REQUEST_WINDOWS: MarketMonitorHistoryTimeframe[] = ["1D", "1W", "1M", "3M", "6M", "1Y"];
const REQUEST_WINDOW_LABELS: Record<MarketMonitorHistoryTimeframe, string> = {
  "15M": "近15分钟",
  "30M": "近30分钟",
  "1H": "近1小时",
  "4H": "近4小时",
  "1D": "近1天",
  "1W": "近1周",
  "1M": "近1个月",
  "3M": "近3个月",
  "6M": "近6个月",
  "1Y": "近1年",
};

export function HistoryObservationPanel({ history, metrics, timeframe, onTimeframeChange }: {
  history: MarketMonitorHistoryResponse | null | undefined;
  metrics: MarketMonitorMetric[];
  timeframe: MarketMonitorHistoryTimeframe;
  onTimeframeChange?: (value: MarketMonitorHistoryTimeframe) => void;
}) {
  const rows = Array.isArray(history?.series) ? history.series : [];
  return (
    <section className="border-t border-[var(--border)] p-3 space-y-3" aria-label="历史观测与图表限制">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="fa-card-title">历史观测：按原始单位分别看变化</h3>
        {onTimeframeChange ? (
          <label className="fa-label flex items-center gap-2">历史请求周期
            <select aria-label="历史请求周期" value={timeframe} onChange={(event) => onTimeframeChange(event.target.value as MarketMonitorHistoryTimeframe)} className="border border-[var(--border)] rounded-[var(--radius-md)] bg-[var(--bg-card)] p-1">
              {REQUEST_WINDOWS.map((value) => <option key={value} value={value}>{REQUEST_WINDOW_LABELS[value]}（{value}）</option>)}
            </select>
          </label>
        ) : null}
      </div>
      <p className="fa-muted-text">
        请求周期 {REQUEST_WINDOW_LABELS[timeframe]}（{timeframe}）；实际返回频率 {formatHistoryTimeframe(history?.source_timeframe)}，{rows.length > 0 ? rows.length : "未提供"} 个时间点。
        周期选择不证明接口已按该窗口裁剪，请以各图实际日期范围为准。
        每张图使用独立刻度，观察各指标自身变化；不比较线条高度或斜率，不据此推断因果。
      </p>
      {!history ? <p role="status" className="fa-muted-text">历史观测尚未读取成功，当前行情值不会补造历史曲线。</p> : (
        <div className="grid gap-3 md:grid-cols-2">
          {SERIES.map((series) => {
            const segments = historyObservationSegments(rows, series.key);
            const points = segments.flat();
            const metric = metrics.find((item) => item.key === series.key);
            const min = Math.min(...points.map((p) => p.value));
            const max = Math.max(...points.map((p) => p.value));
            const firstTime = points[0]?.time ?? 0;
            const lastTime = points[points.length - 1]?.time ?? firstTime;
            const x = (t: number) => 40 + (t - firstTime) / (lastTime - firstTime || 1) * 400;
            const y = (v: number) => max === min ? 55 : 15 + (max - v) / (max - min) * 80;
            return (
              <figure key={series.key} className="min-w-0" aria-label={`${series.label}历史观测`}>
                <figcaption className="fa-label">
                  {series.label} · {metric?.unit ? marketMonitorUnitLabel(metric.unit) : series.unit} · {points.length > 0 ? points.length : "未提供"} 个有效值
                  <span className="block fa-muted-text">历史序列日期：{points[0]?.date ?? "未提供"} → {points[points.length - 1]?.date ?? "未提供"}</span>
                  <span className="block fa-muted-text">最新指标观测：{metric?.latest_date || "未提供"}；与历史图分别读取</span>
                </figcaption>
                {points.length < 2 ? <p className="fa-muted-text py-3">有效观测不足，暂不绘制曲线。</p> : (
                  <svg viewBox="0 0 460 112" className="w-full" role="img" aria-label={`${series.label}独立刻度曲线；缺失值处断开`}>
                    <text x="2" y="15" fill="var(--fg-3)" fontSize="var(--type-caption)">{max.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}</text>
                    <text x="2" y="97" fill="var(--fg-3)" fontSize="var(--type-caption)">{min.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}</text>
                    {segments.map((segment, index) => segment.length > 1
                      ? <polyline key={index} fill="none" stroke="var(--brand)" strokeWidth="2" points={segment.map((point) => `${x(point.time)},${y(point.value)}`).join(" ")} />
                      : <circle key={index} fill="var(--brand)" r="2" cx={x(segment[0].time)} cy={y(segment[0].value)} />)}
                  </svg>
                )}
              </figure>
            );
          })}
        </div>
      )}
      <p className="fa-muted-text">历史序列日期不等于每个上游源的发布时间；接口未提供逐点源时间时，无法确认同步。缺失值处断开。{history?.message ? ` ${readableWarning(history.message)}` : ""}</p>
      {history?.degraded || history?.coverage_note ? <p className="fa-muted-text">覆盖限制：{history.coverage_note ? readableWarning(history.coverage_note) : "后端标记历史序列降级"}</p> : null}
    </section>
  );
}
