import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeEvaluation, makeRun } from '../test/fixtures'
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
})
