import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatCMEExpiryLabel, formatNumber } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";
import { formatGEXM } from "./cmeOptionsGammaFormat";
import { resolveCMEExpiryScope } from "./cmeDecisionIdentity";

export function GEXBreakdown({ snapshot, selectedExpiry }: { snapshot: CMEOptionsResponse; selectedExpiry?: string }) {
  const expiries = Object.keys(snapshot.gex?.by_expiry ?? {});
  if (expiries.length === 0) return null;
  const scope = resolveCMEExpiryScope(expiries, selectedExpiry);
  if (scope.missing) {
    return <CMEOptionsSurface title={`伽马敞口分布 · ${formatCMEExpiryLabel(selectedExpiry)}`}><div className="px-3 py-4 text-[length:var(--type-caption)] text-[var(--fg-3)]">所选到期月未返回 GEX 结构；未回退到其他期限。</div></CMEOptionsSurface>;
  }
  const expiry = scope.expiry;
  if (!expiry) return null;
  const data = snapshot.gex?.by_expiry?.[expiry];
  if (!data?.gex_top?.length) {
    return <CMEOptionsSurface title={`伽马敞口分布 · ${formatCMEExpiryLabel(expiry)}`}><div className="px-3 py-4 text-[length:var(--type-caption)] text-[var(--fg-3)]">该到期月暂无可用 GEX 行。</div></CMEOptionsSurface>;
  }
  const product = snapshot.data_source?.product === "OG"
    ? "COMEX 黄金期权（OG）"
    : snapshot.data_source?.product && /[\u3400-\u9fff]/.test(snapshot.data_source.product)
      ? snapshot.data_source.product
      : "CME 黄金期权";
  const gexMode = snapshot.parameters?.used_real_gex === true
    ? "模型伽马敞口（GEX）"
    : snapshot.parameters?.used_real_gex === false
      ? "代理伽马敞口（GEX）"
      : "伽马敞口（GEX）口径未标注";
  const reportDate = snapshot.data_source?.report_date && snapshot.data_source.report_date !== "unavailable"
    ? `报告发布日期 ${snapshot.data_source.report_date}`
    : "报告发布日期未提供";
  const tradeDate = snapshot.trade_date && snapshot.trade_date !== "unavailable" ? snapshot.trade_date : "未提供";

  return (
    <CMEOptionsSurface title={`伽马敞口分布 · ${formatCMEExpiryLabel(expiry)}`}>
      <div className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
        坐标：{product} 行权价；口径：{gexMode}；交易日 {tradeDate}，{reportDate}。当前到期月为 {formatCMEExpiryLabel(expiry)}；总/净/看涨/看跌伽马是结构敞口，不是价格概率，未提供历史快照比较时不推断变化。
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: "var(--text-10)", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)", color: CME_META_TEXT, fontSize: "var(--text-10)" }}>
              <th style={{ padding: "6px 10px", textAlign: "left" }}>行权价</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>总伽马</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>净伽马</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>看涨伽马</th>
              <th style={{ padding: "6px 10px", textAlign: "right" }}>看跌伽马</th>
            </tr>
          </thead>
          <tbody>
            {data.gex_top.map((item, index) => (
              <tr key={`${item.strike}-${index}`} style={{ borderBottom: "1px solid var(--border-faint)" }}>
                <td className="fa-num" style={{ padding: "4px 10px", fontWeight: 600, color: "var(--fg-2)" }}>{formatNumber(item.strike)}</td>
                <td className="fa-num" style={{ padding: "4px 10px", textAlign: "right", color: "var(--fg-3)" }}>{formatGEXM(item.total_gex)}</td>
                <td className="fa-num" style={{ padding: "4px 10px", textAlign: "right", fontWeight: 600, color: item.net_gex == null || !Number.isFinite(item.net_gex) ? "var(--fg-4)" : item.net_gex < 0 ? "var(--down)" : "var(--up)" }}>{formatGEXM(item.net_gex)}</td>
                <td className="fa-num" style={{ padding: "4px 10px", textAlign: "right", color: "var(--fg-3)" }}>{formatGEXM(item.call_gex)}</td>
                <td className="fa-num" style={{ padding: "4px 10px", textAlign: "right", color: "var(--fg-3)" }}>{formatGEXM(item.put_gex)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </CMEOptionsSurface>
  );
}

export function IVSkewTable({ snapshot, selectedExpiry }: { snapshot: CMEOptionsResponse; selectedExpiry?: string }) {
  const expiries = Object.keys(snapshot.gex?.by_expiry ?? {});
  if (expiries.length === 0) return null;
  const scope = resolveCMEExpiryScope(expiries, selectedExpiry);
  if (scope.missing) {
    return <CMEOptionsSurface title={`波动率偏斜 / 反推参数 · ${formatCMEExpiryLabel(selectedExpiry)}`}><div className="px-3 py-4 text-[length:var(--type-caption)] text-[var(--fg-3)]">所选到期月未返回波动率结构；未回退到其他期限。</div></CMEOptionsSurface>;
  }
  const displayExpiries = selectedExpiry ? [scope.expiry as string] : expiries;
  const product = snapshot.data_source?.product === "OG"
    ? "COMEX 黄金期权（OG）"
    : snapshot.data_source?.product && /[\u3400-\u9fff]/.test(snapshot.data_source.product)
      ? snapshot.data_source.product
      : "CME 黄金期权";

  return (
    <CMEOptionsSurface title={selectedExpiry ? `波动率偏斜 / 反推参数 · ${formatCMEExpiryLabel(selectedExpiry)}` : "波动率偏斜 / 反推参数"}>
      <div className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
        坐标：{product}；表内远期价、剩余期限、隐含波动率和偏斜为按到期月返回的模型参数。它们不等于现货实时行情；未提供历史基准时不推断变化。
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: "var(--text-10)", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)", color: CME_META_TEXT, fontSize: "var(--text-10)" }}>
              <th style={{ padding: "5px 8px", textAlign: "left" }}>到期月</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>反推远期价</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>剩余期限</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>伽马零点</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>平值波动率</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>25Δ 偏度</th>
              <th style={{ padding: "5px 8px", textAlign: "right" }}>10Δ 偏度</th>
            </tr>
          </thead>
          <tbody>
            {displayExpiries.map((expiry) => {
              const expiryData = snapshot.gex?.by_expiry?.[expiry];
              const summary = expiryData?.summary;
              const skew = expiryData?.iv_skew;
              return (
                <tr key={expiry} style={{ borderBottom: "1px solid var(--border-faint)" }}>
                  <td className="fa-num" style={{ padding: "5px 8px", fontWeight: 600, color: "var(--fg-2)" }}>{formatCMEExpiryLabel(expiry)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{formatNumber(summary?.forward_price, 1)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{summary?.time_to_expiry != null ? summary.time_to_expiry.toFixed(4) : "—"}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", fontWeight: 600, color: "var(--brand-hover)" }}>{formatNumber(summary?.gamma_zero, 1)}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{skew?.atm_iv != null ? `${(skew.atm_iv * 100).toFixed(2)}%` : "—"}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", fontWeight: 600, color: skew?.skew_25d == null ? "var(--fg-4)" : skew.skew_25d > 0 ? "var(--down)" : "var(--up)" }}>{skew?.skew_25d != null ? `${skew.skew_25d > 0 ? "+" : ""}${(skew.skew_25d * 100).toFixed(2)}%` : "—"}</td>
                  <td className="fa-num" style={{ padding: "5px 8px", textAlign: "right", color: "var(--fg-3)" }}>{skew?.skew_10d != null ? `${skew.skew_10d > 0 ? "+" : ""}${(skew.skew_10d * 100).toFixed(2)}%` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </CMEOptionsSurface>
  );
}
