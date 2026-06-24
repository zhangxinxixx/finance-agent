import type { DataStatus, SourceRef } from "@/types/common";

export type SettingsSourceStatus = "CONNECTED" | "DISCONNECTED" | "UNAVAILABLE";

export interface SettingsSourceViewModel {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  status: SettingsSourceStatus;
  apiKeyMasked?: string;
  source_refs: SourceRef[];
}

export interface SettingsViewModel {
  status: DataStatus;
  source: "api" | "mock" | "unavailable";
  updated_at?: string | null;
  sources: SettingsSourceViewModel[];
  globalConfig: Array<{ label: string; value: string }>;
  systemInfo: Array<{ label: string; value: string }>;
  has_data: boolean;
  source_refs: SourceRef[];
}
