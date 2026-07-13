import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchReportsIndex } from "@/adapters/reports";
import { isSupportedReportType } from "@/components/reports/reportListMeta";
import type { ReportIndexItem } from "@/types/reports";

const POLL_INTERVAL_MS = 5 * 60 * 1000;
const READ_STORAGE_KEY = "finance-agent:report-update-notifications:read";

export interface ReportUpdateNotification {
  id: string;
  report: ReportIndexItem;
  generatedAt: string;
}

function isSameLocalDate(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate();
}

function notificationId(report: ReportIndexItem): string | null {
  if (!report.generated_at) return null;
  const reportIdentity = [
    report.type,
    report.trade_date,
    report.title ?? report.source_title ?? report.report_id ?? report.run_id ?? "untitled",
  ].join(":");
  return `${reportIdentity}:${report.generated_at}`;
}

function reportIdentity(report: ReportIndexItem): string {
  return [
    report.type,
    report.trade_date,
    report.title ?? report.source_title ?? report.report_id ?? report.run_id ?? "untitled",
  ].join(":");
}

function readStoredNotificationIds(): Set<string> {
  try {
    const raw = window.localStorage.getItem(READ_STORAGE_KEY);
    const values = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(values) ? values.filter((value): value is string => typeof value === "string") : []);
  } catch {
    return new Set();
  }
}

function persistReadNotificationIds(ids: Set<string>): void {
  try {
    window.localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(Array.from(ids).slice(-200)));
  } catch {
    // Browser storage is optional; notifications remain usable for this session.
  }
}

function reportUpdatesForToday(reports: ReportIndexItem[], now: Date): ReportUpdateNotification[] {
  const latestByReport = new Map<string, ReportIndexItem>();

  reports.forEach((report) => {
    if (!report.available || !report.generated_at || !isSupportedReportType(report.type)) return;
    const generatedAt = new Date(report.generated_at);
    if (Number.isNaN(generatedAt.getTime()) || !isSameLocalDate(generatedAt, now)) return;
    const key = reportIdentity(report);
    const current = latestByReport.get(key);
    if (!current || (current.generated_at ?? "").localeCompare(report.generated_at) < 0) {
      latestByReport.set(key, report);
    }
  });

  return Array.from(latestByReport.values())
    .flatMap((report) => {
      const generatedAt = new Date(report.generated_at as string);
      const id = notificationId(report);
      if (!id || Number.isNaN(generatedAt.getTime()) || !isSameLocalDate(generatedAt, now)) return [];
      return [{ id, report, generatedAt: report.generated_at as string }];
    })
    .sort((left, right) => right.generatedAt.localeCompare(left.generatedAt));
}

export function useReportUpdateNotifications() {
  const [notifications, setNotifications] = useState<ReportUpdateNotification[]>([]);
  const [readIds, setReadIds] = useState<Set<string>>(() => readStoredNotificationIds());

  useEffect(() => {
    let cancelled = false;

    async function loadNotifications() {
      try {
        const index = await fetchReportsIndex();
        if (!cancelled) {
          setNotifications(reportUpdatesForToday(index.reports, new Date()));
        }
      } catch {
        // Preserve the last successful notification list during a transient API failure.
      }
    }

    void loadNotifications();
    const timer = window.setInterval(() => void loadNotifications(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const unreadCount = useMemo(
    () => notifications.filter((notification) => !readIds.has(notification.id)).length,
    [notifications, readIds],
  );

  const markRead = useCallback((id: string) => {
    setReadIds((current) => {
      if (current.has(id)) return current;
      const next = new Set(current);
      next.add(id);
      persistReadNotificationIds(next);
      return next;
    });
  }, []);

  const markAllRead = useCallback(() => {
    setReadIds((current) => {
      const next = new Set(current);
      notifications.forEach((notification) => next.add(notification.id));
      persistReadNotificationIds(next);
      return next;
    });
  }, [notifications]);

  return {
    notifications,
    unreadCount,
    isRead: (id: string) => readIds.has(id),
    markRead,
    markAllRead,
  };
}
