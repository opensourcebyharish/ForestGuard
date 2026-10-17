import { afterEach, describe, expect, it, vi } from 'vitest'
import { acknowledgeAlert, loadDashboard } from './forestguard'

const response = (body: unknown) => ({ ok: true, json: async () => body })

describe('loadDashboard API contract', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads the documented array and paged endpoint response formats', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response({ items: [], limit: 200, offset: 0 }))
      .mockResolvedValueOnce(response({ items: [], limit: 100, offset: 0 }))
      .mockResolvedValueOnce(response({ active: 0, acknowledged: 0, resolved: 0, by_severity: {} }))
      .mockResolvedValueOnce(response({ status: 'ok', database: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    const data = await loadDashboard(new AbortController().signal)

    expect(data).toEqual({
      nodes: [],
      readings: [],
      alerts: [],
      summary: { active: 0, acknowledged: 0, resolved: 0, by_severity: {} },
      health: { status: 'ok', database: 'ok' },
    })
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/nodes?limit=200&offset=0',
      '/api/readings?limit=200&offset=0',
      '/api/alerts?limit=100&offset=0',
      '/api/alerts/summary',
      '/health',
    ])
  })

  it('surfaces endpoint failures instead of silently showing zeroed data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    await expect(loadDashboard(new AbortController().signal)).rejects.toThrow('503')
  })

  it('sends an operator token only with the acknowledgement request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ alert_id: 'alert-1' }))
    vi.stubGlobal('fetch', fetchMock)

    await acknowledgeAlert('alert-1', 'operator-token')

    expect(fetchMock).toHaveBeenCalledWith('/api/alerts/alert-1/acknowledge', expect.objectContaining({
      method: 'POST',
      headers: { Accept: 'application/json', Authorization: 'Bearer operator-token' },
    }))
  })

  it('explains rejected and unavailable acknowledgement authorization', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({ ok: false, status: 503 }))

    await expect(acknowledgeAlert('alert-1', 'wrong-token'))
      .rejects.toThrow('Operator token was not accepted')
    await expect(acknowledgeAlert('alert-1', 'any-token'))
      .rejects.toThrow('Operator authorization is not configured on the backend')
  })
})
