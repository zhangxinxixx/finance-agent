const DEFAULT_API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";

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

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
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
