import { FAMetricCard } from "@/components/shared/FAMetricCard";
import type { FinalReportView } from "@/types/reports";

function shortRunId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length <= 12 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function ReportMetaStrip({ report }: { report: FinalReportView }) {
  return (
    <section className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
      <FAMetricCard label="asset" value={report.asset || "—"} hint="报告资产" />
      <FAMetricCard label="trade_date" value={report.trade_date || "—"} hint="交易日期" />
      <FAMetricCard label="run_id" value={shortRunId(report.run_id)} hint="执行批次" />
      <FAMetricCard label="format" value={report.format || "markdown"} hint="产物格式" />
      <FAMetricCard label="content" value={formatCount(report.content_length)} unit="chars" hint="正文长度" />
      <FAMetricCard label="warnings" value={String(report.warning_count)} hint={report.source_endpoint} />
    </section>
  );
}

export default ReportMetaStrip;
