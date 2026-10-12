import { normalizeResearchIdentity } from "@/adapters/researchIdentity";
import { fetchJson } from "@/adapters/apiClient";
import { normalizeResearchTradePlan } from "@/adapters/researchTradePlan";
import type { GoldAnalysisPreflight, GoldAnalysisStart, GoldAnalysisTask, GoldFact, GoldResearchHorizon, GoldResearchTopic, GoldTopicGroup, GoldWorkspace } from "@/types/gold-workspace";

const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): string | null => typeof value === "string" && value.trim() ? value : null;
const number = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
const uuid = (value: unknown): string | null => typeof value === "string" && /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(value) ? value : null;

function normalizeFact(value: unknown): GoldFact {
  const raw = object(value);
  const amount = number(raw.value);
  const statuses = ["fresh", "recent", "stale", "unverified", "unavailable"] as const;
  const impacts = ["supportive", "pressure", "mixed", "neutral", "unconfirmed"] as const;
  const frequencies = ["intraday", "daily", "weekly", "monthly"] as const;
  const metadata = text(raw.observed_at) && text(raw.source);
  const status = amount === null ? "unavailable" : !metadata ? "unverified" : statuses.find(item => item === raw.status) ?? "unverified";
  const macro = object(raw.macro_effect);
  const macroReady = ["fresh", "recent"].includes(status) && (macro.basis === "monthly_comparison" && number(macro.change) !== null
    || macro.basis === "holding_cost_level" && ["US02Y", "US10Y", "US30Y", "REAL10Y"].includes(String(raw.key)));
  return {
    key: text(raw.key) ?? "unknown", label: text(raw.label) ?? "指标待核验", value: amount,
    unit: text(raw.unit) ?? "", change: number(raw.change), change_unit: text(raw.change_unit) ?? "",
    change_window: text(raw.change_window), observed_at: text(raw.observed_at), source: text(raw.source),
    frequency: frequencies.find(item => item === raw.frequency) ?? "daily", status,
    impact: status === "fresh" || status === "recent" ? impacts.find(item => item === raw.impact) ?? "unconfirmed" : "unconfirmed",
    interpretation: text(raw.interpretation) ?? "等待可验证的观测。",
    short_term_summary: text(raw.short_term_summary) ?? text(raw.interpretation) ?? "短线变化尚未核验。",
    macro_effect: { impact: macroReady ? impacts.find(item => item === macro.impact) ?? "unconfirmed" : "unconfirmed",
      summary: macroReady ? text(macro.summary) ?? "长期影响需核验。" : "长期方向需补齐可比数据。",
      change: macroReady ? number(macro.change) : null, unit: text(macro.unit) ?? "", window: macroReady ? text(macro.window) : null,
      basis: macroReady ? macro.basis as string : "unavailable" },
    source_refs: Array.isArray(raw.source_refs) ? raw.source_refs.map(object).filter(ref => Object.keys(ref).length > 0) : [],
  };
}

function normalizeCme(value: unknown): GoldWorkspace["cme_structure"] {
  const raw = object(value);
  const ready = ["reference", "historical"].includes(String(raw.status)) && raw.coordinate === "GC futures"
    && ["PRELIM", "PRELIMINARY", "FINAL"].includes(String(raw.version_type)) && text(raw.trade_date)
    && Array.isArray(raw.source_refs) && raw.source_refs.length > 0;
  const roles = ["primary_support", "primary_resistance", "secondary_support", "secondary_resistance", "magnet_pin", "volatility_hub", "gamma_flip", "tail_protection"];
  const levels = ready && Array.isArray(raw.levels) ? raw.levels.map(object).filter(row => row.coordinate === "GC futures"
    && roles.includes(String(row.role)) && text(row.label) && text(row.meaning)
    && (number(row.price) !== null && Number(row.price) > 0 || number(row.lower) !== null && Number(row.lower) > 0
      && number(row.upper) !== null && Number(row.upper) >= Number(row.lower))).map(row => ({
    price: number(row.price), lower: number(row.lower), upper: number(row.upper), role: row.role as string,
    label: row.label as string, meaning: row.meaning as string, expiry: text(row.expiry), invalidation: strings(row.invalidation),
  })) : [];
  return { status: ready && levels.length ? raw.status as "reference" | "historical" : "unavailable", coordinate: "GC futures",
    trade_date: text(raw.trade_date), version_type: text(raw.version_type), reference_price: ready ? number(raw.reference_price) : null,
    basis_status: "unvalidated", levels, source_refs: ready ? (raw.source_refs as unknown[]).map(object) : [],
    note: text(raw.note) ?? "GC期货结构参考，不能直接当作XAUUSD现货支撑。" };
}

function normalizeEnvironment(value: unknown, factors: GoldFact[]): GoldWorkspace["environment_watch"] {
  const raw = object(value);
  const rows = raw.basis === "latest_observation_comparison" && Array.isArray(raw.conditions) ? raw.conditions.map(object) : [];
  const conditions = rows.filter(row => {
    const fact = factors.find(item => item.key === row.key);
    return fact && ["fresh", "recent"].includes(fact.status) && row.value === fact.value && row.observed_at === fact.observed_at
      && text(row.supportive_condition) && text(row.pressure_condition) && rows.filter(other => other.key === row.key).length === 1;
  }).map(row => ({ key: row.key as string, label: text(row.label) ?? "指标", value: row.value as number,
    unit: text(row.unit) ?? "", supportive_condition: row.supportive_condition as string,
    pressure_condition: row.pressure_condition as string, observed_at: text(row.observed_at) }));
  return { status: conditions.length === 4 ? "available" : conditions.length ? "partial" : "unavailable",
    basis: "latest_observation_comparison", conditions,
    note: text(raw.note) ?? "比较基准需配合连续变化与价格结构，不代表已确认反转。" };
}

function normalizeHorizon(value: unknown, research: Record<string, unknown>, status: GoldWorkspace["research"]["status"]): GoldResearchHorizon {
  const raw = object(value);
  const bound = status !== "unavailable" && ["report_id", "run_id", "snapshot_id", "trade_date", "as_of"]
    .every(key => text(research[key]) && raw[key] === research[key]);
  const sections = Array.isArray(raw.sections) ? raw.sections.map(object)
    .filter(row => text(row.title) && text(row.content)).map(row => ({ title: row.title as string, content: row.content as string })) : [];
  const ready = bound && raw.status === status && text(raw.summary) && sections.length > 0
    && (raw.basis === "report_explicit" || raw.basis === "report_excerpt");
  return { status: ready ? status : "unavailable", horizon: text(raw.horizon) ?? "周期待核验",
    basis: ready ? raw.basis as GoldResearchHorizon["basis"] : "unavailable", summary: ready ? raw.summary as string : "",
    sections: ready ? sections : [], as_of: ready ? text(raw.as_of) : null,
    note: ready ? text(raw.note) ?? "同一研究的周期分析。" : "本研究尚未提供可核验的周期分析，更新分析后再展示。" };
}

function normalizeTopics(value: unknown, research: Record<string, unknown>, status: GoldWorkspace["research"]["status"]): GoldResearchTopic[] {
  if (!Array.isArray(value)) return [];
  const rows = value.map(object);
  return rows.filter(raw => text(raw.key) && text(raw.label) && ["changes", "macro", "funds", "price", "risk"].includes(String(raw.group))
    && rows.filter(other => other.key === raw.key).length === 1).map(raw => {
    const bound = status !== "unavailable" && ["report_id", "run_id", "snapshot_id", "trade_date", "as_of"]
      .every(key => text(research[key]) && raw[key] === research[key]);
    const fields = ["judgment", "facts", "transmission", "response", "alternatives", "falsification"] as const;
    const sections = Array.isArray(raw.sections) ? raw.sections.map(object).filter(row => text(row.title) && text(row.content))
      .map(row => ({ title: row.title as string, content: row.content as string })) : [];
    const full = raw.basis === "verified_report_topics" && fields.every(key => text(raw[key]))
      && Array.isArray(raw.pending) && raw.pending.every(p => typeof p === "string");
    const excerpt = raw.basis === "report_excerpt" && sections.length > 0;
    const ready = bound && raw.status === status && (full || excerpt);
    return { key: raw.key as string, label: raw.label as string, group: raw.group as GoldTopicGroup,
      status: ready ? status : "unavailable", basis: ready ? raw.basis as GoldResearchTopic["basis"] : "unavailable",
      ...Object.fromEntries(fields.map(key => [key, ready ? text(raw[key]) ?? "" : ""])) as Pick<GoldResearchTopic, typeof fields[number]>,
      pending: ready ? strings(raw.pending) : [], sections: ready ? sections : [], as_of: ready ? text(raw.as_of) : null,
      note: ready ? text(raw.note) ?? "同一研究主题。" : "本研究尚未提供可核验的这一分析点，更新分析后补齐。" };
  });
}

export function normalizeGoldWorkspace(value: unknown): GoldWorkspace {
  const raw = object(value);
  if (raw.schema_version !== "gold_workspace.v1" || !text(raw.generated_at) || !Array.isArray(raw.factors) || !Object.keys(object(raw.price)).length) {
    throw new Error("黄金工作台返回了不完整的数据，保留上次观测。");
  }
  const r = object(raw.research), c = object(raw.comparison);
  const identity = { report_id: text(r.report_id) ?? "", run_id: text(r.run_id), snapshot_id: text(r.snapshot_id), trade_date: text(r.trade_date) };
  const bound = identity.report_id && identity.run_id && identity.snapshot_id && identity.trade_date && text(r.narrative);
  const researchStatus = bound && (r.status === "current" || r.status === "historical")
    ? r.latest_status === "unavailable" ? "historical" : r.status : "unavailable";
  const price = normalizeFact(raw.price);
  const factors = raw.factors.map(normalizeFact);
  const compatible = c.status === "available" && price.status === "fresh" && researchStatus !== "unavailable" && r.latest_status !== "unavailable"
    && [c.reference_price, c.price_change, c.price_change_pct].every(v => number(v) !== null);
  return {
    schema_version: "gold_workspace.v1", generated_at: raw.generated_at as string,
    status: raw.status === "available" || raw.status === "partial" ? raw.status : "unavailable", price,
    factors,
    research: {
      research_identity: normalizeResearchIdentity(r.research_identity),
      ...identity, status: researchStatus, report_id: identity.report_id || null, as_of: text(r.as_of),
      bias: researchStatus === "unavailable" ? null : text(r.bias),
      summary: researchStatus === "unavailable" ? "" : text(r.summary) ?? "",
      narrative: researchStatus === "unavailable" ? "" : text(r.narrative) ?? "",
      reason: text(r.reason), authority: "observation_only", publish_allowed: false,
      latest_status: r.latest_status === "unavailable" || researchStatus === "unavailable" ? "unavailable" : "available",
      latest_reason: text(r.latest_reason), latest_run_id: text(r.latest_run_id),
      trade_plan: researchStatus === "unavailable" ? null : normalizeResearchTradePlan(r.trade_plan, identity),
      key_levels: researchStatus === "unavailable" || !Array.isArray(r.key_levels) ? [] : r.key_levels.map(object).filter(row => {
        const coordinate = String(row.coordinate ?? row.coordinate_space ?? "").toLowerCase();
        const instrument = String(row.instrument ?? "").toLowerCase();
        return ["spot", "xauusd", "xauusd_spot", "xauusd spot"].includes(coordinate) && ["spot", "xauusd", "xauusd_spot", "xauusd spot"].includes(instrument)
          && number(row.price) !== null && (row.price as number) > 0;
      }),
      horizons: { short_term: normalizeHorizon(object(r.horizons).short_term, r, researchStatus),
        long_term: normalizeHorizon(object(r.horizons).long_term, r, researchStatus) },
      topics: normalizeTopics(r.topics, r, researchStatus),
    },
    comparison: {
      status: compatible ? "available" : "unavailable", reference_price: compatible ? number(c.reference_price) : null,
      reference_time: compatible ? text(c.reference_time) : null, price_change: compatible ? number(c.price_change) : null,
      price_change_pct: compatible ? number(c.price_change_pct) : null, note: text(c.note) ?? "未取得同口径可对齐报价。",
    }, warnings: strings(raw.warnings), environment_watch: normalizeEnvironment(raw.environment_watch, factors),
    cme_structure: normalizeCme(raw.cme_structure),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return fetchJson<T>(path, init);
}

let workspaceRequest: Promise<GoldWorkspace> | null = null;
export function fetchGoldWorkspace(): Promise<GoldWorkspace> {
  if (workspaceRequest) return workspaceRequest;
  const pending = request<unknown>("/api/gold/workspace").then(normalizeGoldWorkspace);
  workspaceRequest = pending;
  void pending.finally(() => { if (workspaceRequest === pending) workspaceRequest = null; }).catch(() => undefined);
  return pending;
}

export async function fetchGoldAnalysisPreflight(): Promise<GoldAnalysisPreflight> {
  const r = object(await request<unknown>("/api/tasks/premarket/preflight"));
  if (typeof r.can_launch !== "boolean") throw new Error("无法核验启动条件。");
  const dagster = object(r.active_dagster_run), legacy = object(r.active_legacy_task);
  const serviceUnavailable = Boolean(text(r.dagster_check_error));
  return { can_launch: r.can_launch && r.force !== true && !serviceUnavailable,
    blocking_reasons: [...strings(r.blocking_reasons), ...(serviceUnavailable ? ["dagster_check_failed"] : [])],
    active_task_id: uuid(dagster.run_id) ?? uuid(legacy.task_id),
    blocked_sources: strings(object(r.source_readiness_summary).blocked_sources) };
}

const TASK_KEY = "finance-agent-gold-analysis-task";
let rememberedTask: string | null = null;
export function rememberGoldAnalysisTask(value: string | null) {
  rememberedTask = value;
  try { if (value) sessionStorage.setItem(TASK_KEY, value); else sessionStorage.removeItem(TASK_KEY); } catch { /* Private mode still has the in-memory record. */ }
}
export function readGoldAnalysisTask(): string | null {
  try { return sessionStorage.getItem(TASK_KEY) ?? rememberedTask; } catch { return rememberedTask; }
}

function blockedMessage(preflight: GoldAnalysisPreflight): string {
  if (preflight.blocking_reasons.some(reason => reason.includes("dagster"))) return "分析服务尚未就绪，请恢复服务后重新检查。";
  if (preflight.blocking_reasons.includes("source_readiness_blocked")) return "关键数据源尚未齐备，本次分析未启动。可在数据接入页查看缺口。";
  return "当前启动条件未通过，本次分析未启动。请查看数据缺口或已有任务。";
}

let launchRequest: Promise<GoldAnalysisStart> | null = null;
export function startGoldAnalysis(): Promise<GoldAnalysisStart> {
  if (launchRequest) return launchRequest;
  const pending = (async (): Promise<GoldAnalysisStart> => {
    const preflight = await fetchGoldAnalysisPreflight();
    if (preflight.active_task_id) {
      rememberGoldAnalysisTask(preflight.active_task_id);
      return { phase: "running", task_id: preflight.active_task_id, message: "正在跟踪已有分析任务。" };
    }
    if (readGoldAnalysisTask() === "uncertain") return { phase: "uncertain", task_id: null,
      message: "上次启动结果尚未确认，暂未查到活动任务。请先到分析记录核对，避免重复启动。" };
    if (!preflight.can_launch) return { phase: "blocked", task_id: null, message: blockedMessage(preflight) };
    // Persist uncertainty before issuing the one write. Reloads cannot repeat it.
    rememberGoldAnalysisTask("uncertain");
    try {
      const launch = object(await request<unknown>("/api/tasks/premarket", { method: "POST" }));
      const id = uuid(launch.task_id);
      if (!id) throw new Error("启动结果缺少可核验的任务标识。");
      rememberGoldAnalysisTask(id);
      return { phase: "running", task_id: id, message: "已启动数据更新与黄金分析，正在跟踪进度。" };
    } catch {
      try {
        const check = await fetchGoldAnalysisPreflight();
        if (check.active_task_id) {
          rememberGoldAnalysisTask(check.active_task_id);
          return { phase: "running", task_id: check.active_task_id, message: "启动响应未确认，已找到活动任务并继续跟踪。" };
        }
      } catch { /* Leave the uncertainty record intact. */ }
      return { phase: "uncertain", task_id: null, message: "启动响应未确认；请重新核对任务，系统不会自动重复启动。" };
    }
  })();
  launchRequest = pending;
  void pending.finally(() => { if (launchRequest === pending) launchRequest = null; }).catch(() => undefined);
  return pending;
}

export async function fetchGoldAnalysisTask(id: string): Promise<GoldAnalysisTask> {
  if (!uuid(id)) throw new Error("任务标识无法核验。");
  const raw = object(await request<unknown>(`/api/tasks/${encodeURIComponent(id)}`));
  if (raw.id !== id || !text(raw.status)) throw new Error("返回任务与当前跟踪任务不一致。");
  return { id, status: raw.status as string, error: text(raw.error),
    steps: Array.isArray(raw.steps) ? raw.steps.map(object).map(row => ({ name: text(row.name) ?? "未提供步骤",
      status: text(row.status) ?? "unknown", error: text(row.error) })) : [] };
}
