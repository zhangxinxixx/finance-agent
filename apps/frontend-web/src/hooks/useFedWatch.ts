import { useEffect, useState } from "react";
import { fetchJson } from "@/adapters/apiClient";

export interface FedWatchMeeting {
  meeting_date: string;
  expected_rate_pct: number | null;
  expected_change_bp: number | null;
  cut_probability: number | null;
  hold_probability: number | null;
  hike_probability: number | null;
  prob_below_current_target?: number | null;
  prob_at_current_target?: number | null;
  prob_above_current_target?: number | null;
  comparisons: Record<string, { expected_rate_delta_bp: number | null }>;
  bins: { target_low: number; target_high: number; probability: number }[];
}
interface FedWatchView {
  snapshot_id: string | null;
  as_of: string | null;
  source_health: { status: string; reason?: string | null };
  next_meeting: FedWatchMeeting | null;
  year_end: FedWatchMeeting | null;
  repricing: { direction: string | null; strength: string | null };
  factor: { market_implied_path: { meetings: FedWatchMeeting[] } };
}

export function useFedWatch() {
  const [data, setData] = useState<FedWatchView | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const abort = new AbortController();
    async function load() {
      try {
        const value = await fetchJson<FedWatchView>("/api/market/fedwatch/latest", { signal: abort.signal });
        if (!abort.signal.aborted) { setData(value); setError(false); }
      } catch {
        if (!abort.signal.aborted) { setError(true); setData(null); }
      } finally { if (!abort.signal.aborted) setLoading(false); }
    }
    void load();
    const interval = window.setInterval(() => { void load(); }, 60_000);
    return () => { abort.abort(); window.clearInterval(interval); };
  }, []);
  return { data, error, loading };
}
