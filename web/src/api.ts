// API client: admin token lives in localStorage (set on first load / Settings).

const TOKEN_KEY = "tollgate-admin-token";
const EXPIRY_KEY = "tollgate-admin-token-exp";

/** Remembered token (localStorage, 30-day expiry) or session-only
 * (sessionStorage, dies with the window). Entries written before expiry
 * tracking exist have no expiry key and stay valid. */
export function getToken(): string {
  const remembered = localStorage.getItem(TOKEN_KEY) ?? "";
  if (remembered) {
    const exp = Number(localStorage.getItem(EXPIRY_KEY) ?? 0);
    if (exp && Date.now() > exp) {
      clearToken();
      return "";
    }
    return remembered;
  }
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string, rememberDays = 30) {
  clearToken();
  if (rememberDays > 0) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(EXPIRY_KEY, String(Date.now() + rememberDays * 86_400_000));
  } else {
    sessionStorage.setItem(TOKEN_KEY, token);
  }
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EXPIRY_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Server-reachability tracking: fetch throws TypeError on network failure
// (connection refused / server stopped). Any HTTP response — even a 401 —
// means the server is up. Transitions dispatch a "tollgate-conn" event that
// App listens to for the "server unreachable" banner.

let serverUp = true;

export function isServerUp(): boolean {
  return serverUp;
}

function setServerUp(up: boolean) {
  if (up !== serverUp) {
    serverUp = up;
    window.dispatchEvent(new CustomEvent("tollgate-conn", { detail: { up } }));
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let resp: Response;
  try {
    resp = await fetch(path, { ...init, headers });
    setServerUp(true);
  } catch {
    setServerUp(false);
    throw new ApiError(0, "Cannot reach the Tollgate server — is `tollgate serve` running?");
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  download: (path: string) => window.open(withToken(path), "_blank"),
};

/** EventSource can't set headers — the SSE endpoint accepts ?token=. */
export function withToken(path: string): string {
  const token = getToken();
  if (!token) return path;
  return path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
}

// ---------------------------------------------------------------- types

export interface VirtualKey {
  id: string;
  prefix: string;
  name: string;
  project: string | null;
  status: "active" | "disabled" | "blocked" | "expired";
  blocked_reason: string | null;
  created_at: string;
  expires_at: string | null;
  rotated_from: string | null;
  notes: string | null;
  allowed_providers: string[] | null;
  allowed_models_aliases: string[] | null;
  has_stored_plaintext: boolean;
  plaintext?: string; // only on create/rotate
}

export interface LimitRule {
  id: number;
  key_id: string | null;
  metric: string;
  window: string;
  value: number;
  action: "reject" | "warn";
  auto_block: boolean;
}

export interface Provider {
  id: number;
  type: string;
  name: string;
  base_url: string;
  has_key: boolean;
  enabled: boolean;
  timeout_s: number;
  retries: number;
  notes: string | null;
}

export interface Alias {
  id: number;
  alias_name: string;
  provider_id: number;
  upstream_model: string;
  fallbacks: { provider_id: number; upstream_model: string }[];
  enabled: boolean;
}

export interface PriceBand {
  id: number;
  model: string;
  effective_from: string;
  effective_until: string | null;
  price_in_per_1m: number;
  price_out_per_1m: number;
  price_cache_read_per_1m: number;
  price_cache_write_per_1m: number;
  context_window: number | null;
  source: string;
}

export interface PriceDiff {
  model: string;
  kind: "changed" | "new";
  old_in_per_1m: number;
  new_in_per_1m: number;
  old_out_per_1m: number;
  new_out_per_1m: number;
  old_cache_read_per_1m: number;
  new_cache_read_per_1m: number;
}

export interface LogRow {
  id: string;
  instance_id: string;
  ts: string;
  key_id: string | null;
  key: string | null;
  project: string | null;
  provider: string | null;
  model: string | null;
  alias_used: string | null;
  endpoint: string;
  status_code: number | null;
  latency_total_ms: number | null;
  upstream_ms: number | null;
  tokens_in: number;
  tokens_out: number;
  cache_read: number;
  cache_write: number;
  cost_usd: number;
  price_band_id: number | null;
  is_stream: boolean;
  estimated: boolean;
  error: string | null;
  request_bytes: number | null;
  response_bytes: number | null;
  client_ip: string | null;
  fallback_hops: { provider: string; status?: number; error?: string }[] | null;
  request_preview: string | null;
  response_preview: string | null;
}

export interface Stats {
  range: { from: string; to: string; granularity: string };
  summary: {
    requests: number;
    tokens_in: number;
    tokens_out: number;
    tokens_cached: number;
    cost_usd: number;
    error_rate: number;
    overhead_p50_ms: number | null;
    overhead_p95_ms: number | null;
  };
  series: {
    bucket: string;
    requests: number;
    tokens_in: number;
    tokens_out: number;
    tokens_cached: number;
    cost_usd: number;
    errors: number;
    avg_latency_ms: number | null;
    avg_upstream_ms: number | null;
  }[];
  top_keys: { name: string; requests: number; cost_usd: number }[];
  top_models: { name: string; requests: number; cost_usd: number }[];
  top_providers: { name: string; requests: number; cost_usd: number }[];
}

// ---------------------------------------------------------------- formats

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  if (n >= 1_000_000) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1e3).toFixed(1) + "k";
  return String(Math.round(n * 100) / 100);
}

export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  if (n === 0) return "$0";
  if (n < 0.01) return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}

export function fmtMs(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  if (n < 1) return n.toFixed(2) + " ms";
  return Math.round(n) + " ms";
}

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
