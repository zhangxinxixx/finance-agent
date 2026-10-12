import type { GoldWorkspace } from "@/types/gold-workspace";
import { factStatus, goldNumber } from "./GoldEvidenceMatrix";
import { ResearchDetails } from "@/components/shared/ResearchDetails";

/** Plot supplied observations; different dates are never joined into one yield curve. */
export function GoldRatesVisual({ data }: { data: GoldWorkspace }) {
  const keys = ["US02Y", "US10Y", "US30Y", "REAL10Y", "T10YIE"];
  const rows = keys.map(key => data.factors.find(fact => fact.key === key)).filter(fact => fact !== undefined);
  const supplied = rows.filter(row => row.value !== null);
  const extent = Math.max(1, ...supplied.map(row => Math.abs(row.value!)));
  return <section className="fa-card gold-rates-visual" aria-label="名义利率、实际利率与通胀补偿观测图">
    <h2 className="fa-section-title">资金成本：名义利率、实际利率与通胀补偿</h2>
    <p className="fa-muted-text">名义收益率上涨通常增加压力；短线回落可缓冲压力，实际利率单独确认。</p>
    <div className="gold-rate-bars">{rows.map(row => <div className="gold-rate-bar-row" key={row.key}>
      <span className="fa-body-text">{row.label}</span>
      <div className="gold-rate-bar-track" aria-hidden="true"><span className={`gold-rate-bar gold-rate-bar--${row.status}`} style={{ width: row.value === null ? "0%" : `${Math.abs(row.value) / extent * 100}%` }} /></div>
      <strong className="fa-body-text">{goldNumber(row.value)}%</strong><span className="fa-faint-text">{factStatus[row.status]}</span>
    </div>)}</div>
    {!supplied.length ? <p className="fa-muted-text">收益率读数尚未返回。</p> : null}
    <ResearchDetails label="查看收益率观测口径"><p>分别展示已采集读数，不同观测不会拼成同一时点曲线。</p>
      {rows.map(row => <p key={row.key}>{row.label} · {row.observed_at ?? "日期未提供"}</p>)}</ResearchDetails>
  </section>;
}
