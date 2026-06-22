import { useEffect, useState } from "react";
import { fetchFeishuJin10MessageMonitor, fetchLatestFeishuJin10MessageMonitor } from "@/adapters/feishuMonitor";
import type { FeishuMonitorResponse } from "@/types/feishu-monitor";

function isIsoDate(value: string | null | undefined): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function todayLocalDate(): string {
  const now = new Date();
  const yyyy = String(now.getFullYear());
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function normalizeDate(value: string | null | undefined): string {
  return isIsoDate(value) ? value : todayLocalDate();
}

interface UseFeishuMonitorState {
  date: string;
  payload: FeishuMonitorResponse | null;
  loading: boolean;
  error: Error | null;
  resolvedDate: boolean;
  refresh: () => void;
  reload: () => void;
  setDate: (nextDate: string) => void;
}

export function useFeishuMonitor(initialDate?: string | null, options?: { preferLatest?: boolean }): UseFeishuMonitorState {
  const hasExplicitInitialDate = isIsoDate(initialDate);
  const [date, setDate] = useState(() => normalizeDate(initialDate));
  const [payload, setPayload] = useState<FeishuMonitorResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [latestResolved, setLatestResolved] = useState(() => !options?.preferLatest || hasExplicitInitialDate);

  useEffect(() => {
    if (hasExplicitInitialDate) {
      setDate(initialDate);
      setLatestResolved(true);
      return;
    }

    if (options?.preferLatest) {
      setLatestResolved(false);
    }
  }, [initialDate, hasExplicitInitialDate, options?.preferLatest]);

  useEffect(() => {
    let cancelled = false;

    async function loadFeishuMonitor() {
      setLoading(true);
      setError(null);

      try {
        const shouldLoadLatest = Boolean(options?.preferLatest) && !hasExplicitInitialDate && !latestResolved;
        const nextPayload = shouldLoadLatest
          ? await fetchLatestFeishuJin10MessageMonitor()
          : await fetchFeishuJin10MessageMonitor(date);
        if (!cancelled) {
          setPayload(nextPayload);
          if (shouldLoadLatest && isIsoDate(nextPayload.date)) {
            setDate(nextPayload.date);
          }
          if (shouldLoadLatest) {
            setLatestResolved(true);
          }
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("Feishu monitor 加载失败"));
          setPayload(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadFeishuMonitor();

    return () => {
      cancelled = true;
    };
  }, [date, reloadToken, options?.preferLatest, hasExplicitInitialDate, latestResolved]);

  return {
    date,
    payload,
    loading,
    error,
    resolvedDate: hasExplicitInitialDate || latestResolved,
    refresh: () => setReloadToken((value) => value + 1),
    reload: () => setReloadToken((value) => value + 1),
    setDate,
  };
}

export default useFeishuMonitor;
