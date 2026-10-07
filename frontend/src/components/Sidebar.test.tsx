import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeRunSummary } from '../test/fixtures'
import { installFetchMock } from '../test/mockFetch'
import { Sidebar } from './Sidebar'

const runs = [
  makeRunSummary({ id: 'r1', title: 'Solar growth', status: 'COMPLETED', mode: 'DEEP' }),
  makeRunSummary({ id: 'r2', title: 'Battery costs', status: 'RESEARCHING', mode: 'FAST' }),
]

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Sidebar open={false} onClose={vi.fn()} theme="dark" onToggleTheme={vi.fn()} />
      <Routes>
        <Route path="/" element={null} />
        <Route path="/runs/:id" element={<div>opened run r1</div>} />
        <Route path="/documents" element={null} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Sidebar history', () => {
  beforeEach(() => {
    installFetchMock((url) => {
      if (url.startsWith('/api/runs')) {
        return { body: { runs, total: runs.length, limit: 50, offset: 0 } }
      }
      return undefined
    })
  })

  it('renders the run history with titles, status, and mode badges', async () => {
    renderSidebar()
    expect(await screen.findByText('Solar growth')).toBeInTheDocument()
    expect(screen.getByText('Battery costs')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Completed' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Researching' })).toBeInTheDocument()
    expect(screen.getByText('DEEP')).toBeInTheDocument()
    expect(screen.getByText('FAST')).toBeInTheDocument()
  })

  it('navigates to the run when a history item is clicked', async () => {
    renderSidebar()
    await userEvent.click(await screen.findByText('Solar growth'))
    expect(await screen.findByText('opened run r1')).toBeInTheDocument()
  })

  it('shows an empty state when there is no history', async () => {
    installFetchMock((url) => {
      if (url.startsWith('/api/runs')) {
        return { body: { runs: [], total: 0, limit: 50, offset: 0 } }
      }
      return undefined
    })
    renderSidebar()
    expect(await screen.findByText('No research yet.')).toBeInTheDocument()
  })
})
