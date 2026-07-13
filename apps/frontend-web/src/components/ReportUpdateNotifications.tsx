import { useEffect, useRef, useState } from "react";
import { Bell, CheckCheck, FileText } from "lucide-react";
import { Link } from "react-router-dom";
import { useReportUpdateNotifications } from "@/hooks/useReportUpdateNotifications";
import { formatDateTime } from "@/lib/date";
import { CATEGORY_MAP, getReportDetailId, getReportTitle } from "@/components/reports/reportListMeta";

function reportHref(report: Parameters<typeof getReportDetailId>[0]): string {
  const reportId = getReportDetailId(report);
  return reportId ? `/reports/${encodeURIComponent(reportId)}` : "/reports";
}

export function ReportUpdateNotifications() {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { notifications, unreadCount, isRead, markRead, markAllRead } = useReportUpdateNotifications();

  useEffect(() => {
    if (!isOpen) return;

    function closeOnOutsideClick(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }

    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isOpen]);

  return (
    <div ref={containerRef} className="relative">
      <button
        className="relative rounded-full border border-transparent p-2.5 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-hover)]"
        title={unreadCount ? `报告更新：${unreadCount} 条未读` : "报告更新通知"}
        aria-label={unreadCount ? `报告更新：${unreadCount} 条未读` : "报告更新通知"}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        onClick={() => setIsOpen((value) => !value)}
      >
        <Bell size={14} className="text-finance-text-muted" />
        {unreadCount ? (
          <span className="absolute -right-0.5 -top-0.5 inline-flex min-w-4 items-center justify-center rounded-full bg-[var(--down)] px-1 font-mono text-[length:var(--type-caption)] font-semibold leading-4 text-white">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        ) : null}
      </button>

      {isOpen ? (
        <section
          role="dialog"
          aria-label="报告更新通知"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-[min(360px,calc(100vw-24px))] overflow-hidden rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-panel)] shadow-[var(--shadow-card)]"
        >
          <header className="flex items-center justify-between gap-3 border-b border-[var(--border-faint)] px-3 py-2.5">
            <div>
              <div className="fa-card-title">报告更新</div>
            </div>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-2 py-1 fa-label text-[var(--brand-hover)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
              onClick={markAllRead}
              disabled={!unreadCount}
            >
              <CheckCheck size={13} />
              全部已读
            </button>
          </header>

          <div className="max-h-[min(420px,calc(100vh-160px))] overflow-y-auto p-1.5">
            {notifications.length ? notifications.map((notification) => {
              const unread = !isRead(notification.id);
              const report = notification.report;
              return (
                <Link
                  key={notification.id}
                  to={reportHref(report)}
                  onClick={() => {
                    markRead(notification.id);
                    setIsOpen(false);
                  }}
                  className="flex gap-2 rounded-[var(--radius-sm)] px-2.5 py-2 text-left hover:bg-[var(--bg-hover)]"
                >
                  <FileText size={15} className="mt-0.5 shrink-0 text-[var(--brand-hover)]" />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-start justify-between gap-2">
                      <span className="fa-body-text line-clamp-2">{getReportTitle(report)}</span>
                      {unread ? <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--down)]" aria-label="未读" /> : null}
                    </span>
                    <span className="mt-1 flex items-center gap-2 fa-muted-text">
                      <span>{CATEGORY_MAP[report.type]?.label ?? report.type}</span>
                      <time className="fa-num">{formatDateTime(notification.generatedAt)}</time>
                    </span>
                  </span>
                </Link>
              );
            }) : (
              <div className="px-3 py-8 text-center fa-muted-text">今日暂无新报告。</div>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}
