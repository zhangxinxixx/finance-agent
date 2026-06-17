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
}

interface Jin10CalendarResponse {
  generated_at?: string;
  events: Jin10CalendarEvent[];
  status?: string;
}

interface Jin10CalendarState {
  data: Jin10CalendarEvent[];
  isLoading: boolean;
  isError: boolean;
}

export function useJin10Calendar(): Jin10CalendarState {
  const [data, setData] = useState<Jin10CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const result = await fetchJson<Jin10CalendarResponse>("/api/jin10/calendar");
        if (!cancelled) {
          setData(result.events ?? []);
          setIsError(false);
        }
      } catch {
        if (!cancelled) {
          setIsError(true);
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

  return { data, isLoading, isError };
}
