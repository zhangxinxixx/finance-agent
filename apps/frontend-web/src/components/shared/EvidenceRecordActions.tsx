import { useState } from "react";
import { summarizeEvidenceRecord } from "@/adapters/pageDataBoundary.mjs";

interface EvidenceRecordActionsProps {
  record: unknown;
  label?: string;
  url?: string | null;
}

function sourceHref(url?: string | null): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    if ((parsed.protocol === "http:" || parsed.protocol === "https:") && !parsed.username && !parsed.password) {
      return parsed.href;
    }
  } catch {
    // Invalid sources have no navigation action.
  }
  return undefined;
}

export function EvidenceRecordActions({ record, label = "依据记录", url }: EvidenceRecordActionsProps) {
  const [feedback, setFeedback] = useState("");
  const [copying, setCopying] = useState(false);
  const safeRecord = summarizeEvidenceRecord(record);
  const hasRecord = safeRecord !== null;
  const href = sourceHref(url);

  async function copyRecord() {
    if (!hasRecord || copying) return;
    setFeedback("");
    setCopying(true);
    try {
      const payload = JSON.stringify(safeRecord, null, 2);
      if (payload === undefined) throw new Error();
      await navigator.clipboard.writeText(payload);
      setFeedback("依据记录已复制。");
    } catch {
      setFeedback("复制失败，请确认记录可序列化且浏览器允许访问剪贴板后重试。");
    } finally {
      setCopying(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="fa-muted-text">
        {hasRecord ? `${label}可复制页面级摘要以核对身份与状态。` : `${label}没有可在页面层公开的摘要。`}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!hasRecord || copying}
          onClick={copyRecord}
          className="fa-label rounded border border-[var(--border)] px-3 py-1.5 text-[var(--fa-text-body)] hover:bg-[var(--info-soft)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {copying ? "正在复制摘要…" : "复制摘要"}
        </button>
        {href ? (
          <a className="fa-label text-[var(--brand)] underline" href={href} target="_blank" rel="noreferrer">
            查看官方来源
          </a>
        ) : null}
      </div>
      <p className="fa-muted-text" role="status" aria-live="polite" aria-atomic="true">{feedback}</p>
    </div>
  );
}
