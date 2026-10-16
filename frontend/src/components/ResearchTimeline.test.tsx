import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { loadMessages } from '../i18n'
import { installFetchMock } from '../test/mockFetch'
import { renderWithLocale } from '../test/renderWithLocale'
import type { RunTimeline, TimelineEntry } from '../types'
import { ResearchTimeline } from './ResearchTimeline'

function entry(partial: Partial<TimelineEntry> & Pick<TimelineEntry, 'seq' | 'kind'>): TimelineEntry {
  return { at: '2026-10-09T10:00:00Z', offset_ms: 0, agent: '', iteration: 0, detail: {}, ...partial }
}

const ENTRIES: TimelineEntry[] = [
  entry({ seq: 1, kind: 'RUN_STARTED' }),
  entry({ seq: 2, kind: 'PLANNING_STARTED', offset_ms: 2_000, agent: 'planner' }),
  entry({ seq: 3, kind: 'PLAN_CREATED', offset_ms: 41_000, detail: { queries: ['solid state batteries'] } }),
  entry({ seq: 4, kind: 'SEARCH_QUERY_COMPLETED', offset_ms: 65_000, iteration: 1, detail: { query: 'solid state batteries', results: 5 } }),
  entry({ seq: 5, kind: 'CRITIC_COMPLETED', offset_ms: 114_000, iteration: 1, detail: { score: 9, decision: 'SYNTHESIZE' } }),
  entry({ seq: 6, kind: 'SYNTHESIS_STARTED', offset_ms: 115_000 }),
  entry({ seq: 7, kind: 'RUN_COMPLETED', offset_ms: 382_000, detail: { cited: 4 } }),
]

function timeline(overrides: Partial<RunTimeline> = {}): RunTimeline {
  return {
    run_id: 'run-1',
    run_status: 'COMPLETED',
    question: 'Q',
    started_at: '2026-10-09T10:00:00Z',
    completed_at: '2026-10-09T10:06:22Z',
    duration_ms: 382_000,
    entries: ENTRIES,
    iterations: 1,
    incomplete: false,
    ...overrides,
  }
}

function mockTimeline(body: RunTimeline | (() => { status?: number; body?: unknown })) {
  return installFetchMock((url) =>
    url === '/api/runs/run-1/timeline' ? (typeof body === 'function' ? body() : { body }) : undefined,
  )
}

beforeAll(async () => {
  await Promise.all(['hi', 'ml'].map((code) => loadMessages(code)))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Research Timeline', () => {
  it('lists stored events chronologically with offsets and details', async () => {
    mockTimeline(timeline())
    const { t } = await renderWithLocale(<ResearchTimeline runId="run-1" />)
    const list = await screen.findByRole('list', { name: t('runTimeline.listLabel') })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(ENTRIES.length)
    expect(items[0]).toHaveTextContent('00:00')
    expect(items[0]).toHaveTextContent('Research started')
    expect(items[2]).toHaveTextContent('00:41')
    expect(items[3]).toHaveTextContent('“solid state batteries”')
    expect(items[3]).toHaveTextContent('round 1')
    expect(items[4]).toHaveTextContent('9/10')
    expect(items[4]).toHaveTextContent('SYNTHESIZE')
    expect(items[6]).toHaveTextContent('06:22')
    expect(screen.getByText(`${ENTRIES.length} / ${ENTRIES.length} steps`)).toBeInTheDocument()
  })

  it('steps backwards and forwards without inventing entries', async () => {
    const user = userEvent.setup()
    mockTimeline(timeline())
    const { t } = await renderWithLocale(<ResearchTimeline runId="run-1" />)
    await screen.findByRole('list', { name: t('runTimeline.listLabel') })
    await user.click(screen.getByRole('button', { name: t('runTimeline.previous') }))
    expect(screen.getAllByRole('listitem')).toHaveLength(ENTRIES.length - 1)
    await user.click(screen.getByRole('button', { name: t('runTimeline.restart') }))
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    expect(screen.getByText(`0 / ${ENTRIES.length} steps`)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: t('runTimeline.next') }))
    await user.click(screen.getByRole('button', { name: t('runTimeline.next') }))
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[1]).toHaveTextContent('Planner started')
  })

  it('replays stored entries progressively and pauses', async () => {
    vi.useFakeTimers()
    mockTimeline(timeline())
    const { t } = await renderWithLocale(<ResearchTimeline runId="run-1" />)
    await vi.waitFor(() => screen.getByRole('list', { name: t('runTimeline.listLabel') }))
    fireEvent.click(screen.getByRole('button', { name: t('runTimeline.start') }))
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(900)
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1800)
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: t('runTimeline.pause') }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    // Speed control doubles the reveal rate.
    fireEvent.click(screen.getByRole('button', { name: t('runTimeline.speed') }))
    fireEvent.click(screen.getByRole('button', { name: t('runTimeline.start') }))
    await vi.advanceTimersByTimeAsync(900)
    expect(screen.getAllByRole('listitem')).toHaveLength(5)
  })

  it('marks historical runs without events as incomplete, never invented', async () => {
    mockTimeline(timeline({ entries: [], incomplete: true }))
    const { t } = await renderWithLocale(<ResearchTimeline runId="run-1" />)
    expect(await screen.findByText(t('runTimeline.incomplete'))).toBeInTheDocument()
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  })

  it('shows failure entries with the stored message', async () => {
    mockTimeline(
      timeline({
        run_status: 'FAILED',
        entries: [
          entry({ seq: 1, kind: 'RUN_STARTED' }),
          entry({ seq: 2, kind: 'RUN_FAILED', offset_ms: 9_000, detail: { message: 'PlanningError: no plan' } }),
        ],
      }),
    )
    await renderWithLocale(<ResearchTimeline runId="run-1" />)
    expect(await screen.findByText('Research failed')).toBeInTheDocument()
    expect(screen.getByText(/PlanningError: no plan/)).toBeInTheDocument()
  })

  it('shows an error state with retry', async () => {
    const user = userEvent.setup()
    let fail = true
    mockTimeline(() => (fail ? { status: 500, body: { detail: 'down' } } : { body: timeline() }))
    const { t } = await renderWithLocale(<ResearchTimeline runId="run-1" />)
    expect(await screen.findByText(t('runTimeline.error'))).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: t('researchMap.retry') }))
    expect(await screen.findByText('Research started')).toBeInTheDocument()
  })

  it.each(['hi', 'ml'])('translates controls and kinds but never stored details (%s)', async (language) => {
    mockTimeline(timeline())
    const { t } = await renderWithLocale(<ResearchTimeline runId="run-1" />, { language })
    await screen.findByRole('list', { name: t('runTimeline.listLabel') })
    expect(t('runTimeline.start')).not.toBe('Play')
    expect(screen.getByRole('button', { name: t('runTimeline.start') })).toBeInTheDocument()
    expect(screen.getByText(t('runTimeline.kind.PLAN_CREATED'))).toBeInTheDocument()
    expect(screen.getByText('“solid state batteries”')).toBeInTheDocument() // stored query untouched
    expect(document.body.textContent).not.toContain('�')
  })
})
