import { FileText } from "lucide-react";
import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { SettingsHistoryEntry } from "@/adapters/settings";
import { formatSettingsTime } from "./settingsFormat";

interface SettingsHistoryCardProps {
  entries: SettingsHistoryEntry[];
  isLoading: boolean;
  error: string | null;
  rollingBackAuditId: string | null;
  onRollback: (entry: SettingsHistoryEntry) => void;
}

export function SettingsHistoryCard({
  entries,
  isLoading,
  error,
  rollingBackAuditId,
  onRollback,
}: SettingsHistoryCardProps) {
  return (
    <FACard
      title="最近变更"
      eyebrow="Audit History"
      accent="warn"
      action={
        <Link
          to="/settings/audit"
          className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
        >
          <FileText size={12} />
          审计页
        </Link>
      }
    >
      {error ? <div className="text-[11px] text-[var(--down)]">{error}</div> : null}
      {!error && isLoading ? <div className="text-[11px] text-[var(--fg-4)]">加载中...</div> : null}
      {!error && !isLoading ? (
        <div className="space-y-2">
          {entries.length === 0 ? <div className="text-[11px] text-[var(--fg-4)]">暂无配置变更记录</div> : null}
          {entries.map((entry, index) => (
            <div
              key={`${entry.auditId ?? entry.settingKey}-${index}`}
              className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{entry.settingKey}</span>
                <FAStatusPill tone={entry.action === "reset" ? "warn" : "info"}>{entry.action}</FAStatusPill>
              </div>
              <div className="mt-1 text-[10px] text-[var(--fg-4)]">{entry.reason ?? entry.auditId ?? "未提供备注"}</div>
              <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-[var(--fg-5)]">
                <span>{entry.actor ?? "system"}</span>
                <div className="flex items-center gap-2">
                  {entry.scope !== "secret" && entry.action !== "rollback" && entry.auditId ? (
                    <button
                      type="button"
                      disabled={rollingBackAuditId === entry.auditId}
                      onClick={() => onRollback(entry)}
                      className="rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-2.5 py-0.5 text-[10px] font-semibold text-[var(--fg-2)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {rollingBackAuditId === entry.auditId ? "回滚中..." : "回滚"}
                    </button>
                  ) : null}
                  <span className="fa-num">{formatSettingsTime(entry.createdAt)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </FACard>
  );
}
