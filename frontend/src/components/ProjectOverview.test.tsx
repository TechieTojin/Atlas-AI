import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from '../test/mockFetch'
import type { ProjectOverview as Overview } from '../types'
import { ProjectOverview } from './ProjectOverview'

const PROJECT_ID = 'proj-1'

function finding(overrides: Partial<Overview['current_understanding'][0]> = {}) {
  return {
    id: 'f1',
    text: 'Interface instability remains the largest barrier to commercial solid-state cells.',
    section: 'Interface Stability',
    run_id: 'run-earlier',
    question: 'What are the biggest technical barriers for solid-state batteries?',
    created_at: '2026-10-06T10:00:00Z',
    support: 2,
    run_ids: ['run-earlier', 'run-second'],
    sources: [{ url: 'https://nature.com/x', title: 'Nature' }],
    ...overrides,
  }
}

function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    project: {
      id: PROJECT_ID,
      name: 'Battery Technology Research',
      description: 'Solid-state battery research',
      created_at: '2026-10-01T10:00:00Z',
      updated_at: '2026-10-06T10:00:00Z',
    },
    stats: { runs: 5, completed_runs: 3, findings: 26, unique_sources: 15, documents: 0 },
    current_understanding: [finding()],
    key_findings: [
      finding({
        id: 'f2',
        text: 'Manufacturing scale-up is limited by dry-room requirements.',
        section: 'Manufacturing',
        question: 'Which barrier is biggest for mass production?',
        run_id: 'run-second',
        support: 1,
        run_ids: ['run-second'],
      }),
    ],
    knowledge_gaps: [],
    recent_runs: [
      {
        id: 'run-second',
        query: 'Which barrier is biggest for mass production?',
        title: 'Which barrier is biggest for mass production?',
        status: 'COMPLETED',
        mode: 'FAST',
        created_at: '2026-10-06T09:40:00Z',
        findings_added: 8,
      },
    ],
    ...overrides,
  }
}

function renderOverview(onStart = vi.fn()) {
  render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}`]}>
      <Routes>
        <Route
          path="/projects/:id"
          element={<ProjectOverview projectId={PROJECT_ID} onStartResearch={onStart} />}
        />
        <Route path="/runs/:id" element={<p>Run detail page</p>} />
      </Routes>
    </MemoryRouter>,
  )
  return onStart
}

function mockOverview(body: Overview | undefined, status = 200) {
  return installFetchMock((url) =>
    url === `/api/projects/${PROJECT_ID}/overview` ? { status, body } : undefined,
  )
}

describe('ProjectOverview', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the snapshot, understanding, key findings and recent research', async () => {
    mockOverview(overview())
    renderOverview()

    expect(await screen.findByText('Current understanding')).toBeInTheDocument()
    const runsCard = screen.getByText('Runs').closest('.metric-card') as HTMLElement
    expect(within(runsCard).getByText('5')).toBeInTheDocument()
    expect(within(runsCard).getByText('3 completed')).toBeInTheDocument()
    const sourcesCard = screen.getByText('Sources').closest('.metric-card') as HTMLElement
    expect(within(sourcesCard).getByText('15')).toBeInTheDocument()
    expect(within(sourcesCard).getByText('unique')).toBeInTheDocument()
    expect(screen.getByText(/Interface instability remains/)).toBeInTheDocument()
    expect(screen.getByText('Key findings')).toBeInTheDocument()
    expect(screen.getByText(/Manufacturing scale-up is limited/)).toBeInTheDocument()
    // Corroboration across runs is surfaced.
    expect(screen.getByText('2 runs')).toBeInTheDocument()
    expect(screen.getByText('8 findings added')).toBeInTheDocument()
  })

  it('links every finding back to the research that produced it', async () => {
    mockOverview(overview())
    renderOverview()

    const link = await screen.findByRole('link', {
      name: /biggest technical barriers for solid-state batteries/,
    })
    expect(link).toHaveAttribute('href', '/runs/run-earlier')
    await userEvent.click(link)
    expect(await screen.findByText('Run detail page')).toBeInTheDocument()
  })

  it('opens a recent run when clicked', async () => {
    mockOverview(overview())
    renderOverview()

    const recent = (await screen.findByText('Recent research')).closest('section') as HTMLElement
    await userEvent.click(
      within(recent).getByRole('link', { name: 'Which barrier is biggest for mass production?' }),
    )
    expect(await screen.findByText('Run detail page')).toBeInTheDocument()
  })

  it('expands to all findings on request', async () => {
    mockOverview(overview())
    renderOverview()

    const button = await screen.findByRole('button', { name: 'View all findings' })
    expect(screen.getAllByText(/Interface instability remains/)).toHaveLength(1)
    await userEvent.click(button)
    // The understanding item now also appears in the expanded list.
    expect(screen.getAllByText(/Interface instability remains/)).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Show fewer findings' })).toBeInTheDocument()
  })

  it('states honestly when no knowledge gaps are known, and lists real ones', async () => {
    mockOverview(overview())
    renderOverview()
    expect(
      await screen.findByText('No clear knowledge gaps have been identified yet.'),
    ).toBeInTheDocument()

    mockOverview(
      overview({
        knowledge_gaps: [
          {
            text: 'What are the biggest technical barriers for solid-state batteries?',
            reason: 'This research did not complete, so the question is still unanswered.',
            run_id: 'run-failed',
            question: 'What are the biggest technical barriers for solid-state batteries?',
          },
        ],
      }),
    )
    renderOverview()
    expect(await screen.findByText(/did not complete/)).toBeInTheDocument()
  })

  it('distinguishes failed runs and never credits them with findings', async () => {
    mockOverview(
      overview({
        recent_runs: [
          {
            id: 'run-failed',
            query: 'Interrupted question?',
            title: 'Interrupted question?',
            status: 'FAILED',
            mode: 'FAST',
            created_at: '2026-10-06T08:00:00Z',
            findings_added: 0,
          },
        ],
      }),
    )
    renderOverview()

    const row = (await screen.findByText('Interrupted question?')).closest('.run-row') as HTMLElement
    expect(row).toHaveClass('inactive')
    expect(within(row).getByText('Failed')).toBeInTheDocument()
    expect(within(row).queryByText(/finding/)).not.toBeInTheDocument()
  })

  it('invites first research in a brand-new project', async () => {
    const onStart = renderOverviewEmpty()
    expect(await screen.findByText('Start your first research')).toBeInTheDocument()
    expect(screen.queryByText('Current understanding')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Start research' }))
    expect(onStart).toHaveBeenCalled()

    function renderOverviewEmpty() {
      mockOverview(
        overview({
          stats: { runs: 0, completed_runs: 0, findings: 0, unique_sources: 0, documents: 0 },
          current_understanding: [],
          key_findings: [],
          recent_runs: [],
        }),
      )
      return renderOverview()
    }
  })

  it('explains a project that has documents but no research', async () => {
    mockOverview(
      overview({
        stats: { runs: 0, completed_runs: 0, findings: 0, unique_sources: 0, documents: 2 },
        current_understanding: [],
        key_findings: [],
        recent_runs: [],
      }),
    )
    renderOverview()
    expect(await screen.findByText('Documents are ready')).toBeInTheDocument()
    expect(screen.getByText(/2 documents but/)).toBeInTheDocument()
  })

  it('explains a project with runs but no findings yet', async () => {
    mockOverview(
      overview({
        stats: { runs: 2, completed_runs: 0, findings: 0, unique_sources: 0, documents: 0 },
        current_understanding: [],
        key_findings: [],
      }),
    )
    renderOverview()
    expect(await screen.findByText(/No findings yet/)).toBeInTheDocument()
    expect(screen.queryByText('Start your first research')).not.toBeInTheDocument()
  })

  it('shows a retryable error when the overview cannot load', async () => {
    const fetchMock = installFetchMock((url) =>
      url === `/api/projects/${PROJECT_ID}/overview`
        ? { status: 503, body: { detail: 'Storage is unavailable.' } }
        : undefined,
    )
    renderOverview()

    expect(await screen.findByRole('alert')).toHaveTextContent('Storage is unavailable.')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })

  it('shows a loading state first', async () => {
    mockOverview(overview())
    renderOverview()
    expect(screen.getByRole('status')).toHaveTextContent('Loading overview…')
    expect(await screen.findByText('Current understanding')).toBeInTheDocument()
  })
})
