import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { DataSourceCard } from "./DataSourceCard";

interface DataSourceGridProps {
  sources: DataSourceStatusViewModel[];
}

export function DataSourceGrid({ sources }: DataSourceGridProps) {
  return (
    <section className="space-y-3">
      <FASectionHeader
        title="数据源网格"
        eyebrow="数据源注册表"
        description="只读展示当前接入状态、回退关系、最近同步时间和页面级溯源，不触发真实同步任务。"
        action={<FAStatusPill tone="dim">{`${sources.length} sources`}</FAStatusPill>}
      />

      <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
        {sources.map((source) => (
          <DataSourceCard key={source.id} source={source} />
        ))}
      </div>
    </section>
  );
}
