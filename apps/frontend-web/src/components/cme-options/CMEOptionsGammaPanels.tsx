import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatNumber, toneStyle } from "./cmeOptionsFormat";
import { formatBillions } from "./cmeOptionsGammaFormat";
import { GEXBreakdown, IVSkewTable } from "./CMEOptionsGammaTables";
import { CMEOptionsSurface } from "./CMEOptionsSurface";
import { buildPriceLadderLevels, PriceLadderLevelRow } from "./PriceLadderLevels";

export { GEXBreakdown, IVSkewTable };

export function PriceLadder({
  supportResistance,
  currentPrice,
}: {
  supportResistance: CMEOptionsResponse["support_resistance"];
  currentPrice: number;
}) {
  const levels = buildPriceLadderLevels(supportResistance, currentPrice);

  return (
    <CMEOptionsSurface title="价格层级" bodyStyle={{ padding: 0 }}>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {levels.map((level, index) => (
          <PriceLadderLevelRow key={`${level.label}-${level.strike}-${index}`} level={level} isLast={index >= levels.length - 1} />
        ))}
      </div>
    </CMEOptionsSurface>
  );
}

export function ChangeTable({ snapshot }: { snapshot: CMEOptionsResponse }) {
  const gex = snapshot.gex?.netgex_aggregate;
  const rows = [
    { label: "聚合净伽马", value: formatNumber(gex?.net_gex), tone: gex?.net_gex == null ? "slate" : gex.net_gex < 0 ? "down" : "up" },
    { label: "伽马零点", value: formatNumber(gex?.gamma_zero?.price, 1), tone: "up" },
    { label: "看涨持仓", value: formatNumber(snapshot.wall_scores?.reduce((sum, wall) => sum + (wall.side === "CALL" ? wall.oi : 0), 0)), tone: "down" },
    { label: "看跌持仓", value: formatNumber(snapshot.wall_scores?.reduce((sum, wall) => sum + (wall.side === "PUT" ? wall.oi : 0), 0)), tone: "up" },
  ];

  return (
    <CMEOptionsSurface title="日变化" bodyStyle={{ padding: 0 }}>
      {rows.map((row, index) => (
        <div
          key={row.label}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "7px 12px",
            borderBottom: index < rows.length - 1 ? "1px solid var(--border-faint)" : "none",
          }}
        >
          <span style={{ fontSize: "var(--text-10)", color: CME_META_TEXT }}>{row.label}</span>
          <span className="fa-num" style={{ fontSize: "var(--text-10)", fontWeight: 600, color: toneStyle(row.tone).text }}>
            {row.value}
          </span>
        </div>
      ))}
    </CMEOptionsSurface>
  );
}

export function SkewPanel({ snapshot }: { snapshot: CMEOptionsResponse }) {
  const findings = snapshot.calibration?.calibration_warnings ?? [];
  const skewFindings = findings.filter((finding) => /skew|tail|iv/i.test(finding));
  const gex = snapshot.gex?.netgex_aggregate;
  const direction = gex?.net_gex_direction ?? null;
  const directionLabel = direction === "negative" ? "负伽马" : direction === "positive" ? "正伽马" : direction === "neutral" ? "中性" : "未提供";

  const rows = [
    { label: "净伽马方向", value: directionLabel, color: direction === "negative" ? "var(--down)" : direction === "positive" ? "var(--up)" : direction === "neutral" ? "var(--fg-1)" : "var(--fg-4)" },
    { label: "伽马零点", value: formatNumber(gex?.gamma_zero?.price, 1), color: "var(--brand-hover)" },
    ...skewFindings.slice(0, 3).map((finding) => ({
      label: finding.length > 20 ? `${finding.slice(0, 20)}…` : finding,
      value: "",
      color: "var(--fg-3)",
    })),
  ];

  return (
    <CMEOptionsSurface title="波动率偏斜 / 尾部风险" bodyStyle={{ padding: "8px 12px" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.map((row) => (
          <div key={row.label} style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: "var(--text-10)" }}>
            <span style={{ color: "var(--fg-5)", minWidth: 90, flexShrink: 0 }}>{row.label}</span>
            {row.value ? (
              <span className="fa-num" style={{ color: row.color, fontWeight: 600, fontSize: "var(--text-10)" }}>{row.value}</span>
            ) : (
              <span style={{ color: "var(--fg-4)" }}>{row.label}</span>
            )}
          </div>
        ))}
        {skewFindings.length === 0 ? <div style={{ fontSize: "var(--text-10)", color: "var(--fg-5)" }}>暂无 skew 数据</div> : null}
      </div>
    </CMEOptionsSurface>
  );
}

export function ExposurePanel({ snapshot }: { snapshot: CMEOptionsResponse }) {
  const expiries = Object.keys(snapshot.exposure ?? {});
  if (expiries.length === 0) return null;

  return (
    <CMEOptionsSurface title="敞口">
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: "var(--text-10)", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)", color: CME_META_TEXT, fontSize: "var(--text-10)" }}>
              <th style={{ padding: "5px 8px", textAlign: "left" }}>到期月</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>净方向敞口</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>看涨敞口</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>看跌敞口</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>波动敞口</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>时间损耗/日</th>
            </tr>
          </thead>
          <tbody>
            {expiries.map((expiry) => {
              const exposure = snapshot.exposure?.[expiry];
              return (
                <tr key={expiry} style={{ borderBottom: "1px solid var(--border-faint)" }}>
                  <td className="fa-num" style={{ padding: "5px 8px", fontWeight: 600, color: "var(--fg-2)" }}>{expiry}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", fontWeight: 600, color: (exposure?.net_delta_exposure ?? 0) < 0 ? "var(--down)" : "var(--up)" }}>{formatBillions(exposure?.net_delta_exposure)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{formatBillions(exposure?.call_delta_exposure)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{formatBillions(exposure?.put_delta_exposure)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{formatBillions(exposure?.total_vega)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{formatBillions(exposure?.total_theta)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </CMEOptionsSurface>
  );
}
