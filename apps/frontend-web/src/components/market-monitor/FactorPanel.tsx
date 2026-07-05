import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import type { MarketMonitorMetric, MarketMonitorStatus } from "@/types/market-monitor";
import { findMetric, formatMetricChange, formatMetricValue, trendFromChange } from "./format";

interface PricingChainPanelProps {
  metrics: MarketMonitorMetric[];
}

interface PricingChainGroup {
  key: string;
  title: string;
  description: string;
  metricKeys: string[];
  accent: string;
}

const PRICING_CHAIN_GROUPS: PricingChainGroup[] = [
  {
    key: "rates",
    title: "利率链",
    description: "政策路径、实际利率压力、短端拐点",
    metricKeys: ["US02Y", "US10Y", "REAL_10Y", "YIELD_SPREAD_2Y_3M"],
    accent: "#2563eb",
  },
  {
    key: "dollar",
    title: "美元链",
    description: "美元是否对黄金形成反向压制",
    metricKeys: ["DXY"],
    accent: "#0ea5e9",
  },
  {
    key: "inflation",
    title: "通胀链",
    description: "通胀预期与实际利率的方向分解",
    metricKeys: ["T10YIE"],
    accent: "#d4af37",
  },
  {
    key: "liquidity",
    title: "流动性链",
    description: "财政现金、逆回购与资金利率环境",
    metricKeys: ["TGA", "RRP", "SOFR", "EFFR", "IORB"],
    accent: "#14b8a6",
  },
  {
    key: "gold",
    title: "黄金确认",
    description: "宏观因子变化是否被价格响应确认",
    metricKeys: ["XAUUSD"],
    accent: "#d4af37",
  },
];

const METRIC_LABELS: Record<string, string> = {
  XAUUSD: "XAU",
  DXY: "DXY",
  US02Y: "2Y",
  US10Y: "10Y",
  REAL_10Y: "R10Y",
  YIELD_SPREAD_2Y_3M: "2Y3M",
  T10YIE: "BE10Y",
  TGA: "TGA",
  RRP: "RRP",
  SOFR: "SOFR",
  EFFR: "EFFR",
  IORB: "IORB",
};

function groupTone(metrics: Array<MarketMonitorMetric | undefined>): FAStatusTone {
  if (metrics.some((metric) => metric?.status === "error")) return "down";
  if (metrics.some((metric) => metric?.status === "warn")) return "warn";
  if (metrics.some((metric) => !metric || metric.status === "unavailable")) return "dim";
  return "up";
}

function groupStatusLabel(metrics: Array<MarketMonitorMetric | undefined>) {
  const available = metrics.filter((metric) => metric?.status === "ok" || metric?.status === "info").length;
  return `${available}/${metrics.length}`;
}

function metricChangeTone(metric: MarketMonitorMetric | undefined): string {
  const trend = trendFromChange(metric?.one_week_change ?? null);
  if (trend === "up") return "var(--up)";
  if (trend === "down") return "var(--down)";
  return "var(--fg-5)";
}

function statusLabel(status: MarketMonitorStatus | undefined) {
  if (status === "ok") return "正常";
  if (status === "warn") return "关注";
  if (status === "error") return "异常";
  if (status === "info") return "信息";
  return "缺失";
}

function isUnavailable(metric: MarketMonitorMetric | undefined) {
  return !metric || metric.status === "unavailable" || metric.latest_value === null || metric.latest_value === undefined || metric.latest_value === "";
}

function numericChange(metric: MarketMonitorMetric | undefined): number | null {
  const value = metric?.one_week_change;
  if (typeof value === "number") return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value.replace(/[+,]/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function metricLabel(key: string) {
  return METRIC_LABELS[key] ?? key;
}

export function FactorPanel({ metrics }: PricingChainPanelProps) {
  return (
    <FACard
      title="定价链雷达"
      eyebrow="Realtime Chain"
      description="监测因子传导与缺口，不输出交易结论。"
      accent="info"
      density="compact"
      className="market-monitor-pricing-radar-card"
      bodyClassName="market-monitor-pricing-radar"
    >
      {PRICING_CHAIN_GROUPS.map((group) => {
        const groupMetrics = group.metricKeys.map((key) => findMetric(metrics, key));
        const tone = groupTone(groupMetrics);

        return (
          <section
            key={group.key}
            className="market-monitor-pricing-radar-group"
            style={{ ["--pricing-chain-accent" as string]: group.accent }}
          >
            <div className="market-monitor-pricing-radar-head">
              <div className="min-w-0">
                <div className="market-monitor-pricing-radar-title">{group.title}</div>
              </div>
              <FAStatusPill tone={tone} dot={false}>{groupStatusLabel(groupMetrics)}</FAStatusPill>
            </div>
            <div className="market-monitor-pricing-radar-metrics">
              {group.metricKeys.map((key) => {
                const metric = findMetric(metrics, key);
                const value = formatMetricValue(metric?.latest_value ?? null, key === "XAUUSD" ? 2 : 3);
                const interpretation = metric?.interpretation ? ` · ${metric.interpretation}` : "";

                return (
                  <div
                    key={key}
                    className="market-monitor-pricing-radar-metric"
                    data-status={metric?.status ?? "unavailable"}
                    title={`${metricLabel(key)} · ${statusLabel(metric?.status)}${interpretation}`}
                  >
                    <span className="market-monitor-pricing-radar-code">{metricLabel(key)}</span>
                    <div className="market-monitor-pricing-radar-value">
                      {value}
                      {metric?.unit ? <span>{metric.unit}</span> : null}
                    </div>
                    <span className="market-monitor-pricing-radar-change" style={{ color: metricChangeTone(metric) }}>
                      {formatMetricChange(metric?.one_week_change ?? null)}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </FACard>
  );
}

export function PricingChainDiagnosticsPanel({ metrics }: PricingChainPanelProps) {
  const missing = metrics.filter((metric) => isUnavailable(metric));
  const xau = findMetric(metrics, "XAUUSD");
  const dxy = findMetric(metrics, "DXY");
  const real10y = findMetric(metrics, "REAL_10Y");
  const t10yie = findMetric(metrics, "T10YIE");
  const tga = findMetric(metrics, "TGA");
  const rrp = findMetric(metrics, "RRP");
  const sofr = findMetric(metrics, "SOFR");
  const effr = findMetric(metrics, "EFFR");
  const iorb = findMetric(metrics, "IORB");

  const xauChange = numericChange(xau);
  const dxyChange = numericChange(dxy);
  const real10yChange = numericChange(real10y);
  const t10yieChange = numericChange(t10yie);
  const liquidityChanges = [tga, rrp, sofr, effr, iorb].map(numericChange).filter((value): value is number => value !== null && value !== 0);
  const liquidityMixed = liquidityChanges.some((value) => value > 0) && liquidityChanges.some((value) => value < 0);

  const alerts = [
    dxyChange !== null && xauChange !== null && dxyChange > 0 && xauChange > 0
      ? { title: "美元与黄金同涨", detail: "DXY 与 XAUUSD 同向上行，常规反向关系暂未生效，需要看事件或避险解释。", tone: "warn" as const }
      : null,
    real10yChange !== null && xauChange !== null && real10yChange > 0 && xauChange > 0
      ? { title: "实际利率压制未被价格确认", detail: "REAL_10Y 上行但黄金仍上涨，说明价格可能由避险、通胀或流动性因素接管。", tone: "warn" as const }
      : null,
    t10yieChange !== null && real10yChange !== null && t10yieChange > 0 && real10yChange > 0
      ? { title: "通胀与实际利率同升", detail: "通胀预期和实际利率同时抬升，黄金方向需要等待美元或价格结构确认。", tone: "info" as const }
      : null,
    liquidityMixed
      ? { title: "流动性链路分歧", detail: "TGA/RRP/资金利率方向不一致，流动性变量只适合作背景过滤，不单独形成趋势信号。", tone: "info" as const }
      : null,
    missing.length > 0
      ? { title: "数据缺口", detail: `${missing.map((metric) => metric.key).join(" / ")} 暂不可用，相关链路不参与判断。`, tone: "down" as const }
      : null,
  ].filter((item): item is { title: string; detail: string; tone: "warn" | "info" | "down" } => Boolean(item));

  return (
    <FACard title="链路背离 / 数据缺口" eyebrow="Exceptions" accent={alerts.length ? "warn" : "up"} density="compact">
      <div className="market-monitor-pricing-diagnostics">
        {alerts.length ? alerts.map((alert) => (
          <div key={alert.title} className="market-monitor-pricing-diagnostic-row" data-tone={alert.tone}>
            <div className="market-monitor-pricing-diagnostic-title">{alert.title}</div>
            <div className="market-monitor-pricing-diagnostic-detail">{alert.detail}</div>
          </div>
        )) : (
          <div className="market-monitor-pricing-diagnostic-empty">
            当前定价链未发现明显背离，主要指标数据完整。
          </div>
        )}
      </div>
    </FACard>
  );
}

export default FactorPanel;
