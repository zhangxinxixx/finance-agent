import type { CMEOptionsResponse } from "@/types/cme-options";
import { formatNumber, toneStyle } from "./cmeOptionsFormat";

interface CMEOptionsKpiStripProps {
  snapshot: CMEOptionsResponse;
}

interface KpiItem {
  label: string;
  value: string;
  tone: string;
}

function StatCard({ item }: { item: KpiItem }) {
  const tone = toneStyle(item.tone);

  return (
    <div
      style={{
        background: tone.bg,
        border: `1px solid ${tone.border}`,
        borderRadius: "var(--radius-md)",
        padding: "5px 8px",
        display: "flex",
        alignItems: "baseline",
        gap: 6,
        minHeight: 28,
      }}
    >
      <span style={{ fontSize: 9, color: tone.text, fontWeight: 700, whiteSpace: "nowrap" }}>{item.label}</span>
      <span className="fa-num" style={{ fontSize: 12, fontWeight: 800, color: "var(--fg-1)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{item.value}</span>
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

  const kpis: KpiItem[] = [
    { label: "结构", value: direction === "negative" ? "负伽马" : direction === "positive" ? "正伽马" : "中性", tone: "info" },
    { label: "净伽马", value: formatNumber(netGex), tone: direction === "negative" ? "down" : "up" },
    { label: "伽马零点", value: formatNumber(gammaZero, 1), tone: "violet" },
    { label: "远期价", value: formatNumber(forwardPrice, 1), tone: "info" },
    { label: "到期月", value: formatNumber(expiryCount), tone: "warn" },
    { label: "行数", value: formatNumber(rowCount), tone: "warn" },
  ];

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {kpis.map((item) => <StatCard key={item.label} item={item} />)}
    </div>
  );
}
