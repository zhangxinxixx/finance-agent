import { ApiError, fetchJson } from "@/adapters/apiClient";
import type {
  LiveStrategyAvailability,
  LiveStrategyDataQuality,
  LiveStrategyFeasibility,
  LiveStrategyFifteenMinuteConfirmation,
  LiveStrategyMarket,
  LiveStrategyMarketState,
  LiveStrategyNearestLevel,
  LiveStrategyNoTrade,
  LiveStrategyPriceEvent,
  LiveStrategyResponse,
  LiveStrategySetup,
  LiveStrategyStatus,
} from "@/types/live-strategy";

const LIVE_STRATEGY_LATEST_PATH = "/api/live-strategy/latest";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asBoolean(value: unknown): boolean {
  return value === true;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asNumberArray(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((item): item is number => typeof item === "number" && Number.isFinite(item)) : [];
}

function asEvidence(value: unknown): Array<string | Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  const evidence: Array<string | Record<string, unknown>> = [];
  value.forEach((item) => {
    if (typeof item === "string") {
      evidence.push(item);
      return;
    }
    const record = asRecord(item);
    if (Object.keys(record).length > 0) evidence.push(record);
  });
  return evidence;
}

function asAvailability(value: unknown): LiveStrategyAvailability {
  return value === "available" || value === "partial" || value === "unavailable" ? value : "unavailable";
}

function asStrategyStatus(value: unknown): LiveStrategyStatus {
  return value === "WAITING" || value === "WATCHING" || value === "ARMED" || value === "TRIGGERED" || value === "SUSPENDED_DATA"
    ? value
    : "SUSPENDED_DATA";
}

function normalizeLevel(value: unknown): LiveStrategyNearestLevel | null {
  const raw = asRecord(value);
  return Object.keys(raw).length > 0
    ? {
        role: asString(raw.role),
        value: asNumber(raw.value) ?? asNumber(raw.reference_price),
        distance: asNumber(raw.distance),
        distance_pct: asNumber(raw.distance_pct),
        strength: asNumber(raw.strength) ?? asString(raw.strength),
      }
    : null;
}

function asPriceEventType(value: unknown): LiveStrategyPriceEvent["event_type"] {
  return value === "approach" || value === "touch" || value === "intrabar_breach" || value === "accepted_break"
    || value === "failed_break" || value === "retest" || value === "reclaim"
    ? value
    : null;
}

function normalizePriceEvent(value: unknown): LiveStrategyPriceEvent | null {
  const raw = asRecord(value);
  if (Object.keys(raw).length === 0) return null;
  const confirmation = asRecord(raw.confirmation);
  return {
    event_type: asPriceEventType(raw.event_type),
    direction: raw.direction === "above" || raw.direction === "below" ? raw.direction : null,
    confirmed: asBoolean(raw.confirmed),
    detected_at: asString(raw.detected_at),
    price: asNumber(raw.price),
    related_level: normalizeLevel(raw.related_level),
    break_buffer: asNumber(raw.break_buffer),
    confirmation: {
      five_minute_closes: asNumberArray(confirmation.five_minute_closes),
      fifteen_minute_close: asNumber(confirmation.fifteen_minute_close),
    },
    evidence: asEvidence(raw.evidence),
    source_refs: Array.isArray(raw.source_refs) ? raw.source_refs as LiveStrategyPriceEvent["source_refs"] : [],
  };
}

function normalizeFifteenMinuteConfirmation(value: unknown): LiveStrategyFifteenMinuteConfirmation | null {
  const raw = asRecord(value);
  if (Object.keys(raw).length === 0) return null;
  return {
    confirmed: asBoolean(raw.confirmed),
    close: asNumber(raw.close),
    timestamp: asString(raw.timestamp),
  };
}

function asPriceRange(value: unknown): [number, number] | null {
  const values = asNumberArray(value);
  return values.length === 2 ? [values[0], values[1]] : null;
}

function normalizeSetup(value: unknown): LiveStrategySetup | null {
  const raw = asRecord(value);
  if (raw.direction !== "long" && raw.direction !== "short") return null;
  const gate = asRecord(raw.gate);
  const riskReward = asRecord(raw.risk_reward);
  const calculation = asRecord(raw.calculation);
  const statuses: LiveStrategySetup["status"][] = ["watching", "armed", "triggered", "blocked_data", "blocked_rr", "unavailable"];
  return {
    setup_id: asString(raw.setup_id),
    direction: raw.direction,
    status: statuses.includes(raw.status as LiveStrategySetup["status"]) ? raw.status as LiveStrategySetup["status"] : "unavailable",
    reference_level: normalizeLevel(raw.reference_level),
    entry_zone: asPriceRange(raw.entry_zone),
    trigger_conditions: asStringArray(raw.trigger_conditions),
    confirmation_conditions: asStringArray(raw.confirmation_conditions),
    invalidation_level: asNumber(raw.invalidation_level),
    stop_reference: asNumber(raw.stop_reference),
    volatility_buffer: asNumber(raw.volatility_buffer),
    spread_buffer: asNumber(raw.spread_buffer),
    targets: Array.isArray(raw.targets)
      ? raw.targets.map(asRecord).map((target) => ({
          label: asString(target.label),
          price: asNumber(target.price),
          source_role: asString(target.source_role),
        }))
      : [],
    risk_reward: {
      tp1: asNumber(riskReward.tp1),
      tp2: asNumber(riskReward.tp2),
      tp3: asNumber(riskReward.tp3),
    },
    gate: {
      passed: asBoolean(gate.passed),
      reasons: asStringArray(gate.reasons),
    },
    calculation: {
      ruleset: asString(calculation.ruleset),
      inputs: asRecord(calculation.inputs),
    },
  };
}

function normalizeNoTrade(value: unknown): LiveStrategyNoTrade {
  const raw = asRecord(value);
  return {
    range: asPriceRange(raw.range),
    reasons: asStringArray(raw.reasons),
    waiting_conditions: asStringArray(raw.waiting_conditions),
  };
}

function asTimestampRecord(value: unknown): Record<string, string | null> {
  return Object.fromEntries(
    Object.entries(asRecord(value)).map(([key, timestamp]) => [key, asString(timestamp)]),
  );
}

function asReasons(value: unknown): Record<string, string[]> {
  return Object.fromEntries(
    Object.entries(asRecord(value)).map(([key, reason]) => [key, asStringArray(reason)]),
  );
}

function normalizeLiveMarket(value: unknown): LiveStrategyMarket {
  const raw = asRecord(value);
  return {
    price: asNumber(raw.price),
    bid: asNumber(raw.bid),
    ask: asNumber(raw.ask),
    change_pct: asNumber(raw.change_pct),
    provider: asString(raw.provider),
    timestamps: asTimestampRecord(raw.timestamps),
    freshness_seconds: asNumber(raw.freshness_seconds),
    status: asString(raw.status),
    session: asString(raw.session),
  };
}

function normalizeMarketState(value: unknown): LiveStrategyMarketState {
  const raw = asRecord(value);
  return {
    gamma_regime: asString(raw.gamma_regime),
    nearest_level: normalizeLevel(raw.nearest_level),
    atr14: asNumber(raw.atr14),
    level_event: asString(raw.level_event),
    key_levels: Array.isArray(raw.key_levels) ? raw.key_levels.map(asRecord) : [],
    latest_price_event: normalizePriceEvent(raw.latest_price_event),
    confirmation_15m: normalizeFifteenMinuteConfirmation(raw.confirmation_15m),
    break_buffer: asNumber(raw.break_buffer),
    retest_threshold: asNumber(raw.retest_threshold),
  };
}

function normalizeFeasibility(value: unknown): LiveStrategyFeasibility {
  const raw = asRecord(value);
  return {
    data_ready: asBoolean(raw.data_ready),
    level_ready: asBoolean(raw.level_ready),
    trigger_ready: asBoolean(raw.trigger_ready),
    risk_ready: asBoolean(raw.risk_ready),
    rr_ready: asBoolean(raw.rr_ready),
    execution_ready: asBoolean(raw.execution_ready),
    reasons: asReasons(raw.reasons),
  };
}

function normalizeLiveStrategy(payload: unknown): LiveStrategyResponse {
  if (!payload || typeof payload !== "object") {
    throw new ApiError("Live strategy API 响应无效", { url: LIVE_STRATEGY_LATEST_PATH });
  }
  const raw = payload as Record<string, unknown>;
  if (raw.schema_version !== "live_strategy.v1") {
    throw new ApiError("Live strategy API schema 不兼容", { url: LIVE_STRATEGY_LATEST_PATH });
  }
  const baseline = asRecord(raw.baseline);
  const reason = asRecord(raw.update_reason);
  const quality = asRecord(raw.data_quality);

  return {
    schema_version: "live_strategy.v1",
    status: asAvailability(raw.status),
    strategy_id: asString(raw.strategy_id),
    baseline_strategy_id: asString(raw.baseline_strategy_id),
    strategy_version: asString(raw.strategy_version),
    asset: asString(raw.asset) ?? "XAUUSD",
    strategy_status: asStrategyStatus(raw.strategy_status),
    updated_at: asString(raw.updated_at),
    update_reason: {
      reason_code: asString(reason.reason_code),
      message: asString(reason.message),
      related_level: normalizeLevel(reason.related_level),
    },
    baseline: {
      strategy_card_id: asString(baseline.strategy_card_id),
      version: asString(baseline.version),
      bias: asString(baseline.bias),
      market_regime: asString(baseline.market_regime),
      confidence: asNumber(baseline.confidence),
    },
    live_market: normalizeLiveMarket(raw.live_market),
    market_state: normalizeMarketState(raw.market_state),
    active_scenario: raw.active_scenario === "long" || raw.active_scenario === "short" || raw.active_scenario === "no_trade"
      ? raw.active_scenario
      : null,
    setups: Array.isArray(raw.setups) ? raw.setups.map(normalizeSetup).filter((setup): setup is LiveStrategySetup => setup !== null) : [],
    no_trade: normalizeNoTrade(raw.no_trade),
    feasibility: normalizeFeasibility(raw.feasibility),
    source_refs: Array.isArray(raw.source_refs) ? raw.source_refs as LiveStrategyResponse["source_refs"] : [],
    artifact_refs: Array.isArray(raw.artifact_refs) ? raw.artifact_refs as LiveStrategyResponse["artifact_refs"] : [],
    data_quality: {
      ...quality,
      warnings: asStringArray(quality.warnings),
    } as LiveStrategyDataQuality,
  };
}

export async function fetchLiveStrategy(asset: "XAUUSD" = "XAUUSD"): Promise<LiveStrategyResponse> {
  const path = `${LIVE_STRATEGY_LATEST_PATH}?asset=${encodeURIComponent(asset)}`;
  const payload = await fetchJson<unknown>(path);
  return normalizeLiveStrategy(payload);
}
