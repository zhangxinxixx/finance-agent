import type { GoldTopicGroup, GoldWorkspace } from "@/types/gold-workspace";
import type { ResultIdentity } from "@/types/result-identity";
import type { StrategyNavigationState } from "@/components/strategy/strategyNavigation";

/** Browser history carries an already-read DTO; it never grants current validity. */
export interface GoldReadingContext {
  workspace: GoldWorkspace;
  scrollTop: number;
  expandedSections: string[];
  topicGroup: GoldTopicGroup;
  focusLabel: string | null;
}

const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const groups: GoldTopicGroup[] = ["changes", "macro", "funds", "price", "risk"];
export function readGoldReadingContext(value: unknown): GoldReadingContext | null {
  const raw = object(value), data = object(raw.workspace), research = object(data.research);
  const horizons = object(research.horizons), plan = research.trade_plan;
  if (data.schema_version !== "gold_workspace.v1" || typeof data.generated_at !== "string"
    || !["current", "historical", "unavailable"].includes(String(research.status))
    || !Array.isArray(data.factors) || !Array.isArray(data.warnings) || !object(data.price).key
    || !Array.isArray(research.topics) || !Array.isArray(research.key_levels)
    || !horizons.short_term || !horizons.long_term || !data.cme_structure || !data.environment_watch
    || (plan !== null && (!Array.isArray(object(plan).scenarios) || !Array.isArray(object(plan).attention_points)))) return null;
  return {
    workspace: data as unknown as GoldWorkspace,
    scrollTop: typeof raw.scrollTop === "number" && Number.isFinite(raw.scrollTop) ? Math.max(0, raw.scrollTop) : 0,
    expandedSections: Array.isArray(raw.expandedSections) ? raw.expandedSections.filter((item): item is string => typeof item === "string") : [],
    topicGroup: groups.find(group => group === raw.topicGroup) ?? "changes",
    focusLabel: typeof raw.focusLabel === "string" ? raw.focusLabel : null,
  };
}

export function captureGoldReadingContext(data: GoldWorkspace, link: HTMLElement): GoldReadingContext {
  const root = link.closest(".gold-workspace");
  const selected = root?.querySelector("[data-gold-group][aria-pressed='true']")?.getAttribute("data-gold-group");
  return {
    workspace: data,
    scrollTop: link.closest(".app-content")?.scrollTop ?? 0,
    expandedSections: Array.from(root?.querySelectorAll("details") ?? []).flatMap((details, index) =>
      details.open ? [`${index}:${details.querySelector("summary")?.textContent ?? ""}`] : []),
    topicGroup: groups.find(group => group === selected) ?? "changes",
    focusLabel: link.textContent,
  };
}

export function goldStrategyNavigation(context: GoldReadingContext): StrategyNavigationState {
  const r = context.workspace.research;
  return {
    goldWorkspaceResult: context,
    strategySource: {
      source: "dashboard", returnTo: "/dashboard", returnLabel: "返回同一研究工作台", label: "黄金工作台研究",
      reportType: null, tradeDate: r.trade_date, asOf: r.as_of, runId: r.run_id, snapshotId: r.snapshot_id,
      reportId: r.report_id, authority: r.authority, publishAllowed: r.publish_allowed, sourceRefs: [],
      // Workspace v1 supplies research identity, not formal authority/receipt identity.
      sourceResultIdentity: null,
    },
  };
}

export function compareGoldReportResearch(context: GoldReadingContext, target: {
  report_id: string; run_id: string | null; snapshot_id: string | null; trade_date: string | null;
}): string {
  const source = context.workspace.research;
  const fields = ["report_id", "run_id", "snapshot_id", "trade_date"] as const;
  if (fields.some(field => source[field] && target[field] && source[field] !== target[field])) return "详情与来源研究不同，分别阅读，不拼接结论。";
  if (fields.every(field => source[field] && target[field])) return "报告与来源研究字段一致；发布资格和当前有效性仍以报告详情为准。";
  return "报告与来源身份尚未完整核验，不把相同日期当作同一研究。";
}

export function compareGoldStrategyResearch(context: GoldReadingContext, current?: ResultIdentity | null) {
  if (current?.schema_version === "gold_result_identity.v1") {
    const head = current.effective_baseline;
    if (head?.verification_status === "verified" && head.run_id && context.workspace.research.run_id
      && head.run_id !== context.workspace.research.run_id) {
      return { label: "不同研究", tone: "warn" as const, detail: "当前已核验基线与来源研究 run 不同；当前策略独立展示，不能沿用来源结论。" };
    }
  }
  return { label: "无法核验", tone: "warn" as const, detail: "工作台仅提供研究身份，缺少可比的正式 authority/receipt 身份；目标页读取最新策略，不能声称仍为同一有效研究。" };
}
