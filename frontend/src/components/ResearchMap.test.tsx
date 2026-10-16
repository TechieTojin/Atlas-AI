import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { loadMessages } from '../i18n'
import { installFetchMock } from '../test/mockFetch'
import { renderWithLocale } from '../test/renderWithLocale'
import type { ResearchMap as MapData, ResearchMapNode } from '../types'
import { layout, ResearchMap, visibleGraph } from './ResearchMap'

function node(partial: Partial<ResearchMapNode> & Pick<ResearchMapNode, 'id' | 'type'>): ResearchMapNode {
  return {
    label: '',
    status: 'completed',
    rank: 0,
    iteration: null,
    group: null,
    started_at: null,
    completed_at: null,
    duration_ms: null,
    data: {},
    ...partial,
  }
}

const QUESTION = 'सौर सेल की दक्षता क्या है? What changed in 2009?'

function makeMap(overrides: Partial<MapData> = {}): MapData {
  const nodes: ResearchMapNode[] = [
    node({ id: 'question', type: 'question', label: QUESTION, rank: 0, data: { question: QUESTION, mode: 'FAST', source_scope: 'WEB', template: 'STANDARD', output_language: 'en', use_memory: true } }),
    node({ id: 'plan', type: 'plan', label: 'Objective', rank: 1, duration_ms: 4200, data: { objective: 'Objective', subquestions: ['Sub A', 'Sub B'], search_queries: ['perovskite efficiency 2009'] } }),
    node({ id: 'query:1:0', type: 'query', label: 'perovskite efficiency 2009', rank: 2, iteration: 1, data: { query: 'perovskite efficiency 2009', retrieval: 'web', web_results: 5, document_chunks: 0, memory_hits: 0 } }),
    node({ id: 'evidence:a', type: 'evidence', label: 'Excerpt A', rank: 3, iteration: 1, group: 'evidence:1', data: { content: 'Original excerpt A: 3.8% in 2009.', query: 'perovskite efficiency 2009', origin: 'web', extraction: 'full_page', relevance: 0.81, citation: 1, source_title: 'Paper One' } }),
    node({ id: 'evidence:b', type: 'evidence', label: 'Excerpt B', rank: 3, iteration: 1, group: 'evidence:1', data: { content: 'Original excerpt B.', query: 'perovskite efficiency 2009', origin: 'web', extraction: 'snippet', relevance: 0.6, citation: null, source_title: 'Other' } }),
    node({ id: 'critic:1', type: 'critic', rank: 4, iteration: 1, data: { score: 4, decision: 'MORE_RESEARCH', follow_up_queries: ['deeper follow up'] } }),
    node({ id: 'query:2:0', type: 'query', label: 'deeper follow up', rank: 5, iteration: 2, data: { query: 'deeper follow up', retrieval: 'web' } }),
    node({ id: 'critic:2', type: 'critic', rank: 7, iteration: 2, status: 'skipped', data: { score: null, decision: 'SYNTHESIZE', fallback_reason: 'skipped: FAST budget' } }),
    node({ id: 'source:1', type: 'source', label: 'Paper One', rank: 8, group: 'sources', data: { citation: 1, title: 'Paper One', url: 'https://journal.example/p1', domain: 'journal.example', quality: { category: 'academic', tier: 'high', score: 90 } } }),
    node({ id: 'source:2', type: 'source', label: 'Bad link', rank: 8, group: 'sources', data: { citation: 2, title: 'Bad link', url: 'javascript:alert(1)', domain: '' } }),
    node({ id: 'synthesis', type: 'synthesis', rank: 9, status: 'fallback', data: { template: 'STANDARD', output_language: 'en', sources: 2, evidence: 2, fallback: true, fallback_reason: 'synthesis timed out' } }),
    node({ id: 'report', type: 'report', label: 'Perovskite report', rank: 10, data: { citations: 1, word_count: 420 } }),
  ]
  return {
    run_id: 'run-1',
    run_status: 'COMPLETED',
    question: QUESTION,
    mode: 'FAST',
    source_scope: 'WEB',
    template: 'STANDARD',
    output_language: 'en',
    live: false,
    nodes,
    edges: [
      { id: 'e1', source: 'question', target: 'plan', type: 'PLANNED', metadata: {} },
      { id: 'e2', source: 'plan', target: 'query:1:0', type: 'PLANNED', metadata: {} },
      { id: 'e3', source: 'query:1:0', target: 'evidence:a', type: 'RETRIEVED', metadata: {} },
      { id: 'e4', source: 'query:1:0', target: 'evidence:b', type: 'RETRIEVED', metadata: {} },
      { id: 'e5', source: 'evidence:a', target: 'source:1', type: 'FROM_SOURCE', metadata: {} },
      { id: 'e6', source: 'critic:1', target: 'query:2:0', type: 'REQUESTED_MORE_RESEARCH', metadata: {} },
      { id: 'e7', source: 'critic:2', target: 'synthesis', type: 'PROCEEDED_TO_SYNTHESIS', metadata: {} },
      { id: 'e8', source: 'synthesis', target: 'report', type: 'PRODUCED', metadata: {} },
      { id: 'e9', source: 'source:1', target: 'report', type: 'CITED_IN_REPORT', metadata: {} },
    ],
    groups: [
      { id: 'group:evidence:1', key: 'evidence:1', type: 'evidence', iteration: 1, rank: 3, members: ['evidence:a', 'evidence:b'] },
      { id: 'group:sources', key: 'sources', type: 'source', iteration: null, rank: 8, members: ['source:1', 'source:2'] },
    ],
    summary: { node_count: nodes.length, edge_count: 9, source_count: 2, evidence_count: 2, query_count: 2, iterations: 2, incomplete_history: false },
    limitations: [],
    ...overrides,
  }
}

function mockMap(map: MapData | (() => { status?: number; body?: unknown })) {
  return installFetchMock((url) => {
    if (url === '/api/runs/run-1/research-map') return typeof map === 'function' ? map() : { body: map }
    return undefined
  })
}

beforeAll(async () => {
  await Promise.all(['ml', 'hi', 'de'].map((code) => loadMessages(code)))
})

async function renderMap(map: MapData = makeMap(), language = 'en', onOpenReport = vi.fn()) {
  mockMap(map)
  const utils = await renderWithLocale(<ResearchMap runId="run-1" onOpenReport={onOpenReport} />, { language })
  await screen.findByText(utils.t('researchMap.title'))
  return { ...utils, onOpenReport }
}

const nodeButton = (name: RegExp) => screen.getByRole('button', { name })

describe('Research Map — rendering', () => {
  it('shows a loading state, then the real execution stages', async () => {
    mockMap(makeMap())
    const { t } = await renderWithLocale(<ResearchMap runId="run-1" />)
    expect(screen.getByRole('status')).toHaveTextContent(t('researchMap.loading'))
    expect(await screen.findByText(t('researchMap.title'))).toBeInTheDocument()
    for (const type of ['question', 'plan', 'critic', 'synthesis', 'report'] as const) {
      expect(screen.getAllByRole('button', { name: new RegExp(`^${t(`researchMap.type.${type}`)}:`) }).length).toBeGreaterThan(0)
    }
    expect(nodeButton(/^Search: perovskite efficiency 2009/)).toBeInTheDocument()
    expect(nodeButton(/^Search: deeper follow up/)).toBeInTheDocument()
  })

  it('shows truthful statuses as text, not colour alone', async () => {
    await renderMap()
    expect(nodeButton(/^Review: Review\. Skipped$/)).toHaveTextContent('Skipped')
    expect(nodeButton(/^Synthesis: Synthesis\. Fallback$/)).toHaveTextContent('Fallback')
    expect(nodeButton(/^Review: Score 4\/10 · MORE_RESEARCH\. Completed$/)).toBeInTheDocument()
  })

  it('groups sources and evidence by default and expands/collapses them', async () => {
    const user = userEvent.setup()
    await renderMap()
    expect(nodeButton(/^Source: Sources \(2\)/)).toBeInTheDocument()
    expect(nodeButton(/^Evidence: Evidence \(2\)/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Source: \[1\] Paper One/ })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(nodeButton(/^Source: \[1\] Paper One/)).toBeInTheDocument()
    expect(nodeButton(/^Evidence: Excerpt A/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Collapse all' }))
    expect(screen.queryByRole('button', { name: /^Source: \[1\] Paper One/ })).toBeNull()
  })

  it('keeps grouped data reachable from the group inspector', async () => {
    const user = userEvent.setup()
    await renderMap()
    await user.click(nodeButton(/^Evidence: Evidence \(2\)/))
    const drawer = screen.getByRole('dialog', { name: 'Evidence (2)' })
    await user.click(within(drawer).getByRole('button', { name: 'Excerpt A' }))
    const evidence = screen.getByRole('dialog', { name: 'Evidence' })
    expect(evidence).toHaveTextContent('Original excerpt A: 3.8% in 2009.')
    expect(evidence).toHaveTextContent('[1]')
    await user.click(within(evidence).getByRole('button', { name: 'Show source' }))
    expect(screen.getByRole('dialog', { name: 'Source' })).toHaveTextContent('Paper One')
  })

  it('a historical run says what was not recorded', async () => {
    await renderMap(makeMap({ limitations: ['events_not_recorded'] }))
    expect(screen.getByText(/were not recorded for this historical run/)).toBeInTheDocument()
  })

  it('a cancelled run shows only what happened, ending in Cancelled', async () => {
    const map = makeMap({
      run_status: 'CANCELLED',
      nodes: [
        node({ id: 'question', type: 'question', label: 'Q', rank: 0 }),
        node({ id: 'plan', type: 'plan', label: 'P', rank: 1, data: { subquestions: [], search_queries: [] } }),
        node({ id: 'terminal', type: 'terminal', rank: 2, status: 'cancelled', data: { status: 'CANCELLED' } }),
      ],
      edges: [],
      groups: [],
    })
    await renderMap(map)
    expect(nodeButton(/^Run ended: Run ended\. Cancelled$/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Report:/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Expand all' })).toBeNull()
  })

  it('a failed run shows its error', async () => {
    const user = userEvent.setup()
    const map = makeMap({
      run_status: 'FAILED',
      nodes: [
        node({ id: 'question', type: 'question', label: 'Q', rank: 0 }),
        node({ id: 'terminal', type: 'terminal', rank: 1, status: 'failed', data: { status: 'FAILED', error: 'RuntimeError: boom' } }),
      ],
      edges: [],
      groups: [],
    })
    await renderMap(map)
    await user.click(nodeButton(/^Run ended: Run ended\. Failed$/))
    expect(screen.getByRole('dialog')).toHaveTextContent('RuntimeError: boom')
  })

  it('an empty map still renders the question honestly', async () => {
    await renderMap(makeMap({ nodes: [node({ id: 'question', type: 'question', label: 'Only Q', rank: 0 })], edges: [], groups: [] }))
    expect(nodeButton(/^Question: Only Q/)).toBeInTheDocument()
  })

  it('shows an error with a working retry', async () => {
    const user = userEvent.setup()
    let fail = true
    mockMap(() => (fail ? { status: 500, body: { detail: 'Server down' } } : { body: makeMap() }))
    const { t } = await renderWithLocale(<ResearchMap runId="run-1" />)
    expect(await screen.findByText(t('researchMap.error'))).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: t('researchMap.retry') }))
    expect(await screen.findByText(t('researchMap.title'))).toBeInTheDocument()
  })
})

describe('Research Map — inspector', () => {
  it('opens on click, Enter and Space, and closes with Escape and the close button', async () => {
    const user = userEvent.setup()
    await renderMap()
    await user.click(nodeButton(/^Plan:/))
    const plan = screen.getByRole('dialog', { name: 'Plan' })
    expect(plan).toHaveTextContent('Sub A')
    expect(plan).toHaveTextContent('perovskite efficiency 2009')
    expect(plan).toHaveTextContent('4.2 s')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()

    nodeButton(/^Question:/).focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('dialog', { name: 'Question' })).toHaveTextContent(QUESTION)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()

    nodeButton(/^Search: perovskite efficiency 2009/).focus()
    await user.keyboard(' ')
    expect(screen.getByRole('dialog', { name: 'Search' })).toHaveTextContent('Web search')
  })

  it('shows the critic outcome and the follow-up queries that caused the next round', async () => {
    const user = userEvent.setup()
    await renderMap()
    await user.click(nodeButton(/^Review: Score 4\/10/))
    const critic = screen.getByRole('dialog', { name: 'Review' })
    expect(critic).toHaveTextContent('MORE_RESEARCH')
    expect(critic).toHaveTextContent('deeper follow up')
    await user.keyboard('{Escape}')
    await user.click(nodeButton(/^Review: Review\. Skipped$/))
    expect(screen.getByRole('dialog', { name: 'Review' })).toHaveTextContent('skipped: FAST budget')
  })

  it('opens safe sources and refuses unsafe URLs', async () => {
    const user = userEvent.setup()
    await renderMap()
    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    await user.click(nodeButton(/^Source: \[1\] Paper One/))
    const link = within(screen.getByRole('dialog')).getByRole('link', { name: 'Open source' })
    expect(link).toHaveAttribute('href', 'https://journal.example/p1')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    await user.keyboard('{Escape}')
    await user.click(nodeButton(/^Source: \[2\] Bad link/))
    expect(within(screen.getByRole('dialog')).queryByRole('link')).toBeNull()
  })

  it('Open report hands control back to the report tab', async () => {
    const user = userEvent.setup()
    const { onOpenReport } = await renderMap()
    await user.click(nodeButton(/^Report: Perovskite report/))
    await user.click(screen.getByRole('button', { name: 'Open report' }))
    expect(onOpenReport).toHaveBeenCalledTimes(1)
  })

  it('selecting a node highlights its neighbourhood and dims the rest', async () => {
    const user = userEvent.setup()
    await renderMap()
    await user.click(nodeButton(/^Plan:/))
    await user.keyboard('{Escape}')
    await user.click(nodeButton(/^Plan:/))
    expect(nodeButton(/^Plan:/)).toHaveClass('selected')
    expect(nodeButton(/^Question:/)).not.toHaveClass('dim')
    expect(nodeButton(/^Report:/)).toHaveClass('dim')
  })

  it('renders evidence as text, never as markup', async () => {
    const user = userEvent.setup()
    const map = makeMap()
    map.nodes[3].data.content = '<img src=x onerror="alert(1)"> plain'
    await renderMap(map)
    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    await user.click(nodeButton(/^Evidence: Excerpt A/))
    const drawer = screen.getByRole('dialog')
    expect(drawer.querySelector('img')).toBeNull()
    expect(drawer).toHaveTextContent('<img src=x onerror="alert(1)"> plain')
  })
})

describe('Research Map — controls and layout', () => {
  it('zoom and Fit view controls are present and usable', async () => {
    const user = userEvent.setup()
    const { container } = await renderMap()
    const stage = container.querySelector('.research-map-stage') as HTMLElement
    const before = stage.style.transform
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(stage.style.transform).not.toBe(before)
    await user.click(screen.getByRole('button', { name: 'Fit view' }))
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    fireEvent.pointerDown(container.querySelector('.research-map-viewport') as HTMLElement, { clientX: 10, clientY: 10 })
    fireEvent.pointerMove(container.querySelector('.research-map-viewport') as HTMLElement, { clientX: 60, clientY: 40 })
    expect(stage.style.transform).toContain('translate')
  })

  it('layout is deterministic and left-to-right by stored rank', () => {
    const map = makeMap()
    const first = layout(visibleGraph(map, new Set()).items)
    const second = layout(visibleGraph(map, new Set()).items)
    expect(first).toEqual(second)
    const x = (id: string) => first.placed.find((p) => p.item.id === id)!.x
    expect(x('question')).toBeLessThan(x('plan'))
    expect(x('plan')).toBeLessThan(x('query:1:0'))
    expect(x('critic:1')).toBeLessThan(x('query:2:0'))
    expect(x('synthesis')).toBeLessThan(x('report'))
  })

  it('collapsed groups re-point edges without losing them', () => {
    const { edges } = visibleGraph(makeMap(), new Set())
    expect(edges.some((e) => e.source === 'query:1:0' && e.target === 'group:evidence:1')).toBe(true)
    expect(edges.some((e) => e.source === 'group:sources' && e.target === 'report')).toBe(true)
  })

  it('provides a text list of every step for assistive technology', async () => {
    await renderMap()
    const list = screen.getByRole('list', { name: 'Research steps in order' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(makeMap().nodes.length)
  })
})

describe('Research Map — languages', () => {
  it.each(['de', 'hi', 'ml'])('translates static UI but never stored research text (%s)', async (language) => {
    const { t } = await renderMap(makeMap(), language)
    expect(screen.getByText(t('researchMap.title'))).toBeInTheDocument()
    expect(t('researchMap.title')).not.toBe('Research Map')
    expect(screen.getByRole('button', { name: t('researchMap.fit') })).toBeInTheDocument()
    // Stored artifacts stay exactly as stored.
    expect(screen.getByText(QUESTION)).toBeInTheDocument()
    expect(screen.getByText('perovskite efficiency 2009')).toBeInTheDocument()
    await waitFor(() => expect(document.body.textContent).not.toContain('�'))
  })
})

describe('Research Map — V2 branching and views', () => {
  it('offers Map and Timeline views of the same run', async () => {
    const user = userEvent.setup()
    const map = makeMap()
    installFetchMock((url) => {
      if (url === '/api/runs/run-1/research-map') return { body: map }
      if (url === '/api/runs/run-1/timeline')
        return {
          body: {
            run_id: 'run-1', run_status: 'COMPLETED', question: 'Q', started_at: null,
            completed_at: null, duration_ms: 1000, iterations: 1, incomplete: false,
            entries: [{ seq: 1, at: '2026-10-09T10:00:00Z', offset_ms: 0, kind: 'RUN_STARTED', agent: '', iteration: 0, detail: {} }],
          },
        }
      return undefined
    })
    const { t } = await renderWithLocale(<ResearchMap runId="run-1" />)
    await screen.findByText(t('researchMap.title'))
    await user.click(screen.getByRole('tab', { name: t('researchMap.viewTimeline') }))
    expect(await screen.findByText(t('runTimeline.kind.RUN_STARTED'))).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: t('researchMap.viewMap') }))
    expect(await screen.findByText(t('researchMap.title'))).toBeInTheDocument()
  })

  it('renders branched child runs from the backend and opens them', async () => {
    const user = userEvent.setup()
    const map = makeMap()
    map.nodes.push(
      node({
        id: 'branch:child-1', type: 'branch', label: 'Child question', rank: 4,
        data: { run_id: 'child-1', instruction: 'Dig deeper', status: 'COMPLETED', mode: 'FAST' },
      }),
    )
    map.edges.push({ id: 'eb', source: 'evidence:a', target: 'branch:child-1', type: 'BRANCHED', metadata: {} })
    await renderMap(map)
    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    await user.click(nodeButton(/^Branched research: Child question/))
    const drawer = screen.getByRole('dialog', { name: 'Branched research' })
    expect(drawer).toHaveTextContent('Dig deeper')
    expect(within(drawer).getByRole('button', { name: 'Open research' })).toBeInTheDocument()
  })

  it('lets the user research further from real nodes only, via the composer', async () => {
    const user = userEvent.setup()
    const map = makeMap()
    let posted: unknown = null
    installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/research-map') return { body: map }
      if (url === '/api/runs/run-1/branches' && init?.method === 'POST') {
        posted = JSON.parse(String(init.body))
        return { status: 201, body: { id: 'child-9' } }
      }
      return undefined
    })
    const { t } = await renderWithLocale(<ResearchMap runId="run-1" />)
    await screen.findByText(t('researchMap.title'))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Expand all' }))
    await user.click(nodeButton(/^Evidence: Excerpt A/))
    const drawer = screen.getByRole('dialog')
    await user.click(within(drawer).getByRole('button', { name: t('researchMap.branchAction') }))
    const textarea = within(drawer).getByLabelText(t('researchMap.branchInstructionLabel'))
    expect(within(drawer).getByRole('button', { name: t('researchMap.branchStart') })).toBeDisabled()
    await user.type(textarea, 'Investigate encapsulation methods.')
    await user.click(within(drawer).getByRole('button', { name: t('researchMap.branchStart') }))
    await waitFor(() => expect(posted).not.toBeNull())
    expect(posted).toEqual({ node_id: 'evidence:a', instruction: 'Investigate encapsulation methods.', mode: 'FAST' })
  })

  it('never offers branching from synthesis, report or terminal nodes', async () => {
    const user = userEvent.setup()
    const { t } = await renderMap()
    await user.click(nodeButton(/^Synthesis:/))
    expect(screen.queryByRole('button', { name: t('researchMap.branchAction') })).toBeNull()
    await user.keyboard('{Escape}')
    await user.click(nodeButton(/^Report:/))
    expect(screen.queryByRole('button', { name: t('researchMap.branchAction') })).toBeNull()
  })
})

