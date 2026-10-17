export type RiskState = 'NORMAL' | 'WATCH' | 'WARNING' | 'CRITICAL'
export type ConnectivityState = 'ONLINE' | 'STALE' | 'OFFLINE'

export interface NodeRecord {
  node_id: string
  name: string
  latitude: number | null
  longitude: number | null
  location: string | null
  latest_reading_at: string | null
  latest_temperature_c: number | null
  latest_humidity_percent: number | null
  latest_smoke_value: number | null
  latest_gas_value: number | null
  latest_temperature_available: boolean
  latest_humidity_available: boolean
  latest_smoke_available: boolean
  last_seen_at: string | null
  battery_percent: number | null
  latest_is_simulated: boolean
  current_risk_state: RiskState | null
  current_risk_score: number | null
  current_risk_reasons: string[] | null
  risk_assessed_at: string | null
  connectivity_state: ConnectivityState
}

export interface ReadingRecord {
  id: number
  node_id: string
  temperature_c: number | null
  humidity_percent: number | null
  smoke_value: number | null
  gas_value: number | null
  timestamp: string
  received_at: string
  is_simulated: boolean
  risk_state: RiskState | null
  risk_score: number | null
  risk_reasons: string[] | null
  risk_signals: Array<{ name: string; domain: string; available: boolean; value: number | null; triggered: boolean; points: number; detail: string }> | null
  assessment_timestamp: string | null
  connectivity_state: ConnectivityState | null
}

export interface AlertRecord {
  alert_id: string
  node_id: string
  severity: Exclude<RiskState, 'NORMAL'>
  risk_score: number
  reasons: string[]
  created_at: string
  updated_at: string
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED'
  is_simulated: boolean
}

export interface AlertSummary {
  active: number
  acknowledged: number
  resolved: number
  by_severity: Record<string, number>
}

export interface Page<T> {
  items: T[]
  limit: number
  offset: number
}

export interface DashboardData {
  nodes: NodeRecord[]
  readings: ReadingRecord[]
  alerts: AlertRecord[]
  summary: AlertSummary
  health: { status: string; database: string } | null
}

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')
const healthUrl = apiBase.startsWith('/') ? '/health' : new URL('/health', apiBase).toString()

async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    throw new Error(`ForestGuard API returned ${response.status} for ${path}`)
  }
  return (await response.json()) as T
}

export async function loadDashboard(signal: AbortSignal): Promise<DashboardData> {
  const [nodes, readings, alerts, summary, health] = await Promise.all([
    getJson<NodeRecord[]>('/nodes?limit=200&offset=0', signal),
    getJson<Page<ReadingRecord>>('/readings?limit=200&offset=0', signal),
    getJson<Page<AlertRecord>>('/alerts?limit=100&offset=0', signal),
    getJson<AlertSummary>('/alerts/summary', signal),
    fetch(healthUrl, { headers: { Accept: 'application/json' }, signal }).then(async (response) => {
      if (!response.ok) throw new Error(`ForestGuard health check returned ${response.status}`)
      return await response.json() as { status: string; database: string }
    }).catch(() => null),
  ])

  return {
    nodes,
    readings: readings.items,
    alerts: alerts.items,
    summary,
    health,
  }
}

export async function acknowledgeAlert(
  alertId: string,
  operatorToken: string,
  signal?: AbortSignal,
): Promise<AlertRecord> {
  const response = await fetch(`${apiBase}/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
    method: 'POST',
    headers: { Accept: 'application/json', Authorization: `Bearer ${operatorToken}` },
    signal,
  })
  if (response.status === 401) {
    throw new Error('Operator token was not accepted. Check it and try again.')
  }
  if (response.status === 503) {
    throw new Error('Operator authorization is not configured on the backend.')
  }
  if (!response.ok) throw new Error(`Could not acknowledge alert (${response.status})`)
  return await response.json() as AlertRecord
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}
