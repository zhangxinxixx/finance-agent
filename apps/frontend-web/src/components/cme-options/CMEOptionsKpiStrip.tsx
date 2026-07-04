import type { CMEOptionsResponse } from "@/types/cme-options";
import { formatNumber } from "./cmeOptionsFormat";

interface CMEOptionsKpiStripProps {
  snapshot: CMEOptionsResponse;
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

export function CMEOptionsKpiStrip({ snapshot }: CMEOptionsKpiStripProps) {
  const gex = snapshot.gex?.netgex_aggregate;
  const gammaZero = gex?.gamma_zero?.price;
  const forwardPrice = snapshot.parameters?.f_value ?? gammaZero;
  const netGex = gex?.net_gex;
  const direction = gex?.net_gex_direction ?? "neutral";
  const expiryCount = snapshot.data_source?.expiries?.length ?? 0;
  const rowCount = snapshot.data_source?.row_count ?? 0;

  const structure = direction === "negative" ? "负伽马" : direction === "positive" ? "正伽马" : "中性";
  const kpis: KpiItem[] = [
    { label: "净伽马", value: formatNumber(netGex) },
    { label: "伽马零点", value: formatNumber(gammaZero, 1) },
    { label: "远期价", value: formatNumber(forwardPrice, 1) },
    { label: "到期月", value: formatNumber(expiryCount) },
    { label: "行数", value: formatNumber(rowCount) },
  ];

  return (
    <div className="cme-options-kpi-strip">
      <div className={`cme-options-kpi-structure cme-options-kpi-structure--${direction}`}>
        <span>结构</span>
        <strong>{structure}</strong>
      </div>
      <div className="cme-options-kpi-values">
        {kpis.map((item) => <StatChip key={item.label} item={item} />)}
      </div>
    </div>
  );
}
