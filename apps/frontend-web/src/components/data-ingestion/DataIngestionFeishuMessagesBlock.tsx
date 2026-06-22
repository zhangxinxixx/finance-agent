import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchFeishuJin10MessageMonitor } from "@/adapters/feishuMonitor";
import type { FeishuMonitorMessage, FeishuMonitorResponse } from "@/types/feishu-monitor";
import { DetailMetric } from "./DataIngestionDetailBlocks.shared";

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
  return parsed.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function compactDateTime(value?: string | null): string {
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

function normalizeDate(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return null;
  const yyyy = String(parsed.getFullYear());
  const mm = String(parsed.getMonth() + 1).padStart(2, "0");
  const dd = String(parsed.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function normalizeStatus(value?: string | null): string {
  return String(value ?? "").trim().toLowerCase();
}

function statusTone(status: string | null | undefined): { border: string; bg: string; fg: string } {
  const normalized = normalizeStatus(status);
  if (normalized.includes("high") || normalized.includes("queued") || normalized.includes("success")) {
    return { border: "var(--up-border)", bg: "var(--up-soft)", fg: "var(--up)" };
  }
  if (normalized.includes("vip") || normalized.includes("blocked") || normalized.includes("partial")) {
    return { border: "var(--warn-border)", bg: "var(--warn-soft)", fg: "var(--warn)" };
  }
  if (normalized.includes("fail")) {
    return { border: "var(--down-border)", bg: "var(--down-soft)", fg: "var(--down)" };
  }
  return { border: "var(--border)", bg: "var(--bg-card-inner)", fg: "var(--fg-4)" };
}

function messageTitle(message: FeishuMonitorMessage): string {
  return message.title?.trim() || message.summary?.trim() || message.primary_url || message.message_id;
}

function messageSummary(message: FeishuMonitorMessage): string | null {
  const title = messageTitle(message);
  const summary = message.summary?.trim();
  if (!summary || summary === title) return null;
  return summary;
}

function taskLabel(message: FeishuMonitorMessage): string {
  const task = message.task;
  if (!task) return "未建任务";
  return task.blocked_reason?.trim() || task.current_stage?.trim() || task.status?.trim() || "已建任务";
}

function taskRunId(message: FeishuMonitorMessage): string | null {
  return message.task?.run_id?.trim() || null;
}

function sourceUrl(message: FeishuMonitorMessage): string | null {
  return message.article_brief?.final_url?.trim() || message.primary_url?.trim() || null;
}

export function DataIngestionFeishuMessagesBlock({
  preferredDate,
}: {
  preferredDate?: string | null;
}) {
  const date = useMemo(() => normalizeDate(preferredDate) ?? todayLocalDate(), [preferredDate]);
  const [payload, setPayload] = useState<FeishuMonitorResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchFeishuJin10MessageMonitor(date)
      .then((nextPayload) => {
        if (!cancelled) setPayload(nextPayload);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Feishu/Jin10 明细加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [date]);

  const messages = useMemo(() => (payload?.messages ?? []).slice(0, 5), [payload]);

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">Feishu / Jin10 明细</div>
          <div className="mt-0.5 truncate font-mono text-[8px] text-[var(--fg-5)]">date {date} · /api/news/feishu-jin10/messages</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Link
            to={`/feishu-monitor?date=${encodeURIComponent(date)}`}
            className="rounded-full border border-[var(--border)] px-1.5 py-px text-[8px] font-semibold uppercase text-[var(--fg-4)] transition-colors hover:border-[var(--brand-gold)] hover:text-[var(--brand)]"
          >
            查看完整飞书监控
          </Link>
          <span className="rounded-full border border-[var(--border)] px-1.5 py-px text-[8px] font-semibold uppercase text-[var(--fg-4)]">
            {loading ? "loading" : payload?.status ?? "unknown"}
          </span>
        </div>
      </div>

      {error ? (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-2 py-1.5 text-[9px] leading-4 text-[var(--down)]">
          {error}
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-4 gap-1.5">
        <DetailMetric label="messages" value={loading ? "…" : String(payload?.message_count ?? 0)} mono />
        <DetailMetric label="high" value={loading ? "…" : String(payload?.high_value_count ?? 0)} mono />
        <DetailMetric label="triggered" value={loading ? "…" : String(payload?.triggered_count ?? 0)} mono />
        <DetailMetric label="blocked" value={loading ? "…" : String(payload?.blocked_count ?? 0)} mono />
      </div>

      <div className="mt-2 grid grid-cols-2 gap-1.5">
        <CompactField label="latest" value={loading ? "…" : compactDateTime(payload?.latest_published_at)} />
        <CompactField label="as_of" value={loading ? "…" : compactDateTime(payload?.as_of)} />
      </div>

      {!loading && !error && messages.length === 0 ? (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-1.5 text-[9px] leading-4 text-[var(--fg-5)]">
          当天暂无飞书监控消息。
        </div>
      ) : null}

      {messages.length > 0 ? (
        <div className="mt-2 flex flex-col gap-1.5">
          {messages.map((message) => (
            <FeishuMessageRow key={message.message_id} message={message} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FeishuMessageRow({ message }: { message: FeishuMonitorMessage }) {
  const filterTone = statusTone(message.filter_status);
  const accessTone = statusTone(message.article_brief?.access_status);
  const runId = taskRunId(message);
  const url = sourceUrl(message);
  const title = messageTitle(message);
  const summary = messageSummary(message);

  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-1.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-[8px] text-[var(--fg-6)]">{compactTime(message.published_at)}</div>
          <div className="mt-0.5 line-clamp-2 text-[9px] font-medium leading-4 text-[var(--fg-2)]" title={title}>
            {title}
          </div>
          {summary ? (
            <div className="mt-0.5 line-clamp-2 text-[8px] leading-4 text-[var(--fg-4)]" title={summary}>
              {summary}
            </div>
          ) : null}
        </div>
        <span
          className="shrink-0 rounded-full border px-1.5 py-px text-[8px] font-semibold"
          style={{ borderColor: filterTone.border, background: filterTone.bg, color: filterTone.fg }}
        >
          {message.filter_status}
        </span>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-1.5">
        <CompactField label="trigger" value={message.trigger ? `${message.trigger.priority ?? "—"} / ${message.trigger.status ?? "—"}` : "未触发"} />
        <CompactField label="brief" value={message.article_brief?.access_status ?? "无 brief"} tone={accessTone} />
        <CompactField label="task" value={taskLabel(message)} />
        <CompactField label="source" value={message.source_marker ?? "—"} />
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {runId ? (
          <Link
            to={`/agent-tasks/${encodeURIComponent(runId)}`}
            className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-1.5 py-px text-[8px] font-semibold text-[var(--brand)] transition-colors hover:border-[var(--brand-gold)]"
          >
            任务 {runId.slice(0, 8)}
          </Link>
        ) : null}
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-1.5 py-px text-[8px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--brand-gold)] hover:text-[var(--brand)]"
          >
            来源
          </a>
        ) : null}
      </div>
    </div>
  );
}

function CompactField({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: { border: string; bg: string; fg: string };
}) {
  return (
    <div className="min-w-0 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-1.5 py-1">
      <div className="text-[7px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">{label}</div>
      <div
        className="mt-0.5 truncate font-mono text-[8px] text-[var(--fg-4)]"
        title={value}
        style={tone ? { color: tone.fg } : undefined}
      >
        {value}
      </div>
    </div>
  );
}
