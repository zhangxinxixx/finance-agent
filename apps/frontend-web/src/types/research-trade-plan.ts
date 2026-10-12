/** Backend research projection only; never an execution instruction. */
export type ResearchPlanConditions = string | string[];

export interface ResearchTradePlan {
  schema_version: "research_trade_plan.v1";
  report_id: string;
  run_id: string;
  snapshot_id: string | null;
  trade_date: string;
  as_of: string;
  status: "waiting";
  execution_ready: false;
  is_trade_instruction: false;
  current_action: "等待确认，暂不开新单";
  summary: string;
  reason: string;
  scenarios: Array<{
    name: string;
    macro_conditions: ResearchPlanConditions;
    price_conditions: ResearchPlanConditions;
    invalidation: ResearchPlanConditions;
  }>;
  position_guidance: { flat: string; long: string; short: string };
  entry: null;
  stop_loss: null;
  targets: [];
  attention_points: string[];
}
