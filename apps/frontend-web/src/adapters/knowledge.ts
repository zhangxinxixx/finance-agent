import { ApiError, fetchJson } from "@/adapters/apiClient";
import type {
  KnowledgeItem,
  KnowledgeItemType,
  KnowledgeItemStatus,
  KnowledgeTypeTab,
  KnowledgeViewModel,
} from "@/types/knowledge";

const KNOWLEDGE_ITEMS_PATH = "/api/knowledge/items";

// Knowledge items are read from the API only; unavailable data must remain explicit.

const TOPIC_OPTIONS = ["全部主题", "黄金", "实际利率", "流动性", "地缘风险", "芝商所", "智能体规则"];
const STATUS_OPTIONS: Array<"全部状态" | KnowledgeItemStatus> = ["全部状态", "长期有效", "待复核", "阶段有效"];

const TOPIC_FILTER_ALIASES: Record<string, readonly string[]> = {
  "芝商所": ["芝商所", "CME"],
  "智能体规则": ["智能体规则", "Agent规则"],
};

export const KNOWLEDGE_TOPICS = TOPIC_OPTIONS;
export const KNOWLEDGE_STATUSES = STATUS_OPTIONS;

function computeStats(items: KnowledgeItem[]) {
  const reviewQueueCount = items.filter((item) => item.reviewQueued).length;
  const pinnedCount = items.filter((item) => item.pinned).length;
  const agentReadyCount = items.filter((item) => item.agentReady).length;
  const playbookCount = items.filter((item) => item.type === "playbook").length;
  const playbookCandidateCount = items.filter((item) => item.type !== "playbook" && typeof item.confidence === "number" && Number.isFinite(item.confidence) && item.confidence >= 80).length;
  const playbookPublishedCount = items.filter((item) => item.type === "playbook" && item.agentReady).length;
  const totalCitations = items.reduce((sum, item) => sum + item.citations, 0);

  return {
    total: items.length,
    agentReady: agentReadyCount,
    playbookCount,
    playbookCandidateCount,
    playbookPublishedCount,
    reviewQueueCount,
    pinnedCount,
    totalCitations,
  };
}

function computeTypeCounts(items: KnowledgeItem[]): Record<KnowledgeTypeTab, number> {
  const counts: Record<KnowledgeTypeTab, number> = {
    all: items.length,
    method: 0,
    playbook: 0,
    note: 0,
    review: 0,
    agent: 0,
    dict: 0,
  };

  for (const item of items) {
    counts[item.type] += 1;
  }

  return counts;
}

function filterKnowledgeItems(
  items: KnowledgeItem[],
  options?: {
    search?: string;
    topic?: string;
    status?: string;
    typeTab?: string;
  },
): KnowledgeItem[] {
  const { search = "", topic = "全部主题", status = "全部状态", typeTab = "all" } = options ?? {};
  const searchText = search.trim().toLowerCase();

  return items.filter((item) => {
    const matchesSearch =
      !searchText ||
      [item.title, item.summary, item.thesis, item.tags.join(" "), item.inputs.join(" ")]
        .join(" ")
        .toLowerCase()
        .includes(searchText);
    const topicValues = TOPIC_FILTER_ALIASES[topic] ?? [topic];
    const matchesTopic = topic === "全部主题" || topicValues.includes(item.topic) || topicValues.some((value) => item.tags.includes(value));
    const matchesStatus = status === "全部状态" || item.status === status;
    const matchesType = typeTab === "all" || item.type === typeTab;
    return matchesSearch && matchesTopic && matchesStatus && matchesType;
  });
}

function sortKnowledgeItems(items: KnowledgeItem[]): KnowledgeItem[] {
  return [...items].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    if (a.reviewQueued !== b.reviewQueued) return a.reviewQueued ? -1 : 1;
    return b.citations - a.citations;
  });
}

function readNumber(record: Record<string, unknown>, keys: string[], fallback: number): number {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return fallback;
}

function normalizeApiStats(rawStats: unknown, items: KnowledgeItem[]): KnowledgeViewModel["stats"] {
  const fallback = computeStats(items);
  if (!rawStats || typeof rawStats !== "object") {
    return fallback;
  }

  const record = rawStats as Record<string, unknown>;
  return {
    total: readNumber(record, ["total"], fallback.total),
    agentReady: readNumber(record, ["agentReady", "agent_ready"], fallback.agentReady),
    playbookCount: readNumber(record, ["playbookCount", "playbook_count"], fallback.playbookCount),
    playbookCandidateCount: readNumber(record, ["playbookCandidateCount", "playbook_candidate_count"], fallback.playbookCandidateCount),
    playbookPublishedCount: readNumber(record, ["playbookPublishedCount", "playbook_published_count"], fallback.playbookPublishedCount),
    reviewQueueCount: readNumber(record, ["reviewQueueCount", "review_queue_count"], fallback.reviewQueueCount),
    pinnedCount: readNumber(record, ["pinnedCount", "pinned_count"], fallback.pinnedCount),
    totalCitations: readNumber(record, ["totalCitations", "total_citations"], fallback.totalCitations),
  };
}

function isKnowledgeItem(value: unknown): value is KnowledgeItem {
  return Boolean(value && typeof value === "object" && typeof (value as KnowledgeItem).id === "string");
}

function normalizeApiStatus(status: unknown): KnowledgeViewModel["status"] {
  switch (status) {
    case "available":
    case "partial":
    case "unavailable":
    case "error":
      return status;
    case "ok":
    case "live":
      return "available";
    case "warn":
    case "fallback":
      return "partial";
    default:
      return "available";
  }
}

async function fetchKnowledgeItemDetail(itemId: string): Promise<KnowledgeItem | null> {
  let raw: unknown;
  try {
    raw = await fetchJson<unknown>(`${KNOWLEDGE_ITEMS_PATH}/${encodeURIComponent(itemId)}`);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) return null;
    throw new Error("知识条目详情暂时无法读取");
  }
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const record = raw as Record<string, unknown>;
  if (record.status === "unavailable") {
    return null;
  }

  const candidate = isKnowledgeItem(record.item) ? record.item : raw;
  return isKnowledgeItem(candidate) ? candidate : null;
}

function mergeSelectedItem(items: KnowledgeItem[], selectedItem: KnowledgeItem | null): KnowledgeItem[] {
  if (!selectedItem || items.some((item) => item.id === selectedItem.id)) {
    return items;
  }
  return [selectedItem, ...items];
}

export async function fetchKnowledgeView(options?: {
  search?: string;
  topic?: string;
  status?: string;
  typeTab?: string;
  selectedId?: string | null;
}): Promise<KnowledgeViewModel> {
  let raw: Record<string, unknown>;
  try {
    raw = await fetchJson<Record<string, unknown>>(KNOWLEDGE_ITEMS_PATH);
  } catch {
    throw new Error("知识库接口暂时无法连接");
  }
  const apiItems: KnowledgeItem[] = Array.isArray(raw.items) ? raw.items.filter(isKnowledgeItem) : [];
  const { selectedId = null } = options ?? {};
  let selectedItem = selectedId ? await fetchKnowledgeItemDetail(selectedId) : null;
  const selectedExistsInList = selectedId ? apiItems.some((item) => item.id === selectedId) : false;
  let effectiveId = selectedItem?.id ?? (selectedExistsInList ? selectedId : apiItems[0]?.id ?? null);

  selectedItem = selectedItem ?? (effectiveId ? apiItems.find((item) => item.id === effectiveId) ?? null : null);
  if (!selectedItem && effectiveId) {
    selectedItem = await fetchKnowledgeItemDetail(effectiveId);
  }
  const allItems = mergeSelectedItem(apiItems, selectedItem);
  const filteredItems = sortKnowledgeItems(filterKnowledgeItems(allItems, options));
  effectiveId = effectiveId && filteredItems.some((item) => item.id === effectiveId)
    ? effectiveId
    : filteredItems[0]?.id ?? null;

  if (!selectedItem || selectedItem.id !== effectiveId) {
    selectedItem = effectiveId ? await fetchKnowledgeItemDetail(effectiveId) : null;
  }
  selectedItem = selectedItem ?? (effectiveId ? filteredItems.find((item) => item.id === effectiveId) ?? null : null);

  const items = mergeSelectedItem(filteredItems, selectedItem);
  return {
    status: normalizeApiStatus(raw.status),
    source: "api",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null,
    items,
    selectedId: effectiveId,
    selectedItem,
    stats: normalizeApiStats(raw.stats, allItems),
    typeCounts: computeTypeCounts(allItems),
    has_data: allItems.length > 0,
    source_refs: Array.isArray(raw.source_refs) ? raw.source_refs : [],
  };
}

export function fetchAllKnowledgeItems(): Promise<KnowledgeItem[]> {
  return Promise.resolve([]);
}
