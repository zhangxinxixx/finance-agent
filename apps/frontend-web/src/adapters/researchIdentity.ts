import type { ResearchIdentity } from "@/types/research-identity";
const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): string | null => typeof value === "string" && value.trim() ? value : null;
export function normalizeResearchIdentity(value: unknown): ResearchIdentity | null {
  const raw = object(value);
  if (raw.schema_version !== "research_identity.v1") return null;
  const validity = object(raw.key_level_validity);
  return {
    schema_version: "research_identity.v1",
    report_id: text(raw.report_id), run_id: text(raw.run_id), snapshot_id: text(raw.snapshot_id),
    trade_date: text(raw.trade_date), research_version: text(raw.research_version),
    data_as_of: text(raw.data_as_of), generated_at: text(raw.generated_at),
    key_level_validity: {
      status: (["active", "expired", "unavailable", "historical"] as const).find(status => status === validity.status) ?? "unavailable",
      data_as_of: text(validity.data_as_of), valid_until: text(validity.valid_until),
      reason_codes: Array.isArray(validity.reason_codes) ? validity.reason_codes.filter((reason): reason is string => typeof reason === "string") : [],
    },
  };
}
