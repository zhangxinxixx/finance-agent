import { useEffect, useState } from "react";
import { fetchJson } from "@/adapters/apiClient";

export interface Jin10CalendarEvent {
  title: string;
  pub_time: string;
  star: number;
  actual: string | null;
  consensus: string | null;
  previous: string | null;
  affect_txt: string;
  release_state?: "upcoming" | "released";
  event_date?: string | null;
  is_high_impact?: boolean;
}

export interface Jin10CalendarStats {
  total: number;
  upcoming: number;
  released: number;
  high_impact: number;
  earliest_event_date: string | null;
  latest_event_date: string | null;
  window_start_date?: string | null;
  window_end_date?: string | null;
}

export interface Jin10CalendarFreshness {
  is_stale: boolean;
  reason: string;
  cache_age_seconds: number | null;
}

interface Jin10CalendarResponse {
  generated_at?: string;
  events: Jin10CalendarEvent[];
  status?: string;
  stats?: Jin10CalendarStats;
  freshness?: Jin10CalendarFreshness;
}

interface Jin10CalendarState {
  data: Jin10CalendarEvent[];
  generatedAt: string | null;
  status: string;
  stats: Jin10CalendarStats | null;
  freshness: Jin10CalendarFreshness | null;
  isLoading: boolean;
  isError: boolean;
}

export function useJin10Calendar(): Jin10CalendarState {
  const [data, setData] = useState<Jin10CalendarEvent[]>([]);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [status, setStatus] = useState("loading");
  const [stats, setStats] = useState<Jin10CalendarStats | null>(null);
  const [freshness, setFreshness] = useState<Jin10CalendarFreshness | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const result = await fetchJson<Jin10CalendarResponse>("/api/jin10/calendar");
        if (!cancelled) {
          setData(result.events ?? []);
          setGeneratedAt(result.generated_at ?? null);
          setStatus(result.status ?? "ok");
          setStats(result.stats ?? null);
          setFreshness(result.freshness ?? null);
          setIsError(false);
        }
      } catch {
        if (!cancelled) {
          setIsError(true);
          setStatus("error");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();
    return () => { cancelled = true; };
  }, []);

  return { data, generatedAt, status, stats, freshness, isLoading, isError };
}
