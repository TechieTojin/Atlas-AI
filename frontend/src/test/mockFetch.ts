import { vi } from 'vitest'

export interface MockResponseSpec {
  status?: number
  body?: unknown
}

export type FetchHandler = (
  url: string,
  init?: RequestInit,
) => MockResponseSpec | undefined | Promise<MockResponseSpec | undefined>

/**
 * Installs a fetch mock whose behavior is defined by a simple handler
 * returning `{status, body}` specs. Returns the mock for call inspection.
 */
export function installFetchMock(handler: FetchHandler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    // A handler may return a promise to hold a response (e.g. a slow POST).
    const spec = await handler(url, init)
    if (!spec) {
      throw new Error(`No fetch mock registered for ${init?.method ?? 'GET'} ${url}`)
    }
    const status = spec.status ?? 200
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => spec.body,
      text: async () => JSON.stringify(spec.body ?? ''),
    } as Response
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

export function requestBody(init: RequestInit | undefined): unknown {
  if (!init || typeof init.body !== 'string') return undefined
  return JSON.parse(init.body)
}
