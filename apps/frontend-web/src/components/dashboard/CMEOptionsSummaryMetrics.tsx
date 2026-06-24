import { translateIntent } from "./CMEOptionsSummaryFormat";

type MetricItem = {
  label: string;
  value: number | null;
  format: (value: number | null) => string;
};

export function CMEOptionsSummaryMetrics({
  metrics,
  hasIntent,
  intent,
  intentScore,
  hasRegime,
  marketRegime,
}: {
  metrics: MetricItem[];
  hasIntent: boolean;
  intent: string;
  intentScore: number;
  hasRegime: boolean;
  marketRegime: string;
}) {
  if (!hasIntent && !hasRegime && metrics.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-1.5">
      {metrics.map((metric) => (
        <div
          key={metric.label}
          className="rounded border px-2 py-1.5"
          style={{
            borderColor: "var(--border-faint)",
            background: "var(--bg-card-inner)",
          }}
        >
          <div
            style={{
              fontSize: "7px",
              fontWeight: 600,
              letterSpacing: "0.06em",
              color: "var(--fg-5)",
              textTransform: "uppercase" as const,
            }}
          >
            {metric.label}
          </div>
          <div className="fa-num" style={{ marginTop: "2px", fontSize: "12px", fontWeight: 700, color: "var(--fg-1)" }}>
            {metric.format(metric.value)}
          </div>
        </div>
      ))}
      {hasIntent ? (
        <div
          className="rounded border px-2 py-1.5"
          style={{
            borderColor: "var(--border-faint)",
            background: "var(--bg-card-inner)",
          }}
        >
          <div
            style={{
              fontSize: "7px",
              fontWeight: 600,
              letterSpacing: "0.06em",
              color: "var(--fg-5)",
              textTransform: "uppercase" as const,
            }}
          >
            结构倾向
          </div>
          <div style={{ marginTop: "2px", fontSize: "10px", fontWeight: 600, color: "var(--fg-2)" }}>
            {translateIntent(intent)} · {(intentScore * 100).toFixed(0)}%
          </div>
        </div>
      ) : null}
      {hasRegime ? (
        <div
          className="rounded border px-2 py-1.5"
          style={{
            borderColor: "var(--border-faint)",
            background: "var(--bg-card-inner)",
          }}
        >
          <div
            style={{
              fontSize: "7px",
              fontWeight: 600,
              letterSpacing: "0.06em",
              color: "var(--fg-5)",
              textTransform: "uppercase" as const,
            }}
          >
            期权状态
          </div>
          <div style={{ marginTop: "2px", fontSize: "10px", fontWeight: 600, color: "var(--fg-2)" }}>
            {translateIntent(marketRegime)}
          </div>
        </div>
      ) : null}
    </div>
  );
}
