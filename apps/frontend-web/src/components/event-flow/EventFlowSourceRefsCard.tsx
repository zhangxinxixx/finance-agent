import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { compactSourceLabel, dedupeSourceRefs, sourceRefPairs } from "@/lib/sourceRefs";
import type { SourceRef } from "@/types/common";

interface EventFlowSourceRefsCardProps {
  eventRefs: SourceRef[];
  briefRefs: SourceRef[];
  pageRefs: SourceRef[];
}

interface SourceRefGroup {
  label: string;
  emptyText: string;
  refs: SourceRef[];
}

function sourceRefKey(ref: SourceRef): string {
  return [
    ref.source_ref,
    ref.endpoint ?? "",
    ref.artifact_path ?? "",
    ref.snapshot_id ?? "",
    ref.trade_date ?? "",
    ref.run_id ?? "",
  ].join("|");
}

function SourceRefGroupSection({ group }: { group: SourceRefGroup }) {
  if (group.refs.length === 0) {
    return (
      <section className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
        <div className="text-[11px] font-semibold text-[var(--fg-2)]">{group.label}</div>
        <div className="mt-2 text-[11px] leading-5 text-[var(--fg-4)]">{group.emptyText}</div>
      </section>
    );
  }

  return (
    <section className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] font-semibold text-[var(--fg-2)]">{group.label}</div>
        <div className="flex flex-wrap justify-end gap-1.5">
          {group.refs.slice(0, 3).map((ref) => (
            <FASourceTraceBadge key={sourceRefKey(ref)} source={compactSourceLabel(ref)} status={ref.status ?? "ok"} />
          ))}
        </div>
      </div>
      <div className="mt-2 space-y-2">
        {group.refs.map((ref) => (
          <div key={sourceRefKey(ref)} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2">
            <div className="text-[11px] font-semibold text-[var(--fg-2)]">{compactSourceLabel(ref)}</div>
            <div className="mt-2 grid gap-1 text-[10px] text-[var(--fg-4)] sm:grid-cols-2">
              {sourceRefPairs(ref).slice(0, 6).map((pair) => (
                <div key={`${sourceRefKey(ref)}-${pair.label}`} className="min-w-0">
                  <span className="text-[var(--fg-5)]">{pair.label}</span>
                  <div className="break-all font-mono text-[var(--fg-3)]">{pair.value}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function EventFlowSourceRefsCard({ eventRefs, briefRefs, pageRefs }: EventFlowSourceRefsCardProps) {
  const groups: SourceRefGroup[] = [
    { label: "事件来源", emptyText: "当前事件未返回独立来源。", refs: dedupeSourceRefs(eventRefs) },
    { label: "快讯来源", emptyText: "当前关联快讯未返回来源。", refs: dedupeSourceRefs(briefRefs) },
    { label: "页面来源", emptyText: "当前页面未返回汇总来源。", refs: dedupeSourceRefs(pageRefs) },
  ];
  const totalRefs = groups.reduce((sum, group) => sum + group.refs.length, 0);

  if (totalRefs === 0) {
    return (
      <FACard title="来源与工件" eyebrow="Source Trace" accent="info">
        <FAEmptyState title="暂无来源引用" description="后端尚未给当前事件返回 source_refs。" className="py-5" />
      </FACard>
    );
  }

  return (
    <FACard title="来源与工件" eyebrow="Source Trace" accent="info" bodyClassName="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        {groups.map((group) => (
          <div key={group.label} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
            <div className="text-[10px] font-semibold text-[var(--fg-4)]">{group.label}</div>
            <div className="mt-1 font-mono text-[13px] font-semibold text-[var(--fg-1)]">{group.refs.length}</div>
          </div>
        ))}
      </div>
      <div className="space-y-2">
        {groups.map((group) => (
          <SourceRefGroupSection key={group.label} group={group} />
        ))}
      </div>
    </FACard>
  );
}
