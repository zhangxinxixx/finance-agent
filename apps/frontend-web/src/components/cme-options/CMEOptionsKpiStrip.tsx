import type { CMEOptionsDecisionResponse, CMEOptionsResponse } from "@/types/cme-options";
import { formatCompactNumber, formatNumber } from "./cmeOptionsFormat";

interface CMEOptionsKpiStripProps {
  snapshot: CMEOptionsResponse;
  decision?: CMEOptionsDecisionResponse | null;
}

interface KpiItem {
  label: string;
  value: string;
}

function StatChip({ item }: { item: KpiItem }) {
  return (
    <div className="cme-options-kpi-chip">
      <span className="fa-kpi-chip-label">{item.label}</span>
      <span className="fa-kpi-chip-value">{item.value}</span>
    </div>
  );
}

export function CMEOptionsKpiStrip({ snapshot, decision }: CMEOptionsKpiStripProps) {
  const gex = snapshot.gex?.netgex_aggregate;
  const decisionGamma = decision?.gamma_summary;
  const gammaZero = gex?.gamma_zero?.price ?? decisionGamma?.gamma_zero;
  const forwardPrice = snapshot.parameters?.f_value ?? decision?.price_context.report_p0 ?? gammaZero;
  const netGex = gex?.net_gex ?? decisionGamma?.net_gex;
  const decisionDirection = decisionGamma?.regime === "negative_gamma"
    ? "negative"
    : decisionGamma?.regime === "positive_gamma"
      ? "positive"
      : decisionGamma?.regime === "flip_zone"
        ? "neutral"
        : null;
  const snapshotDirection = gex?.net_gex_direction === "negative" || gex?.net_gex_direction === "positive" || gex?.net_gex_direction === "neutral"
    ? gex.net_gex_direction
    : null;
  const direction = snapshotDirection ?? decisionDirection;
  const resolvedDirection = direction ?? (netGex === undefined || netGex === null ? null : netGex < 0 ? "negative" : netGex > 0 ? "positive" : "neutral");
  const expiryCount = snapshot.data_source?.expiries?.length ?? 0;
  const rowCount = snapshot.data_source?.row_count ?? 0;

  const structure = resolvedDirection === "negative" ? "负伽马" : resolvedDirection === "positive" ? "正伽马" : resolvedDirection === "neutral" ? "中性" : "未提供";
  const kpis: KpiItem[] = [
    { label: "聚合净伽马", value: formatCompactNumber(netGex) },
    { label: "伽马零点", value: `${formatNumber(gammaZero, 1)} 点` },
    { label: "远期价", value: `${formatNumber(forwardPrice, 1)} 点` },
    { label: "到期月", value: `${formatNumber(expiryCount)} 个` },
    { label: "样本", value: `${formatNumber(rowCount)} 行` },
  ];

  return (
    <div className="cme-options-kpi-strip">
      <div className={`cme-options-kpi-structure cme-options-kpi-structure--${resolvedDirection ?? "unavailable"}`}>
        <span>结构</span>
        <strong>{structure}</strong>
      </div>
      <div className="cme-options-kpi-values">
        {kpis.map((item) => <StatChip key={item.label} item={item} />)}
      </div>
    </div>
  );
}
