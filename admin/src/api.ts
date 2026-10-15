// Тонкая обёртка над API админки: токен в localStorage, 401 → на страницу входа.

const TOKEN_KEY = 'aw_token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* приватный режим — живём без сохранения */
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const resp = await fetch(path, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })
  if (resp.status === 401 && !path.startsWith('/api/auth/login')) {
    setToken(null)
    window.dispatchEvent(new Event('aw:logout'))
  }
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* не JSON */
    }
    throw new ApiError(resp.status, message)
  }
  return resp.json() as Promise<T>
}

// ---------- типы ответов ----------

export interface Summary {
  users: number
  dau: number
  wau: number
  new_users_24h: number
  blocked: number
  active_subscriptions: number
  searches_24h: number
  cache_hit_rate: number | null
  source_requests_24h: number
  source_errors_24h: number
  notifications_24h: number
  sources_total: number
  sources_enabled: number
  sources_down: string[]
}

export interface ActivityPoint {
  ts: string
  searches: number
  requests: number
  errors: number
  notifications: number
}

export interface SystemSample {
  ts: number
  cpu: number
  mem: number
  disk: number
  net_in_kbps: number
  net_out_kbps: number
  proc_mem_mb: number
}

export interface SourceStats {
  requests: number
  errors: number
  error_rate: number
  latency_p50_ms: number
  latency_p95_ms: number
  avg_offers: number
}

export interface SourceInfo {
  name: string
  title: string
  method: string
  supports_calendar: boolean
  param_schema: Record<string, string>
  status: 'ok' | 'degraded' | 'down' | 'disabled'
  enabled: boolean
  priority: number
  interval_minutes: number
  rate_limit_per_min: number
  timeout_s: number
  retries: number
  proxy: string | null
  params: Record<string, unknown>
  board_x: number | null
  board_y: number | null
  consecutive_failures: number
  disabled_until: string | null
  last_success_at: string | null
  last_error: string | null
  last_error_at: string | null
  stats_24h: SourceStats
}

export interface TestResult {
  ok: boolean
  error: string | null
  elapsed_s: number
  offers: number
  sample: {
    price_rub: number
    departure_at: string
    time_known: boolean
    route: string
    flights: string[]
    transfers: number
    self_transfer: boolean | null
    link: string
    note: string | null
  }[]
}

export interface UserRow {
  id: number
  tg_id: number
  username: string | null
  first_name: string | null
  is_blocked: boolean
  max_subscriptions: number
  created_at: string
  last_seen_at: string
  subscriptions: number
  searches: number
}

export interface Subscription {
  id: number
  origin: string
  destination: string
  origin_name: string
  destination_name: string
  date_from: string
  date_to: string
  adults: number
  threshold_rub: number | null
  is_active: boolean
  last_min_price: number | null
  last_checked_at: string | null
  last_notified_at: string | null
}

export interface UserDetail {
  user: UserRow
  subscriptions: Subscription[]
  searches: { route: string; dates: string; results: number; min_price: number | null; ms: number; cached: boolean; at: string }[]
  notifications: { kind: string; ok: boolean; price: number | null; at: string }[]
}

export interface AppSettings {
  welcome_text: string
  help_text: string
  maintenance: boolean
  maintenance_text: string
  subscription_check_minutes: number
  default_max_subscriptions: number
  default_filters: Record<string, unknown>
  proxy_pools: { name: string; url: string }[]
  board_layout: Record<string, { x: number; y: number }>
}
