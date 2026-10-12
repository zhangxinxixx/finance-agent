import { AlertTriangle, BarChart3, Database, ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { readingErrorMessage } from "@/components/reading/readingFormat";
import type {
  ShadowEvaluationHorizon,
  ShadowEvaluationLifecycleCounts,
  ShadowEvaluationMetricSummary,
  ShadowEvaluationMetricsResponse,
} from "@/types/shadow-evaluation";
import { enumRawTitle, shadowLifecycleLabel, shadowSummaryStatusLabel } from "./strategyDisplayLabels";

interface ShadowEvaluationPanelProps {
  data: ShadowEvaluationMetricsResponse | null;
  isLoading: boolean;
  isUnavailable: boolean;
  error: Error | null;
}

const horizonLabels: Record<ShadowEvaluationHorizon, string> = {
  "1h": "1 小时",
  "4h": "4 小时",
  session: "交易时段",
  "24h": "24 小时",
};
const lifecycleLabels: Record<keyof ShadowEvaluationLifecycleCounts, string> = {
  legacy_unverified: "历史待核验",
  never_triggered: "未触发",
  invalidated_before_entry: "入场前失效",
  triggered: "已触发",
  triggered_then_invalidated: "触发后失效",
  target_reached: "目标命中",
  same_bar_ambiguous: "同 K 线歧义",
  insufficient_market_path: "路径不足",
  insufficient_strategy_contract: "策略契约不足",
  blocked: "质量阻断",
};
const lifecycleOrder = Object.keys(lifecycleLabels) as Array<keyof ShadowEvaluationLifecycleCounts>;

function statusTone(summary: ShadowEvaluationMetricSummary): FAStatusTone {
  if (summary.blocked_count > 0) return "down";
  if (summary.unscorable_count > 0) return "warn";
  if (summary.verified_scored_count > 0) return "up";
  return "dim";
}

function statusLabel(summary: ShadowEvaluationMetricSummary) {
  if (summary.blocked_count > 0) return shadowSummaryStatusLabel("blocked");
  if (summary.unscorable_count > 0) return shadowSummaryStatusLabel("unscorable");
  if (summary.verified_scored_count > 0) return shadowSummaryStatusLabel("verified");
  if (summary.legacy_unverified_count > 0) return shadowSummaryStatusLabel("legacy");
  return shadowSummaryStatusLabel("no_sample");
}

function formatAccuracy(value: number | null) {
  return value === null
    ? "暂无可评分样本"
    : value.toLocaleString("zh-CN", { style: "percent", maximumFractionDigits: 1 });
}

function displayCount(value: number | null | undefined): string | number {
  return value === null || value === undefined ? "未提供" : value;
}

function MetricCell({ label, value, tone = "neutral" }: { label: string; value: string | number; tone?: FAStatusTone }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">{label}</span>
      <div className="mt-1 flex items-center justify-between gap-2">
        <strong className="fa-num text-[length:var(--text-14)] text-[var(--fg-1)]">{value}</strong>
        <FAStatusPill tone={tone} dot={false}>{tone === "neutral" ? "计数" : statusLabelForTone(tone)}</FAStatusPill>
      </div>
    </div>
  );
}

function statusLabelForTone(tone: FAStatusTone) {
  if (tone === "down") return "质量阻断";
  if (tone === "warn") return "待核验";
  if (tone === "up") return "已评分";
  return "计数";
}

function HorizonRow({ horizon, summary }: { horizon: ShadowEvaluationHorizon; summary: ShadowEvaluationMetricSummary | undefined }) {
  return (
    <div className="grid gap-2 border-b border-[var(--border-faint)] px-3 py-2 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto_auto] sm:items-center">
      <div className="flex items-center gap-2">
        <strong className="text-[length:var(--text-12)] text-[var(--fg-2)]">{horizonLabels[horizon]}</strong>
        <FAStatusPill tone={summary ? statusTone(summary) : "dim"} title={summary ? enumRawTitle(statusLabel(summary)) : undefined}>{summary ? statusLabel(summary).label : "暂无样本"}</FAStatusPill>
      </div>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">总数 <b className="fa-num text-[var(--fg-2)]">{displayCount(summary?.total_count)}</b></span>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">已核验评分 <b className="fa-num text-[var(--fg-2)]">{displayCount(summary?.verified_scored_count)}</b></span>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">质量阻断 <b className="fa-num text-[var(--down)]">{displayCount(summary?.blocked_count)}</b></span>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">不可评分 <b className="fa-num text-[var(--warn)]">{displayCount(summary?.unscorable_count)}</b></span>
    </div>
  );
}

function LifecycleSummary({ counts }: { counts: ShadowEvaluationLifecycleCounts | null }) {
  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-3" aria-label="策略生命周期计数">
      <div className="text-[length:var(--text-11)] font-semibold uppercase tracking-[var(--tracking-wide)] text-[var(--fg-4)]">结果生命周期</div>
      {counts ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {lifecycleOrder.map((lifecycle) => (
            <div key={lifecycle} className="flex items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <span className="text-[length:var(--text-11)] text-[var(--fg-4)]" title={enumRawTitle(shadowLifecycleLabel(lifecycle))}>{lifecycleLabels[lifecycle]}</span>
              <strong className="fa-num text-[length:var(--text-13)] text-[var(--fg-1)]">{displayCount(counts[lifecycle])}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-[length:var(--text-11)] leading-relaxed text-[var(--fg-4)]">生命周期数据不可用：当前接口或历史产物尚未包含该字段，页面不会从分类结果推断。</p>
      )}
    </section>
  );
}

export function ShadowEvaluationPanel({ data, isLoading, isUnavailable, error }: ShadowEvaluationPanelProps) {
  if (isLoading && !data) {
    return (
      <FACard title="影子策略评估" eyebrow="评估结果" accent="brand">
        <div className="flex items-center gap-2 text-[length:var(--text-12)] text-[var(--fg-4)]" aria-live="polite">
          <BarChart3 className="h-4 w-4 text-[var(--brand)]" aria-hidden="true" />
          正在读取最新不可变评估分区…
        </div>
      </FACard>
    );
  }

  if (!data) {
    const title = error ? "影子评估读取失败" : "暂无影子评估产物";
    const description = error
      ? readingErrorMessage(error, "影子评估读取失败，请稍后重试。")
      : isUnavailable
        ? "后端尚未生成可读取的 evaluation partition；每日 StrategyCard 和实时策略保持独立可用。"
        : "当前资产没有评估数据，页面不会猜测准确率或补造结果。";
    return (
      <FAEmptyState
        title={title}
        description={description}
        className="border-[var(--border-faint)] bg-[var(--bg-card)]"
      />
    );
  }

  const metrics = data.metrics;
  const blocked = metrics.blocked_count > 0;
  const noDirectionalSample = metrics.accuracy === null;

  return (
    <FACard
      title="影子策略评估"
      eyebrow="评估结果"
      accent={blocked ? "down" : "brand"}
      description="只读消费冻结策略与后验结果；质量阻断和不可评分结果不进入准确率分母。"
      action={(
        <div className="flex flex-wrap items-center justify-end gap-2">
          <FAStatusPill tone={blocked ? "down" : metrics.verified_scored_count > 0 ? "up" : "warn"}>
            {blocked ? "质量闸门阻断" : metrics.verified_scored_count > 0 ? "有可信样本" : "等待可信样本"}
          </FAStatusPill>
          <FAStatusPill tone="info">{data.trade_date}</FAStatusPill>
        </div>
      )}
      bodyClassName="space-y-3"
    >
      {blocked ? (
        <div className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--down-border)] bg-[var(--down-soft)] px-3 py-2 text-[length:var(--text-12)] text-[var(--down)]" role="note">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <strong>当前结果被质量闸门阻断</strong>
            <p className="mt-1 leading-relaxed text-[var(--fg-3)]">{metrics.blocked_count} 个结果保留为质量阻断（blocked）；系统不会把它们计为错误样本，也不会生成伪准确率。</p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <MetricCell label="策略快照" value={data.snapshot_count} />
        <MetricCell label="结果记录" value={data.outcome_count} />
        <MetricCell label="原始 / 已核验评分" value={`${metrics.scored_count} / ${metrics.verified_scored_count}`} tone={metrics.verified_scored_count > 0 ? "up" : "dim"} />
        <MetricCell label="质量阻断" value={metrics.blocked_count} tone={metrics.blocked_count > 0 ? "down" : "dim"} />
        <MetricCell label="不可评分" value={metrics.unscorable_count} tone={metrics.unscorable_count > 0 ? "warn" : "dim"} />
        <MetricCell label="方向性分母" value={metrics.directional_count} tone={metrics.directional_count > 0 ? "info" : "dim"} />
      </div>

      {metrics.legacy_unverified_count > 0 ? (
        <div className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--text-12)] text-[var(--warn)]" role="note">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p><strong>{metrics.legacy_unverified_count} 个历史结果待核验。</strong>它们保留原始观望（HOLD）与已评分记录用于审计，但不进入可信准确率、最大有利变动（MFE）或最大不利变动（MAE）。</p>
        </div>
      ) : null}

      <LifecycleSummary counts={metrics.lifecycle_counts} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <section className="rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-3" aria-label="准确率摘要">
          <div className="flex items-center gap-2 text-[length:var(--text-11)] font-semibold uppercase tracking-[var(--tracking-wide)] text-[var(--fg-4)]">
            {noDirectionalSample ? <AlertTriangle className="h-4 w-4 text-[var(--warn)]" aria-hidden="true" /> : <BarChart3 className="h-4 w-4 text-[var(--up)]" aria-hidden="true" />}
            方向判断准确率
          </div>
          <strong className={`mt-2 block text-[length:var(--text-20)] ${noDirectionalSample ? "text-[var(--warn)]" : "fa-num text-[var(--fg-1)]"}`}>
            {formatAccuracy(metrics.accuracy)}
          </strong>
          <p className="mt-2 text-[length:var(--text-11)] leading-relaxed text-[var(--fg-4)]">
            分母 {metrics.directional_count} · 正确 {metrics.correct_count} · 错误 {metrics.incorrect_count}
          </p>
          <p className="mt-1 text-[length:var(--text-11)] leading-relaxed text-[var(--fg-4)]">
            平均最大有利变动（MFE） <b className="fa-num text-[var(--fg-2)]">{metrics.mfe_avg ?? "—"}</b> · 平均最大不利变动（MAE） <b className="fa-num text-[var(--fg-2)]">{metrics.mae_avg ?? "—"}</b>
          </p>
        </section>

        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-panel)]" aria-label="各周期评估">
          {(["1h", "4h", "session", "24h"] as const).map((horizon) => (
            <HorizonRow key={horizon} horizon={horizon} summary={metrics.by_horizon[horizon]} />
          ))}
        </section>
      </div>

      <details className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-[length:var(--text-11)] font-semibold text-[var(--fg-3)]">
          <Database className="h-4 w-4 text-[var(--info)]" aria-hidden="true" />
          查看评估详情
          <span className="fa-num ml-auto text-[var(--fg-4)]">{data.evaluation_ids.length} 个评估 · {data.artifact_refs.length} 个记录</span>
        </summary>
        <div className="mt-2 grid gap-2 lg:grid-cols-2">
          <div className="lg:col-span-2">
            <EvidenceRecordActions
              label="评估证据记录"
              record={{ evaluation_ids: data.evaluation_ids, artifact_refs: data.artifact_refs }}
            />
          </div>
        </div>
      </details>
    </FACard>
  );
}
