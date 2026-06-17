import type { CMEOptionsDataSource } from "@/types/cme-options";
import { FACard } from "../shared/FACard";
import { FAMetricCard } from "../shared/FAMetricCard";
import { FAStatusPill, type FAStatusTone } from "../shared/FAStatusPill";
import { FAWarningBanner } from "../shared/FAWarningBanner";

interface OptionsSummaryBarProps {
  dataSource: CMEOptionsDataSource;
}

function formatRowCount(rowCount: number | null | undefined) {
  if (rowCount === null || rowCount === undefined) {
    return "—";
  }

  return rowCount.toLocaleString("en-US");
}

function formatExpiries(expiries: string[] | null | undefined) {
  if (!expiries || expiries.length === 0) {
    return [];
  }

  return expiries;
}

function statusTone(status: CMEOptionsDataSource["status"] | null | undefined): FAStatusTone {
  if (status === "FINAL") return "up";
  if (status === "PRELIM") return "warn";
  return "dim";
}

export function OptionsSummaryBar({ dataSource }: OptionsSummaryBarProps) {
  const versionLabel = dataSource.status || "—";
  const productLabel = dataSource.product?.trim() || "—";
  const rowCountLabel = formatRowCount(dataSource.row_count);
  const expiries = formatExpiries(dataSource.expiries);

  return (
    <FACard
      title="结构摘要"
      eyebrow="Snapshot Envelope"
      accent="info"
      action={<FAStatusPill tone={statusTone(dataSource.status)}>{versionLabel}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      {dataSource.status === "PRELIM" ? (
        <FAWarningBanner title="当前为 PRELIM 数据" description="FINAL 结果生成后应优先覆盖当前快照。" tone="warn" />
      ) : null}

      <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <FAMetricCard label="product" value={productLabel} hint="解析产品代码" />
        <FAMetricCard label="version" value={versionLabel} hint="报告版本语义" status={versionLabel} statusTone={statusTone(dataSource.status)} />
        <FAMetricCard label="rows" value={rowCountLabel} hint="规范化行数" />
        <FAMetricCard label="expiries" value={expiries.length > 0 ? expiries.length.toLocaleString("en-US") : "—"} hint="到期月数量" />
      </div>

      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-3">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">covered_expiries</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {expiries.length > 0 ? (
            expiries.map((expiry) => (
              <span
                key={expiry}
                className="inline-flex items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-panel)] px-2 py-1 text-[10px] font-semibold text-[var(--fg-3)]"
              >
                {expiry}
              </span>
            ))
          ) : (
            <span className="text-[11px] text-[var(--fg-4)]">暂无到期月信息</span>
          )}
        </div>
      </div>
    </FACard>
  );
}
