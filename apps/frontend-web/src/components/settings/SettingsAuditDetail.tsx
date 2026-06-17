import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import type { SettingsHistoryEntry } from "@/adapters/settings";
import { prettyJson, toneForAuditAction } from "./settingsAuditFormat";

function DetailRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 text-[11px] text-[var(--fg-4)]">
      <span>{label}</span>
      <span className={`${mono ? "font-mono" : "font-semibold"} text-[var(--fg-2)]`}>{value}</span>
    </div>
  );
}

function ValueBlock({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-[var(--fg-5)]">{title}</div>
      <pre className="max-h-[280px] overflow-y-auto overflow-x-auto rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-panel)] p-3 font-mono text-[10px] leading-5 text-[var(--fg-3)]">
        {value}
      </pre>
    </div>
  );
}

export function SettingsAuditEventDetail({
  entry,
  rollingBackAuditId,
  onRollback,
}: {
  entry: SettingsHistoryEntry | null;
  rollingBackAuditId: string | null;
  onRollback: (entry: SettingsHistoryEntry) => void;
}) {
  return (
    <FACard title="事件详情" eyebrow="Selected Record" accent="info" bodyClassName="space-y-3">
      {entry ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-0.5 text-[10px] text-[var(--fg-4)]">
              {entry.scope}
            </span>
            {entry.sourceKey ? (
              <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-0.5 text-[10px] text-[var(--fg-4)]">
                {entry.sourceKey}
              </span>
            ) : null}
            <FAStatusPill tone={toneForAuditAction(entry.action)}>{entry.action}</FAStatusPill>
          </div>

          <div className="space-y-2 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
            <DetailRow label="setting_key" value={entry.settingKey} />
            <DetailRow label="actor" value={entry.actor ?? "system"} />
            <DetailRow label="request_id" value={entry.requestId ?? "—"} mono />
            <DetailRow label="audit_id" value={entry.auditId ?? "—"} mono />
            <DetailRow label="created_at" value={formatDateTime(entry.createdAt)} mono />
          </div>

          <div className="grid gap-3">
            <ValueBlock title="old_value_json" value={prettyJson(entry.oldValueJson)} />
            <ValueBlock title="new_value_json" value={prettyJson(entry.newValueJson)} />
          </div>

          <div className="flex items-center justify-between gap-3">
            <div className="text-[10px] text-[var(--fg-5)]">{entry.reason ?? "未提供备注"}</div>
            {entry.scope !== "secret" && entry.action !== "rollback" && entry.auditId ? (
              <button
                type="button"
                disabled={rollingBackAuditId === entry.auditId}
                onClick={() => onRollback(entry)}
                className="inline-flex h-8 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3.5 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {rollingBackAuditId === entry.auditId ? "回滚中..." : "回滚此事件"}
              </button>
            ) : (
              <div className="text-[10px] text-[var(--fg-5)]">
                {entry.scope === "secret" ? "secret 事件不支持回滚" : "回滚事件不再提供再次回滚"}
              </div>
            )}
          </div>
        </>
      ) : (
        <FAEmptyState title="请选择一条事件" description="从左侧列表选择一条 Settings 审计记录查看详情。" className="p-6" />
      )}
    </FACard>
  );
}

export const SettingsAuditDetail = SettingsAuditEventDetail;
