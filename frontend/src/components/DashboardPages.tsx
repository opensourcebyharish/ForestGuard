import { lazy, Suspense, useMemo, useState } from 'react'
import { Activity, CircleHelp, Download, RadioTower, Settings2 } from 'lucide-react'
import type { NodeRecord, ReadingRecord } from '../api/forestguard'
import { formatTimestamp } from '../api/forestguard'
import type { EnvironmentalPoint } from './EnvironmentalTrendChart'
const EnvironmentalTrendChart = lazy(() => import('./EnvironmentalTrendChart'))

function Heading({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" />{eyebrow}</div><h1>{title}</h1><p>{detail}</p></div></div>
}

function value(value: number | null | undefined, unit = '') { return value === null || value === undefined ? 'Unavailable' : `${value}${unit}` }
export function MonitoringPage({ nodes, readings }: { nodes: NodeRecord[]; readings: ReadingRecord[] }) {
  const latest = new Map<string, ReadingRecord>()
  for (const reading of readings) {
    const current = latest.get(reading.node_id)
    if (!current || Date.parse(reading.timestamp) > Date.parse(current.timestamp)) latest.set(reading.node_id, reading)
  }
  return <><Heading eyebrow="LIVE TELEMETRY" title="Live monitoring" detail="Latest available sensor values and backend risk explanations. The dashboard refreshes every 15 seconds; it does not use a streaming connection." />
    {!nodes.length ? <div className="panel"><p className="empty-state">No stations are available from the API.</p></div> : <div className="monitor-grid">{nodes.map((node) => {
      const reading = latest.get(node.node_id)
      const time = reading?.timestamp ?? node.latest_reading_at
      const status = node.connectivity_state
      return <article className="panel monitor-card" key={node.node_id}>
        <div className="monitor-title"><span className={`status-orb ${status.toLowerCase()}`} /><div><h2>{node.name}</h2><p>{node.node_id} · {status}</p></div><span className={`risk-tag ${node.current_risk_state ? `risk-${node.current_risk_state.toLowerCase()}` : 'risk-unknown'}`}>{node.current_risk_state ?? 'UNASSESSED'}</span></div>
        <div className="sensor-grid">{[["Temperature", reading?.temperature_c ?? node.latest_temperature_c, ' °C'], ["Humidity", reading?.humidity_percent ?? node.latest_humidity_percent, '%'], ["Smoke", reading?.smoke_value ?? node.latest_smoke_value, ''], ["Gas", reading?.gas_value ?? node.latest_gas_value, ''], ["Battery", node.battery_percent, '%']].map(([label, number, unit]) => <div className="sensor-value" key={String(label)}><small>{label}</small><strong>{value(number as number | null, String(unit))}</strong></div>)}</div>
        <div className="monitor-meta"><span>Last reading: {formatTimestamp(time)}</span>{(reading?.is_simulated ?? node.latest_is_simulated) ? <span className="sim-tag">SIMULATED</span> : null}<strong>Risk score: {node.current_risk_score ?? 'Unavailable'}{node.current_risk_score === null ? '' : ' / 100'}</strong></div>
        <div className="reason-list"><strong>Assessment reasons</strong>{node.current_risk_reasons?.length ? <ul>{node.current_risk_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>No assessment explanation is available.</p>}</div>
      </article>
    })}</div>}
  </>
}

export function AnalyticsPage({ nodes, readings, updatedAt }: { nodes: NodeRecord[]; readings: ReadingRecord[]; updatedAt: string | null }) {
  const [nodeId, setNodeId] = useState('ALL')
  const [range, setRange] = useState('24')
  const filtered = useMemo(() => {
    const end = updatedAt ? Date.parse(updatedAt) : Date.parse(readings[0]?.timestamp ?? '')
    const cutoff = end - Number(range) * 60 * 60 * 1000
    return readings.filter((row) => (nodeId === 'ALL' || row.node_id === nodeId) && Date.parse(row.timestamp) >= cutoff)
      .slice().sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
  }, [readings, nodeId, range, updatedAt])
  const points: EnvironmentalPoint[] = filtered.map((row) => ({ timestamp: row.timestamp, temperature: row.temperature_c, humidity: row.humidity_percent, nodeId: row.node_id, simulated: row.is_simulated }))
  const exportCsv = () => {
    const columns = ['timestamp', 'node_id', 'temperature_c', 'humidity_percent', 'smoke_value', 'gas_value', 'risk_state', 'risk_score', 'is_simulated']
    const quote = (input: unknown) => {
      const text = input === null || input === undefined ? '' : String(input)
      const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text
      return `"${safe.replaceAll('"', '""')}"`
    }
    const csv = [columns.join(','), ...filtered.map((row) => [row.timestamp, row.node_id, row.temperature_c, row.humidity_percent, row.smoke_value, row.gas_value, row.risk_state, row.risk_score, row.is_simulated].map(quote).join(','))].join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = 'forestguard-readings.csv'; link.click(); URL.revokeObjectURL(url)
  }
  return <><Heading eyebrow="HISTORICAL DATA" title="Analytics" detail="Explore the most recent readings returned by the API. Missing sensor values remain gaps, never zeroes." />
    <div className="panel analytics-panel"><div className="directory-toolbar"><div className="analytics-filters"><label>Station<select value={nodeId} onChange={(event) => setNodeId(event.target.value)}><option value="ALL">All stations</option>{nodes.map((node) => <option key={node.node_id} value={node.node_id}>{node.name} ({node.node_id})</option>)}</select></label><label>Time range<select value={range} onChange={(event) => setRange(event.target.value)}><option value="6">Last 6 hours</option><option value="24">Last 24 hours</option><option value="168">Last 7 days</option><option value="720">Last 30 days</option></select></label></div><button className="refresh-button" onClick={exportCsv} disabled={!filtered.length}><Download size={15} />Export filtered CSV</button></div>
      {filtered.length ? <><div className="environment-legend"><span>Temperature °C</span><span>Humidity %</span><span>{filtered.length} readings · simulated values labeled in export</span></div><Suspense fallback={<div className="chart-loading">Loading environmental chart…</div>}><EnvironmentalTrendChart data={points} /></Suspense><div className="table-scroll"><table className="station-table"><thead><tr><th>TIME</th><th>STATION</th><th>TEMPERATURE</th><th>HUMIDITY</th><th>SMOKE</th><th>GAS</th><th>RISK</th><th>PROVENANCE</th></tr></thead><tbody>{filtered.slice(-100).reverse().map((row) => <tr key={row.id}><td>{formatTimestamp(row.timestamp)}</td><td>{row.node_id}</td><td>{value(row.temperature_c, ' °C')}</td><td>{value(row.humidity_percent, '%')}</td><td>{value(row.smoke_value)}</td><td>{value(row.gas_value)}</td><td>{row.risk_state ?? 'Unassessed'}{row.risk_score === null ? '' : ` · ${row.risk_score}`}</td><td>{row.is_simulated ? 'Simulated' : 'Non-simulated'}</td></tr>)}</tbody></table></div></> : <div className="empty-state"><strong>No readings in this time range</strong><p>Only persisted API data is shown. Try a longer range or another station.</p></div>}
    </div></>
}

export function DevicesPage({ nodes }: { nodes: NodeRecord[] }) {
  const [selected, setSelected] = useState<string | null>(nodes[0]?.node_id ?? null)
  const node = nodes.find((item) => item.node_id === selected) ?? nodes[0]
  return <><Heading eyebrow="DEVICE REGISTRY" title="Devices" detail="Station identity and latest state reported by the backend. No remote controls are available." />
    <div className="device-layout"><section className="panel device-list" aria-label="Station list">{nodes.map((item) => <button key={item.node_id} className={`device-item ${node?.node_id === item.node_id ? 'selected' : ''}`} onClick={() => setSelected(item.node_id)}><RadioTower size={17} /><span><strong>{item.name}</strong><small>{item.node_id}</small></span><span className={`connectivity-label conn-${item.connectivity_state.toLowerCase()}`}>{item.connectivity_state}</span></button>)}{!nodes.length && <p className="empty-state">No registered devices.</p>}</section>
    {node ? <section className="panel device-detail"><div className="monitor-title"><RadioTower size={19} /><div><h2>{node.name}</h2><p>{node.node_id}</p></div><span className="sim-tag">{node.latest_is_simulated ? 'SIMULATED' : 'LATEST: NON-SIMULATED'}</span></div><dl className="detail-grid"><dt>Connectivity</dt><dd>{node.connectivity_state}</dd><dt>Coordinates</dt><dd>{node.latitude === null || node.longitude === null ? 'Unavailable' : `${node.latitude}, ${node.longitude}`}</dd><dt>Last seen</dt><dd>{formatTimestamp(node.last_seen_at)}</dd><dt>Latest reading</dt><dd>{formatTimestamp(node.latest_reading_at)}</dd><dt>Temperature</dt><dd>{value(node.latest_temperature_c, ' °C')}</dd><dt>Humidity</dt><dd>{value(node.latest_humidity_percent, '%')}</dd><dt>Smoke</dt><dd>{value(node.latest_smoke_value)}</dd><dt>Gas</dt><dd>{value(node.latest_gas_value)}</dd><dt>Battery</dt><dd>{value(node.battery_percent, '%')}</dd><dt>Risk assessment</dt><dd>{node.current_risk_state ?? 'Unassessed'}{node.current_risk_score === null ? '' : ` · ${node.current_risk_score}/100`}</dd></dl></section> : <section className="panel empty-state">Select a station for details.</section>}</div>
  </>
}

export function SettingsPage({ health }: { health: { status: string; database: string } | null }) {
  return <><Heading eyebrow="APPLICATION STATUS" title="Settings" detail="Connection and capability information exposed by the ForestGuard service." />
    <div className="settings-grid"><section className="panel settings-card"><h2><Activity size={17} /> Backend connection</h2><div className={`connection-pill ${health?.status === 'ok' ? '' : 'connection-error'}`}><span className="pulse-dot" />{health?.status === 'ok' ? 'AVAILABLE' : 'UNAVAILABLE'}</div><p>Health endpoint: <code>/health</code></p><p>Database: {health?.database ?? 'Status unavailable'}</p><p>Dashboard refresh interval: 15 seconds (polling)</p><p>Server-Sent Events: not exposed by this backend</p></section>
    <section className="panel settings-card"><h2><Settings2 size={17} /> Notifications</h2><p>Notification configuration status is not exposed by an API endpoint.</p><p>Configure notification credentials on the server. Server credentials are not embedded in this dashboard or persisted in browser storage.</p></section>
    <section className="panel settings-card"><h2><CircleHelp size={17} /> Application</h2><p>ForestGuard mission control · frontend prototype</p><p>Risk values are explainable estimates, not confirmation of a fire or field-calibrated predictions.</p></section></div>
  </>
}
