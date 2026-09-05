import type {
  ResultIdentity,
  ResultIdentityEffectiveBaseline,
  ResultIdentityRelationship,
  ResultIdentityRelationshipStatus,
  ResultIdentitySubject,
} from "@/types/result-identity";

type RawRecord = Record<string, unknown>;

function asRecord(value: unknown): RawRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as RawRecord : {};
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function booleanValue(value: unknown): boolean {
  return value === true;
}

function normalizeSubject(value: unknown): ResultIdentitySubject {
  const raw = asRecord(value);
  return {
    kind: stringValue(raw.kind),
    run_id: nullableString(raw.run_id),
    premarket_snapshot_id: nullableString(raw.premarket_snapshot_id),
    feature_snapshot_id: nullableString(raw.feature_snapshot_id),
    result_id: nullableString(raw.result_id),
    state_id: nullableString(raw.state_id),
    strategy_id: nullableString(raw.strategy_id),
    receipt_id: nullableString(raw.receipt_id),
    bundle_ref: nullableString(raw.bundle_ref),
    verification_status: nullableString(raw.verification_status),
    reason_code: nullableString(raw.reason_code),
  };
}

function normalizeEffectiveBaseline(value: unknown): ResultIdentityEffectiveBaseline | null {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = asRecord(value);
  return {
    ...normalizeSubject(raw),
    status: stringValue(raw.status),
    held: booleanValue(raw.held),
    authority_ready: booleanValue(raw.authority_ready),
    quality_status: nullableString(raw.quality_status),
    strategy_status: nullableString(raw.strategy_status),
    decision_as_of: nullableString(raw.decision_as_of),
  };
}

function normalizeRelationship(value: unknown): ResultIdentityRelationship {
  const raw = asRecord(value);
  const status = raw.status;
  const knownStatus: ResultIdentityRelationshipStatus =
    status === "same_effective_head" || status === "different_result" || status === "unverified" || status === "unavailable"
      ? status
      : "unavailable";
  return {
    status: knownStatus,
    reason_code: nullableString(raw.reason_code),
  };
}

/** Normalize additive API identity data without deriving or comparing IDs. */
export function normalizeResultIdentity(value: unknown): ResultIdentity | null {
  if (value == null || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = asRecord(value);
  return {
    schema_version: nullableString(raw.schema_version),
    subject: normalizeSubject(raw.subject),
    effective_baseline: normalizeEffectiveBaseline(raw.effective_baseline),
    relationship: normalizeRelationship(raw.relationship),
  };
}
