import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";
import { traceStatusTone } from "./strategyFormat";

const MAX_GROUPED_SOURCE_REFS = 8;

export function SourceRefList({ refs }: { refs: SourceRef[] }) {
  if (!refs.length) return null;

  const grouped = new Map<string, SourceRef[]>();
  for (const ref of refs) {
    const raw = ref as unknown as Record<string, unknown>;
    const key = (raw.source as string) ?? ref.source_ref ?? ref.endpoint ?? "unknown";
    const arr = grouped.get(key) ?? [];
    arr.push(ref);
    grouped.set(key, arr);
  }

  if (grouped.size <= 2 || refs.length <= 6) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {refs.map((ref, idx) => (
          <FASourceTraceBadge
            key={`${ref.source_ref}-${idx}`}
            source={ref.label ?? ref.source_ref}
            status={ref.status ?? "trace"}
            tone={traceStatusTone(typeof ref.status === "string" ? ref.status : null)}
            snapshotId={ref.snapshot_id}
          />
        ))}
      </div>
    );
  }

  const groupedItems = Array.from(grouped.entries()).sort(([, left], [, right]) => right.length - left.length);
  const visibleGroups = groupedItems.slice(0, MAX_GROUPED_SOURCE_REFS);
  const hiddenGroups = groupedItems.slice(MAX_GROUPED_SOURCE_REFS);
  const hiddenRefCount = hiddenGroups.reduce((total, [, items]) => total + items.length, 0);

  return (
    <div className="flex flex-wrap gap-1.5">
      {visibleGroups.map(([source, items]) => (
        <div
          key={source}
          className="inline-flex items-center gap-1 rounded-[3px] border px-1.5 py-0.5"
          style={{
            background: "var(--bg-card-inner)",
            borderColor: "var(--border-faint)",
          }}
        >
          <span className="text-[9px] font-medium text-[var(--fg-3)]">{source}</span>
          <span className="text-[8px] text-[var(--fg-5)]">x{items.length}</span>
        </div>
      ))}
      {hiddenGroups.length > 0 ? (
        <div
          className="inline-flex items-center gap-1 rounded-[3px] border px-1.5 py-0.5"
          style={{
            background: "var(--bg-panel)",
            borderColor: "var(--border-faint)",
          }}
        >
          <span className="text-[9px] font-medium text-[var(--fg-4)]">另 {hiddenGroups.length} 组</span>
          <span className="text-[8px] text-[var(--fg-5)]">x{hiddenRefCount}</span>
        </div>
      ) : null}
    </div>
  );
}

export function ArtifactRefList({ refs }: { refs: ArtifactRef[] }) {
  if (!refs.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {refs.map((ref, idx) => (
        <FASourceTraceBadge
          key={`${ref.artifact_type}-${idx}`}
          source={ref.title ?? ref.artifact_type ?? "artifact"}
          status={ref.status ?? ref.availability ?? "trace"}
          tone={traceStatusTone(
            typeof ref.status === "string"
              ? ref.status
              : typeof ref.availability === "string"
                ? ref.availability.toLowerCase()
                : null,
          )}
        />
      ))}
    </div>
  );
}
