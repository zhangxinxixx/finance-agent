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
            {item.trade_date ?? "-"}
            {item.snapshot_id ? ` · 快照 ${shortId(item.snapshot_id ?? undefined)}` : ""}
          </div>
        </div>
        <FAStatusPill tone={statusTone(item.data_status)}>{getDataStatusLabel(item.data_status)}</FAStatusPill>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-[var(--fg-4)]">
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
          来源 {item.source_refs.length}
        </span>
        <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
          产物 {item.artifact_refs.length}
        </span>
        {item.run_id ? (
          <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1">
            运行 {shortId(item.run_id ?? undefined)}
          </span>
        ) : null}
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

      <ReportTraceDrilldown sourceRefs={item.source_refs} artifactRefs={item.artifact_refs} showPayload={false} />
    </div>
  );
}
