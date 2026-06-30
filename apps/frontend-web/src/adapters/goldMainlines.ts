import { fetchJson } from "@/adapters/apiClient";
import type { SourceRef } from "@/types/common";
import type { GoldMacroOverview, GoldMainlinesViewModel, GoldMainlineStatus } from "@/types/gold-mainlines";

const GOLD_MAINLINES_LATEST_PATH = "/api/gold/mainlines/latest";

export interface GoldMainlinesResponse {
  status: GoldMainlineStatus;
  date: string | null;
  run_id: string | null;
  artifact_path: string | null;
  schema_version: string | null;
  input_snapshot_ids: Record<string, unknown>;
  gold_macro_overview: GoldMacroOverview | null;
  gold_mainlines: GoldMainlinesViewModel;
  source_refs: SourceRef[];
  warnings: string[];
}

interface RawGoldMainlinesResponse {
  status?: string;
  date?: string | null;
  run_id?: string | null;
  artifact_path?: string | null;
  schema_version?: string | null;
  input_snapshot_ids?: Record<string, unknown>;
  gold_macro_overview?: GoldMacroOverview | null;
  gold_mainlines?: GoldMainlinesViewModel | null;
  source_refs?: SourceRef[];
  warnings?: string[];
}

function normalizeStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function unavailableMainlines(): GoldMainlinesViewModel {
  return {
    status: "unavailable",
    schema_version: "gold-event-mainlines-v1",
    asset: "XAUUSD",
    as_of: null,
    mainlines: [],
    event_links: [],
    dominant_forces: [],
    source_refs: [],
    artifact_refs: [],
    warnings: ["gold_event_mainlines artifact unavailable"],
  };
}

function normalizeGoldMainlinesResponse(raw: RawGoldMainlinesResponse): GoldMainlinesResponse {
  return {
    status: (raw.status ?? "unavailable") as GoldMainlineStatus,
    date: raw.date ?? null,
    run_id: raw.run_id ?? null,
    artifact_path: raw.artifact_path ?? null,
    schema_version: raw.schema_version ?? null,
    input_snapshot_ids: raw.input_snapshot_ids ?? {},
    gold_macro_overview: raw.gold_macro_overview ?? null,
    gold_mainlines: raw.gold_mainlines ?? unavailableMainlines(),
    source_refs: Array.isArray(raw.source_refs) ? raw.source_refs : [],
    warnings: normalizeStringList(raw.warnings),
  };
}

export async function fetchGoldMainlinesLatest(): Promise<GoldMainlinesResponse> {
  const raw = await fetchJson<RawGoldMainlinesResponse>(GOLD_MAINLINES_LATEST_PATH);
  return normalizeGoldMainlinesResponse(raw);
}
