import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeComparison } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock } from '../test/mockFetch'
import type { Comparison, ComparisonStatus } from '../types'
import { ComparisonPage } from './ComparisonPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/comparisons/cmp-1']}>
      <Routes>
        <Route path="/comparisons/:id" element={<ComparisonPage />} />
        <Route path="/projects/:id" element={<p>Project workspace</p>} />
        <Route path="/" element={<p>Research home</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

/** Serve a comparison in a given state, plus whatever the page fetches with it. */
function mockComparison(overrides: Partial<Comparison>) {
  return installFetchMock((url, init) => {
    if (url === '/api/comparisons/cmp-1/cancel' && init?.method === 'POST') {
      return { body: makeComparison({ ...overrides, status: 'CANCELLING' }) }
    }
    if (url === '/api/comparisons/cmp-1' && init?.method === 'DELETE') {
      return { status: 204, body: undefined }
    }
    if (url === '/api/comparisons/cmp-1') {
      return { body: makeComparison(overrides) }
    }
    if (url === '/api/comparisons/cmp-1/claims') {
      return { body: { claims: [] } }
    }
    return undefined
  })
}

const RUNNING: Partial<Comparison> = {
  status: 'RUNNING',
  report: '',
  duration_ms: 0,
  completed_at: null,
  metrics: { model: 'qwen3:4b', outcome: 'running', phase: 'writing' },
}

describe('ComparisonPage cancellation and terminal states', () => {
  beforeEach(() => {
    MockEventSource.reset()
    vi.stubGlobal('EventSource', MockEventSource)
  })

  it('offers Cancel while a comparison is running', async () => {
    mockComparison(RUNNING)
    renderPage()

    expect(await screen.findByText(/Comparing 2 runs/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('does not offer Cancel once a comparison is finished', async () => {
    mockComparison({})
    renderPage()

    await screen.findByRole('heading', { name: /Solar growth/ })
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })

  it.each<ComparisonStatus>(['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'])(
    'hides Cancel in the terminal state %s',
    async (status) => {
      mockComparison({ status, report: '', completed_at: '2026-10-06T12:00:08Z' })
      renderPage()

      await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
      expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
    },
  )

  it('cancels through the API and reflects the cancelling state', async () => {
    const fetchMock = mockComparison(RUNNING)
    renderPage()
    await screen.findByText(/Comparing 2 runs/)

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/comparisons/cmp-1/cancel',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    expect(await screen.findByText('Stopping the comparison…')).toBeInTheDocument()
    // The button stays, disabled, so the click cannot be repeated.
    expect(screen.getByRole('button', { name: /Cancelling/ })).toBeDisabled()
  })

  it('stops polling once a comparison reaches a terminal state', async () => {
    mockComparison({ status: 'TIMED_OUT', report: '', error: 'Timed out: 300s limit.' })
    renderPage()

    await screen.findByRole('heading', { name: 'Comparison timed out' })
    // An event stream for a finished comparison would poll forever.
    expect(MockEventSource.instances).toHaveLength(0)
  })

  it('keeps streaming while the comparison is still active', async () => {
    mockComparison(RUNNING)
    renderPage()

    await screen.findByText(/Comparing 2 runs/)
    expect(MockEventSource.instances.length).toBeGreaterThan(0)
  })

  it('says plainly when a comparison timed out', async () => {
    mockComparison({
      status: 'TIMED_OUT',
      report: '',
      error: 'Timed out: comparison exceeded its 300s time limit.',
    })
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Comparison timed out' })).toBeInTheDocument()
    expect(screen.getByText(/exceeded its 300s time limit/)).toBeInTheDocument()
  })

  it('says plainly when a comparison was cancelled', async () => {
    mockComparison({ status: 'CANCELLED', report: '', error: 'Cancelled.' })
    renderPage()

    expect(
      await screen.findByRole('heading', { name: 'Comparison cancelled' }),
    ).toBeInTheDocument()
  })

  it('never shows unavailable token counts as zero', async () => {
    mockComparison({
      status: 'TIMED_OUT',
      report: '',
      duration_ms: 0,
      metrics: {
        model: 'qwen3:4b',
        outcome: 'timed_out',
        phase: 'writing',
        elapsed_ms: 300_000,
        prompt_tokens: null,
        output_tokens: null,
      },
    })
    renderPage()

    const metrics = await screen.findByRole('group', { name: 'Execution details' })
    // 0 would claim the model produced nothing, which is not known after an abort.
    expect(metrics).toHaveTextContent(/Output tokens\s*unavailable/)
    expect(metrics).toHaveTextContent(/Prompt tokens\s*unavailable/)
    expect(metrics).not.toHaveTextContent(/Output tokens\s*0/)
  })

  it('shows real token counts when the model reported them', async () => {
    mockComparison({})
    renderPage()

    const metrics = await screen.findByRole('group', { name: 'Execution details' })
    expect(metrics).toHaveTextContent('2,300')
    expect(metrics).toHaveTextContent('640')
    expect(metrics).toHaveTextContent('qwen3:4b')
  })

  it('still renders a comparison saved before metrics existed', async () => {
    mockComparison({ started_at: null, metrics: {} as never })
    renderPage()

    expect(await screen.findByRole('heading', { name: /Solar growth/ })).toBeInTheDocument()
    expect(screen.getByText(/Both topics share a grid focus/)).toBeInTheDocument()
  })

  it('shows the prompt-read and writing split when Ollama reported them', async () => {
    mockComparison({
      metrics: {
        model: 'qwen3:4b',
        outcome: 'completed',
        phase: 'done',
        elapsed_ms: 120_000,
        prompt_tokens: 2124,
        output_tokens: 420,
        prefill_ms: 60_000,
        generation_ms: 55_000,
        repair_calls: 0,
        output_cap_reached: false,
      },
    })
    renderPage()

    const metrics = await screen.findByRole('group', { name: 'Execution details' })
    expect(metrics).toHaveTextContent(/Prompt read\s*60.0s/)
    expect(metrics).toHaveTextContent(/Writing\s*55.0s/)
    // A completed comparison that did not hit the cap should not claim it did.
    expect(metrics).not.toHaveTextContent('cap reached')
    expect(metrics).not.toHaveTextContent('Repairs')
  })

  it('flags a truncated comparison and any repair attempt', async () => {
    mockComparison({
      metrics: {
        model: 'qwen3:4b',
        outcome: 'completed',
        phase: 'done',
        elapsed_ms: 500_000,
        prompt_tokens: 2124,
        output_tokens: 900,
        output_cap_reached: true,
        repair_calls: 1,
      },
    })
    renderPage()

    const metrics = await screen.findByRole('group', { name: 'Execution details' })
    expect(metrics).toHaveTextContent('cap reached')
    expect(metrics).toHaveTextContent(/Repairs\s*1/)
  })

  it('renders the structured comparison without any model narration', async () => {
    mockComparison({
      report: [
        '# Comparison: Technical Barriers',
        '',
        '## Overview',
        '',
        'Both runs asked the same question about solid-state batteries.',
        '',
        '## Contradictions',
        '',
        'No direct contradiction was identified between the selected research runs.',
      ].join(String.fromCharCode(10)),
    })
    renderPage()

    expect(
      await screen.findByText(/Both runs asked the same question/),
    ).toBeInTheDocument()
    for (const narration of ['We are comparing', 'Let me', 'We need to']) {
      expect(screen.queryByText(new RegExp(narration))).not.toBeInTheDocument()
    }
    expect(
      screen.getByText(/No direct contradiction was identified/),
    ).toBeInTheDocument()
  })
})
