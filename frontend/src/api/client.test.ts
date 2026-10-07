import { beforeEach, describe, expect, it } from 'vitest'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { makeRun } from '../test/fixtures'
import { api, ApiError, exportUrl } from './client'

describe('api client', () => {
  beforeEach(() => {
    // each test installs its own fetch mock
  })

  it('surfaces an error response {detail} as a thrown ApiError with that message', async () => {
    installFetchMock(() => ({ status: 400, body: { detail: 'Query must not be empty' } }))

    await expect(
      api.createRun({
        query: '',
        mode: 'FAST',
        source_scope: 'WEB',
        document_ids: [],
        approval_required: false,
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      message: 'Query must not be empty',
      status: 400,
    })
  })

  it('falls back to a status message when the error body is not JSON', async () => {
    const mock = installFetchMock(() => ({ status: 500 }))
    mock.mockImplementationOnce(async () => {
      return {
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('not json')
        },
      } as unknown as Response
    })

    await expect(api.getRun('r1')).rejects.toThrow('Request failed with status 500')
  })

  it('posts JSON bodies with the right method and headers', async () => {
    const run = makeRun()
    const mock = installFetchMock(() => ({ status: 201, body: run }))

    const result = await api.createRun({
      query: 'test query',
      mode: 'DEEP',
      source_scope: 'DOCUMENTS',
      document_ids: ['doc-1'],
      approval_required: true,
    })

    expect(result.id).toBe('run-1')
    const [url, init] = mock.mock.calls[0]
    expect(url).toBe('/api/runs')
    expect(init?.method).toBe('POST')
    expect(requestBody(init)).toEqual({
      query: 'test query',
      mode: 'DEEP',
      source_scope: 'DOCUMENTS',
      document_ids: ['doc-1'],
      approval_required: true,
    })
  })

  it('returns undefined for 204 responses', async () => {
    const mock = installFetchMock(() => ({ status: 204 }))
    await expect(api.deleteRun('r1')).resolves.toBeUndefined()
    expect(mock.mock.calls[0][0]).toBe('/api/runs/r1')
    expect(mock.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it('wraps network failures in an ApiError', async () => {
    installFetchMock(() => {
      throw new Error('boom')
    })
    await expect(api.health()).rejects.toBeInstanceOf(ApiError)
    await expect(api.health()).rejects.toThrow(/Could not reach the Atlas backend/)
  })

  it('builds query strings for run listing and the export URL', async () => {
    const mock = installFetchMock(() => ({
      body: { runs: [], total: 0, limit: 10, offset: 5 },
    }))
    await api.listRuns({ limit: 10, offset: 5, search: 'solar' })
    expect(mock.mock.calls[0][0]).toBe('/api/runs?limit=10&offset=5&search=solar')
    expect(exportUrl('r9')).toBe('/api/runs/r9/export?format=markdown')
  })
})
