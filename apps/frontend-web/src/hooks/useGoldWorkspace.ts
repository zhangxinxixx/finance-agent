import { useCallback, useEffect, useRef, useState } from "react";
import { fetchGoldWorkspace } from "@/adapters/goldWorkspace";
import type { GoldWorkspace } from "@/types/gold-workspace";

export function useGoldWorkspace(enabled = true) {
  const [data, setData] = useState<GoldWorkspace | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<Error | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const refetch = useCallback(async () => {
    if (!enabled) return null;
    const requestId = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchGoldWorkspace();
      if (mounted.current && generation.current === requestId) setData(result);
      return result;
    } catch (cause) {
      if (mounted.current && generation.current === requestId) setError(cause instanceof Error ? cause : new Error("黄金工作台读取失败。"));
      return null;
    } finally { if (mounted.current && generation.current === requestId) setLoading(false); }
  }, [enabled]);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) { setLoading(false); return () => { mounted.current = false; generation.current++; }; }
    void refetch();
    const visible = () => { if (document.visibilityState === "visible") void refetch(); };
    const interval = window.setInterval(visible, 60_000);
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    return () => {
      mounted.current = false;
      generation.current++;
      window.clearInterval(interval);
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [enabled, refetch]);
  return { data, loading, error, refetch };
}
