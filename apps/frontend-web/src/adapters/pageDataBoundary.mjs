const FRONTEND_ORIGIN = "http://finance-agent.local";

const LOWER_LAYER_PATTERNS = [
  /\/(?:raw|parsed|ods|dwd)(?:\/|$)/i,
  /\/(?:artifact|artifacts|download|files?)(?:\/|$)/i,
  /^\/api\/source-trace\/by-artifact(?:\/|$)/i,
  /^\/api\/runs\/[^/]+\/(?:artifacts|logs|events|steps)(?:\/|$)/i,
  /^\/api\/reports\/[^/]+\/analysis-inputs(?:\/|$)/i,
  /^\/api\/jin10\/(?:flash|calendar)(?:\/|$)/i,
  /^\/api\/news\/feishu-jin10\/messages(?:\/|$)/i,
  /^\/api\/llm\/audits\/[^/]+(?:\/|$)/i,
];

const PRESENTATION_PREFIXES = [
  "/api/dashboard/",
  "/api/live-strategy/",
  "/api/strategy-cards",
  "/api/source-trace/by-strategy/",
  "/api/final-report",
  "/api/reports",
  "/api/options/",
  "/api/jin10/daily-report",
  "/api/jin10/report-bundle",
  "/api/jin10/weekly-report",
  "/api/jin10/web-flash-briefs/",
  "/api/events/",
  "/api/gold/",
  "/api/market/",
  "/api/market-odds/",
  "/api/macro/",
  "/api/knowledge/",
  "/api/playbooks",
  "/api/agent-analysis",
];

const OPERATIONS_PREFIXES = [
  "/api/data-status/",
  "/api/ingestion/",
  "/api/governance/",
  "/api/agents/",
  "/api/settings/",
  "/api/scheduler/",
  "/api/tasks/",
  "/api/runs",
  "/api/reviews",
  "/api/orchestration/",
  "/api/shadow-evaluation/",
  "/api/processing/",
  "/api/llm/audits",
  "/dagster/graphql",
];

function parseRequestUrl(input) {
  const raw = typeof input === "string" ? input.trim() : "";
  if (!raw) return null;
  try {
    const url = new URL(raw, FRONTEND_ORIGIN);
    if (url.origin !== FRONTEND_ORIGIN) return null;
    return url;
  } catch {
    return null;
  }
}

function hasView(url, value) {
  return url.searchParams.get("view") === value;
}

export function classifyPageRequest(input) {
  const url = parseRequestUrl(input);
  if (!url) return { allowed: false, layer: "blocked", reason: "external-or-invalid" };
  let path;
  try {
    path = decodeURIComponent(url.pathname);
  } catch {
    return { allowed: false, layer: "blocked", reason: "external-or-invalid" };
  }

  if (LOWER_LAYER_PATTERNS.some((pattern) => pattern.test(path))) {
    return { allowed: false, layer: "blocked", reason: "lower-layer-content" };
  }

  if (path === "/api/data-sources/status") {
    return hasView(url, "ads")
      ? { allowed: true, layer: "ads", reason: "operations-summary" }
      : { allowed: false, layer: "blocked", reason: "ads-view-required" };
  }

  if (path.startsWith("/api/processing/")) {
    return hasView(url, "ads")
      ? { allowed: true, layer: "ads", reason: "operations-summary" }
      : { allowed: false, layer: "blocked", reason: "ads-view-required" };
  }

  if (/^\/api\/runs(?:\/[^/]+)?$/.test(path)) {
    return hasView(url, "ads")
      ? { allowed: true, layer: "ads", reason: "operations-summary" }
      : { allowed: false, layer: "blocked", reason: "ads-view-required" };
  }

  if (PRESENTATION_PREFIXES.some((prefix) => matchesPrefix(path, prefix))) {
    const layer = path.startsWith("/api/reports") || path.startsWith("/api/final-report")
      ? "output"
      : "dws";
    return { allowed: true, layer, reason: "page-read-model" };
  }

  if (OPERATIONS_PREFIXES.some((prefix) => matchesPrefix(path, prefix))) {
    return { allowed: true, layer: "ads", reason: "operations-summary" };
  }

  return { allowed: false, layer: "blocked", reason: "unclassified-endpoint" };
}

function matchesPrefix(path, prefix) {
  return prefix.endsWith("/") ? path.startsWith(prefix) : path === prefix || path.startsWith(`${prefix}/`);
}

export function assertPageRequestAllowed(input) {
  const classification = classifyPageRequest(input);
  if (!classification.allowed) {
    const error = new Error(`页面请求被数据边界阻止：${classification.reason}`);
    error.name = "PageDataBoundaryError";
    error.reason = classification.reason;
    throw error;
  }
  return classification;
}

const SAFE_EVIDENCE_KEYS = new Set([
  "label", "name", "source_name", "provider", "source", "status", "data_status", "quality_status",
  "trade_date", "data_date", "as_of", "asOf", "generated_at", "updated_at", "published_at",
  "run_id", "snapshot_id", "final_result_id", "version", "model_version", "review_status",
  "lifecycle_status", "reason", "reasons", "warnings", "progress", "duration_ms", "retry_count",
  "count", "source_count", "available_count", "partial_count", "error_count", "source_url", "url",
]);

function safeExternalUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

function safePrimitive(value) {
  if (typeof value !== "string") return value;
  return /(?:^|\b)storage\/|(?:^|\/)(?:raw|parsed|ods|dwd|artifacts?)(?:\/|$)|^\/api\//i.test(value)
    ? null
    : value;
}

function safeEvidenceValue(key, value, depth) {
  if (key === "source_url" || key === "url") return safeExternalUrl(value);
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") return safePrimitive(value);
  if (Array.isArray(value) && depth < 2) {
    return value
      .map((item) => typeof item === "object" && item !== null ? summarizeEvidenceRecord(item, depth + 1) : safePrimitive(item))
      .filter((item) => item !== null && ["string", "number", "boolean", "object"].includes(typeof item));
  }
  return null;
}

export function summarizeEvidenceRecord(record, depth = 0) {
  if (record === null || record === undefined) return null;
  if (typeof record === "string" || typeof record === "number" || typeof record === "boolean") return safePrimitive(record);
  if (Array.isArray(record)) {
    const values = record.map((item) => summarizeEvidenceRecord(item, depth + 1)).filter((item) => item !== null);
    return values.length ? values : null;
  }
  if (typeof record !== "object" || depth > 2) return null;

  const summary = {};
  for (const [key, value] of Object.entries(record)) {
    if (!SAFE_EVIDENCE_KEYS.has(key)) continue;
    const safeValue = safeEvidenceValue(key, value, depth);
    if (safeValue !== null && safeValue !== "") summary[key] = safeValue;
  }
  return Object.keys(summary).length ? summary : null;
}
