import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeKnowledgeGraph } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock } from '../test/mockFetch'
import { KnowledgeGraphTab, runKnowledgeGraphTabProps } from './KnowledgeGraph'

describe('KnowledgeGraphTab', () => {
  beforeEach(() => {
    MockEventSource.reset()
    vi.stubGlobal('EventSource', MockEventSource)
  })

  it('shows an empty state and posts to generate the graph', async () => {
    const mock = installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/knowledge-graph' && init?.method === 'POST') {
        return { status: 202, body: { status: 'RUNNING' } }
      }
      if (url === '/api/runs/run-1/knowledge-graph') {
        return { body: makeKnowledgeGraph({ nodes: [], edges: [], status: 'NONE' }) }
      }
      return undefined
    })
    render(<KnowledgeGraphTab {...runKnowledgeGraphTabProps('run-1')} />)

    const generate = await screen.findByRole('button', { name: 'Generate knowledge graph' })
    await userEvent.click(generate)

    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/runs/run-1/knowledge-graph' && init?.method === 'POST',
    )
    expect(postCall).toBeDefined()
    // After the POST the tab shows the running state and streams progress.
    expect(await screen.findByText('Extracting entities and relationships…')).toBeInTheDocument()
    expect(MockEventSource.latest().url).toBe('/api/runs/run-1/knowledge-graph/events')
  })

  it('renders nodes, edges, legend chips, and opens the node detail panel', async () => {
    installFetchMock((url) => {
      if (url === '/api/runs/run-1/knowledge-graph') {
        return { body: makeKnowledgeGraph() }
      }
      return undefined
    })
    render(<KnowledgeGraphTab {...runKnowledgeGraphTabProps('run-1')} />)

    // Nodes render as labelled interactive elements.
    expect(await screen.findByRole('button', { name: 'Entity: Solar PV' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Entity: Grid storage' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Entity: IEA' })).toBeInTheDocument()

    // Edges are interactive too.
    expect(
      screen.getByRole('button', { name: 'Relationship: Solar PV drives growth of Grid storage' }),
    ).toBeInTheDocument()

    // Type filter chips act as the legend.
    expect(screen.getByRole('button', { name: /Technology/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Organization/ })).toBeInTheDocument()

    // Clicking a node opens its detail panel with description and relationships.
    await userEvent.click(screen.getByRole('button', { name: 'Entity: Solar PV' }))
    expect(screen.getByText('Photovoltaic solar generation')).toBeInTheDocument()
    expect(screen.getByText('Relationships')).toBeInTheDocument()
    expect(screen.getByText('drives growth of')).toBeInTheDocument()
  })

  it('opens the relationship panel with supporting sources on edge click', async () => {
    installFetchMock((url) => {
      if (url === '/api/runs/run-1/knowledge-graph') {
        return { body: makeKnowledgeGraph() }
      }
      return undefined
    })
    render(<KnowledgeGraphTab {...runKnowledgeGraphTabProps('run-1')} />)

    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Relationship: Solar PV drives growth of Grid storage',
      }),
    )
    expect(screen.getByText('Supporting sources')).toBeInTheDocument()
    const supportLink = screen.getByRole('link', { name: /IEA Renewables Report/ })
    expect(supportLink).toHaveAttribute('href', 'https://iea.org/renewables-2026')
  })

  it('filters nodes by type via the legend chips', async () => {
    installFetchMock((url) => {
      if (url === '/api/runs/run-1/knowledge-graph') {
        return { body: makeKnowledgeGraph() }
      }
      return undefined
    })
    render(<KnowledgeGraphTab {...runKnowledgeGraphTabProps('run-1')} />)
    await screen.findByRole('button', { name: 'Entity: Solar PV' })

    await userEvent.click(screen.getByRole('button', { name: /Organization/ }))
    expect(screen.queryByRole('button', { name: 'Entity: IEA' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Entity: Solar PV' })).toBeInTheDocument()
  })
})
