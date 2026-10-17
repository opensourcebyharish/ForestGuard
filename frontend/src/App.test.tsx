import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { acknowledgeAlert, loadDashboard } from './api/forestguard'
import type { DashboardData } from './api/forestguard'

vi.mock('./api/forestguard', async (importOriginal) => {
  const original = await importOriginal<typeof import('./api/forestguard')>()
  return { ...original, loadDashboard: vi.fn(), acknowledgeAlert: vi.fn() }
})

const mockedLoadDashboard = vi.mocked(loadDashboard)
const mockedAcknowledgeAlert = vi.mocked(acknowledgeAlert)
const emptyData: DashboardData = {
  nodes: [],
  readings: [],
  alerts: [],
  summary: { active: 0, acknowledged: 0, resolved: 0, by_severity: {} },
  health: { status: 'ok', database: 'ok' },
}

describe('mission control interface', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows a real empty-state overview without fabricated station or risk values', async () => {
    mockedLoadDashboard.mockResolvedValue(emptyData)
    render(<MemoryRouter><App /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: 'Regional overview' })).toBeInTheDocument()
    expect(screen.getByText('No stations registered')).toBeInTheDocument()
    expect(screen.getByText('No active alerts')).toBeInTheDocument()
    expect(screen.getByText('No risk telemetry yet')).toBeInTheDocument()
    expect(screen.getByText('Registered stations')).toBeInTheDocument()
  })

  it('offers a retry and an understandable error when the API is unavailable', async () => {
    mockedLoadDashboard.mockRejectedValue(new Error('ForestGuard API returned 503'))
    render(<MemoryRouter><App /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: 'Mission data unavailable' })).toBeInTheDocument()
    const retry = screen.getByRole('button', { name: 'Retry connection' })
    fireEvent.click(retry)
    await waitFor(() => expect(mockedLoadDashboard).toHaveBeenCalledTimes(2))
  })

  it('keeps missing station risk assessments visibly unassessed', async () => {
    mockedLoadDashboard.mockResolvedValue({
      ...emptyData,
      nodes: [{
        node_id: 'ridge-east',
        name: 'East Ridge',
        latitude: null,
        longitude: null,
        location: null,
        latest_reading_at: null,
        latest_temperature_c: null,
        latest_humidity_percent: null,
        latest_smoke_value: null,
        latest_gas_value: null,
        latest_temperature_available: false,
        latest_humidity_available: false,
        latest_smoke_available: false,
        last_seen_at: null,
        battery_percent: null,
        latest_is_simulated: false,
        current_risk_state: null,
        current_risk_score: null,
        current_risk_reasons: null,
        risk_assessed_at: null,
        connectivity_state: 'OFFLINE',
      }],
    })
    render(<MemoryRouter initialEntries={['/stations']}><App /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: 'Field stations' })).toBeInTheDocument()
    expect(screen.getAllByText('UNASSESSED').length).toBeGreaterThan(0)
    expect(await screen.findByText('OFFLINE')).toBeInTheDocument()
  })

  it('labels simulated alerts and filters the live alert list', async () => {
    mockedLoadDashboard.mockResolvedValue({
      ...emptyData,
      alerts: [{
        alert_id: 'alert-1',
        node_id: 'ridge-east',
        severity: 'WARNING',
        risk_score: 63,
        reasons: ['Elevated temperature persisted'],
        created_at: '2026-10-16T10:00:00Z',
        updated_at: '2026-10-16T10:01:00Z',
        status: 'ACTIVE',
        is_simulated: true,
      }],
      summary: { active: 1, acknowledged: 0, resolved: 0, by_severity: { WARNING: 1 } },
    })
    render(<MemoryRouter initialEntries={['/alerts']}><App /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: 'Alert center' })).toBeInTheDocument()
    expect(await screen.findByText('SIMULATED')).toBeInTheDocument()
    expect(screen.getByText('Elevated temperature persisted')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'ACKNOWLEDGED' }))
    expect(await screen.findByText('No acknowledged alerts')).toBeInTheDocument()
  })

  it('shows the live-monitoring view and does not replace missing sensors with zero', async () => {
    mockedLoadDashboard.mockResolvedValue({
      ...emptyData,
      nodes: [{
        node_id: 'ridge-east', name: 'East Ridge', latitude: null, longitude: null, location: null,
        latest_reading_at: null, latest_temperature_c: null, latest_humidity_percent: 42,
        latest_smoke_value: null, latest_gas_value: null, latest_temperature_available: false,
        latest_humidity_available: true, latest_smoke_available: false, last_seen_at: null,
        battery_percent: null, latest_is_simulated: false, current_risk_state: null, current_risk_score: null,
        current_risk_reasons: null, risk_assessed_at: null, connectivity_state: 'OFFLINE',
      }],
    })
    render(<MemoryRouter initialEntries={['/monitoring']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Live monitoring' })).toBeInTheDocument()
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0)
    expect(screen.getByText('42%')).toBeInTheDocument()
    expect(screen.getByText(/ridge-east · OFFLINE/)).toBeInTheDocument()
  })

  it('opens alert details and acknowledges an active alert through the API client', async () => {
    mockedLoadDashboard.mockResolvedValue({
      ...emptyData,
      alerts: [{ alert_id: 'alert-1', node_id: 'ridge-east', severity: 'WARNING', risk_score: 63,
        reasons: ['Sustained high temperature'], created_at: '2026-10-16T10:00:00Z', updated_at: '2026-10-16T10:01:00Z',
        status: 'ACTIVE', is_simulated: false }],
      summary: { active: 1, acknowledged: 0, resolved: 0, by_severity: { WARNING: 1 } },
    })
    mockedAcknowledgeAlert.mockResolvedValue({} as Awaited<ReturnType<typeof acknowledgeAlert>>)
    render(<MemoryRouter initialEntries={['/alerts']}><App /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'View incident details' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Sustained high temperature')
    fireEvent.change(screen.getByLabelText('Operator bearer token'), { target: { value: 'operator-secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge alert' }))
    await waitFor(() => expect(mockedAcknowledgeAlert).toHaveBeenCalledWith('alert-1', 'operator-secret'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('keeps an alert active and clears a rejected operator token', async () => {
    mockedLoadDashboard.mockResolvedValue({
      ...emptyData,
      alerts: [{ alert_id: 'alert-2', node_id: 'ridge-west', severity: 'WARNING', risk_score: 58,
        reasons: ['Elevated smoke reading'], created_at: '2026-10-16T10:00:00Z', updated_at: '2026-10-16T10:01:00Z',
        status: 'ACTIVE', is_simulated: true }],
      summary: { active: 1, acknowledged: 0, resolved: 0, by_severity: { WARNING: 1 } },
    })
    mockedAcknowledgeAlert.mockRejectedValue(new Error('Operator token was not accepted. Check it and try again.'))
    render(<MemoryRouter initialEntries={['/alerts']}><App /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'View incident details' }))
    const tokenInput = screen.getByLabelText('Operator bearer token')
    fireEvent.change(tokenInput, { target: { value: 'incorrect-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge alert' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Operator token was not accepted')
    expect(screen.getByRole('dialog')).toHaveTextContent('Current status: ACTIVE')
    expect(tokenInput).toHaveValue('')
  })

  it('shows analytics, devices, and settings routes', async () => {
    mockedLoadDashboard.mockResolvedValue(emptyData)
    const { unmount } = render(<MemoryRouter initialEntries={['/analytics']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Analytics' })).toBeInTheDocument()
    unmount()
    const devices = render(<MemoryRouter initialEntries={['/devices']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Devices' })).toBeInTheDocument()
    devices.unmount()
    render(<MemoryRouter initialEntries={['/settings']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByText(/Notification configuration status is not exposed/)).toBeInTheDocument()
  })
})
