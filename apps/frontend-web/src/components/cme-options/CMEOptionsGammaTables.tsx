import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatNumber } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";
import { formatGEXM } from "./cmeOptionsGammaFormat";

export function GEXBreakdown({ snapshot, selectedExpiry }: { snapshot: CMEOptionsResponse; selectedExpiry?: string }) {
  const expiries = Object.keys(snapshot.gex?.by_expiry ?? {});
  if (expiries.length === 0) return null;
  const expiry = selectedExpiry && expiries.includes(selectedExpiry) ? selectedExpiry : expiries[0];
  const data = snapshot.gex?.by_expiry?.[expiry];
  if (!data?.gex_top?.length) return null;

  return (
    <CMEOptionsSurface title={`伽马敞口分布 · ${expiry}`}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)", color: CME_META_TEXT, fontSize: 10 }}>
              <th style={{ padding: "6px 10px", textAlign: "left" }}>行权价</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>总伽马</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>净伽马</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>看涨伽马</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>看跌伽马</th>
            </tr>
          </thead>
          <tbody>
            {data.gex_top.slice(0, 10).map((item) => (
              <tr key={item.strike} style={{ borderBottom: "1px solid var(--border-faint)" }}>
                <td style={{ padding: "4px 10px", fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--fg-2)" }}>{formatNumber(item.strike)}</td>
                <td style={{ padding: "4px 10px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--fg-3)" }}>{formatGEXM(item.total_gex)}</td>
                <td style={{ padding: "4px 10px", textAlign: "right", fontFamily: "var(--font-mono)", fontWeight: 600, color: item.net_gex < 0 ? "var(--down)" : "var(--up)" }}>{formatGEXM(item.net_gex)}</td>
                <td style={{ padding: "4px 10px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--fg-3)" }}>{formatGEXM(item.call_gex)}</td>
                <td style={{ padding: "4px 10px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--fg-3)" }}>{formatGEXM(item.put_gex)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </CMEOptionsSurface>
  );
}

export function IVSkewTable({ snapshot }: { snapshot: CMEOptionsResponse }) {
  const expiries = Object.keys(snapshot.gex?.by_expiry ?? {});
  if (expiries.length === 0) return null;

  return (
    <CMEOptionsSurface title="波动率偏斜 / 反推参数">
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)", color: CME_META_TEXT, fontSize: 10 }}>
              <th style={{ padding: "5px 8px", textAlign: "left" }}>到期月</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>反推远期价</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>剩余T</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>伽马零点</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>平值波动率</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>25D偏度</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>10D偏度</th>
            </tr>
          </thead>
          <tbody>
            {expiries.map((expiry) => {
              const expiryData = snapshot.gex?.by_expiry?.[expiry];
              const summary = expiryData?.summary;
              const skew = expiryData?.iv_skew;
              return (
                <tr key={expiry} style={{ borderBottom: "1px solid var(--border-faint)" }}>
                  <td style={{ padding: "5px 8px", fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--fg-2)" }}>{expiry}</td>
                  <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--fg-3)" }}>{formatNumber(summary?.forward_price, 1)}</td>
                  <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--fg-3)" }}>{summary?.time_to_expiry != null ? summary.time_to_expiry.toFixed(4) : "—"}</td>
                  <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--brand-hover)" }}>{formatNumber(summary?.gamma_zero, 1)}</td>
                  <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--fg-3)" }}>{skew?.atm_iv != null ? `${(skew.atm_iv * 100).toFixed(2)}%` : "—"}</td>
                  <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "var(--font-mono)", fontWeight: 600, color: skew?.skew_25d != null && skew.skew_25d > 0 ? "var(--down)" : "var(--up)" }}>{skew?.skew_25d != null ? `${skew.skew_25d > 0 ? "+" : ""}${(skew.skew_25d * 100).toFixed(2)}%` : "—"}</td>
                  <td style={{ padding: "5px 8px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--fg-3)" }}>{skew?.skew_10d != null ? `${skew.skew_10d > 0 ? "+" : ""}${(skew.skew_10d * 100).toFixed(2)}%` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </CMEOptionsSurface>
  );
}
