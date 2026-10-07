import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { makeComparison } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock } from '../test/mockFetch'
import { ComparisonPage } from './ComparisonPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/comparisons/cmp-1']}>
      <Routes>
        <Route path="/comparisons/:id" element={<ComparisonPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ComparisonPage', () => {
  beforeEach(() => {
    MockEventSource.reset()
    vi.stubGlobal('EventSource', MockEventSource)
  })

  it('renders overlap stats, run chips, the report, and the export link', async () => {
    installFetchMock((url) => {
      if (url === '/api/comparisons/cmp-1') {
        return { body: makeComparison() }
      }
      if (url === '/api/comparisons/cmp-1/claims') {
        return { body: { claims: [] } }
      }
      return undefined
    })
    renderPage()

    expect(
      await screen.findByRole('heading', { name: 'Solar growth vs Battery costs' }),
    ).toBeInTheDocument()

    // Run overview chips link to the compared runs.
    expect(screen.getByRole('link', { name: 'Solar growth' })).toHaveAttribute('href', '/runs/run-1')
    expect(screen.getByRole('link', { name: 'Battery costs' })).toHaveAttribute('href', '/runs/run-2')

    // Overlap stat cards.
    expect(screen.getByText('Total sources').previousSibling).toHaveTextContent('2')
    expect(screen.getByText('Shared sources').previousSibling).toHaveTextContent('1')
    expect(screen.getByText('Unique to Battery costs').previousSibling).toHaveTextContent('1')

    // The comparison report renders with interactive citations.
    expect(screen.getByRole('heading', { name: 'Comparison' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View source 1' })).toBeInTheDocument()

    expect(screen.getByRole('link', { name: /Export/ })).toHaveAttribute(
      'href',
      '/api/comparisons/cmp-1/export',
    )
  })

  it('opens the citation drawer showing which runs used the source', async () => {
    installFetchMock((url) => {
      if (url === '/api/comparisons/cmp-1') {
        return { body: makeComparison() }
      }
      if (url === '/api/comparisons/cmp-1/claims') {
        return { body: { claims: [] } }
      }
      return undefined
    })
    renderPage()
    await screen.findByRole('heading', { name: 'Solar growth vs Battery costs' })

    await userEvent.click(screen.getByRole('button', { name: 'View source 1' }))
    const drawer = screen.getByRole('dialog', { name: /Source 1/ })
    expect(drawer).toHaveTextContent('Used by runs')
    expect(drawer).toHaveTextContent('Solar growth')
    expect(drawer).toHaveTextContent('Battery costs')
  })

  it('shows a live progress state and refetches once the stream terminates', async () => {
    let status: 'RUNNING' | 'COMPLETED' = 'RUNNING'
    installFetchMock((url) => {
      if (url === '/api/comparisons/cmp-1') {
        return { body: makeComparison({ status }) }
      }
      if (url === '/api/comparisons/cmp-1/claims') {
        return { body: { claims: [] } }
      }
      return undefined
    })
    renderPage()

    expect(await screen.findByText('Comparing 2 runs…')).toBeInTheDocument()
    const source = MockEventSource.latest()
    expect(source.url).toBe('/api/comparisons/cmp-1/events')

    status = 'COMPLETED'
    source.emit('COMPARISON_COMPLETED', {
      type: 'COMPARISON_COMPLETED',
      run_id: 'cmp-1',
      seq: 1,
      timestamp: '2026-10-02T12:00:08Z',
      agent: 'comparison',
      message: '',
      iteration: 0,
      payload: {},
    })

    expect(await screen.findByText('Total sources')).toBeInTheDocument()
  })
})
