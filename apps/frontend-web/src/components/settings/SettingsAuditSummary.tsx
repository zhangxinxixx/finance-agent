import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";

function MetricCard({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">{label}</div>
      <div className={`mt-1 text-[20px] text-[var(--fg-2)] ${mono ? "fa-num" : "text-[11px]"}`}>{value}</div>
    </div>
  );
}

export function SettingsAuditSummary({
  entriesCount,
  rollbackableCount,
  selectedAuditId,
  scopeLabel,
}: {
  entriesCount: number;
  rollbackableCount: number;
  selectedAuditId: string | null;
  scopeLabel: string;
}) {
  return (
    <FACard
      title="Settings 审计页"
      eyebrow="Audit Center"
      accent="warn"
      action={
        <Link
          to="/settings"
          className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
        >
          <ArrowLeft size={12} />
          返回设置
        </Link>
      }
      bodyClassName="space-y-3"
    >
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-4">
        <MetricCard label="总事件数" value={String(entriesCount)} mono />
        <MetricCard label="可回滚" value={String(rollbackableCount)} mono />
        <MetricCard label="选中事件" value={selectedAuditId ?? "无"} />
        <MetricCard label="范围" value={scopeLabel} />
      </div>
    </FACard>
  );
}
