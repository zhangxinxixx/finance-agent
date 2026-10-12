import { assertPageRequestAllowed } from "@/adapters/pageDataBoundary.mjs";

const DEFAULT_API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
const CONFIGURED_DAGSTER_URL = import.meta.env.VITE_DAGSTER_GRAPHQL_URL?.trim();

export class ApiError extends Error {
  readonly status: number | null;
  readonly url: string;
  readonly responseBody: string | null;
  readonly cause?: unknown;

  constructor(message: string, options: { status?: number | null; url: string; responseBody?: string | null; cause?: unknown }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? null;
    this.url = options.url;
    this.responseBody = options.responseBody ?? null;
    if (options.cause !== undefined) {
      this.cause = options.cause;
    }
  }
}

function joinApiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!DEFAULT_API_BASE_URL) {
    return normalizedPath;
  }

  return `${DEFAULT_API_BASE_URL.replace(/\/$/, "")}${normalizedPath}`;
}

async function readResponseBody(response: Response): Promise<string | null> {
  try {
    return await response.text();
  } catch {
    return null;
  }
}

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  // A configured Dagster transport still uses the same classified operations contract.
  assertPageRequestAllowed(CONFIGURED_DAGSTER_URL && path === CONFIGURED_DAGSTER_URL ? "/dagster/graphql" : path);
  const url = joinApiUrl(path);

  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    headers.set("Accept", "application/json");
    response = await fetch(url, {
      ...init,
      headers,
    });
  } catch (cause) {
    throw new ApiError(`请求 ${path} 失败`, { url, cause });
  }

  if (!response.ok) {
    const responseBody = await readResponseBody(response);
    throw new ApiError(`请求 ${path} 失败 (${response.status})`, {
      status: response.status,
      url,
      responseBody,
    });
  }

  const responseClone = response.clone();
  try {
    return (await response.json()) as T;
  } catch (cause) {
    const responseBody = await readResponseBody(responseClone);
    throw new ApiError(`解析 ${path} JSON 失败`, {
      url,
      responseBody,
      cause,
    });
  }
}

/** Covers fetch and body decoding, including transports that ignore abort. */
export async function fetchJson<T>(path: string, init?: RequestInit, timeoutMs = 45_000): Promise<T> {
  const url = joinApiUrl(path);
  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let cancel: (() => void) | undefined;
  const stopped = new Promise<never>((_, reject) => {
    cancel = () => {
      controller.abort(init?.signal?.reason);
      reject(new ApiError(`请求 ${path} 已取消`, { url, cause: init?.signal?.reason }));
    };
    if (init?.signal?.aborted) cancel();
    else init?.signal?.addEventListener("abort", cancel, { once: true });
    timeout = setTimeout(() => {
      controller.abort();
      reject(new ApiError(`请求 ${path} 超时，请重试`, { url }));
    }, timeoutMs);
  });
  try {
    if (init?.signal?.aborted) return await stopped;
    return await Promise.race([stopped, readJson<T>(path, { ...init, signal: controller.signal })]);
  } finally {
    clearTimeout(timeout);
    if (cancel) init?.signal?.removeEventListener("abort", cancel);
  }
}
