import { render as baseRender, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'

/** The Research Map tab uses router hooks, so renders need a router around them. */
const render = (ui: React.ReactElement) => baseRender(<MemoryRouter>{ui}</MemoryRouter>)
import { describe, expect, it } from 'vitest'
import { makeEvaluation, makeRun } from '../test/fixtures'
import { installFetchMock } from '../test/mockFetch'
import type { Source } from '../types'
import { RunTabs } from './RunTabs'

const sources: Source[] = [
  {
    index: 1,
    title: 'IEA Renewables Report',
    url: 'https://iea.org/renewables-2026',
    domain: 'iea.org',
    kind: 'web',
    filename: null,
    page: null,
  },
  {
    index: 2,
    title: 'Internal energy memo',
    url: '',
    domain: '',
    kind: 'document',
    filename: 'energy-memo.pdf',
    page: 4,
  },
]

const run = makeRun({
  final_report: '# Key Findings\n\nSolar capacity **doubled** since 2022. [1]\n\n- Record additions [2]',
  sources,
})

describe('RunTabs', () => {
  it('renders the report markdown as semantic HTML', () => {
    render(<RunTabs run={run} />)
    expect(screen.getByRole('heading', { level: 1, name: 'Key Findings' })).toBeInTheDocument()
    expect(screen.getByText('doubled').tagName).toBe('STRONG')
    expect(screen.getByText(/Record additions/)).toBeInTheDocument()
  })

  it('shows web sources with their domain and an external link', async () => {
    render(<RunTabs run={run} />)
    await userEvent.click(screen.getByRole('tab', { name: /Sources/ }))

    expect(screen.getByText('IEA Renewables Report')).toBeInTheDocument()
    expect(screen.getByText('iea.org')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /Open IEA Renewables Report/ })
    expect(link).toHaveAttribute('href', 'https://iea.org/renewables-2026')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('shows document sources as "filename, p. N" with a Document badge', async () => {
    render(<RunTabs run={run} />)
    await userEvent.click(screen.getByRole('tab', { name: /Sources/ }))

    expect(screen.getByText('energy-memo.pdf, p. 4')).toBeInTheDocument()
    expect(screen.getByText('Document')).toBeInTheDocument()
  })

  it('renders metrics and the evaluation checklist', async () => {
    const failing = makeRun({
      ...run,
      evaluation: makeEvaluation({ citations_valid: false, passed: false, notes: ['Citation [9] missing'] }),
    })
    render(<RunTabs run={failing} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Metrics' }))

    expect(screen.getByText('Total runtime')).toBeInTheDocument()
    expect(screen.getByText('17.4s')).toBeInTheDocument()
    expect(screen.getByText('Citation coverage 85%')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText('Citation [9] missing')).toBeInTheDocument()
  })

  it('adds a Research Map tab next to the existing tabs, and Open report returns to the report', async () => {
    const user = userEvent.setup()
    installFetchMock((url) =>
      url === `/api/runs/${run.id}/research-map`
        ? {
            body: {
              run_id: run.id, run_status: 'COMPLETED', question: 'Q', mode: 'FAST', source_scope: 'WEB',
              template: 'STANDARD', output_language: 'en', live: false,
              nodes: [
                { id: 'question', type: 'question', label: 'Q', status: 'completed', rank: 0, iteration: null, group: null, started_at: null, completed_at: null, duration_ms: null, data: {} },
                { id: 'report', type: 'report', label: 'The report', status: 'completed', rank: 1, iteration: null, group: null, started_at: null, completed_at: null, duration_ms: null, data: { citations: 2, word_count: 10 } },
              ],
              edges: [], groups: [],
              summary: { node_count: 2, edge_count: 0, source_count: 0, evidence_count: 0, query_count: 0, iterations: 1, incomplete_history: false },
              limitations: [],
            },
          }
        : undefined,
    )
    render(<RunTabs run={run} />)
    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent)
    expect(tabs.slice(0, 6).map((text) => text?.replace(/\d+$/, ''))).toEqual([
      'Report',
      'Sources',
      'Evidence',
      'Integrity',
      'Metrics',
      'Graph',
    ])
    await user.click(screen.getByRole('tab', { name: 'Research Map' }))
    expect(screen.getByRole('tab', { name: 'Research Map' })).toHaveAttribute('aria-selected', 'true')
    await user.click(await screen.findByRole('button', { name: /^Report: The report/ }))
    await user.click(screen.getByRole('button', { name: 'Open report' }))
    expect(screen.getByRole('tab', { name: /^Report/ })).toHaveAttribute('aria-selected', 'true')
  })
})
