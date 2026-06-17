import { useCallback, useEffect, useState } from "react";
import { fetchSchedulerOverview } from "@/adapters/scheduler";
import type { SchedulerOverviewResponse } from "@/adapters/scheduler";
import { fetchDagsterRuns, fetchDagsterSchedules, mapDagsterStatus } from "@/adapters/dagster";

interface UseSchedulerState {
  data: SchedulerOverviewResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refresh: () => void;
}

// Build a SchedulerOverviewResponse-compatible object from Dagster data
async function fetchFromDagster(days: number): Promise<SchedulerOverviewResponse | null> {
  try {
    const [runs, schedules] = await Promise.all([
      fetchDagsterRuns("premarket_job", 100),
      fetchDagsterSchedules().catch(() => []),
    ]);

    if (runs.length === 0) return null;

    const cutoff = Date.now() - days * 86400_000;
    const recentRuns = runs.filter((r) => new Date(r.createdAt).getTime() >= cutoff);

    const successCount = recentRuns.filter((r) => r.status === "success").length;
    const failedCount = recentRuns.filter((r) => r.status === "failed").length;
    const runningCount = recentRuns.filter((r) => r.status === "running").length;
    const pendingCount = recentRuns.filter((r) => r.status === "pending" || r.status === "queued").length;

    const today = new Date().toISOString().slice(0, 10);
    const todayRuns = recentRuns.filter((r) => r.createdAt.slice(0, 10) === today);

    return {
      generated_at: new Date().toISOString(),
      period_days: days,
      summary: {
        total_runs: recentRuns.length,
        today_runs: todayRuns.length,
        success_count: successCount,
        failed_count: failedCount,
        running_count: runningCount,
        pending_count: pendingCount,
        data_sources_ok: 0,
        data_sources_total: 0,
        artifacts_today: 0,
      },
      task_runs: recentRuns.map((r) => ({
        run_id: r.runId,
        task_name: r.jobName,
        task_type: r.tags?.pipeline || r.jobName,
        category: r.tags?.pipeline || "premarket",
        status: r.status,
        current_stage: null,
        trade_date: r.tradeDate,
        started_at: r.startedAt,
        ended_at: r.endedAt,
        error_summary: null,
        progress: null,
        step_count: 0,
        snapshot_id: null,
      })),
      category_stats: {},
      daily_summary: [],
      data_source_status: { ok: 0, error: 0, not_connected: 0, total: 0 },
      cron_jobs: schedules.map((s) => ({
        job_id: s.name,
        name: s.name,
        schedule: { kind: "cron", expr: s.cronSchedule, display: s.cronSchedule },
        enabled: s.status === "RUNNING",
        last_run_at: s.lastRunAt,
        last_status: s.lastRunStatus ? mapDagsterStatus(s.lastRunStatus) : null,
        next_run_at: null,
      })),
      artifacts_summary: { today_count: 0, recent_outputs: [] },
    };
  } catch {
    return null;
  }
}

export function useSchedulerOverview(days: number = 7): UseSchedulerState {
  const [data, setData] = useState<SchedulerOverviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [token, setToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetch() {
      setIsLoading(true);
      setError(null);
      try {
        // Try Dagster first
        const dagsterData = await fetchFromDagster(days);
        if (cancelled) return;

        if (dagsterData) {
          setData(dagsterData);
        } else {
          // Fallback to legacy API
          const result = await fetchSchedulerOverview(days);
          if (!cancelled) setData(result);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载调度中心数据失败"));
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void fetch();
    return () => { cancelled = true; };
  }, [days, token]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refresh: () => setToken((t) => t + 1),
  };
}
