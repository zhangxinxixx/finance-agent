import { ApiError, fetchJson } from "@/adapters/apiClient";
import type {
  ShadowEvaluationHistoryItem,
  ShadowEvaluationHistoryResponse,
} from "@/types/shadow-evaluation-history";

const SHADOW_EVALUATION_HISTORY_PATH = "/api/shadow-evaluation/history";
const DEFAULT_ACCOUNT_ID = "codex-xauusd-shadow";
const DEFAULT_ASSET = "XAUUSD";
const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

function fail(message: string, url: string): never {
  throw new ApiError(`Shadow evaluation history API ${message}`, { url });
}
function asRecord(value: unknown, field: string, url: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return fail(`${field} 必须是对象`, url);
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown, field: string, url: string): string {
  if (typeof value !== "string" || !value.trim()) return fail(`${field} 必须是非空字符串`, url);
  return value;
}

function asCount(value: unknown, field: string, url: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return fail(`${field} 必须是非负整数`, url);
  }
  return value;
}

function asNullableAccuracy(value: unknown, field: string, url: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    return fail(`${field} 必须是 0 到 1 之间的有限数值或 null`, url);
  }
  return value;
}

function asStringArray(value: unknown, field: string, url: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item.trim())) {
    return fail(`${field} 必须是字符串数组`, url);
  }
  return [...value];
}

function normalizeItem(value: unknown, index: number, url: string): ShadowEvaluationHistoryItem {
  const raw = asRecord(value, `items[${index}]`, url);
  if (typeof raw.publish_allowed !== "boolean") return fail(`items[${index}].publish_allowed 必须是布尔值`, url);
  return {
    trade_date: asString(raw.trade_date, `items[${index}].trade_date`, url),
    evaluation_id: asString(raw.evaluation_id, `items[${index}].evaluation_id`, url),
    strategy_status: asString(raw.strategy_status ?? raw.status, `items[${index}].strategy_status`, url),
    publish_allowed: raw.publish_allowed,
    outcome_count: asCount(raw.outcome_count, `items[${index}].outcome_count`, url),
    approved_count: asCount(raw.approved_count, `items[${index}].approved_count`, url),
    blocked_count: asCount(raw.blocked_count, `items[${index}].blocked_count`, url),
    unscorable_count: asCount(raw.unscorable_count, `items[${index}].unscorable_count`, url),
    accuracy: asNullableAccuracy(raw.accuracy, `items[${index}].accuracy`, url),
    artifact_refs: asStringArray(raw.artifact_refs, `items[${index}].artifact_refs`, url),
  };
}

function normalizeResponse(value: unknown, url: string): ShadowEvaluationHistoryResponse {
  const raw = asRecord(value, "响应", url);
  if (raw.schema_version !== "shadow_evaluation_history.v1") return fail("schema 不兼容", url);
  if (!Array.isArray(raw.items)) return fail("items 必须是数组", url);
  if (typeof raw.truncated !== "boolean") return fail("truncated 必须是布尔值", url);
  return {
    schema_version: "shadow_evaluation_history.v1",
    account_id: asString(raw.account_id, "account_id", url),
    asset: asString(raw.asset, "asset", url),
    items: raw.items.map((item, index) => normalizeItem(item, index, url)),
    total: asCount(raw.total, "total", url),
    truncated: raw.truncated,
  };
}

export interface ShadowEvaluationHistoryQuery {
  accountId?: string;
  asset?: "XAUUSD";
  limit?: number;
}

export async function fetchShadowEvaluationHistory({
  accountId = DEFAULT_ACCOUNT_ID,
  asset = DEFAULT_ASSET,
  limit = DEFAULT_LIMIT,
}: ShadowEvaluationHistoryQuery = {}): Promise<ShadowEvaluationHistoryResponse> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    throw new Error(`history limit must be between 1 and ${MAX_LIMIT}`);
  }
  const search = new URLSearchParams({ account_id: accountId, asset, limit: String(limit) });
  const path = `${SHADOW_EVALUATION_HISTORY_PATH}?${search.toString()}`;
  return normalizeResponse(await fetchJson<unknown>(path), path);
}
