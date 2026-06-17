import { FACard } from "@/components/shared/FACard";
import type { StrategyViewModel } from "@/types/strategy";
import { ArtifactRefList, SourceRefList } from "./StrategySourceRefs";

export function StrategyDataTraceSection({ data }: { data: StrategyViewModel }) {
  return (
    <FACard title="数据溯源" eyebrow="Trace" bodyClassName="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">来源引用</div>
          <SourceRefList refs={data.source_refs} />
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">产物引用</div>
          <ArtifactRefList refs={data.artifact_refs} />
        </div>
      </div>
    </FACard>
  );
}
