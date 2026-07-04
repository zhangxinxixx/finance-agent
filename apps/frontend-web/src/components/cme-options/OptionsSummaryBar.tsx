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

function statusLabel(status: CMEOptionsDataSource["status"] | null | undefined) {
  if (status === "FINAL") return "终版";
  if (status === "PRELIM") return "预览";
  return "—";
}

export function OptionsSummaryBar({ dataSource }: OptionsSummaryBarProps) {
  const versionLabel = statusLabel(dataSource.status);
  const productLabel = "黄金期权";
  const rowCountLabel = formatRowCount(dataSource.row_count);
  const expiries = formatExpiries(dataSource.expiries);

  return (
    <FACard
      title="结构摘要"
      eyebrow="快照概况"
      accent="info"
      action={<FAStatusPill tone={statusTone(dataSource.status)}>{versionLabel}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      {dataSource.status === "PRELIM" ? (
        <FAWarningBanner title="当前为预览数据" description="终版结果生成后应优先覆盖当前快照。" tone="warn" />
      ) : null}

      <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <FAMetricCard label="产品" value={productLabel} hint="解析产品代码" />
        <FAMetricCard label="版本" value={versionLabel} hint="报告版本语义" status={versionLabel} statusTone={statusTone(dataSource.status)} />
        <FAMetricCard label="行数" value={rowCountLabel} hint="规范化行数" />
        <FAMetricCard label="到期月" value={expiries.length > 0 ? expiries.length.toLocaleString("en-US") : "—"} hint="到期月数量" />
      </div>

      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-3">
        <div className="text-[length:var(--text-10)] font-semibold text-[var(--fg-5)]">覆盖到期月</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {expiries.length > 0 ? (
            expiries.map((expiry) => (
              <span
                key={expiry}
                className="inline-flex items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-panel)] px-2 py-1 text-[length:var(--text-10)] font-semibold text-[var(--fg-3)]"
              >
                {expiry}
              </span>
            ))
          ) : (
            <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">暂无到期月信息</span>
          )}
        </div>
      </div>
    </FACard>
  );
}
