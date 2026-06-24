import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { compactSourceLabel, dedupeSourceRefs, sourceRefPairs } from "@/lib/sourceRefs";
import type { SourceRef } from "@/types/common";
import { formatEventFlowArtifactLabel, formatEventFlowSourceLabel } from "./eventFlowFormat";

interface EventFlowSourceRefsCardProps {
  eventRefs: SourceRef[];
  briefRefs: SourceRef[];
  pageRefs: SourceRef[];
  embedded?: boolean;
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

function translateSourceRefLabel(label: string): string {
  const map: Record<string, string> = {
    source_ref: "来源标识",
    endpoint: "接口",
    artifact: "工件",
    snapshot_id: "快照 ID",
    trade_date: "交易日",
    dataDate: "数据日",
    asOf: "截止时间",
    run_id: "运行 ID",
    generated_at: "生成时间",
    source_url: "来源链接",
  };
  return map[label] ?? label;
}

function isPathPair(label: string): boolean {
  return label === "artifact_path" || label === "raw_path" || label === "parsed_path" || label === "path";
}

function formatSourceRefPairValue(label: string, value: string): string {
  if (isPathPair(label)) return formatEventFlowArtifactLabel(value);
  return value;
}

function SourceRefGroupSection({ group }: { group: SourceRefGroup }) {
  if (group.refs.length === 0) {
    return (
      <section className="py-2 first:pt-0 last:pb-0">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-semibold text-[var(--fg-2)]">{group.label}</div>
          <div className="text-[10px] text-[var(--fg-5)]">0 条</div>
        </div>
        <div className="mt-1 text-[11px] leading-5 text-[var(--fg-4)]">{group.emptyText}</div>
      </section>
    );
  }

  return (
    <section className="border-t border-[var(--border-faint)] py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold text-[var(--fg-2)]">{group.label}</div>
        <div className="text-[10px] text-[var(--fg-5)]">{group.refs.length} 条</div>
      </div>
      <div className="mt-2 grid gap-2">
        {group.refs.map((ref) => (
          <div
            key={sourceRefKey(ref)}
            className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <FASourceTraceBadge source={formatEventFlowSourceLabel(compactSourceLabel(ref), 20).text} status={ref.status ?? "ok"} />
              <span className="text-[10px] text-[var(--fg-5)]">
                {formatEventFlowSourceLabel(ref.provider ?? ref.source_ref ?? "来源", 18).text}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
              {sourceRefPairs(ref).filter((pair) => pair.label !== "source_ref").slice(0, 5).map((pair) => {
                const displayValue = formatSourceRefPairValue(pair.label, pair.value);
                return (
                <span
                  key={`${sourceRefKey(ref)}-${pair.label}`}
                  className="inline-flex max-w-full items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5 text-[var(--fg-4)]"
                  title={`${translateSourceRefLabel(pair.label)}: ${displayValue}`}
                >
                  <span className="text-[var(--fg-5)]">{translateSourceRefLabel(pair.label)}</span>
                  <span className="truncate max-w-[180px] font-mono text-[var(--fg-3)]">{displayValue}</span>
                </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function EventFlowSourceRefsCard({ eventRefs, briefRefs, pageRefs, embedded = false }: EventFlowSourceRefsCardProps) {
  const groups: SourceRefGroup[] = [
    { label: "事件来源", emptyText: "当前事件未返回独立来源。", refs: dedupeSourceRefs(eventRefs) },
    { label: "快讯来源", emptyText: "当前关联快讯未返回来源。", refs: dedupeSourceRefs(briefRefs) },
    { label: "页面来源", emptyText: "当前页面未返回汇总来源。", refs: dedupeSourceRefs(pageRefs) },
  ];
  const totalRefs = groups.reduce((sum, group) => sum + group.refs.length, 0);

  if (totalRefs === 0) {
    if (embedded) {
      return <FAEmptyState title="暂无来源引用" description="后端尚未给当前页面返回 source_refs。" className="py-5" />;
    }
    return (
      <FACard title="来源与工件" eyebrow="数据溯源" accent="info">
        <FAEmptyState title="暂无来源引用" description="后端尚未给当前事件返回 source_refs。" className="py-5" />
      </FACard>
    );
  }

  const content = (
    <>
      <div className="flex flex-wrap items-center gap-3 text-[10px] text-[var(--fg-4)]">
        <span>总计 {totalRefs} 条</span>
        <span>事件 {groups[0].refs.length} 条</span>
        <span>快讯 {groups[1].refs.length} 条</span>
        <span>页面 {groups[2].refs.length} 条</span>
      </div>
      <div>
        {groups.map((group) => (
          <SourceRefGroupSection key={group.label} group={group} />
        ))}
      </div>
    </>
  );

  if (embedded) {
    return <div className="space-y-3">{content}</div>;
  }

  return (
    <FACard title="来源与工件" eyebrow="数据溯源" accent="info" bodyClassName="space-y-3">
      {content}
    </FACard>
  );
}
