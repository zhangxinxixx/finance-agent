import type { DashboardSummary } from "@/types/dashboard";

/** A timezone-free timestamp is kept verbatim, never silently assigned a zone. */
export function beijingTime(value?: string | null): string {
  if (!value) return "未提供";
  if (!/[T ]\d{2}:\d{2}.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) return `${value}（时区未提供）`;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return `${value}（时间不可解析）`;
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date) + " 北京时间";
}

export function beijingToday(now = new Date()): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

export function selectedResearchReport(summary: DashboardSummary) {
  const research = summary.integrated_macro;
  if (!research?.run_id || !research.trade_date) return undefined;
  return summary.latest_reports.find(report => report.status === "ready" && report.run_id === research.run_id
    && report.trade_date === research.trade_date
    && !/option|期权|supplement/i.test(`${report.type ?? ""} ${report.family ?? ""} ${report.title}`)
    && (report.report_id || report.url?.startsWith("/reports/")));
}

export function researchReportTarget(summary: DashboardSummary): string | null {
  const report = selectedResearchReport(summary);
  if (report?.report_id) return `/reports/${encodeURIComponent(report.report_id)}`;
  if (report?.url?.startsWith("/reports/")) return report.url;
  const research = summary.integrated_macro;
  // This identity must already exist in backend evidence; a run alone is insufficient.
  const ref = research?.source_refs?.find(item => research.run_id
    && item.trade_date === research.trade_date && item.source_ref === `observation_report:${research.run_id}`);
  return ref ? `/reports/${encodeURIComponent(ref.source_ref)}` : null;
}

const validValue = (value: unknown): value is string | number =>
  typeof value === "number" ? Number.isFinite(value) : typeof value === "string" && Boolean(value.trim()) && value !== "—";

export function dashboardResearchFacts(summary: DashboardSummary) {
  return ([ ["XAUUSD", "黄金现货 XAUUSD"], ["DXY", "美元指数 DXY"], ["US02Y", "美国 2Y"], ["US10Y", "美国 10Y"], ["REAL_10Y", "10Y 实际利率"] ] as const).map(([key, label]) => {
    const metric = summary.market_summary[key];
    const quote = summary.realtime_quotes?.[key] ?? summary.realtime_quotes?.[key.toLowerCase()];
    const quoteValue = quote?.price ?? quote?.value;
    const hasQuote = validValue(quoteValue);
    const spotMetric = key !== "XAUUSD" || metric?.instrument_kind === "spot";
    const hasMetric = spotMetric && metric?.status !== "unavailable" && metric?.status !== "error" && validValue(metric?.value);
    const value = hasQuote ? quoteValue : hasMetric ? metric.value : null;
    const priceTime = hasQuote ? quote?.price_time ?? quote?.time : null;
    const date = hasQuote ? quote?.trade_date ?? metric?.data_date : metric?.data_date;
    const source = hasQuote ? quote?.source : metric?.source;
    const barQuote = Boolean(source?.startsWith("twelvedata_") && source.endsWith("_5m"));
    return { key, label, value, unit: hasQuote ? quote?.unit ?? metric?.unit : metric?.unit,
      source,
      timing: priceTime ? `${barQuote ? "5分钟K线时点" : "行情时点"}：${beijingTime(priceTime)}` : `观测日期：${date || "未提供"}（非即时行情）`,
      note: key === "XAUUSD" && value === null ? "未取得可验证现价；GC 代理不可替代黄金现货。" : value === null ? "未取得有效读数" : barQuote ? "5分钟K线读数，非逐笔现价。" : null,
    };
  });
}

export function buildDashboardResearchBrief(summary: DashboardSummary, today = beijingToday()) {
  const research = summary.integrated_macro;
  const tradeDate = research?.trade_date || null;
  const date = tradeDate?.slice(0, 10);
  return { research, tradeDate, stale: Boolean(date && /^\d{4}-\d{2}-\d{2}$/.test(date) && date < today),
    observation: research?.authority === "observation_only" || research?.publish_allowed === false,
    asOf: beijingTime(research?.as_of), facts: dashboardResearchFacts(summary), reportTarget: researchReportTarget(summary),
  };
}
