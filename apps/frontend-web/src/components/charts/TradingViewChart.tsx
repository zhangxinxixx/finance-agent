import { useMemo } from "react";

type TradingViewTheme = "light" | "dark";

interface TradingViewChartProps {
  symbol?: string;
  interval?: string;
  theme?: TradingViewTheme;
  height?: number;
  className?: string;
}

export function TradingViewChart({
  symbol = "OANDA:XAUUSD",
  interval = "15",
  theme = "dark",
  height = 430,
  className = "",
}: TradingViewChartProps) {
  const src = useMemo(() => {
    const params = new URLSearchParams({
      symbol,
      interval,
      timezone: "Asia/Shanghai",
      theme,
      style: "1",
      locale: "zh_CN",
      toolbarbg: "131722",
      withdateranges: "1",
      hide_side_toolbar: "0",
      hide_top_toolbar: "0",
      saveimage: "0",
      hideideas: "1",
      symboledit: "1",
    });

    return `https://s.tradingview.com/widgetembed/?${params.toString()}`;
  }, [symbol, interval, theme]);

  return (
    <div className={`tradingview-chart-frame ${className}`} style={{ height }}>
      <iframe
        title={`TradingView ${symbol}`}
        src={src}
        className="tradingview-chart-frame__iframe"
        allowFullScreen
      />
    </div>
  );
}

export default TradingViewChart;
