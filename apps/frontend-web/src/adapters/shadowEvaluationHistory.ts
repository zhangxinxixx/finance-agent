import { ApiError, fetchJson } from "@/adapters/apiClient";
import type {
  ShadowEvaluationHistoryItem,
  ShadowEvaluationHistoryResponse,
  ShadowEvaluationLifecycleStatus,
  ShadowEvaluationOutcomeSummary,
} from "@/types/shadow-evaluation-history";
import type { ShadowEvaluationHorizon } from "@/types/shadow-evaluation";

const SHADOW_EVALUATION_HISTORY_PATH = "/api/shadow-evaluation/history";
const DEFAULT_ACCOUNT_ID = "codex-xauusd-shadow";
const DEFAULT_ASSET = "XAUUSD";
const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;
const HORIZONS: ShadowEvaluationHorizon[] = ["1h", "4h", "session", "24h"];
const STATUSES: ShadowEvaluationOutcomeSummary["status"][] = ["scored", "blocked", "unscorable"];
const CLASSIFICATIONS: ShadowEvaluationOutcomeSummary["classification"][] = ["correct", "incorrect", "neutral", "hold", "invalidated", "blocked", "unscorable"];
const LIFECYCLES: ShadowEvaluationLifecycleStatus[] = ["never_triggered", "invalidated_before_entry", "triggered", "triggered_then_invalidated", "target_reached", "same_bar_ambiguous", "insufficient_market_path", "insufficient_strategy_contract", "blocked"];

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

function asOptionalString(value: unknown, field: string, url: string): string | null {
  if (value === null || value === undefined) return null;
  return asString(value, field, url);
}

function asOptionalNumber(value: unknown, field: string, url: string): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) return fail(`${field} 必须是有限数值或 null`, url);
  return value;
}

function asEnum<T extends string>(value: unknown, allowed: readonly T[], field: string, url: string): T {
  const normalized = asString(value, field, url);
  if (!allowed.includes(normalized as T)) return fail(`${field} 不兼容`, url);
  return normalized as T;
}

function normalizeOutcome(value: unknown, index: number, field: string, url: string): ShadowEvaluationOutcomeSummary {
  const raw = asRecord(value, `${field}[${index}]`, url);
  const lifecycle = raw.lifecycle_status === null || raw.lifecycle_status === undefined
    ? null
    : asEnum(raw.lifecycle_status, LIFECYCLES, `${field}[${index}].lifecycle_status`, url);
  return {
    horizon: asEnum(raw.horizon, HORIZONS, `${field}[${index}].horizon`, url),
    status: asEnum(raw.status, STATUSES, `${field}[${index}].status`, url),
    classification: asEnum(raw.classification, CLASSIFICATIONS, `${field}[${index}].classification`, url),
    verification_status: asEnum(raw.verification_status, ["verified", "legacy_unverified"] as const, `${field}[${index}].verification_status`, url),
    lifecycle_status: lifecycle,
    setup_id: asOptionalString(raw.setup_id, `${field}[${index}].setup_id`, url),
    fill_price: asOptionalNumber(raw.fill_price, `${field}[${index}].fill_price`, url),
    fill_time: asOptionalString(raw.fill_time, `${field}[${index}].fill_time`, url),
    target_price: asOptionalNumber(raw.target_price, `${field}[${index}].target_price`, url),
    target_time: asOptionalString(raw.target_time, `${field}[${index}].target_time`, url),
    exit_price: asOptionalNumber(raw.exit_price, `${field}[${index}].exit_price`, url),
    exit_time: asOptionalString(raw.exit_time, `${field}[${index}].exit_time`, url),
    return_abs: asOptionalNumber(raw.return_abs, `${field}[${index}].return_abs`, url),
    return_pct: asOptionalNumber(raw.return_pct, `${field}[${index}].return_pct`, url),
    mfe: asOptionalNumber(raw.mfe, `${field}[${index}].mfe`, url),
    mae: asOptionalNumber(raw.mae, `${field}[${index}].mae`, url),
    reason_codes: raw.reason_codes === undefined ? [] : asStringArray(raw.reason_codes, `${field}[${index}].reason_codes`, url),
  };
}

function normalizeItem(value: unknown, index: number, url: string): ShadowEvaluationHistoryItem {
  const raw = asRecord(value, `items[${index}]`, url);
  if (typeof raw.publish_allowed !== "boolean") return fail(`items[${index}].publish_allowed 必须是布尔值`, url);
  return {
    trade_date: asString(raw.trade_date, `items[${index}].trade_date`, url),
    evaluation_id: asString(raw.evaluation_id, `items[${index}].evaluation_id`, url),
    strategy_status: asString(raw.strategy_status ?? raw.status, `items[${index}].strategy_status`, url),
    as_of: asOptionalString(raw.as_of, `items[${index}].as_of`, url),
    publish_allowed: raw.publish_allowed,
    outcome_count: asCount(raw.outcome_count, `items[${index}].outcome_count`, url),
    approved_count: asCount(raw.approved_count, `items[${index}].approved_count`, url),
    blocked_count: asCount(raw.blocked_count, `items[${index}].blocked_count`, url),
    unscorable_count: asCount(raw.unscorable_count, `items[${index}].unscorable_count`, url),
    legacy_unverified_count: asCount(raw.legacy_unverified_count, `items[${index}].legacy_unverified_count`, url),
    accuracy: asNullableAccuracy(raw.accuracy, `items[${index}].accuracy`, url),
    outcomes: raw.outcomes === undefined
      ? []
      : (Array.isArray(raw.outcomes)
          ? raw.outcomes.map((outcome, outcomeIndex) => normalizeOutcome(outcome, outcomeIndex, `items[${index}].outcomes`, url))
          : fail(`items[${index}].outcomes 必须是数组`, url)),
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
