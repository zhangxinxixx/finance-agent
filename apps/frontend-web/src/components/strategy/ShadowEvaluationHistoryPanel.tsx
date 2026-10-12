import { Database, History, ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { readingErrorMessage } from "@/components/reading/readingFormat";
import type {
  ShadowEvaluationHistoryItem,
  ShadowEvaluationHistoryResponse,
  ShadowEvaluationOutcomeSummary,
} from "@/types/shadow-evaluation-history";
import {
  enumRawTitle,
  liveStrategyStatusLabel,
  shadowClassificationLabel,
  shadowLifecycleLabel,
  shadowOutcomeStatusLabel,
  shadowVerificationLabel,
} from "./strategyDisplayLabels";

interface ShadowEvaluationHistoryPanelProps {
  data: ShadowEvaluationHistoryResponse | null;
  isLoading: boolean;
  isUnavailable: boolean;
  error: Error | null;
}
function formatAccuracy(value: number | null) {
  return value === null ? "暂无可评分样本" : value.toLocaleString("zh-CN", { style: "percent", maximumFractionDigits: 1 });
}

function horizonLabel(value: string): string {
  if (value === "1h") return "1 小时";
  if (value === "4h") return "4 小时";
  if (value === "24h") return "24 小时";
  if (value === "session") return "交易时段";
  return `未知周期（${value}）`;
}

function statusTone(item: ShadowEvaluationHistoryItem): FAStatusTone {
  const strategyStatus = typeof item.strategy_status === "string" ? item.strategy_status.toUpperCase() : "";
  if (item.blocked_count > 0 || strategyStatus.includes("SUSPENDED")) return "down";
  if (item.unscorable_count > 0 || item.legacy_unverified_count > 0 || !item.publish_allowed) return "warn";
  if (item.accuracy !== null) return "up";
  return "dim";
}

function statusLabel(item: ShadowEvaluationHistoryItem) {
  if (item.blocked_count > 0) return shadowOutcomeStatusLabel("blocked");
  if (item.unscorable_count > 0) return shadowOutcomeStatusLabel("unscorable");
  if (item.legacy_unverified_count > 0) return shadowVerificationLabel("legacy_unverified");
  return liveStrategyStatusLabel(item.strategy_status);
}

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
  const verification = shadowVerificationLabel(outcome.verification_status);
  const lifecycle = outcome.lifecycle_status ? shadowLifecycleLabel(outcome.lifecycle_status) : null;
  const outcomeStatus = shadowOutcomeStatusLabel(outcome.status);
  const classification = shadowClassificationLabel(outcome.classification);
  const outcomeLabel = lifecycle ?? (outcome.status === "scored" ? classification : outcomeStatus);
  const rawTitle = [lifecycle, verification, outcomeStatus, classification]
    .map((value) => value ? enumRawTitle(value) : undefined)
    .filter((value): value is string => Boolean(value))
    .join(" · ") || undefined;
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="fa-num text-[length:var(--text-12)] text-[var(--fg-2)]" title={`原始周期：${outcome.horizon}`}>{horizonLabel(outcome.horizon)}</strong>
        <FAStatusPill tone={outcomeTone(outcome)} title={rawTitle}>{outcomeLabel.label}</FAStatusPill>
        {outcome.setup_id ? <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">已关联场景</span> : null}
      </div>
      {outcome.verification_status === "legacy_unverified" ? <p className="mt-1 text-[length:var(--text-11)] text-[var(--warn)]">原始分类为“{classification.label}”；旧产物缺少生命周期、场景与成交基准，仅保留审计，不计入已批准结果或准确率。</p> : null}
      <div className="mt-2 grid gap-1 text-[length:var(--text-11)] text-[var(--fg-4)] sm:grid-cols-2 lg:grid-cols-4">
        <span>成交价 <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.fill_price)}</b></span>
        <span>退出价 <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.exit_price)}</b></span>
        <span>最大有利变动（MFE） <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.mfe)}</b></span>
        <span>最大不利变动（MAE） <b className="fa-num text-[var(--fg-2)]">{formatNumber(outcome.mae)}</b></span>
      </div>
      {(outcome.fill_time || outcome.exit_time) ? (
        <p className="mt-1 break-all text-[length:var(--text-11)] text-[var(--fg-4)]">{outcome.fill_time ?? "—"} → {outcome.exit_time ?? "—"}</p>
      ) : null}
      {outcome.setup_id ? <div className="mt-2"><EvidenceRecordActions label="场景追踪记录" record={{ setup_id: outcome.setup_id, horizon: outcome.horizon }} /></div> : null}
    </div>
  );
}

function HistoryRow({ item }: { item: ShadowEvaluationHistoryItem }) {
  const tone = statusTone(item);
  const strategyStatus = liveStrategyStatusLabel(item.strategy_status);
  const rowStatus = statusLabel(item);
  return (
    <article className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="fa-num text-[length:var(--text-13)] text-[var(--fg-1)]">{item.trade_date}</strong>
            <FAStatusPill tone={tone} title={enumRawTitle(strategyStatus)}>{rowStatus.label}</FAStatusPill>
            <FAStatusPill tone={item.publish_allowed ? "up" : "warn"}>{item.publish_allowed ? "可发布" : "未发布"}</FAStatusPill>
          </div>
          <EvidenceRecordActions label="评估记录" record={{ evaluation_id: item.evaluation_id, trade_date: item.trade_date, artifact_refs: item.artifact_refs }} />
          {item.as_of ? <span className="mt-1 block text-[length:var(--text-11)] text-[var(--fg-4)]">数据时间 {new Date(item.as_of).toLocaleString("zh-CN", { hour12: false })}</span> : null}
        </div>
        <div className="text-right">
          <span className="block text-[length:var(--text-11)] text-[var(--fg-4)]">准确率</span>
          <strong className={`text-[length:var(--text-13)] ${item.accuracy === null ? "text-[var(--warn)]" : "fa-num text-[var(--fg-1)]"}`}>{formatAccuracy(item.accuracy)}</strong>
        </div>
      </div>
      <div className="mt-3 grid gap-2 text-[length:var(--text-11)] text-[var(--fg-4)] sm:grid-cols-5">
        <span>结果 <b className="fa-num text-[var(--fg-2)]">{item.outcome_count}</b></span>
        <span>已批准 <b className="fa-num text-[var(--fg-2)]">{item.approved_count}</b></span>
        <span>质量阻断 <b className="fa-num text-[var(--down)]">{item.blocked_count}</b></span>
        <span>不可评分 <b className="fa-num text-[var(--warn)]">{item.unscorable_count}</b></span>
        <span>历史待核验（不计入已批准样本或准确率） <b className="fa-num text-[var(--warn)]">{item.legacy_unverified_count}</b></span>
      </div>
      {item.outcomes.length > 0 ? (
        <details className="mt-2 border-t border-[var(--border-faint)] pt-2">
          <summary className="cursor-pointer list-none text-[length:var(--text-11)] font-semibold text-[var(--fg-3)]">生命周期与成交基准 · <span className="fa-num">{item.outcomes.length}</span></summary>
          <div className="mt-2 grid gap-2 lg:grid-cols-2">
            {item.outcomes.map((outcome) => <OutcomeSummaryRow key={outcome.horizon} outcome={outcome} />)}
          </div>
        </details>
      ) : (
        <p className="mt-2 border-t border-[var(--border-faint)] pt-2 text-[length:var(--text-11)] text-[var(--fg-4)]">尚未提供评估明细，暂无法进一步核实。</p>
      )}
      <details className="mt-2 border-t border-[var(--border-faint)] pt-2">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-[length:var(--text-11)] text-[var(--fg-4)]">
          <Database className="h-3.5 w-3.5 text-[var(--info)]" aria-hidden="true" />
          产物引用 <span className="fa-num">{item.artifact_refs.length}</span>
        </summary>
        <div className="mt-1"><EvidenceRecordActions label="评估产物记录" record={{ trade_date: item.trade_date, artifact_refs: item.artifact_refs }} /></div>
      </details>
    </article>
  );
}

export function ShadowEvaluationHistoryPanel({ data, isLoading, isUnavailable, error }: ShadowEvaluationHistoryPanelProps) {
  if (isLoading && !data) {
    return <FACard title="影子评估历史" eyebrow="历史评估" accent="brand"><div className="flex items-center gap-2 text-[length:var(--text-12)] text-[var(--fg-4)]" aria-live="polite"><History className="h-4 w-4 text-[var(--brand)]" aria-hidden="true" />正在读取不可变评估历史…</div></FACard>;
  }
  if (!data) {
    return <FAEmptyState title={error ? "影子评估历史读取失败" : isUnavailable ? "影子评估历史不可用" : "暂无影子评估历史"} description={readingErrorMessage(error, isUnavailable ? "尚未提供评估历史。" : "当前没有可展示的评估分区。")} className="border-[var(--border-faint)] bg-[var(--bg-card)]" />;
  }
  if (data.items.length === 0) {
    return <FAEmptyState title="暂无影子评估历史" description="后端返回空历史结果；页面不会把空结果伪装成准确率或样本。" className="border-[var(--border-faint)] bg-[var(--bg-card)]" />;
  }
  const blockedCount = data.items.reduce((sum, item) => sum + item.blocked_count, 0);
  return (
    <FACard
      title="影子评估历史"
      eyebrow="历史评估"
      accent={blockedCount > 0 ? "down" : "brand"}
      description="只读展示冻结评估分区；质量阻断和不可评分结果保留原状态，不进入准确率分母。"
      action={<FAStatusPill tone={data.truncated ? "warn" : "info"}>{data.total} 条记录{data.truncated ? " · 已截断" : ""}</FAStatusPill>}
      bodyClassName="space-y-2"
    >
      {blockedCount > 0 ? <div className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--down-border)] bg-[var(--down-soft)] px-3 py-2 text-[length:var(--text-11)] text-[var(--down)]" role="note"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><span>历史中有 {blockedCount} 个质量阻断结果，不参与准确率统计。</span></div> : null}
      {data.items.map((item) => <HistoryRow key={`${item.trade_date}:${item.evaluation_id}`} item={item} />)}
    </FACard>
  );
}
