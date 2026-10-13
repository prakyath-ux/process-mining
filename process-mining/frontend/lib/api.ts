/** Typed API client with JWT auth (token in localStorage; sent as Bearer). */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "pm_token";
const USER_KEY = "pm_user";

export type Role = "admin" | "analyst" | "viewer";

export interface SessionUser {
  id: number;
  email: string;
  role: Role;
}

export interface LogSummary {
  id: number;
  name: string;
  description: string;
  source_type: string;
  source_detail: string;
  case_count: number;
  event_count: number;
  activity_count: number;
  start_time: string | null;
  end_time: string | null;
  status: string;
  created_at: string;
}

export interface DurationStat {
  count: number;
  avg_s: number;
  min_s: number;
  max_s: number;
  p50_s: number;
  p90_s: number;
}

export interface MapNode {
  id: string;
  label: string;
  kind: "activity" | "start" | "end";
  count: number;
  starts?: number;
  ends?: number;
  wait?: DurationStat | null;
  active?: DurationStat | null;
  bottleneck?: number;
}

export interface MapEdge {
  source: string;
  target: string;
  count: number;
  share: number;
  duration: DurationStat | null;
}

export interface ProcessMap {
  log: { id: number; name: string };
  nodes: MapNode[];
  edges: MapEdge[];
  bottleneck_scores: Record<string, number>;
  stats: {
    log_id: number;
    case_count: number;
    event_count: number;
    activity_count: number;
    variant_count: number;
    start_time: string | null;
    end_time: string | null;
    case_durations: Record<string, number>;
  };
}

export interface Variant {
  rank: number;
  activities: string[];
  length: number;
  cases: number;
  share: number;
  cumulative_share?: number;
}

export interface VariantsResponse {
  total_variants: number;
  case_count: number;
  pareto_80_variant_count: number;
  variants: Variant[];
}

export interface BottleneckRow {
  activity: string;
  score: number;
  count: number;
  wait: DurationStat | null;
}

export interface BottlenecksResponse {
  bottlenecks: BottleneckRow[];
  case_durations: Record<string, number>;
  total_activities: number;
}

export interface ModelSummary {
  id: number;
  name: string;
  miner: string;
  created_at?: string;
}

export interface ConformanceResult {
  model_id: number;
  model_name: string;
  cases_checked: number;
  max_cases: number | null;
  perfect_fits: number;
  non_conforming: number;
  conformance_rate: number;
  avg_fitness: number;
  total_log_moves: number;
  total_visible_model_moves: number;
  worst_cases: {
    fitness: number;
    cost: number;
    conforming: boolean;
    log_moves: number;
    visible_model_moves: number;
    silent_moves: number;
  }[];
}

export interface AttrInfo {
  key: string;
  samples: string[];
  numeric: boolean;
  events_with_key: number;
}

export interface BreakdownRow {
  value: string;
  cases: number;
  avg_duration_s: number;
  p50_duration_s: number;
  p90_duration_s: number;
  top_waits: { activity: string; avg_wait_s: number; p90_wait_s: number; events: number }[];
}

export interface BreakdownResponse {
  attribute: string;
  values: BreakdownRow[];
  truncated: boolean;
  max_values: number;
}

export interface HandoverResponse {
  actor_attr: string;
  nodes: { id: string; events: number; top_activities: { activity: string; count: number }[] }[];
  edges: { source: string; target: string; count: number; avg_wait_s: number; p50_wait_s: number }[];
  actors: number;
  handovers: number;
}

export interface TimelineResponse {
  cases: { case_id: string; events: { activity: string; ts: string }[] }[];
  total_cases: number;
  sampled_cases: number;
  activities: string[];
}

export interface CaseSummary {
  case_id: string;
  events: number;
  start?: string;
  end?: string;
  first?: string;
  last_activity?: string;
  start_activity?: string;
}

export interface CaseSearchResponse {
  cases: CaseSummary[];
  variant?: string[];
  total_matching: number;
  returned: number;
}

export interface CaseTrace {
  case_id: string;
  events: { activity: string; timestamp: string; lifecycle: string | null; attrs: Record<string, unknown> | null }[];
}

export interface GlobalModel {
  id: number;
  name: string;
  miner: string;
  log_id: number;
  log_name: string | null;
  created_at: string;
}

export interface AuditRow {
  id: number;
  user_email: string | null;
  action: string;
  resource: string;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): SessionUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as SessionUser) : null;
}

export function setSession(token: string, user: SessionUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined") {
    clearSession();
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
      throw new ApiError(401, "Session expired");
    }
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),

  async login(email: string, password: string): Promise<SessionUser> {
    const form = new URLSearchParams({ username: email, password });
    const res = await fetch(`${API_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
    if (!res.ok) throw new ApiError(res.status, "Invalid email or password");
    const data = (await res.json()) as { access_token: string; role: Role; email: string };
    const user: SessionUser = { id: 0, email: data.email, role: data.role };
    setSession(data.access_token, user);
    return user;
  },
};

/** Filter state shared by the analytics tabs. */
export interface LogFilters {
  start?: string; // ISO datetime
  end?: string;
  attr?: string;
  attr_value?: string;
}

export function qs(filters?: LogFilters, extra?: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  if (filters?.start) params.set("start", filters.start);
  if (filters?.end) params.set("end", filters.end);
  if (filters?.attr && filters?.attr_value) {
    params.set("attr", filters.attr);
    params.set("attr_value", filters.attr_value);
  }
  for (const [k, v] of Object.entries(extra ?? {})) {
    if (v !== undefined && v !== "") params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

/** Format seconds as human-friendly duration. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export function fmtNumber(n: number): string {
  return n.toLocaleString("en-US");
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
