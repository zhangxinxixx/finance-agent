import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { beijingTime } from "@/components/dashboard/DashboardResearchBriefModel";
import type { GoldWorkspace } from "@/types/gold-workspace";
import { factChange, goldNumber } from "./GoldEvidenceMatrix";
import { changeTone, goldSourceLabel } from "./goldPresentation";

export function GoldMarketHeadline({ data, reviewOnly }: { data: GoldWorkspace; reviewOnly: boolean }) {
  const price = data.price;
  const verified = !reviewOnly && price.status === "fresh";
  const tone = changeTone(price.change, verified);
  const compared = !reviewOnly && data.comparison.status === "available";
  return <section className="fa-card gold-market-headline" aria-label="黄金当前观测与研究截止">
    <div className="gold-quote-main">
      <div className="gold-quote-heading"><h2 className="fa-section-title">当前行情 <span className="fa-label">XAUUSD</span></h2>
        <FAStatusPill tone={verified ? "info" : "warn"}>{reviewOnly ? "上次观测" : verified ? "行情已更新" : "行情待更新"}</FAStatusPill></div>
      <div className="gold-quote-number"><strong className={`fa-price-num gold-tone--${tone}`}>{goldNumber(price.value)}</strong><span className="fa-label">美元/盎司</span>
        <span className={`gold-price-change gold-tone--${tone}`}>{price.change === null ? "日涨跌待补齐"
          : `${tone === "up" ? "↑ 上涨 · " : tone === "down" ? "↓ 下跌 · " : ""}${factChange(price)}`}</span></div>
      <p className="fa-muted-text">{goldSourceLabel(price.source)}</p>
    </div>
    <div className="gold-quote-research"><span className="fa-label">研究状态</span>
      <strong className="fa-body-text">{data.research.latest_status === "unavailable" ? "等待本次分析" : data.research.status === "current" ? "本次研究" : "原研究需更新"}</strong>
      <p className="fa-muted-text">{data.research.status === "unavailable" ? "点击更新数据并分析，生成短线与长线研究。"
        : data.research.status === "current" && !reviewOnly ? "短线、长线和策略均沿用这次研究。" : "行情与研究分别更新，原结论仍需核验。"}</p>
      {compared ? <p className={`fa-body-text gold-tone--${changeTone(data.comparison.price_change)}`}>较研究参考价 {goldNumber(data.comparison.price_change)} 美元（{goldNumber(data.comparison.price_change_pct)}%）</p> : null}
    </div>
    <ResearchDetails className="gold-quote-details" label="查看行情来源与涨跌口径">
      <div className="gold-detail-copy"><p className="fa-body-text">{price.interpretation}</p>
        <p className="fa-body-text">行情观测：{beijingTime(price.observed_at)} · 研究截止：{beijingTime(data.research.as_of)}</p>
        {price.change === null ? <p className="fa-body-text">未计算日涨跌：当前来源没有提供可核验的日变动，不能用一根K线推算全天涨跌。</p> : null}
        <p className="fa-body-text">{data.comparison.note}</p>
        {data.warnings.map((warning, index) => <p key={index} className="fa-body-text">{warning}</p>)}
      </div>
    </ResearchDetails>
  </section>;
}
