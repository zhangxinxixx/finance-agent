/** Backend-owned research timing and financial validity; never inferred from wall time. */
export interface ResearchIdentity {
  schema_version: "research_identity.v1";
  report_id: string | null;
  run_id: string | null;
  snapshot_id: string | null;
  trade_date: string | null;
  research_version: string | null;
  data_as_of: string | null;
  generated_at: string | null;
  key_level_validity: {
    status: "active" | "expired" | "unavailable" | "historical";
    data_as_of: string | null;
    valid_until: string | null;
    reason_codes: string[];
  };
}
