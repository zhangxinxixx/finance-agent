import { fetchJson } from "@/adapters/apiClient";
import type { FeishuMonitorResponse } from "@/types/feishu-monitor";

export async function fetchFeishuJin10MessageMonitorDates(): Promise<string[]> {
  const payload = await fetchJson<{ dates?: string[] }>("/api/news/feishu-jin10/dates");
  return Array.isArray(payload.dates) ? payload.dates.filter((value): value is string => typeof value === "string" && value.length > 0) : [];
}

export async function fetchFeishuJin10MessageMonitor(date: string): Promise<FeishuMonitorResponse> {
  const params = new URLSearchParams({ date });
  return fetchJson<FeishuMonitorResponse>(`/api/news/feishu-jin10/messages?${params.toString()}`);
}

export async function fetchLatestFeishuJin10MessageMonitor(): Promise<FeishuMonitorResponse> {
  return fetchJson<FeishuMonitorResponse>("/api/news/feishu-jin10/messages/latest");
}
