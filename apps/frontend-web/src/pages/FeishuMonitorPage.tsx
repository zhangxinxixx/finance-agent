import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, RefreshCw } from "lucide-react";
import { fetchFeishuJin10MessageMonitor } from "@/adapters/feishuMonitor";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { FeishuMonitorMessage, FeishuMonitorResponse } from "@/types/feishu-monitor";

function todayLocalDate(): string {
  const now = new Date();
  const yyyy = String(now.getFullYear());
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function compactTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16);
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function messageTitle(message: FeishuMonitorMessage): string {
  return (
    message.accepted_item?.title?.trim()
    || message.article_brief?.headline?.trim()
    || message.content?.trim()
    || message.primary_url
    || message.message_id
  );
}

function statusTone(status?: string | null): "up" | "warn" | "down" | "dim" | "neutral" {
  const normalized = String(status ?? "").toLowerCase();
  if (normalized.includes("high") || normalized.includes("success") || normalized.includes("readable") || normalized.includes("queued")) return "up";
  if (normalized.includes("vip") || normalized.includes("blocked") || normalized.includes("partial") || normalized.includes("candidate")) return "warn";
  if (normalized.includes("fail") || normalized.includes("reject")) return "down";
  if (normalized.includes("empty") || normalized.includes("unknown")) return "dim";
  return "neutral";
}

function taskSummary(message: FeishuMonitorMessage): string {
  const task = message.task;
  if (!task) return "未建 follow-up 任务";
  const blocked = task.steps.find((step) => step.blocked_reason || step.error_type);
  if (blocked?.blocked_reason) return blocked.blocked_reason;
  if (blocked?.error_type) return blocked.error_type;
  return task.current_stage || task.status || "已登记";
}

function MessageCard({ message }: { message: FeishuMonitorMessage }) {
  return (
    <article className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <FAStatusPill tone={statusTone(message.filter_status)}>{message.filter_status}</FAStatusPill>
            {message.trigger?.priority ? <FAStatusPill tone={statusTone(message.trigger.priority)}>{message.trigger.priority}</FAStatusPill> : null}
            {message.article_brief?.access_status ? <FAStatusPill tone={statusTone(message.article_brief.access_status)}>{message.article_brief.access_status}</FAStatusPill> : null}
            {message.task?.current_stage ? <FAStatusPill tone="neutral">{message.task.current_stage}</FAStatusPill> : null}
          </div>
          <div className="mt-2 text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{messageTitle(message)}</div>
          <div className="mt-1 text-[11px] leading-5 text-[var(--fg-3)]">
            {message.article_brief?.analysis_summary || message.content || "当前消息没有额外摘要。"}
          </div>
        </div>
        {message.primary_url ? (
          <a
            href={message.article_brief?.final_url || message.primary_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] text-[var(--fg-4)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
            title="打开来源链接"
          >
            <ExternalLink size={14} />
          </a>
        ) : null}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <MetricRow label="发布时间" value={compactTime(message.published_at)} />
        <MetricRow label="来源标记" value={message.source_marker || "—"} />
        <MetricRow label="Trigger" value={message.trigger ? `${message.trigger.event_type ?? "—"} / ${message.trigger.status ?? "queued"}` : "未触发"} />
        <MetricRow label="Task" value={taskSummary(message)} />
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {message.accepted_item?.event_type ? <FASourceTraceBadge source={message.accepted_item.event_type} status="event_type" tone="info" /> : null}
        {message.article_brief?.artifact_path ? <FASourceTraceBadge source={message.article_brief.artifact_path} status="artifact" tone="dim" /> : null}
        {message.trigger?.artifact_path ? <FASourceTraceBadge source={message.trigger.artifact_path} status="artifact" tone="dim" /> : null}
        {message.parsed_artifact_path ? <FASourceTraceBadge source={message.parsed_artifact_path} status="parsed" tone="dim" /> : null}
      </div>
    </article>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 text-[11px] text-[var(--fg-2)]">{value}</div>
    </div>
  );
}

export function FeishuMonitorPage() {
  const [date, setDate] = useState(todayLocalDate());
  const [reloadToken, setReloadToken] = useState(0);
  const [payload, setPayload] = useState<FeishuMonitorResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFeishuJin10MessageMonitor(date)
      .then((nextPayload) => {
        if (!cancelled) setPayload(nextPayload);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Feishu monitor 加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [date, reloadToken]);

  const warnings = useMemo(() => payload?.data_quality?.warnings ?? [], [payload]);

  return (
    <div className="finance-page-shell space-y-4">
      <FACard
        title="Feishu / Jin10 监控"
        eyebrow="Feishu Monitor"
        accent="brand"
        action={
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              className="h-8 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[11px] text-[var(--fg-2)]"
            />
            <button
              type="button"
              onClick={() => setReloadToken((current) => current + 1)}
              className="inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 text-[11px] font-semibold text-[var(--fg-2)]"
            >
              <RefreshCw size={12} />
              刷新
            </button>
            <Link
              to="/data-sources/jin10_feishu"
              className="inline-flex h-8 items-center rounded-[var(--radius-sm)] border border-[var(--border)] px-3 text-[11px] font-semibold text-[var(--fg-3)]"
            >
              数据源详情
            </Link>
          </div>
        }
        bodyClassName="space-y-3"
      >
        <div className="flex flex-wrap gap-2">
          <FAStatusPill tone={statusTone(payload?.status)}>{loading ? "loading" : payload?.status ?? "unknown"}</FAStatusPill>
          <FASourceTraceBadge source={`/api/news/feishu-jin10/messages?date=${date}`} status="api" tone="info" />
          {payload?.source_refs?.[0]?.path ? <FASourceTraceBadge source={String(payload.source_refs[0].path)} status="artifact" tone="dim" /> : null}
        </div>
        <div className="text-[11px] leading-5 text-[var(--fg-3)]">
          展示飞书金十群消息从采集、过滤、生成 trigger / article brief，到 follow-up task 与 VIP 补抓状态的每日闭环。
        </div>
        {error ? (
          <div className="rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--down)]">
            {error}
          </div>
        ) : null}
      </FACard>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <FAMetricCard label="messages" value={loading ? "…" : String(payload?.message_count ?? 0)} hint="当日消息总数" />
        <FAMetricCard label="accepted" value={loading ? "…" : String(payload?.accepted_count ?? 0)} hint="进入系统候选" />
        <FAMetricCard label="triggered" value={loading ? "…" : String(payload?.triggered_count ?? 0)} hint="已生成 trigger" />
        <FAMetricCard label="briefs" value={loading ? "…" : String(payload?.brief_count ?? 0)} hint="已生成文章简报" />
        <FAMetricCard label="tasks" value={loading ? "…" : String(payload?.task_count ?? 0)} hint="已建 follow-up task" />
      </div>

      <FACard title="消息清单" eyebrow="Daily Messages" accent="brand" bodyClassName="space-y-3">
        {loading ? (
          <div className="grid gap-3 md:grid-cols-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="finance-skeleton-card h-28" />
            ))}
          </div>
        ) : payload && payload.messages.length > 0 ? (
          <div className="space-y-3">
            {payload.messages.map((message) => (
              <MessageCard key={message.message_id} message={message} />
            ))}
          </div>
        ) : (
          <FAEmptyState title="当天暂无监控消息" description="当前日期没有 Feishu/Jin10 解析 artifact 或消息列表为空。" className="py-8" />
        )}
      </FACard>

      <FACard title="数据质量" eyebrow="Warnings" accent="warn" bodyClassName="space-y-2">
        {warnings.length > 0 ? (
          warnings.map((warning) => (
            <div key={warning} className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--warn)]">
              {warning}
            </div>
          ))
        ) : (
          <div className="text-[11px] leading-5 text-[var(--fg-4)]">当前没有额外 warnings。</div>
        )}
      </FACard>
    </div>
  );
}

export default FeishuMonitorPage;
