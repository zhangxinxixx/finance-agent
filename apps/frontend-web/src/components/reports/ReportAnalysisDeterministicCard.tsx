import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getDataStatusLabel } from "@/lib/status";
import type { ReportAnalysisInputItemView } from "@/types/reports";
import { ReportTraceDrilldown } from "./ReportTraceDrilldown";
import { shortId, statusTone } from "./reportDetailMeta";

export function ReportAnalysisDeterministicCard({ item }: { item: ReportAnalysisInputItemView }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[13px] font-semibold text-[var(--fg-1)]">{item.title}</div>
          <div className="mt-1 text-[11px] text-[var(--fg-4)]">
            {item.snapshot_type ?? item.input_type} · {item.snapshot_id ?? "无 snapshot_id"}
          </div>
        </div>
        <FAStatusPill tone={statusTone(item.data_status)}>{getDataStatusLabel(item.data_status)}</FAStatusPill>
      </div>

      <div className="mt-3 grid gap-2 text-[11px] text-[var(--fg-4)] sm:grid-cols-2 xl:grid-cols-4">
        <div>run：{shortId(item.run_id ?? undefined)}</div>
        <div>date：{item.trade_date ?? "-"}</div>
        <div>sources：{item.source_refs.length}</div>
        <div>artifacts：{item.artifact_refs.length}</div>
      </div>

      {item.sections.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.sections.map((section) => (
            <span
              key={section}
              className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-terminal)] px-2 py-1 text-[11px] text-[var(--fg-3)]"
            >
              {section}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-3 grid gap-2 text-[11px] text-[var(--fg-4)] sm:grid-cols-2">
        <div>snapshot：{shortId(item.snapshot_id ?? undefined)}</div>
        <div>created_at：{item.created_at ?? "-"}</div>
      </div>

      {item.input_snapshot_ids.length > 0 ? (
        <div className="mt-3 space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">上游输入快照</div>
          <div className="flex flex-wrap gap-2">
            {item.input_snapshot_ids.map((snapshotId) => (
              <span
                key={snapshotId}
                className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-terminal)] px-2 py-1 font-mono text-[10px] text-[var(--fg-3)]"
              >
                {snapshotId}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <ReportTraceDrilldown sourceRefs={item.source_refs} artifactRefs={item.artifact_refs} payload={item.payload} defaultOpen />
    </div>
  );
}
