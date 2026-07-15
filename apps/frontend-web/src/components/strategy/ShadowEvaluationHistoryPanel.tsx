import { Database, History, ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type {
  ShadowEvaluationHistoryItem,
  ShadowEvaluationHistoryResponse,
  ShadowEvaluationLifecycleStatus,
  ShadowEvaluationOutcomeSummary,
} from "@/types/shadow-evaluation-history";

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
  if (item.unscorable_count > 0 || item.legacy_unverified_count > 0 || !item.publish_allowed) return "warn";
  if (item.accuracy !== null) return "up";
  return "dim";
}

function statusLabel(item: ShadowEvaluationHistoryItem) {
  if (item.blocked_count > 0) return "Blocked";
  if (item.unscorable_count > 0) return "Unscorable";
  if (item.legacy_unverified_count > 0) return "历史待核验";
  return item.strategy_status;
}

const lifecycleLabels: Record<ShadowEvaluationLifecycleStatus, string> = {
  never_triggered: "未触发",
  invalidated_before_entry: "入场前失效",
  triggered: "已触发",
  triggered_then_invalidated: "触发后止损",
  target_reached: "目标命中",
  same_bar_ambiguous: "同 K 线歧义",
  insufficient_market_path: "路径不足",
  insufficient_strategy_contract: "策略契约不足",
  blocked: "质量阻断",
};

function outcomeTone(outcome: ShadowEvaluationOutcomeSummary): FAStatusTone {
  if (outcome.verification_status === "legacy_unverified") return "warn";
  if (outcome.status === "blocked") return "down";
  if (outcome.status === "unscorable") return "warn";
  if (outcome.classification === "correct" || outcome.lifecycle_status === "target_reached") return "up";
  return "info";
}

function formatNumber(value: number | null) {
  return value === null ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}

function OutcomeSummaryRow({ outcome }: { outcome: ShadowEvaluationOutcomeSummary }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="fa-num text-[length:var(--text-12)] text-[var(--fg-2)]">{outcome.horizon}</strong>
        <FAStatusPill tone={outcomeTone(outcome)}>{outcome.verification_status === "legacy_unverified" ? "历史待核验" : outcome.lifecycle_status ? lifecycleLabels[outcome.lifecycle_status] : outcome.classification}</FAStatusPill>
        {outcome.setup_id ? <code className="break-all text-[length:var(--text-11)] text-[var(--fg-4)]">{outcome.setup_id}</code> : null}
      </div>
      {outcome.verification_status === "legacy_unverified" ? <p className="mt-1 text-[length:var(--text-11)] text-[var(--warn)]">原始分类 {outcome.classification.toUpperCase()}；旧产物缺少生命周期、setup 与成交基准，仅保留审计，不计入 approved 或准确率。</p> : null}
      <div className="mt-2 grid gap-1 text-[length:var(--text-11)] text-[var(--fg-4)] sm:grid-cols-2 lg:grid-cols-4">
        <span>Fill <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.fill_price)}</b></span>
        <span>Exit <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.exit_price)}</b></span>
        <span>MFE <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.mfe)}</b></span>
        <span>MAE <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.mae)}</b></span>
      </div>
      {(outcome.fill_time || outcome.exit_time) ? (
        <p className="mt-1 break-all text-[length:var(--text-11)] text-[var(--fg-4)]">{outcome.fill_time ?? "—"} → {outcome.exit_time ?? "—"}</p>
      ) : null}
    </div>
  );
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
          {item.as_of ? <span className="mt-1 block text-[length:var(--text-11)] text-[var(--fg-4)]">快照 {new Date(item.as_of).toLocaleString("zh-CN", { hour12: false })}</span> : null}
        </div>
        <div className="text-right">
          <span className="block text-[length:var(--text-11)] text-[var(--fg-4)]">准确率</span>
          <strong className={`text-[length:var(--text-13)] ${item.accuracy === null ? "text-[var(--warn)]" : "fa-num text-[var(--fg-1)]"}`}>{formatAccuracy(item.accuracy)}</strong>
        </div>
      </div>
      <div className="mt-3 grid gap-2 text-[length:var(--text-11)] text-[var(--fg-4)] sm:grid-cols-5">
        <span>Outcome <b className="fa-num text-[var(--fg-2)]">{item.outcome_count}</b></span>
        <span>Approved <b className="fa-num text-[var(--fg-2)]">{item.approved_count}</b></span>
        <span>Blocked <b className="fa-num text-[var(--down)]">{item.blocked_count}</b></span>
        <span>Unscorable <b className="fa-num text-[var(--warn)]">{item.unscorable_count}</b></span>
        <span>Legacy <b className="fa-num text-[var(--warn)]">{item.legacy_unverified_count}</b></span>
      </div>
      {item.outcomes.length > 0 ? (
        <details className="mt-2 border-t border-[var(--border-faint)] pt-2">
          <summary className="cursor-pointer list-none text-[length:var(--text-11)] font-semibold text-[var(--fg-3)]">生命周期与成交基准 · <span className="fa-num">{item.outcomes.length}</span></summary>
          <div className="mt-2 grid gap-2 lg:grid-cols-2">
            {item.outcomes.map((outcome) => <OutcomeSummaryRow key={outcome.horizon} outcome={outcome} />)}
          </div>
        </details>
      ) : (
        <p className="mt-2 border-t border-[var(--border-faint)] pt-2 text-[length:var(--text-11)] text-[var(--fg-4)]">当前 API 未提供 outcome 明细；页面不会读取本地 artifact path 补算。</p>
      )}
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
