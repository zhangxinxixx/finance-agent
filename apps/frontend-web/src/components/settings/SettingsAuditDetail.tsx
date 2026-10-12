import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { formatDateTime } from "@/lib/date";
import type { SettingsHistoryEntry } from "@/adapters/settings";
import { prettyJson, toneForAuditAction } from "./settingsAuditFormat";
import { settingsActionLabel, settingsActorLabel, settingsKeyLabel, settingsScopeLabel, settingsSourceLabel } from "./settingsFormat";

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
      <div className="mb-1 text-[9px] font-semibold tracking-[0.1em] text-[var(--fg-5)]">{title}</div>
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
    <FACard title="事件详情" eyebrow="已选记录" accent="info" bodyClassName="space-y-3">
      {entry ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-0.5 text-[10px] text-[var(--fg-4)]">
              {settingsScopeLabel(entry.scope)}
            </span>
            {entry.sourceKey ? (
              <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-0.5 text-[10px] text-[var(--fg-4)]">
                {settingsSourceLabel(entry.sourceKey)}
              </span>
            ) : null}
            <FAStatusPill tone={toneForAuditAction(entry.action)}>{settingsActionLabel(entry.action)}</FAStatusPill>
          </div>

          <div className="space-y-2 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
            <DetailRow label="配置项" value={settingsKeyLabel(entry.settingKey)} />
            <DetailRow label="操作者" value={settingsActorLabel(entry.actor)} />
            <DetailRow label="发生时间" value={formatDateTime(entry.createdAt)} mono />
            <details className="border-t border-[var(--border-faint)] pt-2 text-[10px] text-[var(--fg-5)]">
              <summary className="cursor-pointer">查看技术追踪标识</summary>
              <div className="mt-2"><EvidenceRecordActions label="脱敏审计标识" record={{ request_id: entry.requestId, audit_id: entry.auditId, setting_key: entry.settingKey, scope: entry.scope, source_key: entry.sourceKey }} /></div>
            </details>
          </div>

          {entry.scope === "secret" ? (
            <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">密钥事件只保留状态和脱敏追踪标识，密钥值不在审计详情中展示。</div>
          ) : (
            <div className="grid gap-3">
              <ValueBlock title="变更前配置结构" value={prettyJson(entry.oldValueJson)} />
              <ValueBlock title="变更后配置结构" value={prettyJson(entry.newValueJson)} />
            </div>
          )}

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
                {entry.scope === "secret" ? "密钥事件不支持回滚" : "回滚事件不再提供再次回滚"}
              </div>
            )}
          </div>
        </>
      ) : (
        <FAEmptyState title="请选择一条事件" description="从左侧列表选择一条设置变更记录查看详情。" className="p-6" />
      )}
    </FACard>
  );
}

export const SettingsAuditDetail = SettingsAuditEventDetail;
