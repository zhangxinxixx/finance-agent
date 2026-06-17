import type { ReactNode } from "react";

export type FARuntimeLogLevel = "debug" | "info" | "warn" | "error" | "success";

export interface FARuntimeLogEntry {
  id: string;
  time?: ReactNode;
  level?: FARuntimeLogLevel;
  source?: ReactNode;
  message: ReactNode;
}

interface FARuntimeLogProps {
  entries: FARuntimeLogEntry[];
  emptyText?: ReactNode;
  className?: string;
}

const levelClass: Record<FARuntimeLogLevel, string> = {
  debug: "text-[var(--fg-5)]",
  info: "text-[var(--info)]",
  warn: "text-[var(--warn)]",
  error: "text-[var(--down)]",
  success: "text-[var(--up)]",
};

export function FARuntimeLog({ entries, emptyText = "暂无运行日志", className = "" }: FARuntimeLogProps) {
  return (
    <div
      className={`rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-terminal)] p-2 font-mono text-[10px] leading-relaxed shadow-[inset_0_1px_0_var(--border-faint)] ${className}`}
    >
      {entries.length === 0 ? (
        <div className="px-2 py-3 text-[var(--fg-5)]">{emptyText}</div>
      ) : (
        <div className="space-y-1">
          {entries.map((entry) => {
            const level = entry.level ?? "info";
            return (
              <div key={entry.id} className="grid grid-cols-[72px_54px_minmax(0,1fr)] gap-2 rounded-[var(--radius-sm)] px-2 py-1 hover:bg-[var(--bg-hover)]">
                <span className="text-[var(--fg-5)]">{entry.time ?? "--:--:--"}</span>
                <span className={`font-semibold uppercase ${levelClass[level]}`}>{level}</span>
                <span className="min-w-0 truncate text-[var(--fg-3)]">
                  {entry.source ? <span className="mr-2 text-[var(--fg-5)]">[{entry.source}]</span> : null}
                  {entry.message}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
