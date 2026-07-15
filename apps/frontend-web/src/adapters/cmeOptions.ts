import { ApiError, fetchJson } from "@/adapters/apiClient";
import type {
  CMEOptionsAnalysis,
  CMEOptionsAnalysisAgentSummary,
  CMEOptionsCalibration,
  CMEOptionsDataSource,
  CMEOptionsDecisionKeyLevel,
  CMEOptionsDecisionMetric,
  CMEOptionsDecisionOIByExpiry,
  CMEOptionsDecisionResponse,
  CMEOptionsDecisionRoll,
  CMEOptionsDecisionSetup,
  CMEOptionsDecisionStatus,
  CMEOptionsDecisionStrategy,
  CMEOptionsExposure,
  CMEOptionsGEX,
  CMEOptionsGEXByExpiry,
  CMEOptionsGEXTopItem,
  CMEOptionsIVSkew,
  CMEOptionsMockFile,
  CMEOptionsParameters,
  CMEOptionsPendingReview,
  CMEOptionsResponse,
  CMEOptionsRollSignal,
  CMEOptionsSourceTraceItem,
  CMEOptionsSupportResistance,
  CMEOptionsWallScore,
} from "@/types/cme-options";

const CME_OPTIONS_MOCK_URL = new URL("../mocks/cme-options.json", import.meta.url);
const CME_OPTIONS_SNAPSHOT_PATH = "/api/options/snapshot";
const CME_OPTIONS_DATES_PATH = "/api/options/dates";
const CME_OPTIONS_DECISION_PATH = "/api/options/decision";

function sortDatesDesc(dates: string[]): string[] {
  return [...dates].sort((left, right) => right.localeCompare(left));
}

type RawCMEOptionsDataSource = {
  product?: unknown;
  status?: unknown;
  expiries?: unknown;
  row_count?: unknown;
  report_date?: unknown;
  source_url?: unknown;
  input_snapshot_ids?: unknown;
};

type RawCMEOptionsParameters = {
  f_value?: unknown;
  r_value?: unknown;
  r?: unknown;
  p0?: unknown;
  p0_source?: unknown;
  report_p0?: unknown;
  report_p0_source?: unknown;
  live_p0?: unknown;
  live_p0_source?: unknown;
  price_anchor_rule?: unknown;
  model?: unknown;
  used_real_gex?: unknown;
  netgex_scope?: unknown;
  analysis_range?: unknown;
};

type RawCMEOptionsWallScore = {
  strike?: unknown;
  wall_type?: unknown;
  side?: unknown;
  oi?: unknown;
  delta_oi?: unknown;
  oi_change?: unknown;
  wall_score?: unknown;
  pnt?: unknown;
};

type RawCMEOptionsLevelItem = {
  strike?: unknown;
  wall_score?: unknown;
  distance_pct?: unknown;
};

type RawCMEOptionsIntent = {
  type?: unknown;
  confidence?: unknown;
  score?: unknown;
  evidence?: unknown;
};

type RawCMEOptionsCalibration = {
  calculation_method?: unknown;
  calibration_warnings?: unknown;
  expiry_roll_signal?: unknown;
  oi_change_by_strike?: unknown;
  near_month_vs_next_month?: unknown;
  source_refs?: unknown;
  wall_score_delta_1d?: unknown;
  wall_score_delta_1w?: unknown;
  wall_map?: unknown;
};

type RawCMEOptionsGEX = {
  netgex_aggregate?: {
    net_gex?: unknown;
    net_gex_direction?: unknown;
    gamma_zero?: {
      price?: unknown;
      method?: unknown;
    };
  };
  by_expiry?: unknown;
};

type RawCMEOptionsSnapshot = {
  trade_date?: unknown;
  run_id?: unknown;
  snapshot_id?: unknown;
  data_source?: RawCMEOptionsDataSource;
  parameters?: RawCMEOptionsParameters;
  gex?: RawCMEOptionsGEX;
  wall_scores?: unknown;
  support_resistance?: {
    resistance?: unknown;
    support?: unknown;
  };
  intent?: RawCMEOptionsIntent;
  calibration?: RawCMEOptionsCalibration;
  source_trace?: unknown;
  has_data?: unknown;
  version?: unknown;
  analysis?: unknown;
  exposure?: unknown;
  roll_signals?: unknown;
  normalization?: unknown;
  data_quality?: unknown;
  audit?: unknown;
};

type RawCMEOptionsDatesResponse = {
  dates?: unknown;
};

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asDecisionStatus(value: unknown): CMEOptionsDecisionStatus {
  return value === "available" || value === "partial" || value === "unavailable" ? value : "unavailable";
}

function asMetric(value: unknown): CMEOptionsDecisionMetric {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    current: asNullableNumber(raw.current),
    previous: asNullableNumber(raw.previous),
    delta: asNullableNumber(raw.delta),
    pct_change: asNullableNumber(raw.pct_change),
  };
}

function asNumberRecord(value: unknown): Record<string, number> {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).filter((entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1])),
  );
}

function asNumberArray(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((item): item is number => typeof item === "number" && Number.isFinite(item)) : [];
}

function normalizeDecisionStrategy(value: unknown): CMEOptionsDecisionStrategy {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const setup = (item: unknown): CMEOptionsDecisionSetup | null => {
    if (!item || typeof item !== "object") return null;
    const setupRaw = item as Record<string, unknown>;
    return {
      triggers: asStringArray(setupRaw.triggers),
      targets: asNumberArray(setupRaw.targets),
      invalidation: asStringArray(setupRaw.invalidation),
    };
  };
  return {
    status: asDecisionStatus(raw.status),
    horizon: typeof raw.horizon === "string" ? raw.horizon : undefined,
    reason: typeof raw.reason === "string" ? raw.reason : undefined,
    regime: typeof raw.regime === "string" ? raw.regime : undefined,
    bias: typeof raw.bias === "string" ? raw.bias : undefined,
    summary: typeof raw.summary === "string" ? raw.summary : undefined,
    no_trade_zone: asNumberArray(raw.no_trade_zone),
    long_setup: setup(raw.long_setup),
    short_setup: setup(raw.short_setup),
    confirmation: asStringArray(raw.confirmation),
    invalidation: asStringArray(raw.invalidation),
    targets: asNumberArray(raw.targets),
    structure_bias: typeof raw.structure_bias === "string" ? raw.structure_bias : undefined,
    oi_trend: typeof raw.oi_trend === "string" ? raw.oi_trend : undefined,
    sample_count: typeof raw.sample_count === "number" ? raw.sample_count : undefined,
    required_sample_count: typeof raw.required_sample_count === "number" ? raw.required_sample_count : undefined,
    sample_window: raw.sample_window && typeof raw.sample_window === "object"
      ? {
          from: asString((raw.sample_window as Record<string, unknown>).from),
          to: asString((raw.sample_window as Record<string, unknown>).to),
        }
      : null,
    call_oi_change: asNullableNumber(raw.call_oi_change),
    put_oi_change: asNullableNumber(raw.put_oi_change),
    confidence: asNullableNumber(raw.confidence),
    risk_notes: asStringArray(raw.risk_notes),
  };
}

function normalizeDecisionKeyLevels(value: unknown): CMEOptionsDecisionKeyLevel[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const raw = item && typeof item === "object" ? item as Record<string, unknown> : {};
    const bandRaw = raw.band && typeof raw.band === "object" ? raw.band as Record<string, unknown> : null;
    return {
      strike: asNullableNumber(raw.strike),
      band: bandRaw && asNullableNumber(bandRaw.lower) !== null && asNullableNumber(bandRaw.upper) !== null
        ? { lower: asNumber(bandRaw.lower), upper: asNumber(bandRaw.upper), step: asNullableNumber(bandRaw.step) }
        : null,
      role: asString(raw.role, "unavailable"),
      strength: typeof raw.strength === "string" ? raw.strength : asNullableNumber(raw.strength),
      trend: typeof raw.trend === "string" ? raw.trend : null,
      evidence: asStringArray(raw.evidence),
      invalidation: asStringArray(raw.invalidation),
      expiry_scope: asString(raw.expiry_scope, "aggregate"),
      distance_pct: asNullableNumber(raw.distance_pct),
    };
  });
}

function buildDecisionPath(date?: string): string {
  return date ? `${CME_OPTIONS_DECISION_PATH}?date=${encodeURIComponent(date)}` : CME_OPTIONS_DECISION_PATH;
}

function normalizeDecisionResponse(payload: unknown): CMEOptionsDecisionResponse {
  if (!payload || typeof payload !== "object") {
    throw new ApiError("CME Options decision API 响应无效", { url: CME_OPTIONS_DECISION_PATH });
  }
  const raw = payload as Record<string, unknown>;
  if (raw.schema_version !== "cme_options_decision.v1") {
    throw new ApiError("CME Options decision API schema 不兼容", { url: CME_OPTIONS_DECISION_PATH });
  }
  const meta = raw.meta && typeof raw.meta === "object" ? raw.meta as Record<string, unknown> : {};
  const executive = raw.executive_summary && typeof raw.executive_summary === "object" ? raw.executive_summary as Record<string, unknown> : {};
  const prices = raw.price_context && typeof raw.price_context === "object" ? raw.price_context as Record<string, unknown> : {};
  const oi = raw.oi_summary && typeof raw.oi_summary === "object" ? raw.oi_summary as Record<string, unknown> : {};
  const gamma = raw.gamma_summary && typeof raw.gamma_summary === "object" ? raw.gamma_summary as Record<string, unknown> : {};
  const band = gamma.flip_band && typeof gamma.flip_band === "object" ? gamma.flip_band as Record<string, unknown> : null;
  const profile = raw.gamma_profile && typeof raw.gamma_profile === "object" ? raw.gamma_profile as Record<string, unknown> : {};
  const roll = raw.roll_summary && typeof raw.roll_summary === "object" ? raw.roll_summary as Record<string, unknown> : {};
  const quality = raw.data_quality && typeof raw.data_quality === "object" ? raw.data_quality as Record<string, unknown> : {};
  const oiByExpiry: CMEOptionsDecisionOIByExpiry[] = Array.isArray(raw.oi_by_expiry) ? raw.oi_by_expiry.map((item) => {
    const entry = item && typeof item === "object" ? item as Record<string, unknown> : {};
    return {
      expiry: asString(entry.expiry, "—"),
      expiry_scope: asString(entry.expiry_scope, "contract_expiry"),
      comparison_status: entry.comparison_status === "available" ? "available" : "unavailable",
      total: asMetric(entry.total), call: asMetric(entry.call), put: asMetric(entry.put),
    };
  }) : [];
  const rolls: CMEOptionsDecisionRoll[] = Array.isArray(roll.items) ? roll.items.map((item) => {
    const entry = item && typeof item === "object" ? item as Record<string, unknown> : {};
    return {
      near_expiry: asString(entry.near_expiry, "—"), far_expiry: asString(entry.far_expiry, "—"),
      near_oi_delta: asNullableNumber(entry.near_oi_delta), far_oi_delta: asNullableNumber(entry.far_oi_delta),
      far_put_delta: asNullableNumber(entry.far_put_delta), far_call_delta: asNullableNumber(entry.far_call_delta), labels: asStringArray(entry.labels),
    };
  }) : [];
  return {
    schema_version: "cme_options_decision.v1", status: asDecisionStatus(raw.status),
    meta: { current_trade_date: typeof meta.current_trade_date === "string" ? meta.current_trade_date : null, previous_trade_date: typeof meta.previous_trade_date === "string" ? meta.previous_trade_date : null, product: asString(meta.product), lookback_days: asNumber(meta.lookback_days), comparison_status: meta.comparison_status === "available" ? "available" : "unavailable" },
    executive_summary: { oi_delta: asNullableNumber(executive.oi_delta), gamma_regime: asString(executive.gamma_regime, "unavailable"), roll_status: asDecisionStatus(executive.roll_status), intraday_status: asDecisionStatus(executive.intraday_status) },
    price_context: { report_p0: asNullableNumber(prices.report_p0), report_p0_source: typeof prices.report_p0_source === "string" ? prices.report_p0_source : null, report_p0_timestamp: typeof prices.report_p0_timestamp === "string" ? prices.report_p0_timestamp : null, live_p0: asNullableNumber(prices.live_p0), live_p0_source: typeof prices.live_p0_source === "string" ? prices.live_p0_source : null, live_p0_timestamp: typeof prices.live_p0_timestamp === "string" ? prices.live_p0_timestamp : null, model_f: asNumberRecord(prices.model_f), price_anchor_rule: typeof prices.price_anchor_rule === "string" ? prices.price_anchor_rule : null },
    oi_summary: { comparison_status: oi.comparison_status === "available" ? "available" : "unavailable", total: asMetric(oi.total), call: asMetric(oi.call), put: asMetric(oi.put) },
    oi_by_expiry: oiByExpiry,
    gamma_summary: { regime: asString(gamma.regime, "unavailable"), net_gex: asNullableNumber(gamma.net_gex), gamma_zero: asNullableNumber(gamma.gamma_zero), method: typeof gamma.method === "string" ? gamma.method : null, flip_band: band && asNullableNumber(band.lower) !== null && asNullableNumber(band.upper) !== null && asNullableNumber(band.step) !== null ? { lower: asNumber(band.lower), upper: asNumber(band.upper), step: asNumber(band.step) } : null, live_price: asNullableNumber(gamma.live_price) },
    gamma_profile: { price_grid: asNumberArray(profile.price_grid), net_gex_values: asNumberArray(profile.net_gex_values), scope: asString(profile.scope, "aggregate_across_expiries") },
    key_levels: normalizeDecisionKeyLevels(raw.key_levels),
    roll_summary: { status: asDecisionStatus(roll.status), reason: typeof roll.reason === "string" ? roll.reason : undefined, items: rolls },
    intraday_strategy: normalizeDecisionStrategy(raw.intraday_strategy), swing_strategy: normalizeDecisionStrategy(raw.swing_strategy),
    data_quality: {
      ...quality,
      cme_status: typeof quality.cme_status === "string"
        ? quality.cme_status
        : Array.isArray(quality.cme_status)
          ? asStringArray(quality.cme_status)
          : null,
      warnings: asStringArray(quality.warnings),
    },
  };
}

function normalizeDataSourceStatus(status: unknown): "FINAL" | "PRELIM" {
  return status === "FINAL" ? "FINAL" : "PRELIM";
}

function normalizeWallType(value: unknown, side?: unknown): CMEOptionsWallScore["wall_type"] {
  if (value === "Call Wall" || value === "Put Wall" || value === "Balanced Wall") {
    return value;
  }

  const mapping: Record<string, CMEOptionsWallScore["wall_type"]> = {
    "pin": "Pin Wall",
    "active": "Active Wall",
    "static": "Static Wall",
    "turnover": "Turnover Wall",
    "new": "New Wall",
    "resistance": "Resistance Wall",
    "support": "Support Wall",
    "Pin Wall": "Pin Wall",
    "Active Wall": "Active Wall",
    "Static Wall": "Static Wall",
    "Turnover Wall": "Turnover Wall",
    "New Wall": "New Wall",
    "Resistance Wall": "Resistance Wall",
    "Support Wall": "Support Wall",
  };

  if (typeof value === "string" && value in mapping) {
    const mapped = mapping[value];
    if (value === "active" || value === "Active Wall") {
      if (side === "CALL") return "Call Wall";
      if (side === "PUT") return "Put Wall";
    }
    return mapped;
  }

  if (side === "CALL") return "Call Wall";
  if (side === "PUT") return "Put Wall";
  return "Balanced Wall";
}

function normalizeNetGEXDirection(value: unknown): "positive" | "negative" | "neutral" | null {
  return value === "positive" || value === "negative" || value === "neutral" ? value : null;
}

function normalizeSourceTraceItem(value: unknown): CMEOptionsSourceTraceItem | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const item = value as Record<string, unknown>;
  const status = item.status;
  const normalizedStatus =
    status === "ok" || status === "warn" || status === "error" || status === "unavailable" || status === "info"
      ? status
      : "info";

  return {
    name: asString(item.name),
    trade_date: asString(item.trade_date),
    file: asString(item.file),
    snapshot_id: typeof item.snapshot_id === "string" ? item.snapshot_id : null,
    source_ref: asString(item.source_ref),
    status: normalizedStatus,
    endpoint: typeof item.endpoint === "string" ? item.endpoint : null,
    latest_raw_time: typeof item.latest_raw_time === "string" ? item.latest_raw_time : null,
    latest_parsed_time: typeof item.latest_parsed_time === "string" ? item.latest_parsed_time : null,
    model_version: typeof item.model_version === "string" ? item.model_version : null,
  };
}

function normalizeSourceTrace(value: unknown): CMEOptionsSourceTraceItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => normalizeSourceTraceItem(item))
    .filter((item): item is CMEOptionsSourceTraceItem => item !== null);
}

function normalizeClaimReviews(value: unknown): CMEOptionsAnalysisAgentSummary["claim_reviews"] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const raw = item as Record<string, unknown>;
      return {
        claim_id: asString(raw.claim_id),
        verdict: asString(raw.verdict),
        reason: asString(raw.reason),
      };
    })
    .filter((item): item is CMEOptionsAnalysisAgentSummary["claim_reviews"][number] => item !== null && Boolean(item.claim_id));
}

function normalizeAnalysisAgent(value: unknown): CMEOptionsAnalysisAgentSummary | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const raw = value as Record<string, unknown>;
  const warnings = Array.isArray(raw.warnings)
    ? raw.warnings
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const warning = item as Record<string, unknown>;
        return {
          code: asString(warning.code),
          message: asString(warning.message),
        };
      })
      .filter((item): item is { code: string; message: string } => item !== null && Boolean(item.code || item.message))
    : [];

  return {
    agent_output_id: asString(raw.agent_output_id),
    agent_name: asString(raw.agent_name),
    display_name: asString(raw.display_name, asString(raw.agent_name)),
    status: asString(raw.status),
    bias: asString(raw.bias, "neutral"),
    confidence: asNumber(raw.confidence),
    summary: asString(raw.summary_zh, asString(raw.summary)),
    fact_review_status: typeof raw.fact_review_status === "string" ? raw.fact_review_status : null,
    synthesis_status: typeof raw.synthesis_status === "string" ? raw.synthesis_status : null,
    key_findings: asStringArray(raw.key_findings),
    risk_points: asStringArray(raw.risk_points),
    watchlist: asStringArray(raw.watchlist),
    invalid_conditions: asStringArray(raw.invalid_conditions),
    claim_count: asNumber(raw.claim_count),
    claim_reviews: normalizeClaimReviews(raw.claim_reviews),
    warning_count: typeof raw.warning_count === "number" ? raw.warning_count : undefined,
    warnings,
    reading_order: asStringArray(raw.reading_order),
    consensus_points: asStringArray(raw.consensus_points),
    divergent_points: asStringArray(raw.divergent_points),
    excluded_claim_ids: asStringArray(raw.excluded_claim_ids),
    review_item_ids: asStringArray(raw.review_item_ids),
  };
}

function normalizePendingReviews(value: unknown): CMEOptionsPendingReview[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const raw = item as Record<string, unknown>;
      return {
        review_id: asString(raw.review_id),
        claim_id: typeof raw.claim_id === "string" ? raw.claim_id : null,
        source_module: asString(raw.source_module),
        severity: asString(raw.severity, "warning"),
        reason: asString(raw.reason),
        suggested_action: typeof raw.suggested_action === "string" ? raw.suggested_action : null,
      };
    })
    .filter((item): item is CMEOptionsPendingReview => item !== null && Boolean(item.review_id));
}

function normalizeAnalysis(value: unknown): CMEOptionsAnalysis | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const raw = value as Record<string, unknown>;
  return {
    snapshot_id: typeof raw.snapshot_id === "string" ? raw.snapshot_id : null,
    run_id: typeof raw.run_id === "string" ? raw.run_id : null,
    fact_review_status: typeof raw.fact_review_status === "string" ? raw.fact_review_status : null,
    cme_options_agent: normalizeAnalysisAgent(raw.cme_options_agent),
    fact_review: normalizeAnalysisAgent(raw.fact_review),
    synthesis: normalizeAnalysisAgent(raw.synthesis),
    pending_review_count: asNumber(raw.pending_review_count),
    pending_reviews: normalizePendingReviews(raw.pending_reviews),
  };
}

function normalizeSupportResistance(value: RawCMEOptionsSnapshot["support_resistance"]): CMEOptionsSupportResistance {
  const normalizeLevels = (levels: unknown) => {
    if (!Array.isArray(levels)) {
      return [];
    }

    return levels.map((level) => {
      const entry = (level ?? {}) as RawCMEOptionsLevelItem;
      return {
        strike: asNumber(entry.strike),
        wall_score: asNumber(entry.wall_score),
        distance_pct: asNumber(entry.distance_pct),
      };
    });
  };

  return {
    resistance: normalizeLevels(value?.resistance),
    support: normalizeLevels(value?.support),
  };
}

function normalizeNumberMap(value: unknown): Record<string, number> | null {
  if (!value || typeof value !== "object") return null;
  const map: Record<string, number> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (typeof v === "number" && Number.isFinite(v)) map[k] = v;
  }
  return Object.keys(map).length > 0 ? map : null;
}

function normalizeIVSkew(value: unknown): CMEOptionsIVSkew {
  if (!value || typeof value !== "object") return {};
  const r = value as Record<string, unknown>;
  return {
    atm_iv: typeof r.atm_iv === "number" ? r.atm_iv : null,
    call_25d_iv: typeof r.call_25d_iv === "number" ? r.call_25d_iv : null,
    put_25d_iv: typeof r.put_25d_iv === "number" ? r.put_25d_iv : null,
    skew_25d: typeof r.skew_25d === "number" ? r.skew_25d : null,
    call_10d_iv: typeof r.call_10d_iv === "number" ? r.call_10d_iv : null,
    put_10d_iv: typeof r.put_10d_iv === "number" ? r.put_10d_iv : null,
    skew_10d: typeof r.skew_10d === "number" ? r.skew_10d : null,
    tail_skew_10d: typeof r.tail_skew_10d === "number" ? r.tail_skew_10d : null,
    interpretation: typeof r.interpretation === "string" ? r.interpretation : null,
  };
}

function normalizeGEXTopItems(value: unknown): CMEOptionsGEXTopItem[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const r = (item ?? {}) as Record<string, unknown>;
    return {
      strike: asNumber(r.strike),
      call_gex: asNumber(r.call_gex),
      put_gex: asNumber(r.put_gex),
      net_gex: asNumber(r.net_gex),
      total_gex: asNumber(r.total_gex),
    };
  });
}

function normalizeGEXByExpiry(value: unknown): Record<string, CMEOptionsGEXByExpiry> {
  if (!value || typeof value !== "object") return {};
  const result: Record<string, CMEOptionsGEXByExpiry> = {};
  for (const [expiry, data] of Object.entries(value as Record<string, unknown>)) {
    if (!data || typeof data !== "object") continue;
    const r = data as Record<string, unknown>;
    const summary = r.summary && typeof r.summary === "object" ? r.summary as Record<string, unknown> : r;
    result[expiry] = {
      gex_top: normalizeGEXTopItems(r.gex_top),
      summary: {
        forward_price: typeof summary.forward_price === "number" ? summary.forward_price : (typeof summary.f_value === "number" ? summary.f_value : null),
        f_value: typeof summary.f_value === "number" ? summary.f_value : null,
        gamma_zero: typeof summary.gamma_zero === "number" ? summary.gamma_zero : null,
        gamma_zero_method: typeof summary.gamma_zero_method === "string" ? summary.gamma_zero_method : null,
        net_gex: typeof summary.net_gex === "number" ? summary.net_gex : null,
        call_gex: typeof summary.call_gex === "number" ? summary.call_gex : null,
        put_gex: typeof summary.put_gex === "number" ? summary.put_gex : null,
        total_gex: typeof summary.total_gex === "number" ? summary.total_gex : null,
        atm_iv: typeof summary.atm_iv === "number" ? summary.atm_iv : null,
        time_to_expiry: typeof summary.time_to_expiry === "number" ? summary.time_to_expiry : null,
        structure: typeof summary.structure === "string" ? summary.structure : null,
      },
      iv_skew: normalizeIVSkew(r.iv_skew),
    };
  }
  return result;
}

function normalizeExposure(value: unknown): CMEOptionsExposure | null {
  if (!value || typeof value !== "object") return null;
  const result: CMEOptionsExposure = {};
  for (const [expiry, data] of Object.entries(value as Record<string, unknown>)) {
    if (!data || typeof data !== "object") continue;
    const r = data as Record<string, unknown>;
    const vexTop = Array.isArray(r.vex_top) ? (r.vex_top as Array<Record<string,unknown>>).reduce((s: number, v) => s + (typeof v.vex === "number" ? v.vex : 0), 0) : 0;
    const thetaTop = Array.isArray(r.theta_top) ? (r.theta_top as Array<Record<string,unknown>>).reduce((s: number, v) => s + (typeof v.theta === "number" ? v.theta : 0), 0) : 0;
    result[expiry] = {
      net_delta_exposure: typeof r.net_dex === "number" ? r.net_dex : null,
      total_vega: vexTop > 0 ? vexTop : null,
      total_theta: thetaTop > 0 ? thetaTop : null,
      call_delta_exposure: null,
      put_delta_exposure: null,
    };
  }
  return Object.keys(result).length > 0 ? result : null;
}

function normalizeRollSignals(value: unknown): CMEOptionsRollSignal[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const r = (item ?? {}) as Record<string, unknown>;
    return {
      roll_type: typeof r.roll_type === "string" ? r.roll_type : null,
      near_expiry: asString(r.near_expiry),
      far_expiry: asString(r.far_expiry),
      evidence: asStringArray(r.evidence),
      confidence: asNumber(r.confidence),
    };
  });
}

function normalizeParameters(value: unknown): CMEOptionsParameters {
  if (!value || typeof value !== "object") return {};
  const r = value as Record<string, unknown>;
  const analysisRange = r.analysis_range && typeof r.analysis_range === "object"
    ? r.analysis_range as Record<string, unknown>
    : null;
  return {
    f_value: typeof r.f_value === "number" ? r.f_value : null,
    r_value: typeof r.r_value === "number" ? r.r_value : (typeof r.r === "number" ? r.r : null),
    p0: typeof r.p0 === "number" ? r.p0 : (typeof r.report_p0 === "number" ? r.report_p0 : null),
    p0_source: typeof r.p0_source === "string" ? r.p0_source : (typeof r.report_p0_source === "string" ? r.report_p0_source : null),
    report_p0: typeof r.report_p0 === "number" ? r.report_p0 : null,
    report_p0_source: typeof r.report_p0_source === "string" ? r.report_p0_source : null,
    live_p0: typeof r.live_p0 === "number" ? r.live_p0 : null,
    live_p0_source: typeof r.live_p0_source === "string" ? r.live_p0_source : null,
    price_anchor_rule: typeof r.price_anchor_rule === "string" ? r.price_anchor_rule : null,
    model: typeof r.model === "string" ? r.model : null,
    used_real_gex: typeof r.used_real_gex === "boolean" ? r.used_real_gex : null,
    netgex_scope: typeof r.netgex_scope === "string" ? r.netgex_scope : null,
    analysis_range: analysisRange
      ? {
          strike_min: typeof analysisRange.strike_min === "number" ? analysisRange.strike_min : null,
          strike_max: typeof analysisRange.strike_max === "number" ? analysisRange.strike_max : null,
          source: typeof analysisRange.source === "string" ? analysisRange.source : null,
        }
      : null,
  };
}

function normalizeCalibration(value: RawCMEOptionsCalibration | undefined): CMEOptionsCalibration {
  if (!value) return {};
  return {
    calculation_method: typeof value.calculation_method === "string" ? value.calculation_method : null,
    wall_map: typeof value.wall_map === "object" && value.wall_map ? (value.wall_map as Record<string, unknown>) : null,
    wall_score_delta_1d: normalizeNumberMap(value.wall_score_delta_1d),
    wall_score_delta_1w: normalizeNumberMap(value.wall_score_delta_1w),
    oi_change_by_strike: typeof value.oi_change_by_strike === "object" ? (value.oi_change_by_strike as Record<string, number[]>) : null,
    expiry_roll_signal: normalizeRollSignals(value.expiry_roll_signal),
    near_month_vs_next_month: value.near_month_vs_next_month && typeof value.near_month_vs_next_month === "object"
      ? {
          near_total_oi: typeof (value.near_month_vs_next_month as Record<string,unknown>).near_total_oi === "number" ? (value.near_month_vs_next_month as Record<string,unknown>).near_total_oi as number : null,
          near_total_volume: null,
          next_total_oi: typeof (value.near_month_vs_next_month as Record<string,unknown>).next_total_oi === "number" ? (value.near_month_vs_next_month as Record<string,unknown>).next_total_oi as number : null,
          next_total_volume: null,
          oi_ratio: null,
          volume_ratio: null,
        }
      : null,
    calibration_warnings: Array.isArray(value.calibration_warnings) ? value.calibration_warnings.filter((item): item is string => typeof item === "string") : [],
    source_refs: Array.isArray(value.source_refs) ? value.source_refs.filter((item): item is string => typeof item === "string") : [],
  };
}

function normalizeWallScores(value: unknown): CMEOptionsWallScore[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.map((item) => {
    const wall = (item ?? {}) as RawCMEOptionsWallScore;
    return {
      strike: asNumber(wall.strike),
      wall_type: normalizeWallType(wall.wall_type, wall.side),
      side: wall.side === "CALL" || wall.side === "PUT" ? wall.side : null,
      oi: asNumber(wall.oi),
      delta_oi:
        typeof wall.oi_change === "number" && Number.isFinite(wall.oi_change)
          ? wall.oi_change
          : typeof wall.delta_oi === "number" && Number.isFinite(wall.delta_oi)
            ? wall.delta_oi
            : null,
      wall_score: asNumber(wall.wall_score),
      pnt: asNumber(wall.pnt),
    };
  });
}

function normalizeDataSource(value: RawCMEOptionsDataSource | undefined): CMEOptionsDataSource {
  return {
    product: asString(value?.product),
    status: normalizeDataSourceStatus(value?.status),
    expiries: asStringArray(value?.expiries),
    row_count: asNumber(value?.row_count),
    report_date: typeof value?.report_date === "string" ? value.report_date : null,
    source_url: typeof value?.source_url === "string" ? value.source_url : null,
    input_snapshot_ids: asStringArray(value?.input_snapshot_ids),
  };
}

function buildFallbackSourceTrace(payload: RawCMEOptionsSnapshot, date?: string): CMEOptionsSourceTraceItem[] {
  const dataSource = payload.data_source;
  const sourceUrl = typeof dataSource?.source_url === "string" ? dataSource.source_url : "";
  const inputSnapshotIds = asStringArray(dataSource?.input_snapshot_ids);

  if (!sourceUrl && inputSnapshotIds.length === 0) {
    return [];
  }

  return [
    {
      name: asString(dataSource?.product, "CME Options"),
      trade_date: asString(payload.trade_date, date ?? ""),
      file: sourceUrl,
      snapshot_id: inputSnapshotIds[0] ?? null,
      source_ref: sourceUrl || `${CME_OPTIONS_SNAPSHOT_PATH}#${date ?? "latest"}`,
      status: "info",
      endpoint: buildSnapshotPath(date),
      latest_raw_time: null,
      latest_parsed_time: null,
      model_version: typeof payload.version === "string" ? payload.version : null,
    },
  ];
}

function createUnavailableResponse(reason: string): CMEOptionsResponse {
  return {
    trade_date: "unavailable",
    data_source: {
      product: "",
      status: "PRELIM",
      expiries: [],
      row_count: 0,
    },
    parameters: {
      f_value: 0,
      r_value: 0,
    },
    gex: {
      netgex_aggregate: {
        net_gex: null,
        net_gex_direction: null,
        gamma_zero: {
          price: 0,
          method: "",
        },
      },
      by_expiry: {},
    },
    wall_scores: [],
    support_resistance: { resistance: [], support: [] },
    intent: { type: "neutral", confidence: 0 },
    calibration: {},
    source_trace: [],
    has_data: false,
    source: "unavailable",
    error_reason: reason,
    run_id: null,
    snapshot_id: null,
    analysis: null,
  };
}

export async function fetchCMEOptionsDates(): Promise<string[]> {
  try {
    const payload = await fetchJson<RawCMEOptionsDatesResponse>(CME_OPTIONS_DATES_PATH);
    return sortDatesDesc(asStringArray(payload.dates));
  } catch {
    return [];
  }
}

async function loadMockCMEOptions(): Promise<CMEOptionsResponse> {
  const response = await fetch(CME_OPTIONS_MOCK_URL);

  if (!response.ok) {
    throw new Error(`加载 CME Options mock 失败：${response.status}`);
  }

  const payload = (await response.json()) as CMEOptionsMockFile;

  return {
    ...payload,
    has_data: payload.has_data ?? payload.wall_scores.length > 0,
    source: "mock",
  };
}

function buildSnapshotPath(date?: string): string {
  if (!date) {
    return CME_OPTIONS_SNAPSHOT_PATH;
  }

  return `${CME_OPTIONS_SNAPSHOT_PATH}?date=${encodeURIComponent(date)}`;
}

function normalizeApiSnapshot(payload: RawCMEOptionsSnapshot, date?: string): CMEOptionsResponse {
  const wallScores = normalizeWallScores(payload.wall_scores);
  const sourceTrace = normalizeSourceTrace(payload.source_trace);

  if (!Array.isArray(payload.wall_scores)) {
    throw new ApiError("CME Options API 响应缺少 wall_scores", {
      url: CME_OPTIONS_SNAPSHOT_PATH,
    });
  }

  return {
    trade_date: asString(payload.trade_date, "unavailable"),
    run_id: typeof payload.run_id === "string" ? payload.run_id : null,
    snapshot_id: typeof payload.snapshot_id === "string" ? payload.snapshot_id : null,
    data_source: normalizeDataSource(payload.data_source),
    parameters: normalizeParameters(payload.parameters),
    gex: {
      netgex_aggregate: {
        net_gex: asNullableNumber(payload.gex?.netgex_aggregate?.net_gex),
        net_gex_direction: normalizeNetGEXDirection(payload.gex?.netgex_aggregate?.net_gex_direction),
        gamma_zero: {
          price: asNumber(payload.gex?.netgex_aggregate?.gamma_zero?.price),
          method: asString(payload.gex?.netgex_aggregate?.gamma_zero?.method),
        },
      },
      by_expiry: normalizeGEXByExpiry(payload.gex?.by_expiry),
    },
    wall_scores: wallScores,
    support_resistance: normalizeSupportResistance(payload.support_resistance),
    intent: {
      type: asString(payload.intent?.type, "neutral"),
      confidence: asNumber(payload.intent?.confidence),
      score: asNumber(payload.intent?.score),
      evidence: Array.isArray(payload.intent?.evidence)
        ? payload.intent.evidence.filter((item): item is string => typeof item === "string")
        : [],
    },
    calibration: normalizeCalibration(payload.calibration),
    source_trace: sourceTrace.length > 0 ? sourceTrace : buildFallbackSourceTrace(payload, date),
    has_data: typeof payload.has_data === "boolean" ? payload.has_data : wallScores.length > 0,
    source: "api",
    analysis: normalizeAnalysis(payload.analysis),
    exposure: normalizeExposure(payload.exposure),
    roll_signals: normalizeRollSignals(payload.roll_signals),
    normalization: typeof payload.normalization === "object" ? (payload.normalization as Record<string, unknown>) : null,
    data_quality: typeof payload.data_quality === "object" ? payload.data_quality : null,
    audit: typeof payload.audit === "object" ? (payload.audit as Record<string, unknown>) : null,
  };
}

export async function fetchCMEOptionsData(date?: string): Promise<CMEOptionsResponse> {
  try {
    const payload = await fetchJson<RawCMEOptionsSnapshot>(buildSnapshotPath(date));
    return normalizeApiSnapshot(payload, date);
  } catch (apiCause) {
    const apiError = apiCause instanceof Error ? apiCause.message : "CME Options API 请求失败";

    try {
      const mockData = await loadMockCMEOptions();
      return {
        ...mockData,
        source: "mock",
        error_reason: apiError,
      };
    } catch (mockCause) {
      const mockError = mockCause instanceof Error ? mockCause.message : "CME Options mock 请求失败";
      return createUnavailableResponse(`${apiError}; ${mockError}`);
    }
  }
}

export async function fetchCMEOptionsDecision(date?: string): Promise<CMEOptionsDecisionResponse> {
  const payload = await fetchJson<unknown>(buildDecisionPath(date));
  return normalizeDecisionResponse(payload);
}
