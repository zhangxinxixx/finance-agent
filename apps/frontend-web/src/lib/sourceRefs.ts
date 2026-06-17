import type { SourceRef } from "@/types/common";

const TRACEABLE_STATUSES = new Set([
  "available",
  "partial",
  "unavailable",
  "error",
  "live",
  "mock",
  "ok",
  "warn",
  "neutral",
  "info",
  "stale",
  "fallback",
  "manual_required",
]);

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function readStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  return items.length > 0 ? items : null;
}

function readStatus(value: unknown): SourceRef["status"] | null {
  const status = readString(value);
  if (!status) return null;
  const normalized = status.toLowerCase() === "info" ? "unavailable" : status.toLowerCase();
  return TRACEABLE_STATUSES.has(normalized) ? (normalized as SourceRef["status"]) : null;
}

function mergeSourceRef(base: SourceRef, fallback: SourceRef): SourceRef {
  return {
    ...fallback,
    ...base,
    endpoint: base.endpoint ?? fallback.endpoint ?? null,
    artifact_path: base.artifact_path ?? fallback.artifact_path ?? null,
    snapshot_id: base.snapshot_id ?? fallback.snapshot_id ?? null,
    input_snapshot_ids: base.input_snapshot_ids ?? fallback.input_snapshot_ids ?? null,
    trade_date: base.trade_date ?? fallback.trade_date ?? fallback.dataDate ?? null,
    dataDate: base.dataDate ?? fallback.dataDate ?? fallback.trade_date ?? null,
    asOf: base.asOf ?? fallback.asOf ?? fallback.generated_at ?? null,
    run_id: base.run_id ?? fallback.run_id ?? null,
    generated_at: base.generated_at ?? fallback.generated_at ?? null,
    provider: base.provider ?? fallback.provider ?? null,
    label: base.label ?? fallback.label ?? null,
    status: base.status ?? fallback.status ?? null,
    source_url: base.source_url ?? fallback.source_url ?? null,
  };
}

export function normalizeSourceRefs(input: unknown): SourceRef[] {
  if (!input) return [];

  const items = Array.isArray(input) ? input : [input];

  return items.flatMap((item) => {
    if (typeof item === "string") {
      return [{ source_ref: item }];
    }

    if (!item || typeof item !== "object") return [];

    const record = item as Record<string, unknown>;
    const sourceRef = readString(record.source_ref) ?? readString(record.ref) ?? readString(record.endpoint) ?? readString(record.artifact_path);

    if (!sourceRef) return [];

    return [
      {
        source_ref: sourceRef,
        endpoint: readString(record.endpoint),
        artifact_path: readString(record.artifact_path) ?? readString(record.file) ?? readString(record.path),
        snapshot_id: readString(record.snapshot_id),
        input_snapshot_ids: readStringArray(record.input_snapshot_ids),
        trade_date: readString(record.trade_date) ?? readString(record.data_date),
        dataDate: readString(record.dataDate) ?? readString(record.data_date) ?? readString(record.trade_date),
        asOf: readString(record.asOf) ?? readString(record.as_of) ?? readString(record.generated_at) ?? readString(record.updated_at) ?? readString(record.latest_parsed_time) ?? readString(record.latest_raw_time),
        run_id: readString(record.run_id),
        generated_at: readString(record.generated_at) ?? readString(record.updated_at) ?? readString(record.latest_parsed_time) ?? readString(record.latest_raw_time),
        provider: readString(record.provider) ?? readString(record.source) ?? readString(record.model_version),
        label: readString(record.label) ?? readString(record.name),
        status: readStatus(record.status),
        source_url: readString(record.source_url),
      },
    ];
  });
}

export function resolveSourceRefs(sourceRefs?: unknown, sources?: unknown): SourceRef[] {
  const normalizedSourceRefs = normalizeSourceRefs(sourceRefs);
  const normalizedLegacySources = normalizeSourceRefs(sources);

  if (normalizedSourceRefs.length === 0) {
    return normalizedLegacySources;
  }
  if (normalizedLegacySources.length === 0) {
    return normalizedSourceRefs;
  }

  const merged = new Map<string, SourceRef>();
  const keyOf = (source: SourceRef) => [
    source.source_ref,
    source.snapshot_id ?? "",
    source.run_id ?? "",
  ].join("|");

  for (const source of normalizedLegacySources) {
    merged.set(keyOf(source), source);
  }

  for (const source of normalizedSourceRefs) {
    const key = keyOf(source);
    const fallback = merged.get(key);
    merged.set(key, fallback ? mergeSourceRef(source, fallback) : source);
  }

  return Array.from(merged.values());
}

export function sourceRefFromEndpoint(endpoint: string, extra: Partial<SourceRef> = {}): SourceRef {
  return {
    source_ref: extra.source_ref ?? endpoint,
    endpoint,
    ...extra,
  };
}

export function dedupeSourceRefs(sourceRefs: SourceRef[]): SourceRef[] {
  const seen = new Set<string>();
  const result: SourceRef[] = [];

  for (const source of sourceRefs) {
    const key = [
      source.source_ref,
      source.endpoint ?? "",
      source.artifact_path ?? "",
      source.snapshot_id ?? "",
      source.trade_date ?? "",
      source.run_id ?? "",
    ].join("|");

    if (seen.has(key)) continue;
    seen.add(key);
    result.push(source);
  }

  return result;
}

export function compactSourceLabel(source: SourceRef): string {
  return (
    source.label ??
    source.provider ??
    source.endpoint ??
    source.artifact_path ??
    source.snapshot_id ??
    source.source_ref
  );
}

export function sourceRefPairs(source: SourceRef): Array<{ label: string; value: string }> {
  return [
    { label: "source_ref", value: source.source_ref },
    { label: "endpoint", value: source.endpoint ?? "" },
    { label: "artifact", value: source.artifact_path ?? "" },
    { label: "snapshot_id", value: source.snapshot_id ?? "" },
    { label: "trade_date", value: source.trade_date ?? "" },
    { label: "dataDate", value: source.dataDate ?? "" },
    { label: "asOf", value: source.asOf ?? "" },
    { label: "run_id", value: source.run_id ?? "" },
    { label: "generated_at", value: source.generated_at ?? "" },
    { label: "source_url", value: source.source_url ?? "" },
  ].filter((item) => item.value.trim().length > 0);
}
