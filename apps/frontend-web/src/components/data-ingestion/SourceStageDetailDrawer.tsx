import type {
  DataSourceStatusViewModel,
  PipelineStageKey,
  PipelineStageStatus,
} from "@/types/data-ingestion";
import { StageNode } from "./StageNode";
import { X, RefreshCw, Upload, FileText, ExternalLink } from "lucide-react";

interface SourceStageDetailDrawerProps {
  source: DataSourceStatusViewModel | null;
  stageKey: PipelineStageKey | null;
  onClose: () => void;
  onRetry?: (sourceId: string) => void;
}

const STAGE_LABELS: Record<PipelineStageKey, string> = {
  connection: "连接",
  collect: "采集",
  rawLanding: "Raw 落地",
  parse: "解析",
  validate: "标准化/校验",
  snapshot: "快照/事实表",
  consumerReady: "下游可用",
};

const STATUS_EXPLANATIONS: Record<PipelineStageStatus, string> = {
  OK: "该阶段已完成，数据正常",
  READY: "快照/数据已就绪，下游模块可消费",
  WARN: "该阶段有警告，数据可能不完整",
  PARTIAL: "部分数据可用",
  ERROR: "该阶段执行失败",
  BLOCKED: "被上游阻塞，需要上游先修复",
  WAITING: "等待调度或上游完成",
  NO_DATA: "没有数据",
  NO_SNAPSHOT: "未生成快照",
  SKIPPED: "该阶段被跳过",
};

export function SourceStageDetailDrawer({ source, stageKey, onClose, onRetry }: SourceStageDetailDrawerProps) {
  if (!source || !stageKey) return null;

  const health = source.pipeline_health;
  const stage = health?.stages[stageKey];
  const status = stage?.status ?? "NO_DATA";
  const message = stage?.message;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40"
        style={{ background: "rgba(0,0,0,0.35)", backdropFilter: "blur(2px)" }}
        onClick={onClose}
      />

      {/* Drawer */}
      <div
        className="fixed top-0 right-0 bottom-0 z-50 flex max-h-[100dvh] min-h-0 flex-col overflow-hidden"
        style={{
          width: 360,
          height: "100dvh",
          maxHeight: "100dvh",
          background: "var(--bg-panel)",
          borderLeft: "1px solid var(--border)",
          boxShadow: "var(--shadow-popover)",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2">
            <StageNode status={status} />
            <div>
              <div className="text-[12px] font-bold text-[var(--fg-1)]">{STAGE_LABELS[stageKey]}</div>
              <div className="text-[9px] text-[var(--fg-5)]">{source.label}</div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-[var(--bg-hover)] transition-colors"
          >
            <X size={14} className="text-[var(--fg-5)]" />
          </button>
        </div>

        {/* Content */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {/* Status grid */}
          <div className="grid grid-cols-2 gap-2">
            <InfoCard label="阶段状态" value={status} color={statusColor(status)} />
            <InfoCard label="数据源" value={source.label} />
            <InfoCard label="类型" value={source.type} />
            <InfoCard label="角色" value={source.role} />
          </div>

          {/* Explanation */}
          <div className="rounded-[var(--radius-md)] bg-[var(--bg-card)] border border-[var(--border)] p-2.5">
            <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)] mb-1">状态说明</div>
            <div className="text-[10px] text-[var(--fg-3)] leading-relaxed">
              {STATUS_EXPLANATIONS[status]}
              {message && <div className="mt-1 text-[9px] text-[var(--fg-5)] font-mono">{message}</div>}
            </div>
          </div>

          {/* Stage chain (all stages for this source) */}
          {health && (
            <div className="rounded-[var(--radius-md)] bg-[var(--bg-card)] border border-[var(--border)] p-2.5">
              <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)] mb-2">完整链路状态</div>
              <div className="max-h-[220px] overflow-y-auto">
                <div className="flex flex-col gap-1.5">
                  {(Object.keys(health.stages) as PipelineStageKey[]).map((key) => {
                    const s = health.stages[key];
                    return (
                      <div key={key} className="flex items-center gap-2">
                        <StageNode status={s.status} compact />
                        <span className={`text-[9px] ${key === stageKey ? "font-bold text-[var(--fg-1)]" : "text-[var(--fg-4)]"}`}>
                          {STAGE_LABELS[key]}
                        </span>
                        {s.message && (
                          <span className="text-[8px] text-[var(--fg-6)] truncate flex-1">{s.message}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Metadata */}
          <div className="rounded-[var(--radius-md)] bg-[var(--bg-card)] border border-[var(--border)] p-2.5 space-y-1.5">
            <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)] mb-1">元数据</div>
            <MetaRow label="snapshot_id" value={source.snapshot_id ?? "—"} />
            <MetaRow label="last_run_id" value={source.last_run_id ?? "—"} />
            <MetaRow label="latest_raw" value={source.latest_raw_time ?? "—"} />
            <MetaRow label="latest_parsed" value={source.latest_parsed_time ?? "—"} />
            <MetaRow label="row_count" value={String(source.row_count)} />
            {health?.affectedModules && (
              <MetaRow label="影响模块" value={health.affectedModules.join(", ")} />
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 px-4 py-3 border-t border-[var(--border)] shrink-0">
          {onRetry && (
            <button
              onClick={() => onRetry(source.id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-sm)] text-[10px] font-semibold bg-[var(--brand-dim)] text-[var(--brand)] hover:bg-[var(--brand)] hover:text-white transition-colors"
            >
              <RefreshCw size={10} /> 手动重试
            </button>
          )}
          <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-sm)] text-[10px] font-semibold border border-[var(--border)] text-[var(--fg-4)] hover:bg-[var(--bg-hover)] transition-colors">
            <Upload size={10} /> 上传兜底
          </button>
          <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-sm)] text-[10px] font-semibold border border-[var(--border)] text-[var(--fg-4)] hover:bg-[var(--bg-hover)] transition-colors">
            <FileText size={10} /> 日志
          </button>
          <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-sm)] text-[10px] font-semibold border border-[var(--border)] text-[var(--fg-4)] hover:bg-[var(--bg-hover)] transition-colors ml-auto">
            <ExternalLink size={10} /> 影响链
          </button>
        </div>
      </div>
    </>
  );
}

/* ── helpers ────────────────────────────────────────── */

function InfoCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card)] border border-[var(--border-faint)] px-2 py-1.5">
      <div className="text-[7px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">{label}</div>
      <div className="text-[10px] font-semibold truncate" style={{ color: color ?? "var(--fg-2)" }}>{value}</div>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[8px] font-mono text-[var(--fg-6)] w-[90px] shrink-0">{label}</span>
      <span className="text-[9px] font-mono text-[var(--fg-4)] truncate flex-1">{value}</span>
    </div>
  );
}

function statusColor(status: PipelineStageStatus): string {
  switch (status) {
    case "OK":
    case "READY":
      return "var(--up)";
    case "WARN":
    case "PARTIAL":
      return "var(--warn)";
    case "ERROR":
    case "BLOCKED":
      return "var(--down)";
    default:
      return "var(--fg-5)";
  }
}
