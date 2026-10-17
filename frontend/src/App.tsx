import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  AlertTriangle,
  Bell,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Gauge,
  Settings2,
  MapPinned,
  Menu,
  RadioTower,
  RefreshCw,
  Search,
  ShieldCheck,
  Thermometer,
  Trees,
  X,
} from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import {
  NavLink,
  Route,
  Routes,
  useLocation,
} from 'react-router'
import {
  formatTimestamp,
  loadDashboard,
  acknowledgeAlert,
  type AlertRecord,
  type DashboardData,
  type NodeRecord,
} from './api/forestguard'
import { AnalyticsPage, DevicesPage, MonitoringPage, SettingsPage } from './components/DashboardPages'

const ForestMap = lazy(() => import('./components/ForestMap'))
const RiskTelemetryChart = lazy(() => import('./components/RiskTelemetryChart'))
const EnvironmentalTrendChart = lazy(() => import('./components/EnvironmentalTrendChart'))

const navItems = [
  { to: '/', label: 'Overview', icon: Gauge },
  { to: '/monitoring', label: 'Live monitoring', icon: Activity },
  { to: '/analytics', label: 'Analytics', icon: Gauge },
  { to: '/devices', label: 'Devices', icon: RadioTower },
  { to: '/alerts', label: 'Alert center', icon: Bell },
  { to: '/settings', label: 'Settings', icon: Settings2 },
]
const EMPTY_READINGS: DashboardData['readings'] = []

function useMissionData() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const hasLoaded = useRef(false)

  const refresh = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    if (!hasLoaded.current) setLoading(true)
    try {
      const next = await loadDashboard(controller.signal)
      if (!controller.signal.aborted) {
        setData(next)
        setError(null)
        setUpdatedAt(new Date().toISOString())
        hasLoaded.current = true
      }
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : 'Unable to reach the ForestGuard API.')
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), 15_000)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
      controllerRef.current?.abort()
    }
  }, [refresh])

  return { data, loading, error, updatedAt, refresh }
}

function App() {
  const mission = useMissionData()
  const route = useLocation()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const reducedMotion = useReducedMotion()
  const connectionUnavailable = Boolean(mission.error || (mission.data && mission.data.health?.status !== 'ok'))
  const pageMotion = reducedMotion
    ? { initial: false as const, animate: { opacity: 1 } }
    : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 } }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to dashboard content</a>
      <aside className={`sidebar ${mobileNavOpen ? 'sidebar-open' : ''}`} aria-label="Main navigation">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><Trees size={22} strokeWidth={1.7} /></div>
          <div>
            <div className="brand-name">forest<span>guard</span></div>
            <div className="brand-caption">WILDLAND INTELLIGENCE</div>
          </div>
          <button className="icon-button close-mobile" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>

        <div className="workspace-label">OPERATIONS</div>
        <nav className="main-nav">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} onClick={() => setMobileNavOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              {label === 'Alert center' && mission.data?.summary.active ? (
                <span className="nav-count">{mission.data.summary.active}</span>
              ) : null}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-spacer" />
        <section className="region-card" aria-label="Monitoring region">
          <div className="region-heading"><MapPinned size={15} /> ACTIVE REGION</div>
          <strong>All stations</strong>
          <span>{mission.data?.nodes.length ?? '—'} registered stations</span>
          <div className={`region-signal ${connectionUnavailable ? 'region-offline' : ''}`}><span /> {mission.error ? 'API connection unavailable' : mission.loading ? 'Connecting to local API' : mission.data?.health?.status === 'ok' ? 'Backend health check passed' : 'Backend health unknown'}</div>
        </section>
        <div className="sidebar-foot"><CircleHelp size={15} /> Prototype monitoring interface</div>
      </aside>

      {mobileNavOpen ? <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} /> : null}

      <div className="main-column">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation">
            <Menu size={20} />
          </button>
          <div className="breadcrumb"><span>FORESTGUARD</span><ChevronRight size={14} /><strong>MISSION CONTROL</strong></div>
          <div className="topbar-right">
          <div className={`connection-pill ${connectionUnavailable ? 'connection-error' : ''}`}>
              <span className="pulse-dot" />
            {mission.error ? 'API UNAVAILABLE' : mission.loading ? 'CONNECTING' : mission.data?.health?.status === 'ok' ? 'API POLLING' : 'HEALTH UNKNOWN'}
            </div>
            <button className="refresh-button" onClick={() => void mission.refresh()} disabled={mission.loading} aria-label="Refresh dashboard data">
              <RefreshCw size={15} className={mission.loading ? 'spin' : ''} />
              <span>Refresh</span>
            </button>
            <div className="operator-avatar" title="Local operator">FG</div>
          </div>
        </header>

        <main id="main-content" className="main-content">
          <AnimatePresence mode="wait">
            <motion.div key={route.pathname} {...pageMotion} transition={{ duration: reducedMotion ? 0 : 0.22 }}>
              {mission.error && !mission.data ? (
                <ApiFailure error={mission.error} retry={() => void mission.refresh()} />
              ) : (
                <Routes>
                  <Route path="/" element={<Overview data={mission.data} loading={mission.loading} error={mission.error} updatedAt={mission.updatedAt} />} />
                  <Route path="/stations" element={<StationsPage nodes={mission.data?.nodes ?? []} loading={mission.loading} />} />
                  <Route path="/monitoring" element={<MonitoringPage nodes={mission.data?.nodes ?? []} readings={mission.data?.readings ?? []} />} />
                  <Route path="/analytics" element={<AnalyticsPage nodes={mission.data?.nodes ?? []} readings={mission.data?.readings ?? EMPTY_READINGS} updatedAt={mission.updatedAt} />} />
                  <Route path="/devices" element={<DevicesPage nodes={mission.data?.nodes ?? []} />} />
                  <Route path="/settings" element={<SettingsPage health={mission.data?.health ?? null} />} />
                  <Route path="/alerts" element={<AlertsPage alerts={mission.data?.alerts ?? []} summary={mission.data?.summary} loading={mission.loading} onAcknowledged={mission.refresh} />} />
                  <Route path="*" element={<Overview data={mission.data} loading={mission.loading} error={mission.error} updatedAt={mission.updatedAt} />} />
                </Routes>
              )}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  )
}

function PageHeading({ eyebrow, title, detail, trailing }: { eyebrow: string; title: string; detail: string; trailing?: ReactNode }) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-line" />{eyebrow}</div>
        <h1>{title}</h1>
        <p>{detail}</p>
      </div>
      {trailing}
    </div>
  )
}

function Overview({ data, loading, error, updatedAt }: { data: DashboardData | null; loading: boolean; error: string | null; updatedAt: string | null }) {
  const nodes = data?.nodes ?? []
  const alerts = data?.alerts ?? []
  const readings = data?.readings ?? EMPTY_READINGS
  const online = nodes.filter((node) => node.connectivity_state === 'ONLINE').length
  const risks = nodes.filter((node) => node.current_risk_state && node.current_risk_state !== 'NORMAL').length
  const peak = nodes.reduce<NodeRecord | null>((highest, node) => {
    if (node.current_risk_score === null) return highest
    return !highest || (highest.current_risk_score ?? -1) < node.current_risk_score ? node : highest
  }, null)
  const chartData = useMemo(() => readings
    .filter((reading) => reading.risk_score !== null)
    .slice()
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
    .slice(-24)
    .map((reading) => ({ time: formatTimestamp(reading.timestamp), timeMs: Date.parse(reading.timestamp), score: reading.risk_score, node: reading.node_id, simulated: reading.is_simulated })), [readings])
  const environmentalData = useMemo(() => readings.slice().sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp)).slice(-48).map((reading) => ({ timestamp: reading.timestamp, temperature: reading.temperature_c, humidity: reading.humidity_percent, nodeId: reading.node_id, simulated: reading.is_simulated })), [readings])
  const recentReadings = readings.slice().sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp)).slice(0, 6)
  const recentAlerts = alerts.filter((alert) => alert.status !== 'RESOLVED').slice(0, 5)

  return (
    <>
      <PageHeading
        eyebrow="REGIONAL OVERVIEW"
        title="Regional overview"
        detail="A live view of station health, environmental telemetry, and active risk assessments."
        trailing={<div className="updated-label"><Clock3 size={14} /><span>{updatedAt ? `Updated ${formatTimestamp(updatedAt)}` : 'Waiting for first sync'}</span></div>}
      />
      {error ? <div className="inline-warning" role="status"><AlertTriangle size={15} /> Refresh failed. Showing the last successful API response.</div> : null}

      <section className="stat-grid" aria-label="Network summary">
        <StatCard label="Registered stations" value={loading && !data ? '—' : String(nodes.length)} detail={`${online} reporting online`} icon={RadioTower} accent="cyan" />
        <StatCard label="Active alerts" value={loading && !data ? '—' : String(data?.summary.active ?? 0)} detail={`${data?.summary.acknowledged ?? 0} acknowledged`} icon={Bell} accent="amber" />
        <StatCard label="Elevated risk" value={loading && !data ? '—' : String(risks)} detail={nodes.length ? `${nodes.filter((node) => node.current_risk_state === null).length} stations unassessed` : 'No stations in registry'} icon={Activity} accent="red" />
        <StatCard label="Peak assessment" value={peak?.current_risk_score === null || !peak ? '—' : `${peak.current_risk_score}`} detail={peak ? `${peak.node_id} · ${peak.current_risk_state ?? 'Unassessed'}` : 'No assessment data'} icon={ShieldCheck} accent="violet" />
      </section>

      <section className="dashboard-grid">
        <div className="panel map-panel">
          <PanelHeader title="Station network" subtitle="Mapped from station coordinates" icon={MapPinned} action={<NavLink className="text-link" to="/stations">All stations <ChevronRight size={14} /></NavLink>} />
          <Suspense fallback={<div className="map-loading">Loading station map…</div>}><ForestMap nodes={nodes} /></Suspense>
          <div className="map-legend"><span><i className="legend-dot online" />Online</span><span><i className="legend-dot stale" />Stale</span><span><i className="legend-dot offline" />Offline</span><span><i className="legend-dot simulated" />Simulated</span></div>
        </div>

        <div className="panel telemetry-panel">
          <PanelHeader title="Risk telemetry" subtitle="Persisted assessment scores · latest 24 readings" icon={Activity} action={<span className="chart-unit">SCORE / 100</span>} />
          {chartData.length ? (
            <Suspense fallback={<div className="chart-loading">Loading telemetry visualization…</div>}>
              <RiskTelemetryChart data={chartData} />
            </Suspense>
          ) : <EmptyState icon={Activity} title="No risk telemetry yet" detail="Risk history will appear after sensor readings have been assessed by the backend." />}
          <div className="telemetry-footer"><span><i className="legend-dot normal" />Non-simulated</span><span><i className="legend-dot simulated" />Simulated</span><span className="telemetry-count">{readings.length} recent readings loaded</span></div>
        </div>
      </section>

      <section className="lower-grid">
        <div className="panel station-panel">
          <PanelHeader title="Field status" subtitle="Most recently seen stations" icon={RadioTower} action={<NavLink className="text-link" to="/stations">View network <ChevronRight size={14} /></NavLink>} />
          {nodes.length ? <div className="station-list">{nodes.slice(0, 5).map((node) => <StationRow key={node.node_id} node={node} />)}</div> : <EmptyState icon={RadioTower} title="No stations registered" detail="Stations appear here when the backend receives station records or sensor readings." />}
        </div>
        <div className="panel alert-panel">
          <PanelHeader title="Active incidents" subtitle="Open risk alerts from the API" icon={AlertTriangle} action={<NavLink className="text-link" to="/alerts">Alert center <ChevronRight size={14} /></NavLink>} />
          {recentAlerts.length ? <div className="alert-list">{recentAlerts.map((alert) => <AlertRow key={alert.alert_id} alert={alert} />)}</div> : <EmptyState icon={ShieldCheck} title="No active alerts" detail="The backend currently reports no unresolved alerts." calm />}
          <div className="alert-footnote">Risk assessments are estimates and do not confirm a fire.</div>
        </div>
      </section>
      <section className="lower-grid insight-grid">
        <div className="panel telemetry-panel"><PanelHeader title="Environmental trends" subtitle="Latest persisted temperature and humidity values" icon={Thermometer} /><div className="environment-legend"><span>Temperature °C</span><span>Humidity %</span></div>{environmentalData.length ? <Suspense fallback={<div className="chart-loading">Loading environmental chart…</div>}><EnvironmentalTrendChart data={environmentalData} /></Suspense> : <EmptyState icon={Thermometer} title="No environmental history" detail="Temperature and humidity trends appear after readings are persisted." />}</div>
        <div className="panel station-panel"><PanelHeader title="Latest readings" subtitle="Most recent API records" icon={Clock3} action={<NavLink className="text-link" to="/monitoring">Live monitoring <ChevronRight size={14} /></NavLink>} />{recentReadings.length ? <div className="latest-reading-list">{recentReadings.map((row) => <div className="latest-reading-row" key={row.id}><div><strong>{row.node_id}</strong><small>{formatTimestamp(row.timestamp)}{row.is_simulated ? ' · SIMULATED' : ''}</small></div><span>{row.temperature_c === null ? '—' : `${row.temperature_c.toFixed(1)}°C`}</span><span>{row.humidity_percent === null ? '—' : `${row.humidity_percent.toFixed(0)}%`}</span><span>{row.risk_score === null ? 'Unassessed' : `${row.risk_score}/100`}</span></div>)}</div> : <EmptyState icon={Clock3} title="No readings received" detail="Latest activity will appear when the API has persisted sensor records." />}</div>
      </section>
      <section className="risk-distribution" aria-label="Risk state distribution">{(['NORMAL', 'WATCH', 'WARNING', 'CRITICAL'] as const).map((state) => <div className={`risk-distribution-item risk-${state.toLowerCase()}`} key={state}><small>{state}</small><strong>{nodes.filter((node) => node.current_risk_state === state).length}</strong></div>)}<div className="risk-distribution-item risk-unknown"><small>UNASSESSED</small><strong>{nodes.filter((node) => node.current_risk_state === null).length}</strong></div></section>
      <footer className="page-foot"><span>FORESTGUARD MISSION CONTROL</span><span>Environmental monitoring prototype · Not a fire confirmation system</span></footer>
    </>
  )
}

function StatCard({ label, value, detail, icon: Icon, accent }: { label: string; value: string; detail: string; icon: LucideIcon; accent: string }) {
  return (
    <article className={`stat-card accent-${accent}`}>
      <div className="stat-top"><span>{label}</span><span className="stat-icon"><Icon size={17} /></span></div>
      <div className="stat-value">{value}</div>
      <div className="stat-detail">{detail}</div>
      <div className="stat-sheen" aria-hidden="true" />
    </article>
  )
}

function PanelHeader({ title, subtitle, icon: Icon, action }: { title: string; subtitle: string; icon: LucideIcon; action?: ReactNode }) {
  return <div className="panel-header"><div className="panel-title-wrap"><div className="panel-icon"><Icon size={16} /></div><div><h2>{title}</h2><p>{subtitle}</p></div></div>{action}</div>
}

function StationRow({ node }: { node: NodeRecord }) {
  const risk = node.current_risk_state
  return (
    <div className="station-row">
      <span className={`status-orb ${node.connectivity_state.toLowerCase()}`} />
      <div className="station-main"><strong>{node.name}</strong><span>{node.node_id}{node.location ? ` · ${node.location}` : ''}</span></div>
      <span className={`risk-tag ${risk ? `risk-${risk.toLowerCase()}` : 'risk-unknown'}`}>{risk ?? 'UNASSESSED'}</span>
      {node.latest_is_simulated ? <span className="sim-tag">SIM</span> : null}
      <span className="station-seen">{formatTimestamp(node.latest_reading_at)}</span>
      <ChevronRight className="row-chevron" size={15} />
    </div>
  )
}

function AlertRow({ alert, onSelect }: { alert: AlertRecord; onSelect?: () => void }) {
  return (
    <article className={`alert-row severity-${alert.severity.toLowerCase()}`}>
      <span className="alert-mark"><AlertTriangle size={15} /></span>
      <div className="alert-main"><div><strong>{alert.node_id}</strong><span className={`risk-tag risk-${alert.severity.toLowerCase()}`}>{alert.severity}</span>{alert.is_simulated ? <span className="sim-tag">SIMULATED</span> : null}</div><p>{alert.reasons[0] ?? 'Risk assessment updated'}</p><time>{formatTimestamp(alert.updated_at)}</time>{onSelect ? <button className="text-link alert-detail-button" onClick={onSelect}>View incident details</button> : null}</div>
      <span className="alert-score">{alert.risk_score}<small>/100</small></span>
    </article>
  )
}

function EmptyState({ icon: Icon, title, detail, calm = false }: { icon: LucideIcon; title: string; detail: string; calm?: boolean }) {
  return <div className={`empty-state ${calm ? 'empty-calm' : ''}`}><span className="empty-icon"><Icon size={19} /></span><strong>{title}</strong><p>{detail}</p></div>
}

function StationsPage({ nodes, loading }: { nodes: NodeRecord[]; loading: boolean }) {
  const [search, setSearch] = useState('')
  const filtered = nodes.filter((node) => `${node.name} ${node.node_id} ${node.location ?? ''}`.toLowerCase().includes(search.toLowerCase()))
  return (
    <>
      <PageHeading eyebrow="NETWORK DIRECTORY" title="Field stations" detail="Connectivity, latest telemetry, and backend risk state for each registered station." trailing={<div className="heading-count"><RadioTower size={16} />{nodes.length} TOTAL</div>} />
      <div className="panel directory-panel">
        <div className="directory-toolbar"><div className="search-field"><Search size={16} /><input aria-label="Search stations" placeholder="Search by name, ID, or location" value={search} onChange={(event) => setSearch(event.target.value)} /></div><span className="muted-label">{filtered.length} stations shown</span></div>
        {filtered.length ? <div className="station-table-wrap"><table className="station-table"><thead><tr><th>STATION</th><th>CONNECTIVITY</th><th>RISK STATE</th><th>TEMPERATURE</th><th>HUMIDITY</th><th>BATTERY</th><th>LAST READING</th></tr></thead><tbody>{filtered.map((node) => <StationTableRow key={node.node_id} node={node} />)}</tbody></table></div> : <EmptyState icon={loading ? RefreshCw : RadioTower} title={loading ? 'Loading station registry' : search ? 'No matching stations' : 'No stations registered'} detail={search ? 'Try a different station name, identifier, or location.' : 'Station records will appear after ingestion or registration through the API.'} />}
      </div>
      <div className="panel map-directory"><PanelHeader title="Geospatial view" subtitle="Only stations with coordinates from the backend are plotted" icon={MapPinned} /><Suspense fallback={<div className="map-loading">Loading station map…</div>}><ForestMap nodes={nodes} /></Suspense></div>
    </>
  )
}

function StationTableRow({ node }: { node: NodeRecord }) {
  const risk = node.current_risk_state
  return <tr><td><div className="table-station"><span className={`status-orb ${node.connectivity_state.toLowerCase()}`} /><span><strong>{node.name}</strong><small>{node.node_id}{node.latest_is_simulated ? ' · simulated' : ''}</small></span></div></td><td><span className={`connectivity-label conn-${node.connectivity_state.toLowerCase()}`}>{node.connectivity_state}</span></td><td><span className={`risk-tag ${risk ? `risk-${risk.toLowerCase()}` : 'risk-unknown'}`}>{risk ?? 'UNASSESSED'}</span>{node.current_risk_score !== null ? <small className="table-score"> {node.current_risk_score}</small> : null}</td><td>{node.latest_temperature_c === null ? '—' : `${node.latest_temperature_c.toFixed(1)}°C`}</td><td>{node.latest_humidity_percent === null ? '—' : `${node.latest_humidity_percent.toFixed(0)}%`}</td><td>{node.battery_percent === null ? '—' : `${node.battery_percent.toFixed(0)}%`}</td><td>{formatTimestamp(node.latest_reading_at)}</td></tr>
}

function AlertsPage({ alerts, summary, loading, onAcknowledged }: { alerts: AlertRecord[]; summary?: DashboardData['summary']; loading: boolean; onAcknowledged: () => Promise<void> }) {
  const [filter, setFilter] = useState<'ALL' | 'ACTIVE' | 'ACKNOWLEDGED'>('ALL')
  const [severity, setSeverity] = useState('ALL')
  const [station, setStation] = useState('ALL')
  const [simulation, setSimulation] = useState('ALL')
  const [selected, setSelected] = useState<AlertRecord | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [operatorToken, setOperatorToken] = useState('')
  const stations = [...new Set(alerts.map((alert) => alert.node_id))]
  const visible = alerts.filter((alert) => alert.status !== 'RESOLVED' && (filter === 'ALL' || alert.status === filter) && (severity === 'ALL' || alert.severity === severity) && (station === 'ALL' || alert.node_id === station) && (simulation === 'ALL' || String(alert.is_simulated) === simulation))
  const acknowledge = async () => {
    if (!selected || selected.status !== 'ACTIVE' || !operatorToken.trim()) return
    setBusy(true); setMessage(null)
    try {
      await acknowledgeAlert(selected.alert_id, operatorToken.trim())
      await onAcknowledged()
      setSelected(null)
      setOperatorToken('')
    }
    catch (error) {
      setMessage(error instanceof Error ? error.message : 'Acknowledgement failed')
      setOperatorToken('')
    }
    finally { setBusy(false) }
  }
  useEffect(() => {
    if (selected) document.getElementById('incident-title')?.focus()
  }, [selected])
  return (
    <>
      <PageHeading eyebrow="RISK RESPONSE" title="Alert center" detail="Review estimated risk incidents reported by the backend. An alert is not a confirmed fire." trailing={<div className="heading-count"><Bell size={16} />{summary?.active ?? 0} ACTIVE</div>} />
      <section className="alert-summary-grid"><SummaryChip label="Active" value={summary?.active ?? 0} tone="red" icon={AlertTriangle} /><SummaryChip label="Acknowledged" value={summary?.acknowledged ?? 0} tone="amber" icon={ShieldCheck} /><SummaryChip label="Resolved" value={summary?.resolved ?? 0} tone="green" icon={Activity} /></section>
      <div className="panel alerts-directory"><div className="directory-toolbar"><div className="filter-tabs" role="group" aria-label="Filter alert status">{(['ALL', 'ACTIVE', 'ACKNOWLEDGED'] as const).map((value) => <button key={value} className={filter === value ? 'selected' : ''} onClick={() => setFilter(value)}>{value === 'ALL' ? 'All open' : value}</button>)}</div><div className="analytics-filters"><label>Severity<select aria-label="Filter by severity" value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="ALL">All severities</option>{['WATCH', 'WARNING', 'CRITICAL'].map((item) => <option key={item}>{item}</option>)}</select></label><label>Station<select aria-label="Filter by station" value={station} onChange={(event) => setStation(event.target.value)}><option value="ALL">All stations</option>{stations.map((item) => <option key={item}>{item}</option>)}</select></label><label>Source<select aria-label="Filter by source" value={simulation} onChange={(event) => setSimulation(event.target.value)}><option value="ALL">All sources</option><option value="false">Non-simulated</option><option value="true">Simulated</option></select></label></div><span className="muted-label">{visible.length} incidents</span></div>
        {message ? <div role="alert" className="inline-warning">{message}</div> : null}
        {visible.length ? <div className="full-alert-list">{visible.map((alert) => <AlertRow key={alert.alert_id} alert={alert} onSelect={() => setSelected(alert)} />)}</div> : <EmptyState icon={loading ? RefreshCw : ShieldCheck} title={loading ? 'Loading alert records' : filter === 'ALL' ? 'No open alerts' : `No ${filter.toLowerCase()} alerts`} detail="Alert state is read from the backend. This dashboard does not infer or confirm fires." calm />}
      </div>
      {selected ? <div className="dialog-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) { setSelected(null); setOperatorToken('') } }}><section className="panel alert-dialog" role="dialog" aria-modal="true" aria-labelledby="incident-title" onKeyDown={(event) => { if (event.key === 'Escape') { setSelected(null); setOperatorToken('') } }}><button className="icon-button dialog-close" onClick={() => { setSelected(null); setOperatorToken('') }} aria-label="Close alert details"><X size={18} /></button><div className="eyebrow">INCIDENT DETAIL</div><h2 id="incident-title" tabIndex={-1}>{selected.node_id} · {selected.severity}</h2><p>Current status: {selected.status} · Risk estimate {selected.risk_score}/100</p><p>Created {formatTimestamp(selected.created_at)} · Updated {formatTimestamp(selected.updated_at)}</p><p>Provenance: {selected.is_simulated ? 'SIMULATED' : 'NON-SIMULATED'}</p><h3>Assessment reasons</h3><ul>{selected.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>{selected.status === 'ACTIVE' ? <><label className="operator-token-field">Operator bearer token<input type="password" autoComplete="off" value={operatorToken} onChange={(event) => setOperatorToken(event.target.value)} aria-describedby="operator-token-note" /></label><p id="operator-token-note">Required by the server. Used for this request only and not saved in the browser.</p><button className="primary-button" onClick={() => void acknowledge()} disabled={busy || !operatorToken.trim()}><Check size={15} />{busy ? 'Acknowledging…' : 'Acknowledge alert'}</button></> : <p>This alert has already been acknowledged.</p>}</section></div> : null}
    </>
  )
}

function SummaryChip({ label, value, tone, icon: Icon }: { label: string; value: number; tone: string; icon: LucideIcon }) {
  return <div className={`summary-chip tone-${tone}`}><span className="summary-icon"><Icon size={17} /></span><span><strong>{value}</strong><small>{label}</small></span></div>
}

function ApiFailure({ error, retry }: { error: string; retry: () => void }) {
  return <div className="api-failure"><div className="failure-icon"><AlertTriangle size={22} /></div><div><span className="eyebrow">CONNECTION INTERRUPTED</span><h1>Mission data unavailable</h1><p>{error}</p><button className="primary-button" onClick={retry}><RefreshCw size={15} />Retry connection</button></div></div>
}

export default App
