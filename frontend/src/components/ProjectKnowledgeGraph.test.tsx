import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from '../test/mockFetch'
import type { ProjectGraph } from '../types'
import {
  ProjectKnowledgeGraph,
  fitTransform,
  layoutGraph,
  wrapLabel,
} from './ProjectKnowledgeGraph'

const PROJECT_ID = 'proj-1'

function graph(overrides: Partial<ProjectGraph> = {}): ProjectGraph {
  return {
    project: { id: PROJECT_ID, name: 'Battery Technology Research' },
    stats: { concepts: 2, findings: 3, runs: 2 },
    nodes: [
      {
        id: 'project-proj-1',
        label: 'Battery Technology Research',
        type: 'project',
        project_id: PROJECT_ID,
        support_count: 2,
        finding_count: 3,
      },
      {
        id: 'concept-interface',
        label: 'interface stability',
        type: 'concept',
        project_id: PROJECT_ID,
        support_count: 2,
        finding_count: 2,
      },
      {
        id: 'concept-manufacturing',
        label: 'manufacturing scalability',
        type: 'concept',
        project_id: PROJECT_ID,
        support_count: 1,
        finding_count: 1,
      },
      {
        id: 'f1',
        label: 'Interface stability limits solid-state cells at the boundary.',
        type: 'finding',
        project_id: PROJECT_ID,
        support_count: 1,
        finding_count: 1,
        text: 'Interface stability limits solid-state cells at the boundary.',
        section: 'Interface Stability',
        source_run_id: 'run-a',
        source_question: 'What are the biggest technical barriers?',
        created_at: '2026-10-01T09:00:00Z',
        sources: [{ url: 'https://nature.test/a', title: 'Nature' }],
      },
      {
        id: 'f2',
        label: 'Dendrites form at the electrolyte boundary.',
        type: 'finding',
        project_id: PROJECT_ID,
        support_count: 1,
        finding_count: 1,
        text: 'Dendrites form at the electrolyte boundary.',
        section: 'Interface Stability',
        source_run_id: 'run-b',
        source_question: 'Which barrier blocks mass production?',
        created_at: '2026-10-02T09:00:00Z',
        sources: [],
      },
      {
        id: 'f3',
        label: 'Dry-room requirements constrain throughput.',
        type: 'finding',
        project_id: PROJECT_ID,
        support_count: 1,
        finding_count: 1,
        text: 'Dry-room requirements constrain throughput.',
        section: 'Manufacturing',
        source_run_id: 'run-b',
        source_question: 'Which barrier blocks mass production?',
        created_at: '2026-10-02T09:10:00Z',
        sources: [],
      },
    ],
    edges: [
      { id: 'e1', source: 'project-proj-1', target: 'concept-interface', relation: 'HAS_TOPIC', weight: 2 },
      { id: 'e2', source: 'project-proj-1', target: 'concept-manufacturing', relation: 'HAS_TOPIC', weight: 1 },
      { id: 'e3', source: 'concept-interface', target: 'f1', relation: 'SUPPORTED_BY', weight: 1 },
      { id: 'e4', source: 'concept-interface', target: 'f2', relation: 'SUPPORTED_BY', weight: 1 },
      { id: 'e5', source: 'concept-manufacturing', target: 'f3', relation: 'SUPPORTED_BY', weight: 1 },
      { id: 'e6', source: 'concept-interface', target: 'concept-manufacturing', relation: 'RELATED_TO', weight: 2 },
    ],
    ...overrides,
  }
}

function renderGraph(onStart = vi.fn()) {
  render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}`]}>
      <Routes>
        <Route
          path="/projects/:id"
          element={<ProjectKnowledgeGraph projectId={PROJECT_ID} onStartResearch={onStart} />}
        />
        <Route path="/runs/:id" element={<p>Run detail page</p>} />
      </Routes>
    </MemoryRouter>,
  )
  return onStart
}

function mockGraph(body: ProjectGraph | undefined, status = 200) {
  return installFetchMock((url) =>
    url === `/api/projects/${PROJECT_ID}/knowledge-graph` ? { status, body } : undefined,
  )
}

/** Concept nodes are the ones carrying a visible label plus a support count. */
function conceptNode(label: string) {
  // Anchored so a finding whose text repeats the concept's words is not matched.
  return screen.getByRole('button', { name: new RegExp(`^${label}, \\d+ finding`, 'i') })
}

describe('ProjectKnowledgeGraph', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders a populated graph with its stats header', async () => {
    mockGraph(graph())
    renderGraph()

    expect(await screen.findByText('2 concepts · 3 findings · 2 research runs')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Battery Technology Research/ })).toBeInTheDocument()
    expect(conceptNode('interface stability')).toBeInTheDocument()
  })

  it('defaults to a concepts-only view and reveals findings on demand', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    // Finding nodes are collapsed under their concepts to keep the first view readable.
    expect(screen.queryByRole('button', { name: /^Finding:/ })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Concepts + findings' }))
    expect(await screen.findAllByRole('button', { name: /^Finding:/ })).toHaveLength(3)
  })

  it('expands only the selected concept while staying in the concepts view', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.click(conceptNode('interface stability'))

    // The two findings behind this concept appear; the third concept's does not.
    const findings = await screen.findAllByRole('button', { name: /^Finding:/ })
    expect(findings).toHaveLength(2)
  })

  it('opens an inspector with support counts when a concept is clicked', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.click(conceptNode('interface stability'))

    const panel = await screen.findByRole('complementary', { name: 'Concept details' })
    expect(within(panel).getByText('interface stability')).toBeInTheDocument()
    expect(
      within(panel).getByText('Supported by 2 findings across 2 research runs.'),
    ).toBeInTheDocument()
    expect(within(panel).getByText('manufacturing scalability')).toBeInTheDocument()
    expect(within(panel).getByText(/Interface stability limits solid-state cells/)).toBeInTheDocument()
  })

  it('shows full provenance for a finding and navigates to its run', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.click(screen.getByRole('button', { name: 'Concepts + findings' }))
    await userEvent.click(
      await screen.findByRole('button', { name: /^Finding: Interface stability limits/ }),
    )

    const panel = await screen.findByRole('complementary', { name: 'Finding details' })
    expect(within(panel).getByText(/Interface stability limits solid-state cells/)).toBeInTheDocument()
    expect(within(panel).getByText('Section: Interface Stability')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Nature' })).toHaveAttribute(
      'href',
      'https://nature.test/a',
    )

    const runLink = within(panel).getByRole('link', { name: 'What are the biggest technical barriers?' })
    expect(runLink).toHaveAttribute('href', '/runs/run-a')
    await userEvent.click(runLink)
    expect(await screen.findByText('Run detail page')).toBeInTheDocument()
  })

  it('searches the loaded graph locally and reports matches', async () => {
    const fetchMock = mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search the graph' }), 'interface')

    expect(await screen.findByText(/1 match for/)).toBeInTheDocument()
    // Non-matching nodes are dimmed rather than removed, so context is preserved.
    expect(conceptNode('manufacturing scalability').getAttribute('class')).toContain('dimmed')
    expect(conceptNode('interface stability').getAttribute('class')).not.toContain('dimmed')
    // Searching must never hit the network again.
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('says so when nothing matches the search', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search the graph' }), 'photovoltaic')

    expect(await screen.findByText(/Nothing in this graph matches/)).toBeInTheDocument()
  })

  it('resets the view, selection and search', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.click(screen.getByRole('button', { name: 'Concepts + findings' }))
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search the graph' }), 'interface')
    await userEvent.click(conceptNode('interface stability'))
    expect(screen.getByRole('complementary', { name: 'Concept details' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Reset' }))

    expect(screen.getByRole('button', { name: 'Concepts' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('searchbox', { name: 'Search the graph' })).toHaveValue('')
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
  })

  it('fits the whole graph into view', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    const canvas = screen.getByRole('img', { name: /Battery Technology Research/ })
    const transformed = () => canvas.querySelector('g')?.getAttribute('transform') ?? ''
    const before = transformed()

    await userEvent.click(screen.getByRole('button', { name: 'Fit view' }))

    // Fit always resolves to a concrete, finite transform.
    expect(transformed()).toMatch(/^translate\(-?[\d.]+ -?[\d.]+\) scale\([\d.]+\)$/)
    expect(before).toBeTruthy()
  })

  it('invites first research when the project has no findings', async () => {
    const onStart = vi.fn()
    mockGraph(
      graph({ stats: { concepts: 0, findings: 0, runs: 0 }, nodes: [], edges: [] }),
    )
    renderGraph(onStart)

    expect(await screen.findByText('No project knowledge yet')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Start research' }))
    expect(onStart).toHaveBeenCalled()
  })

  it('explains findings that are too sparse to chart', async () => {
    mockGraph(graph({ stats: { concepts: 0, findings: 4, runs: 1 }, edges: [] }))
    renderGraph()

    expect(
      await screen.findByText('No graphable findings are available yet'),
    ).toBeInTheDocument()
    expect(screen.getByText(/4 findings, but no concept recurs/)).toBeInTheDocument()
  })

  it('marks the project root as the visual anchor', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    const root = await screen.findByRole('button', {
      name: 'Project: Battery Technology Research',
    })
    // Type is carried by an explicit label and a shape class, not by colour alone.
    expect(root.getAttribute('class')).toContain('kind-project')
    expect(within(root).getByText('PROJECT')).toBeInTheDocument()
  })

  it('states what each count counts, on the node itself', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    const node = conceptNode('interface stability')
    // Never a bare "2" the user has to decode.
    expect(within(node).getByText('2 findings · 2 runs')).toBeInTheDocument()
    expect(node).toHaveAttribute('aria-label', 'interface stability, 2 findings · 2 runs')
  })

  it('renders long concept labels across lines rather than cutting them', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    const node = conceptNode('manufacturing scalability')
    expect(within(node).getByText('manufacturing')).toBeInTheDocument()
    expect(within(node).getByText('scalability')).toBeInTheDocument()
    // The full name is still what assistive tech announces.
    expect(node.getAttribute('aria-label')).toContain('manufacturing scalability')
  })

  it('offers a legend for the node kinds', async () => {
    mockGraph(graph())
    renderGraph()

    const legend = await screen.findByRole('list', { name: 'Legend' })
    expect(within(legend).getByText('Project')).toBeInTheDocument()
    expect(within(legend).getByText('Concept')).toBeInTheDocument()
    expect(within(legend).getByText('Finding')).toBeInTheDocument()
  })

  it('shows a hover tooltip with the counts, without opening the inspector', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.hover(conceptNode('interface stability'))

    const tooltip = await screen.findByRole('tooltip')
    expect(within(tooltip).getByText('interface stability')).toBeInTheDocument()
    expect(within(tooltip).getByText('2 supporting findings')).toBeInTheDocument()
    expect(within(tooltip).getByText('2 research runs')).toBeInTheDocument()
    // Hover must not open the full panel.
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
  })

  it('emphasises the selected concept neighbourhood and dims the rest', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    await userEvent.click(conceptNode('interface stability'))

    // The related concept stays lit; the unrelated project root does not dim away
    // because it is one hop from the selection.
    expect(conceptNode('manufacturing scalability').getAttribute('class')).not.toContain('dimmed')
    const canvas = screen.getByRole('img', { name: /Battery Technology Research/ })
    expect(canvas.querySelectorAll('.graph-edge.emphasised').length).toBeGreaterThan(0)
    expect(canvas.querySelectorAll('.graph-edge.faded').length).toBeGreaterThan(0)
  })

  it('separates hierarchy edges from secondary similarity edges', async () => {
    mockGraph(graph())
    renderGraph()
    await screen.findByText(/2 concepts/)

    const canvas = screen.getByRole('img', { name: /Battery Technology Research/ })
    expect(canvas.querySelectorAll('.relation-has_topic').length).toBe(2)
    // RELATED_TO is drawn as a curve so it reads as a distinct, quieter layer.
    expect(canvas.querySelectorAll('path.relation-related_to').length).toBe(1)
  })

  it('shows a loading state and then a retryable error', async () => {
    const fetchMock = installFetchMock((url) =>
      url === `/api/projects/${PROJECT_ID}/knowledge-graph`
        ? { status: 503, body: { detail: 'Storage is unavailable.' } }
        : undefined,
    )
    renderGraph()

    expect(screen.getByRole('status')).toHaveTextContent('Loading knowledge graph…')
    expect(await screen.findByRole('alert')).toHaveTextContent('Storage is unavailable.')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })
})

describe('graph layout', () => {
  it('is deterministic for the same graph', () => {
    const first = layoutGraph(graph().nodes, graph().edges)
    const second = layoutGraph(graph().nodes, graph().edges)
    expect(first.nodes.map((entry) => [entry.node.id, entry.x, entry.y])).toEqual(
      second.nodes.map((entry) => [entry.node.id, entry.x, entry.y]),
    )
  })

  it('anchors the project at the centre and spreads concepts around it', () => {
    const { nodes } = layoutGraph(graph().nodes, graph().edges)
    const root = nodes.find((entry) => entry.node.type === 'project')!
    const concepts = nodes.filter((entry) => entry.node.type === 'concept')

    // Concepts sit away from the root rather than piling on top of it.
    for (const concept of concepts) {
      const distance = Math.hypot(concept.x - root.x, concept.y - root.y)
      expect(distance).toBeGreaterThan(150)
    }
    // ...and away from each other.
    expect(Math.hypot(concepts[0].x - concepts[1].x, concepts[0].y - concepts[1].y)).toBeGreaterThan(
      100,
    )
  })

  it('gives the root node more presence than a concept', () => {
    const { nodes } = layoutGraph(graph().nodes, graph().edges)
    const root = nodes.find((entry) => entry.node.type === 'project')!
    const concept = nodes.find((entry) => entry.node.type === 'concept')!
    expect(root.width).toBeGreaterThan(concept.width)
    expect(root.height).toBeGreaterThan(concept.height - 1)
  })

  it('drops edges whose endpoints are not drawn', () => {
    const base = graph()
    const conceptsOnly = base.nodes.filter((node) => node.type !== 'finding')
    const { edges } = layoutGraph(conceptsOnly, base.edges)
    expect(edges.every((entry) => entry.edge.relation !== 'SUPPORTED_BY')).toBe(true)
  })

  it('fits an empty graph without producing NaN', () => {
    expect(fitTransform([])).toEqual({ x: 0, y: 0, k: 1 })
  })

  it('frames a real layout at a readable zoom', () => {
    const { nodes } = layoutGraph(graph().nodes, graph().edges)
    const transform = fitTransform(nodes)
    expect(Number.isFinite(transform.x)).toBe(true)
    expect(Number.isFinite(transform.y)).toBe(true)
    // Never so far out that the labels stop being legible.
    expect(transform.k).toBeGreaterThanOrEqual(0.72)
    expect(transform.k).toBeLessThanOrEqual(3)
  })
})

describe('wrapLabel', () => {
  it('wraps a long concept name instead of truncating it', () => {
    expect(wrapLabel('manufacturing scalability challenges', 20)).toEqual([
      'manufacturing',
      'scalability',
      'challenges',
    ])
  })

  it('keeps a short name on one line', () => {
    expect(wrapLabel('interface stability', 20)).toEqual(['interface stability'])
  })

  it('ellipsises only what cannot fit in the line budget', () => {
    const lines = wrapLabel('alpha beta gamma delta epsilon zeta eta theta', 12, 3)
    expect(lines).toHaveLength(3)
    expect(lines[2].endsWith('…')).toBe(true)
  })
})
