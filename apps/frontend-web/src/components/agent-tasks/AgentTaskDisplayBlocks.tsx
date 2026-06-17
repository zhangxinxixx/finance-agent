import type { ReactNode } from "react";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { ArtifactRef } from "@/types/artifact";
import type { TaskRunViewModel } from "@/types/agent-task";

export function RefList({
  title,
  icon,
  items,
  emptyText,
}: {
  title: string;
  icon: ReactNode;
  items: ArtifactRef[] | TaskRunViewModel["source_refs"];
  emptyText: string;
}) {
  return (
    <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
      <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold text-[var(--fg-2)]">
        {icon}
        <span>{title}</span>
      </div>
      {items.length > 0 ? (
        <div className="max-h-[300px] space-y-2 overflow-y-auto pr-1">
          {items.map((item, index) => {
            const label = "source_ref" in item ? item.label || item.source_ref : item.artifact_type || "artifact";
            const detail = "source_ref" in item
              ? item.artifact_path || item.endpoint || item.source_url || "-"
              : item.file_path || item.path || "-";
            return (
              <div key={`${label}-${index}`} className="rounded-[10px] bg-[var(--bg-panel)] px-3 py-2">
                <div className="text-[11px] font-semibold text-[var(--fg-2)]">{label}</div>
                <div className="mt-1 break-all font-mono text-[10px] text-[var(--fg-4)]">{detail}</div>
              </div>
            );
          })}
        </div>
      ) : (
        <FAEmptyState title="暂无引用" description={emptyText} className="p-4" />
      )}
    </div>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? null, null, 2);
  return (
    <pre className="max-h-[300px] overflow-y-auto overflow-x-auto rounded-[10px] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3 text-[10px] leading-relaxed text-[var(--fg-3)]">
      {text}
    </pre>
  );
}
