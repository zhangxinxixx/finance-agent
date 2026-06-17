import { fetchJson } from "@/adapters/apiClient";
import type { FeishuMonitorResponse } from "@/types/feishu-monitor";

export async function fetchFeishuJin10MessageMonitor(date: string): Promise<FeishuMonitorResponse> {
  const params = new URLSearchParams({ date });
  return fetchJson<FeishuMonitorResponse>(`/api/news/feishu-jin10/messages?${params.toString()}`);
}
