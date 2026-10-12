import { useEffect, useState } from "react";
import { fetchEventFlowOverviewView } from "@/adapters/eventFlow";
import type { EventFlowProgressTrigger } from "@/types/event-flow";

export interface EventFlowLiveFlashItem {
  id: string;
  time: string;
  content: string;
  summary_zh?: string;
  url?: string;
  channel?: string[];
  is_key_event?: boolean;
  importance?: "high" | "medium" | "normal" | string;
  signal_tags?: string[];
  filter_reason?: string;
  classification_provider?: string;
  classification_model?: string;
  classification_confidence?: number;
}

interface UseEventFlowLiveFlashState {
  data: EventFlowLiveFlashItem[];
  status: "loading" | "event_flow" | "jin10" | "disabled" | "empty" | "error";
  isLoading: boolean;
  isError: boolean;
}

function priorityLabel(priority: string | null | undefined): string | undefined {
  const normalized = String(priority ?? "").trim().toLowerCase();
  if (normalized === "high" || normalized === "高") return "高";
  if (normalized === "medium" || normalized === "中") return "中";
  if (normalized === "normal" || normalized === "low" || normalized === "低") return "低";
  return undefined;
}

function toFlashItem(trigger: EventFlowProgressTrigger): EventFlowLiveFlashItem {
  const summary = trigger.evidence_text?.trim();
  const title = trigger.source_title?.trim() || "未命名当日重点事件";
  return {
    id: trigger.trigger_id,
    time: trigger.published_at || trigger.created_at || "",
    content: title,
    summary_zh: summary && summary !== title ? summary : undefined,
    url: trigger.source_url || undefined,
    channel: priorityLabel(trigger.priority) ? [`优先级 ${priorityLabel(trigger.priority)}`] : undefined,
    is_key_event: true,
    importance: trigger.priority,
    signal_tags: [...(trigger.asset_tags ?? []), ...(trigger.topic_tags ?? [])].slice(0, 3),
    filter_reason: summary || undefined,
  };
}

export function useEventFlowLiveFlash(limit = 10, pollIntervalMs = 60_000): UseEventFlowLiveFlashState {
  const [data, setData] = useState<EventFlowLiveFlashItem[]>([]);
  const [status, setStatus] = useState<UseEventFlowLiveFlashState["status"]>("loading");
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;

    async function load({ initial = false }: { initial?: boolean } = {}) {
      if (initial) {
        setIsLoading(true);
      }
      try {
        const result = await fetchEventFlowOverviewView();
        const triggerItems = (result.daily_analysis_triggers?.triggers ?? []).map(toFlashItem).slice(0, limit);
        const items = triggerItems;
        const nextStatus: UseEventFlowLiveFlashState["status"] = triggerItems.length > 0 ? "event_flow" : "empty";
        if (!cancelled) {
          setData(items);
          setStatus(nextStatus);
          setIsError(false);
        }
      } catch {
        if (!cancelled) {
          setStatus("error");
          setIsError(true);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void load({ initial: true });
    if (pollIntervalMs > 0) {
      timer = setInterval(() => {
        void load();
      }, pollIntervalMs);
    }
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [limit, pollIntervalMs]);

  return { data, status, isLoading, isError };
}
