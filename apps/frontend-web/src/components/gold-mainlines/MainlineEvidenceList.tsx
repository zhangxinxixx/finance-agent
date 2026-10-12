import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import {
  GOLD_MAINLINE_META,
  formatGoldSourceRefLabel,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview } from "@/types/gold-mainlines";
import {
  coverageStatusTone,
  formatEventCount,
  type MainlineCoverageRow,
} from "./goldMainlineCoverage";

interface MainlineEvidenceListProps {
  overview: GoldMacroOverview;
  rows: MainlineCoverageRow[];
}

function EventEvidenceLinks({ eventIds, offset = 0 }: { eventIds: string[]; offset?: number }) {
  const kinds: Record<string, string> = { fed_speech: "美联储讲话", oil_supply_shock: "原油供应事件", geopolitical_conflict: "地缘事件", macro_release: "宏观数据事件" };
  return <div className="grid gap-2">
    {eventIds.map((eventId, index) => <div key={eventId} className="min-w-0">
      <Link to={`/event-flow/${encodeURIComponent(eventId)}`} state={{ eventReturnTo: "/gold-mainlines" }} className="break-words text-[length:var(--type-body-sm)] text-[var(--brand-hover)] hover:underline">
        查看事件证据 · {kinds[eventId.split(":")[1]] ?? "标题未提供"} {offset + index + 1}
      </Link>
      <details className="text-[length:var(--type-caption)] text-[var(--fg-4)]">
        <summary className="cursor-pointer">事件记录</summary><EvidenceRecordActions record={{ event_id: eventId }} label="事件关联记录" />
      </details>
    </div>)}
  </div>;
}

export function MainlineEvidenceList({ overview, rows }: MainlineEvidenceListProps) {
  const eventRows = rows.filter((row) => row.eventIds.length > 0);
  const sourceRefs = overview.source_refs;

  return (
    <div className="grid content-start gap-3">
      <FACard title="事件归因索引" accent="none" className="shrink-0">
        <p className="mb-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">主线结果只返回事件标识，是否匹配当前事件库尚未核验。进入详情查看事实与已有分析；引用缺失时不会补造内容。</p>
        {eventRows.length ? (
          <div className="grid gap-2">
            {eventRows.map((row) => (
              <div key={row.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{GOLD_MAINLINE_META[row.id].label}</div>
                  <FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{formatEventCount(row.eventIds.length)}</FAStatusPill>
                </div>
                <div className="mt-1.5">
                  <EventEvidenceLinks eventIds={row.eventIds.slice(0, 3)} />
                  {row.eventIds.length > 3 ? <details className="mt-2">
                    <summary className="cursor-pointer text-[length:var(--type-body-sm)] text-[var(--brand-hover)]">查看其余 {row.eventIds.length - 3} 条事件证据</summary>
                    <div className="mt-2"><EventEvidenceLinks eventIds={row.eventIds.slice(3)} offset={3} /></div>
                  </details> : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前主线总览未返回事件归因索引。</div>
        )}
      </FACard>

      <ResearchDetails label="查看主线依据记录">{sourceRefs.length ? (
        <FACard title="证据来源" accent="none" className="shrink-0">
          <div className="flex flex-wrap gap-1.5">
            {sourceRefs.map((ref, index) => (
              <div key={`${ref.source_ref}-${ref.snapshot_id ?? index}`} className="min-w-0 max-w-full">
              <FASourceTraceBadge
                key={`${ref.source_ref}-${ref.snapshot_id ?? index}`}
                source={formatGoldSourceRefLabel(ref, `来源 ${index + 1}`)}
                status={ref.status ?? "trace"}
                snapshotId={ref.snapshot_id}
              />
              <details className="text-[length:var(--type-caption)] text-[var(--fg-4)]">
                <summary className="cursor-pointer">来源记录</summary>
                <EvidenceRecordActions record={ref} url={ref.source_url} />
              </details>
              </div>
            ))}
          </div>
        </FACard>
      ) : null}</ResearchDetails>
    </div>
  );
}
import { Link } from "react-router-dom";
