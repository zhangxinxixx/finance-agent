import { useEffect, useState } from "react";
import { fetchJson } from "@/adapters/apiClient";
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
  isLoading: boolean;
  isError: boolean;
}

interface Jin10FlashApiResponse {
  items?: Jin10FlashApiItem[];
}

interface Jin10FlashApiItem {
  id?: string;
  time?: string;
  content?: string;
  title?: string;
  summary_zh?: string;
  url?: string;
  channel?: string[];
  is_key_event?: boolean;
  importance?: string;
  signal_tags?: string[];
  filter_reason?: string;
  classification_provider?: string;
  classification_model?: string;
  classification_confidence?: number;
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

function fromJin10FlashItem(item: Jin10FlashApiItem): EventFlowLiveFlashItem {
  return {
    id: item.id || item.time || item.content || item.title || "",
    time: item.time || "",
    content: item.content || item.title || "未命名当日重点事件",
    summary_zh: item.summary_zh || undefined,
    url: item.url || undefined,
    channel: item.channel || undefined,
    is_key_event: item.is_key_event ?? false,
    importance: item.importance,
    signal_tags: item.signal_tags || undefined,
    filter_reason: item.filter_reason || undefined,
    classification_provider: item.classification_provider || undefined,
    classification_model: item.classification_model || undefined,
    classification_confidence: item.classification_confidence,
  };
}

export function useEventFlowLiveFlash(limit = 10, pollIntervalMs = 60_000): UseEventFlowLiveFlashState {
  const [data, setData] = useState<EventFlowLiveFlashItem[]>([]);
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
        const items = triggerItems.length > 0
          ? triggerItems
          : ((await fetchJson<Jin10FlashApiResponse>(`/api/jin10/flash?limit=${limit}`)).items ?? [])
              .map(fromJin10FlashItem)
              .filter((item) => item.is_key_event);
        if (!cancelled) {
          setData(items);
          setIsError(false);
        }
      } catch {
        if (!cancelled) setIsError(true);
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

  return { data, isLoading, isError };
}
