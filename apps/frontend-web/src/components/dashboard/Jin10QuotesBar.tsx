import { useJin10Quotes } from "@/hooks/useJin10Quotes";
import type { Jin10Quote } from "@/types/jin10";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";

const PRIORITY_SYMBOLS: { code: string; label: string; precision: number }[] = [
  { code: "XAUUSD", label: "黄金", precision: 1 },
  { code: "XAGUSD", label: "白银", precision: 2 },
  { code: "DXY", label: "美元指数", precision: 2 },
  { code: "SPX", label: "标普500", precision: 0 },
  { code: "USOIL", label: "WTI原油", precision: 2 },
  { code: "USDJPY", label: "美元/日元", precision: 2 },
  { code: "EURUSD", label: "欧元/美元", precision: 4 },
  { code: "USDCNH", label: "美元/人民币", precision: 4 },
];

function formatPrice(value: number | null, precision: number): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}

function formatChange(change: number | null, changePct: number | null): {
  text: string;
  tone: "up" | "down" | "dim";
} {
  if (change === null && changePct === null) {
    return { text: "—", tone: "dim" };
  }
  const delta = change ?? 0;
  const pct = changePct ?? 0;
  const sign = delta >= 0 ? "+" : "";
  const text = `${sign}${formatPrice(delta, 2)} (${sign}${pct.toFixed(2)}%)`;

  if (delta > 0) return { text, tone: "up" };
  if (delta < 0) return { text, tone: "down" };
  return { text: "0.00 (0.00%)", tone: "dim" };
}

function QuoteCard({ quote, label, precision }: { quote: Jin10Quote; label: string; precision: number }) {
  const price = formatPrice(quote.price, precision);
  const change = formatChange(quote.change, quote.change_pct);

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 font-mono text-[16px] font-bold leading-none text-[var(--fg-1)]">{price}</div>
      <div className={`mt-1 text-[10px] font-semibold ${change.tone === "up" ? "text-[var(--up)]" : change.tone === "down" ? "text-[var(--down)]" : "text-[var(--fg-5)]"}`}>
        {change.text}
      </div>
    </div>
  );
}

function EmptyQuoteCard({ label }: { label: string }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2.5 opacity-60">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 font-mono text-[16px] font-bold leading-none text-[var(--fg-4)]">—</div>
      <div className="mt-1 text-[10px] text-[var(--fg-5)]">等待数据</div>
    </div>
  );
}

export function Jin10QuotesBar() {
  const { data, isError } = useJin10Quotes();

  if (isError || !data || data.status === "unavailable") {
    return null;
  }

  const quotes = data.quotes ?? {};

  return (
    <FACard
      title="实时行情"
      eyebrow="Jin10 MCP"
      accent="info"
      bodyClassName="space-y-3"
      action={<FAStatusPill tone="dim">30s refresh</FAStatusPill>}
    >
      <div className="flex items-center gap-2 text-[10px] text-[var(--fg-5)]">
        <span>实时行情条</span>
        {data.counts.flash_news > 0 ? <span className="text-[var(--brand-hover)]">{data.counts.flash_news} 条快讯</span> : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        {PRIORITY_SYMBOLS.map(({ code, label, precision }) => {
          const quote = quotes[code];
          if (!quote) {
            return <EmptyQuoteCard key={code} label={label} />;
          }
          return <QuoteCard key={code} quote={quote} label={label} precision={precision} />;
        })}
      </div>
    </FACard>
  );
}
