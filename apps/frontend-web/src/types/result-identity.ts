/**
 * Shared identity contract for Gold results and the effective daily baseline.
 *
 * The API may add fields, but these fields are the stable minimum.  A missing
 * or unknown schema is intentionally kept distinguishable from a verified
 * relationship so consumers cannot infer that two results share a head.
 */
export const GOLD_RESULT_IDENTITY_SCHEMA_VERSION = "gold_result_identity.v1" as const;

export interface ResultIdentitySubject {
  kind: string;
  run_id: string | null;
  premarket_snapshot_id: string | null;
  feature_snapshot_id: string | null;
  result_id: string | null;
  state_id: string | null;
  strategy_id: string | null;
  receipt_id: string | null;
  bundle_ref: string | null;
  verification_status: string | null;
  reason_code: string | null;
}

export interface ResultIdentityEffectiveBaseline extends ResultIdentitySubject {
  status: string;
  held: boolean;
  authority_ready: boolean;
  quality_status: string | null;
  strategy_status: string | null;
  decision_as_of: string | null;
}

export type ResultIdentityRelationshipStatus =
  | "same_effective_head"
  | "different_result"
  | "unverified"
  | "unavailable";

export interface ResultIdentityRelationship {
  status: ResultIdentityRelationshipStatus;
  reason_code: string | null;
}

export interface ResultIdentity {
  schema_version: string | null;
  subject: ResultIdentitySubject;
  effective_baseline: ResultIdentityEffectiveBaseline | null;
  relationship: ResultIdentityRelationship;
}

export function isKnownResultIdentity(identity: ResultIdentity | null | undefined): boolean {
  return identity?.schema_version === GOLD_RESULT_IDENTITY_SCHEMA_VERSION;
}
