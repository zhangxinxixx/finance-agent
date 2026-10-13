import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatCMEExpiryLabel, formatNumber, isFiniteNumber, toneStyle, translateDecisionText } from "./cmeOptionsFormat";
import { formatBillions } from "./cmeOptionsGammaFormat";
import { GEXBreakdown, IVSkewTable } from "./CMEOptionsGammaTables";
import { CMEOptionsSurface } from "./CMEOptionsSurface";
import { buildPriceLadderLevels, PriceLadderLevelRow } from "./PriceLadderLevels";
import { resolveCMEExpiryScope } from "./cmeDecisionIdentity";

export { GEXBreakdown, IVSkewTable };

export function PriceLadder({
  supportResistance,
  currentPrice,
  }: {
  supportResistance: CMEOptionsResponse["support_resistance"];
  currentPrice: number | null;
}) {
  const levels = buildPriceLadderLevels(supportResistance, currentPrice);
  const missingLevels = [...supportResistance.resistance, ...supportResistance.support].filter((item) => !isFiniteNumber(item.strike));

  return (
    <CMEOptionsSurface title="价格层级" bodyStyle={{ padding: 0 }}>
      <div className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
        这是 CME 期权行权价坐标上的结构参考。报告锚点不是实时现货；支撑/阻力也不代表触发概率，实时条件需另行核验。
        {missingLevels.length > 0 ? ` ${missingLevels.length} 行行权价未提供，未绘制为零点。` : null}
      </div>
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
  const wallScores = snapshot.wall_scores ?? [];
  const callWalls = wallScores.filter((wall) => wall.side === "CALL");
  const putWalls = wallScores.filter((wall) => wall.side === "PUT");
  const completeOi = (rows: typeof wallScores) => {
    const values = rows.map((wall) => wall.oi);
    return values.length > 0 && values.every(isFiniteNumber) ? values.reduce((sum, value) => sum + value, 0) : null;
  };
  const callOi = completeOi(callWalls);
  const putOi = completeOi(putWalls);
  const partialOi = wallScores.some((wall) => !isFiniteNumber(wall.oi));
  const hasHistoricalComparison = Object.keys(snapshot.calibration?.wall_score_delta_1d ?? {}).length > 0
    || Object.keys(snapshot.calibration?.wall_score_delta_1w ?? {}).length > 0
    || Object.keys(snapshot.calibration?.oi_change_by_strike ?? {}).length > 0;
  const rows = [
    { label: "聚合净伽马", value: formatNumber(gex?.net_gex), tone: gex?.net_gex == null ? "slate" : gex.net_gex < 0 ? "down" : "up" },
    { label: "伽马零点", value: formatNumber(gex?.gamma_zero?.price, 1), tone: gex?.gamma_zero?.price == null ? "slate" : "up" },
    { label: "看涨持仓", value: formatNumber(callOi), tone: callOi == null ? "slate" : "down" },
    { label: "看跌持仓", value: formatNumber(putOi), tone: putOi == null ? "slate" : "up" },
  ];

  return (
    <CMEOptionsSurface title="当前结构指标" bodyStyle={{ padding: 0 }}>
      <div className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
        {hasHistoricalComparison
          ? "接口返回部分历史校准字段；下方仍是当前快照值，不能把当前值直接当成日变化。"
          : "未提供历史快照比较；下方当前值不能解释为日变化。"}
        {partialOi ? " 持仓部分未提供，对应汇总不可比；明细保留缺失行。" : null}
      </div>
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
    ...skewFindings.map((finding) => ({
      label: "模型提示",
      value: translateDecisionText(finding),
      color: "var(--fg-3)",
    })),
  ];

  return (
    <CMEOptionsSurface title="波动率偏斜 / 尾部风险" bodyStyle={{ padding: "8px 12px" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ fontSize: "var(--type-caption)", lineHeight: 1.5, color: "var(--fg-4)", paddingBottom: 4 }}>
          偏斜和伽马零点是按当前期权结构推导的模型指标，不是方向概率；未提供历史基准时不推断偏斜变化。
        </div>
        {rows.map((row, index) => (
          <div key={`${row.label}-${row.value}-${index}`} style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: "var(--text-10)" }}>
            <span style={{ color: "var(--fg-5)", minWidth: 90, flexShrink: 0 }}>{row.label}</span>
            {row.value ? (
              <span className="fa-num" style={{ color: row.color, fontWeight: 600, fontSize: "var(--text-10)" }}>{row.value}</span>
            ) : (
              <span style={{ color: "var(--fg-4)" }}>{row.label}</span>
            )}
          </div>
        ))}
        {skewFindings.length === 0 ? <div style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-5)" }}>暂无波动率偏斜数据</div> : null}
      </div>
    </CMEOptionsSurface>
  );
}

export function ExposurePanel({ snapshot, selectedExpiry }: { snapshot: CMEOptionsResponse; selectedExpiry?: string }) {
  const expiries = Object.keys(snapshot.exposure ?? {});
  if (expiries.length === 0) return null;
  const scope = resolveCMEExpiryScope(expiries, selectedExpiry);
  if (scope.missing) {
    return <CMEOptionsSurface title={`敞口 · ${formatCMEExpiryLabel(selectedExpiry)}`}><div className="px-3 py-4 text-[length:var(--type-caption)] text-[var(--fg-3)]">所选到期月未返回敞口；未回退到其他期限。</div></CMEOptionsSurface>;
  }
  const displayExpiries = selectedExpiry ? [scope.expiry as string] : expiries;

  return (
    <CMEOptionsSurface title={selectedExpiry ? `敞口 · ${formatCMEExpiryLabel(selectedExpiry)}` : "敞口"}>
      <div className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
        到期月筛选只作用于已返回的敞口键；数值是结构敞口，不代表价格方向概率。缺少字段显示为“—”，不会补成 0。
      </div>
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
            {displayExpiries.map((expiry) => {
              const exposure = snapshot.exposure?.[expiry];
              return (
                <tr key={expiry} style={{ borderBottom: "1px solid var(--border-faint)" }}>
                  <td className="fa-num" style={{ padding: "5px 8px", fontWeight: 600, color: "var(--fg-2)" }}>{formatCMEExpiryLabel(expiry)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", fontWeight: 600, color: exposure?.net_delta_exposure == null ? "var(--fg-4)" : exposure.net_delta_exposure < 0 ? "var(--down)" : "var(--up)" }}>{formatBillions(exposure?.net_delta_exposure)}</td>
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
