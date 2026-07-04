import { ApiError, fetchJson } from "@/adapters/apiClient";
import type { Jin10WebFlashBriefsResponse } from "@/types/jin10-web-flash";

const JIN10_WEB_FLASH_BRIEFS_PATH = "/api/jin10/web-flash-briefs/latest";

export interface FetchJin10WebFlashBriefsResult {
  data: Jin10WebFlashBriefsResponse | null;
  isEmpty: boolean;
  error: string | null;
}

export async function fetchJin10WebFlashBriefs(): Promise<FetchJin10WebFlashBriefsResult> {
  try {
    const data = await fetchJson<Jin10WebFlashBriefsResponse>(JIN10_WEB_FLASH_BRIEFS_PATH);
    return { data, isEmpty: data.briefs.length === 0, error: null };
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      return { data: null, isEmpty: true, error: null };
    }
    const message = cause instanceof Error ? cause.message : "加载金十 Web 快讯失败";
    return { data: null, isEmpty: false, error: message };
  }
}
