import { Database, History, ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type { ShadowEvaluationHistoryItem, ShadowEvaluationHistoryResponse } from "@/types/shadow-evaluation-history";

interface ShadowEvaluationHistoryPanelProps {
  data: ShadowEvaluationHistoryResponse | null;
  isLoading: boolean;
  isUnavailable: boolean;
  error: Error | null;
}
function formatAccuracy(value: number | null) {
  return value === null ? "暂无可评分样本" : value.toLocaleString("zh-CN", { style: "percent", maximumFractionDigits: 1 });
}

function statusTone(item: ShadowEvaluationHistoryItem): FAStatusTone {
  if (item.blocked_count > 0 || item.strategy_status.toUpperCase().includes("SUSPENDED")) return "down";
  if (item.unscorable_count > 0 || !item.publish_allowed) return "warn";
  if (item.accuracy !== null) return "up";
  return "dim";
}

function statusLabel(item: ShadowEvaluationHistoryItem) {
  if (item.blocked_count > 0) return "Blocked";
  if (item.unscorable_count > 0) return "Unscorable";
  return item.strategy_status;
}

function HistoryRow({ item }: { item: ShadowEvaluationHistoryItem }) {
  const tone = statusTone(item);
  return (
    <article className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="fa-num text-[length:var(--text-13)] text-[var(--fg-1)]">{item.trade_date}</strong>
            <FAStatusPill tone={tone}>{statusLabel(item)}</FAStatusPill>
            <FAStatusPill tone={item.publish_allowed ? "up" : "warn"}>{item.publish_allowed ? "可发布" : "未发布"}</FAStatusPill>
          </div>
          <code className="mt-1 block break-all text-[length:var(--text-11)] text-[var(--fg-4)]">{item.evaluation_id}</code>
        </div>
        <div className="text-right">
          <span className="block text-[length:var(--text-11)] text-[var(--fg-4)]">准确率</span>
          <strong className={`text-[length:var(--text-13)] ${item.accuracy === null ? "text-[var(--warn)]" : "fa-num text-[var(--fg-1)]"}`}>{formatAccuracy(item.accuracy)}</strong>
        </div>
      </div>
      <div className="mt-3 grid gap-2 text-[length:var(--text-11)] text-[var(--fg-4)] sm:grid-cols-4">
        <span>Outcome <b className="fa-num text-[var(--fg-2)]">{item.outcome_count}</b></span>
        <span>Approved <b className="fa-num text-[var(--fg-2)]">{item.approved_count}</b></span>
        <span>Blocked <b className="fa-num text-[var(--down)]">{item.blocked_count}</b></span>
        <span>Unscorable <b className="fa-num text-[var(--warn)]">{item.unscorable_count}</b></span>
      </div>
      <details className="mt-2 border-t border-[var(--border-faint)] pt-2">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-[length:var(--text-11)] text-[var(--fg-4)]">
          <Database className="h-3.5 w-3.5 text-[var(--info)]" aria-hidden="true" />
          产物引用 <span className="fa-num">{item.artifact_refs.length}</span>
        </summary>
        <div className="mt-1 space-y-1">
          {item.artifact_refs.map((ref) => <code key={ref} className="block break-all text-[length:var(--text-11)] text-[var(--fg-3)]">{ref}</code>)}
        </div>
      </details>
    </article>
  );
}

export function ShadowEvaluationHistoryPanel({ data, isLoading, isUnavailable, error }: ShadowEvaluationHistoryPanelProps) {
  if (isLoading && !data) {
    return <FACard title="影子评估历史" eyebrow="shadow_evaluation_history.v1" accent="brand"><div className="flex items-center gap-2 text-[length:var(--text-12)] text-[var(--fg-4)]" aria-live="polite"><History className="h-4 w-4 text-[var(--brand)]" aria-hidden="true" />正在读取不可变评估历史…</div></FACard>;
  }
  if (!data) {
    return <FAEmptyState title={error ? "影子评估历史读取失败" : isUnavailable ? "影子评估历史不可用" : "暂无影子评估历史"} description={error?.message ?? (isUnavailable ? "后端尚未提供 shadow evaluation history；页面不会补造历史记录。" : "当前没有可展示的评估分区。")} className="border-[var(--border-faint)] bg-[var(--bg-card)]" />;
  }
  if (data.items.length === 0) {
    return <FAEmptyState title="暂无影子评估历史" description="后端返回空历史结果；页面不会把空结果伪装成准确率或样本。" className="border-[var(--border-faint)] bg-[var(--bg-card)]" />;
  }
  const blockedCount = data.items.reduce((sum, item) => sum + item.blocked_count, 0);
  return (
    <FACard
      title="影子评估历史"
      eyebrow="shadow_evaluation_history.v1"
      accent={blockedCount > 0 ? "down" : "brand"}
      description="只读展示冻结评估分区；blocked / unscorable 保留原状态，不进入准确率分母。"
      action={<FAStatusPill tone={data.truncated ? "warn" : "info"}>{data.total} 条记录{data.truncated ? " · 已截断" : ""}</FAStatusPill>}
      bodyClassName="space-y-2"
    >
      {blockedCount > 0 ? <div className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--down-border)] bg-[var(--down-soft)] px-3 py-2 text-[length:var(--text-11)] text-[var(--down)]" role="note"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><span>历史中有 {blockedCount} 个 blocked outcome，系统保留阻断状态，不把它们计为错误。</span></div> : null}
      {data.items.map((item) => <HistoryRow key={`${item.trade_date}:${item.evaluation_id}`} item={item} />)}
    </FACard>
  );
}
