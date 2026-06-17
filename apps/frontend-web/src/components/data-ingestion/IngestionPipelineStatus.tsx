import type { DataStatus } from "@/types/common";
import type { PipelineLayerStatus } from "@/types/data-ingestion";
import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FAPipelineStepper, type FAPipelineStageStatus } from "@/components/shared/FAPipelineStepper";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";

interface IngestionPipelineStatusProps {
  layers: PipelineLayerStatus[];
  updatedAt?: string | null;
}

const layerDescriptions: Record<PipelineLayerStatus["id"], string> = {
  configured: "数据源已配置",
  raw_ingested: "原始数据已接入",
  parsed: "结构化解析完成",
  analysis_ready: "可供分析层消费",
};

function toStageStatus(status: DataStatus): FAPipelineStageStatus {
  switch (status) {
    case "available":
      return "done";
    case "partial":
      return "running";
    case "error":
      return "error";
    case "unavailable":
    default:
      return "unavailable";
  }
}

function valueForLayer(layers: PipelineLayerStatus[], id: PipelineLayerStatus["id"]): number {
  return layers.find((layer) => layer.id === id)?.completed_count ?? 0;
}

export function IngestionPipelineStatus({ layers, updatedAt }: IngestionPipelineStatusProps) {
  const totalCount = layers[0]?.total_count ?? 0;
  const stages = layers.map((layer) => ({
    id: layer.id,
    label: layer.label,
    description: `${layerDescriptions[layer.id]} · ${layer.completed_count}/${layer.total_count}`,
    status: toStageStatus(layer.status),
  }));

  return (
    <FACard
      title="采集流水线"
      eyebrow="Pipeline Status"
      accent="brand"
      action={updatedAt ? <FASourceTraceBadge source={updatedAt} status="updated_at" tone="info" /> : null}
      bodyClassName="space-y-4"
    >
      <FAPipelineStepper stages={stages} />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <FAMetricCard label="source_count" value={totalCount.toLocaleString("en-US")} hint="当前纳管数据源" />
        <FAMetricCard label="raw_ingested" value={valueForLayer(layers, "raw_ingested").toLocaleString("en-US")} hint="原始层已接入" />
        <FAMetricCard label="parsed" value={valueForLayer(layers, "parsed").toLocaleString("en-US")} hint="结构化解析完成" />
        <FAMetricCard label="analysis_ready" value={valueForLayer(layers, "analysis_ready").toLocaleString("en-US")} hint="分析层可消费" />
      </div>
    </FACard>
  );
}
