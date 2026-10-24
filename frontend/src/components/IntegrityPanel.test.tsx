import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntegrityPanel } from './IntegrityPanel'
import type { RunIntegrity } from '../types'

/** Minimal persisted-shaped payload; mirrors what /runs/{id}/integrity returns. */
function payload(overrides: Partial<RunIntegrity> = {}): RunIntegrity {
  return {
    run_id: 'run-1',
    analyzed: true,
    summary: {
      run_id: 'run-1',
      total_claims: 3,
      supported: 1,
      partially_supported: 1,
      unsupported: 1,
      contradicted: 0,
      not_verifiable: 0,
      contradiction_count: 1,
      verified_claims: 3,
      support_rate: 1 / 3,
    },
    claims: [
      {
        id: 'c1',
        run_id: 'run-1',
        project_id: null,
        section: 'Findings',
        text: 'Manufacturing scalability remains a barrier [1].',
        text_norm: 'manufacturing scalability remains a barrier',
        citations: [1],
        position: 0,
        created_at: '2026-01-01T00:00:00Z',
        verification: {
          id: 'v1',
          claim_id: 'c1',
          run_id: 'run-1',
          status: 'SUPPORTED',
          confidence: 'HIGH',
          verifier: 'DETERMINISTIC',
          signals: [
            { name: 'term_overlap', value: 0.82, detail: '9 of 11 distinctive terms appear.' },
            { name: 'numeric_match', value: 1, detail: 'The claim states no figures to check.' },
          ],
          explanation: 'The cited passage contains the substance of this claim.',
          checked_citations: [1],
          created_at: '2026-01-01T00:00:00Z',
        },
        contradictions: [],
      },
      {
        id: 'c2',
        run_id: 'run-1',
        project_id: null,
        section: 'Findings',
        text: 'Reported efficiency reached 25.7% [1][2].',
        text_norm: 'reported efficiency reached 25 7',
        citations: [1, 2],
        position: 1,
        created_at: '2026-01-01T00:00:00Z',
        verification: {
          id: 'v2',
          claim_id: 'c2',
          run_id: 'run-1',
          status: 'PARTIALLY_SUPPORTED',
          confidence: 'MODERATE',
          verifier: 'DETERMINISTIC',
          signals: [{ name: 'term_overlap', value: 0.4, detail: '4 of 10 terms appear.' }],
          explanation: 'The cited passage supports part of this claim.',
          checked_citations: [1, 2],
          created_at: '2026-01-01T00:00:00Z',
        },
        contradictions: [
          {
            id: 'x1',
            run_id: 'run-1',
            claim_id: 'c2',
            kind: 'MIXED_EVIDENCE',
            source_a: 1,
            source_b: 2,
            excerpt_a: 'Efficiency reached 25.7 percent.',
            excerpt_b: 'Efficiency reached 18.1 percent.',
            explanation: 'The sources report materially different figures.',
            resolved: false,
            created_at: '2026-01-01T00:00:00Z',
          },
        ],
      },
      {
        id: 'c3',
        run_id: 'run-1',
        project_id: null,
        section: '',
        text: 'An unrelated assertion [3].',
        text_norm: 'an unrelated assertion',
        citations: [3],
        position: 2,
        created_at: '2026-01-01T00:00:00Z',
        verification: {
          id: 'v3',
          claim_id: 'c3',
          run_id: 'run-1',
          status: 'UNSUPPORTED',
          confidence: 'MODERATE',
          verifier: 'DETERMINISTIC',
          signals: [{ name: 'term_overlap', value: 0.05, detail: '0 of 6 terms appear.' }],
          explanation: 'The cited passage does not contain the substance of this claim.',
          checked_citations: [3],
          created_at: '2026-01-01T00:00:00Z',
        },
        contradictions: [],
      },
    ],
    contradictions: [],
    quality: {
      run_id: 'run-1',
      formula_version: 1,
      overall: 0.74,
      created_at: '2026-01-01T00:00:00Z',
      components: [
        {
          name: 'citation_coverage',
          available: true,
          value: 1,
          weight: 0.2,
          detail: '100% of report claims carry a citation.',
        },
        {
          name: 'source_authority',
          available: false,
          value: null,
          weight: 0.15,
          detail: 'This run stored no source-authority ratings.',
        },
      ],
    },
    ...overrides,
  }
}

function mockFetch(body: unknown, status = 200) {
  const spy = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', spy)
  return spy
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('IntegrityPanel', () => {
  it('reports real supported/verifiable counts from persisted data', async () => {
    mockFetch(payload())
    render(<IntegrityPanel runId="run-1" />)
    expect(
      await screen.findByText('9 of 17 verifiable claims fully supported'.replace('9', '1').replace('17', '3')),
    ).toBeInTheDocument()
  })

  it('separates citation coverage from citation support', async () => {
    mockFetch(payload())
    render(<IntegrityPanel runId="run-1" />)
    expect(
      await screen.findByText(/Coverage means a claim carries a citation/),
    ).toBeInTheDocument()
  })

  it('shows every verdict status with its count', async () => {
    mockFetch(payload())
    render(<IntegrityPanel runId="run-1" />)
    await screen.findByText('Citation integrity')
    // Scope to the summary chips: the same labels also appear per matrix row.
    const summary = screen.getByLabelText('Citation integrity')
    const chips = within(summary).getAllByRole('listitem')
    const labelled = (name: string) =>
      chips.find((li) => within(li).queryByText(name)) as HTMLElement
    expect(within(labelled('Supported')).getByText('1')).toBeInTheDocument()
    expect(within(labelled('Partly supported')).getByText('1')).toBeInTheDocument()
    expect(within(labelled('Unsupported')).getByText('1')).toBeInTheDocument()
    expect(within(labelled('Not verifiable')).getByText('0')).toBeInTheDocument()
  })

  it('renders NOT AVAILABLE for a dimension Atlas could not compute', async () => {
    mockFetch(payload())
    render(<IntegrityPanel runId="run-1" />)
    await screen.findByText('Research quality')
    const authority = screen.getByText('Source authority').closest('li') as HTMLElement
    expect(within(authority).getByText('Not available')).toBeInTheDocument()
    // and never a fabricated number in its place
    expect(within(authority).queryByText(/%$/)).toBeNull()
  })

  it('never invents an overall score when none could be computed', async () => {
    mockFetch(payload({ quality: { ...payload().quality!, overall: null } }))
    render(<IntegrityPanel runId="run-1" />)
    await screen.findByText('Research quality')
    const quality = screen.getByLabelText('Research quality')
    expect(within(quality).getAllByText('Not available').length).toBeGreaterThan(0)
  })

  it('reveals the signals behind a verdict when a claim is opened', async () => {
    const user = userEvent.setup()
    mockFetch(payload())
    render(<IntegrityPanel runId="run-1" />)
    await screen.findByText('Evidence matrix')
    await user.click(screen.getByText('Manufacturing scalability remains a barrier [1].'))
    expect(await screen.findByText('Why Atlas decided this')).toBeInTheDocument()
    expect(screen.getByText('Term overlap')).toBeInTheDocument()
    expect(
      screen.getByText('The cited passage contains the substance of this claim.'),
    ).toBeInTheDocument()
  })

  it('shows a disagreement with both source excerpts', async () => {
    const user = userEvent.setup()
    mockFetch(payload())
    render(<IntegrityPanel runId="run-1" />)
    await screen.findByText('Evidence matrix')
    await user.click(screen.getByText('Reported efficiency reached 25.7% [1][2].'))
    expect(await screen.findByText('Mixed evidence')).toBeInTheDocument()
    expect(screen.getByText('Efficiency reached 25.7 percent.')).toBeInTheDocument()
    expect(screen.getByText('Efficiency reached 18.1 percent.')).toBeInTheDocument()
    expect(screen.getByText('Source 1')).toBeInTheDocument()
    expect(screen.getByText('Source 2')).toBeInTheDocument()
  })

  it('offers analysis instead of empty numbers for an unanalysed run', async () => {
    mockFetch(payload({ analyzed: false, claims: [], quality: null }))
    render(<IntegrityPanel runId="run-1" />)
    expect(await screen.findByText('Not analysed yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyse this report' })).toBeInTheDocument()
  })

  it('surfaces a backend failure as a readable alert', async () => {
    mockFetch({ detail: 'Run not found' }, 404)
    render(<IntegrityPanel runId="run-1" />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
