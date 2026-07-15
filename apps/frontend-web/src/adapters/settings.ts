import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { fetchJson } from "@/adapters/apiClient";

export type SettingsSourceStatus = "CONNECTED" | "DISCONNECTED" | "UNKNOWN";

export interface SettingsDataSource {
  id: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  enabled: boolean;
  defaultEnabled: boolean;
  isOverridden: boolean;
  status: SettingsSourceStatus;
  apiKeyMasked: string | null;
  secretConfigured: boolean;
  secretLastUpdatedAt: string | null;
  secretWritable: boolean;
}

export interface SettingsPreferenceItem {
  key: "language" | "timezone" | "report_template";
  label: string;
  value: string;
  options: string[];
}

export interface GlobalConfigItem {
  label: string;
  value: string;
}

export interface SystemInfoItem {
  label: string;
  value: string;
}

export interface SettingsData {
  status: string;
  source: string;
  preferences: SettingsPreferenceItem[];
  sources: SettingsDataSource[];
  globalConfig: GlobalConfigItem[];
  systemInfo: SystemInfoItem[];
}

export interface SettingsHistoryEntry {
  settingKey: string;
  scope: string;
  sourceKey: string | null;
  action: string;
  oldValueJson: Record<string, unknown> | null;
  newValueJson: Record<string, unknown> | null;
  actor: string | null;
  reason: string | null;
  requestId: string | null;
  auditId: string | null;
  createdAt: string | null;
}

export interface SettingsPreferencesUpdatePayload {
  language?: string;
  timezone?: string;
  report_template?: string;
  actor?: string;
  reason?: string;
  request_id?: string;
}

export interface SettingsSourceUpdatePayload {
  enabled: boolean;
  actor?: string;
  reason?: string;
  request_id?: string;
}

export interface SettingsPreferencesResetPayload {
  keys?: string[];
  actor?: string;
  reason?: string;
  request_id?: string;
}

export interface SettingsSourceResetPayload {
  actor?: string;
  reason?: string;
  request_id?: string;
}

export interface SettingsSecretUpdatePayload {
  secret_value: string;
  actor?: string;
  reason?: string;
  request_id?: string;
}

export interface SettingsSecretResetPayload {
  actor?: string;
  reason?: string;
  request_id?: string;
}

export interface SettingsRollbackPayload {
  actor?: string;
  reason?: string;
  request_id?: string;
}

interface SettingsStatusApiResponse {
  status?: string;
  source?: string;
  preferences?: Array<Record<string, unknown>>;
  sources?: Array<Record<string, unknown>>;
  global_config?: Array<Record<string, unknown>>;
  system_info?: Array<Record<string, unknown>>;
}

interface SettingsHistoryApiResponse {
  events?: Array<Record<string, unknown>>;
}

interface SettingsActionResponse {
  status: string;
  audit_id?: string | null;
  rolled_back_audit_id?: string | null;
  updated_keys?: string[];
  source_key?: string | null;
  enabled?: boolean | null;
  updated_at?: string | null;
}

export interface SettingsHistoryFilters {
  limit?: number;
  settingKey?: string;
  sourceKey?: string;
  scope?: string;
  action?: string;
  actor?: string;
  query?: string;
  days?: number;
}

const SOURCE_VISUALS: Record<string, { icon: string; color: string }> = {
  fred: { icon: "LineChart", color: "#3b82f6" },
  openbb: { icon: "BarChart3", color: "#f59e0b" },
  jin10_mcp: { icon: "Newspaper", color: "#06b6d4" },
  cme_bulletin: { icon: "FileText", color: "#f97316" },
  treasury: { icon: "Landmark", color: "#10b981" },
  fed_prates: { icon: "Landmark", color: "#22c55e" },
};

export function sourceStatusTone(source: SettingsDataSource): FAStatusTone {
  if (source.status === "CONNECTED") return "up";
  if (source.status === "UNKNOWN") return "warn";
  return "dim";
}

export async function fetchSettingsData(): Promise<SettingsData> {
  const raw = await fetchJson<SettingsStatusApiResponse>("/api/settings/status");
  return {
    status: raw.status ?? "available",
    source: raw.source ?? "api",
    preferences: (raw.preferences ?? []).map(mapPreference),
    sources: (raw.sources ?? []).map(mapSource),
    globalConfig: (raw.global_config ?? []).map((item) => ({
      label: asString(item.label),
      value: asString(item.value),
    })),
    systemInfo: (raw.system_info ?? []).map((item) => ({
      label: asString(item.label),
      value: asString(item.value),
    })),
  };
}

export async function updateSettingsPreferences(
  payload: SettingsPreferencesUpdatePayload,
): Promise<SettingsActionResponse> {
  return fetchJson<SettingsActionResponse>("/api/settings/preferences", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateSettingsSource(
  sourceKey: string,
  payload: SettingsSourceUpdatePayload,
): Promise<SettingsActionResponse> {
  return fetchJson<SettingsActionResponse>(`/api/settings/sources/${sourceKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function resetSettingsPreferences(
  payload: SettingsPreferencesResetPayload,
): Promise<SettingsActionResponse> {
  return fetchJson<SettingsActionResponse>("/api/settings/preferences/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function resetSettingsSource(
  sourceKey: string,
  payload: SettingsSourceResetPayload,
): Promise<SettingsActionResponse> {
  return fetchJson<SettingsActionResponse>(`/api/settings/sources/${sourceKey}/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchSettingsHistory(filters: SettingsHistoryFilters = {}): Promise<SettingsHistoryEntry[]> {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit ?? 12));
  if (filters.settingKey) params.set("setting_key", filters.settingKey);
  if (filters.sourceKey) params.set("source_key", filters.sourceKey);
  if (filters.scope) params.set("scope", filters.scope);
  if (filters.action) params.set("action", filters.action);
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.query) params.set("q", filters.query);
  if (typeof filters.days === "number") params.set("days", String(filters.days));
  const raw = await fetchJson<SettingsHistoryApiResponse>(`/api/settings/history?${params.toString()}`);
  return (raw.events ?? []).map((item) => ({
    settingKey: asString(item.setting_key),
    scope: asString(item.scope),
    sourceKey: typeof item.source_key === "string" ? item.source_key : null,
    action: asString(item.action),
    oldValueJson: asObject(item.old_value_json),
    newValueJson: asObject(item.new_value_json),
    actor: typeof item.actor === "string" ? item.actor : null,
    reason: typeof item.reason === "string" ? item.reason : null,
    requestId: typeof item.request_id === "string" ? item.request_id : null,
    auditId: typeof item.audit_id === "string" ? item.audit_id : null,
    createdAt: typeof item.created_at === "string" ? item.created_at : null,
  }));
}

export async function updateSettingsSecret(
  sourceKey: string,
  payload: SettingsSecretUpdatePayload,
): Promise<SettingsActionResponse> {
  return fetchJson<SettingsActionResponse>(`/api/settings/secrets/${sourceKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function resetSettingsSecret(
  sourceKey: string,
  payload: SettingsSecretResetPayload,
): Promise<SettingsActionResponse> {
  return fetchJson<SettingsActionResponse>(`/api/settings/secrets/${sourceKey}/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function rollbackSettingsEvent(
  auditId: string,
  payload: SettingsRollbackPayload,
): Promise<SettingsActionResponse> {
  return fetchJson<SettingsActionResponse>(`/api/settings/history/${auditId}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function mapPreference(value: Record<string, unknown>): SettingsPreferenceItem {
  return {
    key: asPreferenceKey(value.key),
    label: asString(value.label),
    value: asString(value.value),
    options: Array.isArray(value.options) ? value.options.map((item) => String(item)) : [],
  };
}

function mapSource(value: Record<string, unknown>): SettingsDataSource {
  const id = asString(value.id);
  const visuals = SOURCE_VISUALS[id] ?? { icon: "BarChart3", color: "#64748b" };
  return {
    id,
    name: asString(value.name),
    description: asString(value.description),
    icon: visuals.icon,
    color: visuals.color,
    enabled: Boolean(value.enabled),
    defaultEnabled: Boolean(value.default_enabled),
    isOverridden: Boolean(value.is_overridden),
    status: asStatus(value.status),
    apiKeyMasked: typeof value.api_key_masked === "string" ? value.api_key_masked : null,
    secretConfigured: Boolean(value.secret_configured),
    secretLastUpdatedAt: typeof value.secret_last_updated_at === "string" ? value.secret_last_updated_at : null,
    secretWritable: Boolean(value.secret_writable),
  };
}

function asPreferenceKey(value: unknown): SettingsPreferenceItem["key"] {
  if (value === "language" || value === "timezone" || value === "report_template") {
    return value;
  }
  return "language";
}

function asStatus(value: unknown): SettingsSourceStatus {
  if (value === "CONNECTED" || value === "DISCONNECTED" || value === "UNKNOWN") {
    return value;
  }
  return "UNKNOWN";
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}
