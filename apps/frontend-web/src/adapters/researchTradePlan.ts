import type { ResearchPlanConditions, ResearchTradePlan } from "@/types/research-trade-plan";

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, max = 12000): value is string =>
  typeof value === "string" && value.length <= max && value.trim().length > 0;
const list = (value: unknown): value is string[] =>
  Array.isArray(value) && value.length <= 32 && value.every(item => text(item));
const optionalProse = (value: unknown) => value == null || (typeof value === "string" && value.length <= 12000);
const conditions = (value: unknown): value is ResearchPlanConditions =>
  text(value) || (list(value) && value.length > 0);

export interface ResearchPlanIdentity {
  report_id: string;
  run_id: string | null | undefined;
  trade_date: string | null | undefined;
  snapshot_id?: string | null;
}

/** Fail closed and copy bounded known fields; preserve condition prose verbatim. */
export function normalizeResearchTradePlan(value: unknown, identity: ResearchPlanIdentity): ResearchTradePlan | null {
  if (!record(value) || value.schema_version !== "research_trade_plan.v1"
    || value.status !== "waiting" || value.execution_ready !== false || value.is_trade_instruction !== false
    || value.current_action !== "等待确认，暂不开新单"
    || value.entry !== null || value.stop_loss !== null || !Array.isArray(value.targets) || value.targets.length !== 0
    || !text(value.report_id, 512) || !text(value.run_id, 512)
    || !(value.snapshot_id === null || text(value.snapshot_id, 512))
    || !text(value.trade_date, 10) || !/^\d{4}-\d{2}-\d{2}$/.test(value.trade_date)
    || !Number.isFinite(Date.parse(value.trade_date)) || new Date(value.trade_date).toISOString().slice(0, 10) !== value.trade_date
    || !text(value.as_of, 64) || !/[T ]\d{2}:\d{2}.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(value.as_of) || !Number.isFinite(Date.parse(value.as_of))
    || value.report_id !== identity.report_id || value.run_id !== identity.run_id || value.trade_date !== identity.trade_date
    || (Object.prototype.hasOwnProperty.call(identity, "snapshot_id") && value.snapshot_id !== identity.snapshot_id)
    || !optionalProse(value.summary) || !optionalProse(value.reason) || !list(value.attention_points)
    || !record(value.position_guidance) || !optionalProse(value.position_guidance.flat) || !optionalProse(value.position_guidance.long) || !optionalProse(value.position_guidance.short)
    || !Array.isArray(value.scenarios) || value.scenarios.length > 8) return null;
  const scenarios: ResearchTradePlan["scenarios"] = [];
  const copy = (item: ResearchPlanConditions) => Array.isArray(item) ? [...item] : item;
  for (const scenario of value.scenarios) {
    if (!record(scenario) || !text(scenario.name, 256) || !conditions(scenario.macro_conditions)
      || !conditions(scenario.price_conditions) || !conditions(scenario.invalidation)) return null;
    scenarios.push({ name: scenario.name, macro_conditions: copy(scenario.macro_conditions),
      price_conditions: copy(scenario.price_conditions), invalidation: copy(scenario.invalidation) });
  }
  return {
    schema_version: "research_trade_plan.v1", report_id: value.report_id, run_id: value.run_id,
    snapshot_id: value.snapshot_id, trade_date: value.trade_date, as_of: value.as_of,
    status: "waiting", execution_ready: false, is_trade_instruction: false, current_action: value.current_action,
    summary: typeof value.summary === "string" ? value.summary : "", reason: typeof value.reason === "string" ? value.reason : "", scenarios,
    position_guidance: { flat: typeof value.position_guidance.flat === "string" ? value.position_guidance.flat : "",
      long: typeof value.position_guidance.long === "string" ? value.position_guidance.long : "",
      short: typeof value.position_guidance.short === "string" ? value.position_guidance.short : "" },
    entry: null, stop_loss: null, targets: [], attention_points: [...value.attention_points],
  };
}

/** Match only an explicit identity already present in this research's sources. */
export function normalizeDashboardTradePlan(value: unknown, research: {
  run_id?: string | null; trade_date?: string;
  source_refs?: Array<{ report_id?: string | null; source_ref?: string; trade_date?: string; snapshot_id?: string | null }>;
}): ResearchTradePlan | null {
  if (!record(value) || !text(value.report_id, 512) || !Array.isArray(research.source_refs)) return null;
  const ref = research.source_refs.find(item => item && item.trade_date === research.trade_date
    && (item.report_id != null ? item.report_id === value.report_id : item.source_ref === value.report_id));
  return ref ? normalizeResearchTradePlan(value, { report_id: value.report_id, run_id: research.run_id, trade_date: research.trade_date,
    ...(ref.snapshot_id !== undefined ? { snapshot_id: ref.snapshot_id } : {}) }) : null;
}
