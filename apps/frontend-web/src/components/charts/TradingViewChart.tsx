import { useEffect, useState } from "react";

const SYMBOL = "OANDA:XAUUSD";
const PERIODS = { "15m": "15", "1h": "60", "4h": "240" } as const;
type Period = keyof typeof PERIODS;
const LOAD_TIMEOUT_MS = 20_000;

// This isolated external view never supplies facts to the system read models.
function TradingViewFrame({ period, height }: { period: Period; height: number }) {
  const [status, setStatus] = useState<"loading" | "loaded" | "slow" | "failed">("loading");
  useEffect(() => {
    const timer = window.setTimeout(() => setStatus(current => current === "loading" ? "slow" : current), LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, []);
  const params = new URLSearchParams({
    symbol: SYMBOL, interval: PERIODS[period], theme: "light", style: "1",
    locale: "zh_CN", timezone: "Asia/Shanghai", allow_symbol_change: "false",
    hide_side_toolbar: "true", save_image: "false", hidesidetoolbar: "1",
  });
  return <>
    {status !== "loaded" && <p role="status" className="fa-muted-text px-3 py-2">
      {status === "loading" ? "正在加载 TradingView…" : status === "failed"
        ? "TradingView 暂时无法加载，可在新窗口查看。"
        : "TradingView 加载较慢，可在新窗口查看。"}
    </p>}
    <iframe title={`TradingView 黄金现货 ${period}`} src={`https://www.tradingview.com/widgetembed/?${params}`}
      className="block w-full border-0 bg-[var(--bg-card)]" style={{ height }}
      referrerPolicy="strict-origin-when-cross-origin"
      onLoad={() => setStatus(current => current === "failed" ? current : "loaded")}
      onError={() => setStatus("failed")} />
  </>;
}

export function TradingViewChart({ height = 400 }: { height?: number }) {
  const [period, setPeriod] = useState<Period>("15m");
  return <section aria-label="TradingView 黄金看盘">
    <div className="flex flex-wrap items-center gap-2 px-3 py-2" aria-label="看盘周期">
      {(Object.keys(PERIODS) as Period[]).map(value => <button key={value} type="button"
        className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1 text-[length:var(--type-label)] text-[var(--fg-2)] aria-pressed:border-[var(--brand)] aria-pressed:bg-[var(--brand-dim)] aria-pressed:text-[var(--brand)]"
        aria-pressed={period === value} onClick={() => setPeriod(value)}>{value}</button>)}
      <a href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(SYMBOL)}&interval=${PERIODS[period]}`}
        target="_blank" rel="noopener noreferrer" className="fa-muted-text">在 TradingView 新窗口查看 ↗</a>
    </div>
    <TradingViewFrame key={period} period={period} height={height} />
    <p className="fa-muted-text px-3 py-2">OANDA:XAUUSD · 行情由 TradingView 提供，分析以研究报告的数据时点为准。</p>
  </section>;
}
