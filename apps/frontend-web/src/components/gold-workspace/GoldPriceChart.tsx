import { TradingViewChart } from "@/components/charts/TradingViewChart";

export function GoldPriceChart() {
  return <section className="fa-card gold-workspace-chart" aria-label="黄金现货多周期走势图">
    <header className="gold-section-header"><div><h2 className="fa-section-title">黄金走势与结构检验</h2>
      <p className="fa-muted-text">4H 看方向，1H 看结构，15m 看确认。外部看盘不补充旧报告事实。</p></div></header>
    <TradingViewChart height={350} />
  </section>;
}
