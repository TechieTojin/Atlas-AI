import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeEvent, makeRun, resetEventSeq } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock } from '../test/mockFetch'
import type { RunDetail } from '../types'
import { RunPage } from './RunPage'

const STARTED = Date.parse('2026-10-05T10:00:00Z')

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/runs/run-1']}>
      <Routes>
        <Route path="/runs/:id" element={<RunPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const planning = makeRun({
  status: 'PLANNING',
  mode: 'FAST',
  started_at: '2026-10-05T10:00:00Z',
  completed_at: undefined,
  final_report: '',
})

describe('RunPage cancellation', () => {
  let current: RunDetail

  beforeEach(() => {
    resetEventSeq()
    MockEventSource.reset()
    vi.stubGlobal('EventSource', MockEventSource)
    current = planning
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows Cancelling… immediately, then the cancelled state with a stopped timeline', async () => {
    const fetchMock = installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/cancel' && init?.method === 'POST') {
        current = { ...current, status: 'CANCELLING' }
        return { body: current }
      }
      if (url === '/api/runs/run-1') return { body: current }
      return undefined
    })
    renderPage()
    const button = await screen.findByRole('button', { name: 'Cancel' })
    act(() => {
      MockEventSource.latest().emit('RUN_STARTED', makeEvent('RUN_STARTED'))
      MockEventSource.latest().emit('PLANNING_STARTED', makeEvent('PLANNING_STARTED'))
    })

    await userEvent.click(button)
    const cancelling = screen.getByRole('button', { name: 'Cancelling…' })
    expect(cancelling).toBeDisabled()
    expect(fetchMock).toHaveBeenCalledWith('/api/runs/run-1/cancel', expect.anything())

    // Backend confirms through the stream.
    current = { ...current, status: 'CANCELLED', completed_at: '2026-10-05T10:00:42Z' }
    await act(async () => {
      MockEventSource.latest().emit('CANCEL_REQUESTED', makeEvent('CANCEL_REQUESTED'))
      MockEventSource.latest().emit('RUN_CANCELLED', makeEvent('RUN_CANCELLED'))
    })

    expect(await screen.findByRole('heading', { name: 'Research cancelled' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cancel/ })).not.toBeInTheDocument()
    expect(screen.getByText('Cancelled by user')).toBeInTheDocument()
    expect(screen.getByText('Planning research')).toBeInTheDocument()
    // No later stage is shown as pending/active after cancellation.
    expect(screen.queryByText('Searching sources')).not.toBeInTheDocument()
    expect(screen.queryByText('Synthesis')).not.toBeInTheDocument()
    // Timer stopped at completion: 42 seconds.
    expect(screen.getByTitle('Elapsed time')).toHaveTextContent('0:42')
  })

  it('freezes the timer the moment Cancel is clicked', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(STARTED + 10_000)
    installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/cancel' && init?.method === 'POST') {
        current = { ...current, status: 'CANCELLING' }
        return { body: current }
      }
      if (url === '/api/runs/run-1') return { body: current }
      return undefined
    })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(screen.getByTitle('Elapsed time')).toHaveTextContent('0:10')

    now.mockReturnValue(STARTED + 300_000) // five minutes later, still cancelling
    act(() => {
      MockEventSource.latest().emit('CANCEL_REQUESTED', makeEvent('CANCEL_REQUESTED'))
    })
    expect(screen.getByTitle('Elapsed time')).toHaveTextContent('0:10')
  })

  it('shows a clear error and allows retry when the cancel request fails', async () => {
    let attempts = 0
    installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/cancel' && init?.method === 'POST') {
        attempts += 1
        if (attempts === 1) return { status: 503, body: { detail: 'Storage is unavailable.' } }
        current = { ...current, status: 'CANCELLING' }
        return { body: current }
      }
      if (url === '/api/runs/run-1') return { body: current }
      return undefined
    })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not cancel the run')
    const retry = screen.getByRole('button', { name: 'Cancel' }) // not pretending
    expect(retry).toBeEnabled()
    await userEvent.click(retry)
    expect(await screen.findByRole('button', { name: 'Cancelling…' })).toBeDisabled()
    expect(attempts).toBe(2)
  })

  it('reports when the run finished before the cancellation arrived', async () => {
    installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/cancel' && init?.method === 'POST') {
        current = { ...current, status: 'COMPLETED', completed_at: '2026-10-05T10:05:00Z' }
        return { status: 409, body: { detail: 'Run run-1 already finished.' } }
      }
      if (url === '/api/runs/run-1') return { body: current }
      if (url.startsWith('/api/runs/run-1/followups')) return { body: { followups: [] } }
      return undefined
    })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'finished before the cancellation reached the server',
    )
    expect(screen.queryByRole('heading', { name: 'Research cancelled' })).not.toBeInTheDocument()
  })
})
