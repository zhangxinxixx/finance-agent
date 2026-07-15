import { AlertTriangle, BarChart3, Database, ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type {
  ShadowEvaluationHorizon,
  ShadowEvaluationMetricSummary,
  ShadowEvaluationMetricsResponse,
} from "@/types/shadow-evaluation";

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
const MAX_DISPLAY_ITEMS = 40;

function statusTone(summary: ShadowEvaluationMetricSummary): FAStatusTone {
  if (summary.blocked_count > 0) return "down";
  if (summary.unscorable_count > 0) return "warn";
  if (summary.scored_count > 0) return "up";
  return "dim";
}

function statusLabel(summary: ShadowEvaluationMetricSummary) {
  if (summary.blocked_count > 0) return "Blocked";
  if (summary.unscorable_count > 0) return "Unscorable";
  if (summary.scored_count > 0) return "Scored";
  return "No sample";
}

function formatAccuracy(value: number | null) {
  return value === null
    ? "暂无可评分样本"
    : value.toLocaleString("zh-CN", { style: "percent", maximumFractionDigits: 1 });
}

function MetricCell({ label, value, tone = "neutral" }: { label: string; value: string | number; tone?: FAStatusTone }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">{label}</span>
      <div className="mt-1 flex items-center justify-between gap-2">
        <strong className="fa-num text-[length:var(--text-14)] text-[var(--fg-1)]">{value}</strong>
        <FAStatusPill tone={tone} dot={false}>{tone === "neutral" ? "count" : statusLabelForTone(tone)}</FAStatusPill>
      </div>
    </div>
  );
}

function statusLabelForTone(tone: FAStatusTone) {
  if (tone === "down") return "blocked";
  if (tone === "warn") return "pending";
  if (tone === "up") return "scored";
  return "count";
}

function HorizonRow({ horizon, summary }: { horizon: ShadowEvaluationHorizon; summary: ShadowEvaluationMetricSummary | undefined }) {
  return (
    <div className="grid gap-2 border-b border-[var(--border-faint)] px-3 py-2 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto_auto] sm:items-center">
      <div className="flex items-center gap-2">
        <strong className="text-[length:var(--text-12)] text-[var(--fg-2)]">{horizonLabels[horizon]}</strong>
        <FAStatusPill tone={summary ? statusTone(summary) : "dim"}>{summary ? statusLabel(summary) : "No sample"}</FAStatusPill>
      </div>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">总数 <b className="fa-num text-[var(--fg-2)]">{summary?.total_count ?? 0}</b></span>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">Scored <b className="fa-num text-[var(--fg-2)]">{summary?.scored_count ?? 0}</b></span>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">Blocked <b className="fa-num text-[var(--down)]">{summary?.blocked_count ?? 0}</b></span>
      <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">Unscorable <b className="fa-num text-[var(--warn)]">{summary?.unscorable_count ?? 0}</b></span>
    </div>
  );
}

export function ShadowEvaluationPanel({ data, isLoading, isUnavailable, error }: ShadowEvaluationPanelProps) {
  if (isLoading && !data) {
    return (
      <FACard title="影子策略评估" eyebrow="shadow_evaluation_metrics.v1" accent="brand">
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
      ? error.message
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
      eyebrow="shadow_evaluation_metrics.v1"
      accent={blocked ? "down" : "brand"}
      description="只读消费冻结策略与后验结果；blocked / unscorable 不进入准确率分母。"
      action={(
        <div className="flex flex-wrap items-center justify-end gap-2">
          <FAStatusPill tone={blocked ? "down" : metrics.scored_count > 0 ? "up" : "warn"}>
            {blocked ? "QualityGate blocked" : metrics.scored_count > 0 ? "有可评分样本" : "等待样本"}
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
            <p className="mt-1 leading-relaxed text-[var(--fg-3)]">{metrics.blocked_count} 个 outcome 保留为 blocked；系统不会把它们计为错误样本，也不会生成伪准确率。</p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <MetricCell label="Strategy snapshots" value={data.snapshot_count} />
        <MetricCell label="Outcome records" value={data.outcome_count} />
        <MetricCell label="Approved / scored" value={`${metrics.approved_count} / ${metrics.scored_count}`} tone={metrics.scored_count > 0 ? "up" : "dim"} />
        <MetricCell label="Blocked" value={metrics.blocked_count} tone={metrics.blocked_count > 0 ? "down" : "dim"} />
        <MetricCell label="Unscorable" value={metrics.unscorable_count} tone={metrics.unscorable_count > 0 ? "warn" : "dim"} />
        <MetricCell label="Directional denominator" value={metrics.directional_count} tone={metrics.directional_count > 0 ? "info" : "dim"} />
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <section className="rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-3" aria-label="准确率摘要">
          <div className="flex items-center gap-2 text-[length:var(--text-11)] font-semibold uppercase tracking-[var(--tracking-wide)] text-[var(--fg-4)]">
            {noDirectionalSample ? <AlertTriangle className="h-4 w-4 text-[var(--warn)]" aria-hidden="true" /> : <BarChart3 className="h-4 w-4 text-[var(--up)]" aria-hidden="true" />}
            Direction accuracy
          </div>
          <strong className={`mt-2 block text-[length:var(--text-20)] ${noDirectionalSample ? "text-[var(--warn)]" : "fa-num text-[var(--fg-1)]"}`}>
            {formatAccuracy(metrics.accuracy)}
          </strong>
          <p className="mt-2 text-[length:var(--text-11)] leading-relaxed text-[var(--fg-4)]">
            分母 {metrics.directional_count} · 正确 {metrics.correct_count} · 错误 {metrics.incorrect_count}
          </p>
          <p className="mt-1 text-[length:var(--text-11)] leading-relaxed text-[var(--fg-4)]">
            MFE avg <b className="fa-num text-[var(--fg-2)]">{metrics.mfe_avg ?? "—"}</b> · MAE avg <b className="fa-num text-[var(--fg-2)]">{metrics.mae_avg ?? "—"}</b>
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
          不可变产物与评估 ID
          <span className="fa-num ml-auto text-[var(--fg-4)]">{data.evaluation_ids.length} IDs · {data.artifact_refs.length} refs</span>
        </summary>
        <div className="mt-2 grid gap-2 lg:grid-cols-2">
          <div>
            <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">Evaluation IDs</span>
            {data.evaluation_ids.slice(0, MAX_DISPLAY_ITEMS).map((id) => <code key={id} className="mt-1 block break-all text-[length:var(--text-11)] text-[var(--fg-2)]">{id}</code>)}
            {data.evaluation_ids.length > MAX_DISPLAY_ITEMS ? <span className="mt-1 block text-[length:var(--text-11)] text-[var(--fg-4)]">另有 {data.evaluation_ids.length - MAX_DISPLAY_ITEMS} 个 ID 未展开</span> : null}
          </div>
          <div>
            <span className="text-[length:var(--text-11)] text-[var(--fg-4)]">Artifact refs</span>
            {data.artifact_refs.slice(0, MAX_DISPLAY_ITEMS).map((ref) => <code key={ref} className="mt-1 block break-all text-[length:var(--text-11)] text-[var(--fg-3)]">{ref}</code>)}
            {data.artifact_refs.length > MAX_DISPLAY_ITEMS ? <span className="mt-1 block text-[length:var(--text-11)] text-[var(--fg-4)]">另有 {data.artifact_refs.length - MAX_DISPLAY_ITEMS} 个 ref 未展开</span> : null}
          </div>
        </div>
      </details>
    </FACard>
  );
}
