import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import type { SettingsHistoryEntry } from "@/adapters/settings";
import { toneForAuditAction } from "./settingsAuditFormat";

function AuditItem({
  entry,
  active,
  onSelect,
}: {
  entry: SettingsHistoryEntry;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        "w-full rounded-[var(--radius-md)] border px-3 py-2 text-left transition-colors",
        active
          ? "border-[var(--brand)] bg-[var(--bg-active)]"
          : "border-[var(--border)] bg-[var(--bg-card-inner)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{entry.settingKey}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-[var(--fg-5)]">
            <span>{entry.actor ?? "system"}</span>
            <span>·</span>
            <span className="fa-num">{formatDateTime(entry.createdAt)}</span>
          </div>
        </div>
        <FAStatusPill tone={toneForAuditAction(entry.action)}>{entry.action}</FAStatusPill>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-4)]">
        <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-0.5">{entry.scope}</span>
        {entry.sourceKey ? (
          <span
            title={entry.sourceKey}
            className="inline-block max-w-[180px] truncate rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-0.5"
          >
            {entry.sourceKey}
          </span>
        ) : null}
      </div>
      <div className="mt-2 line-clamp-2 text-[10px] leading-5 text-[var(--fg-4)]">{entry.reason ?? entry.auditId ?? "未提供备注"}</div>
    </button>
  );
}

export function SettingsAuditEventList({
  entries,
  selectedAuditId,
  onSelect,
}: {
  entries: SettingsHistoryEntry[];
  selectedAuditId: string | null;
  onSelect: (auditId: string | null) => void;
}) {
  return (
    <FACard title="事件列表" eyebrow="Filtered Events" accent="warn" bodyClassName="space-y-2">
      {entries.length === 0 ? (
        <FAEmptyState title="没有匹配的审计事件" description="调整过滤条件后再试，或者清空筛选查看完整历史。" className="p-6" />
      ) : (
        <div className="max-h-[calc(100vh-280px)] space-y-2 overflow-y-auto pr-1">
          {entries.map((entry) => (
            <AuditItem
              key={entry.auditId ?? `${entry.settingKey}-${entry.createdAt}`}
              entry={entry}
              active={selectedAuditId === entry.auditId}
              onSelect={() => onSelect(entry.auditId)}
            />
          ))}
        </div>
      )}
    </FACard>
  );
}
