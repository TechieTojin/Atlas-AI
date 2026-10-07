import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeEvidence, makeQuality, makeSource } from '../test/fixtures'
import type { Claim, Source } from '../types'
import { CitedReport } from './CitedReport'

const webSource = makeSource({ index: 1, quality: makeQuality() })
const documentSource: Source = makeSource({
  index: 2,
  title: 'Internal energy memo',
  url: '',
  domain: '',
  kind: 'document',
  filename: 'energy-memo.pdf',
  page: 4,
  quality: null,
})

const markdown = 'Solar **grew** rapidly. [1]\n\nThe memo confirms it. [2]'

const claims: Claim[] = [
  { text: 'Solar capacity doubled since 2022.', citations: [1], section: 'Key findings' },
  { text: 'Grid costs fell.', citations: [2], section: 'Costs' },
]

describe('CitedReport', () => {
  it('renders [n] markers as accessible citation buttons', () => {
    render(<CitedReport markdown={markdown} sources={[webSource, documentSource]} />)
    expect(screen.getByRole('button', { name: 'View source 1' })).toHaveTextContent('[1]')
    expect(screen.getByRole('button', { name: 'View source 2' })).toBeInTheDocument()
    // Markdown structure is preserved around the buttons.
    expect(screen.getByText('grew').tagName).toBe('STRONG')
  })

  it('opens a drawer with source, evidence, and supporting claims on citation click', async () => {
    const loadClaims = vi.fn(async () => claims)
    render(
      <CitedReport
        markdown={markdown}
        sources={[webSource, documentSource]}
        evidence={[makeEvidence()]}
        loadClaims={loadClaims}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'View source 1' }))

    const drawer = await screen.findByRole('dialog', { name: /Source 1/ })
    expect(drawer).toHaveTextContent('IEA Renewables Report')
    expect(loadClaims).toHaveBeenCalledTimes(1)

    // Quality badge for the source.
    expect(screen.getByRole('button', { name: 'Academic · High authority' })).toBeInTheDocument()
    // External link for web sources.
    const link = screen.getByRole('link', { name: /Open source/ })
    expect(link).toHaveAttribute('href', 'https://iea.org/renewables-2026')
    // Evidence excerpt with its found-by query.
    expect(
      screen.getByText('Solar capacity additions reached a record 600 GW in 2025.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/Found by: “solar capacity additions 2025”/)).toBeInTheDocument()
    // Only the claims citing [1] appear.
    expect(await screen.findByText('Solar capacity doubled since 2022.')).toBeInTheDocument()
    expect(screen.getByText('Key findings')).toBeInTheDocument()
    expect(screen.queryByText('Grid costs fell.')).not.toBeInTheDocument()
  })

  it('closes the drawer on Escape and on backdrop click', async () => {
    render(<CitedReport markdown={markdown} sources={[webSource, documentSource]} />)

    await userEvent.click(screen.getByRole('button', { name: 'View source 1' }))
    expect(screen.getByRole('dialog', { name: /Source 1/ })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'View source 1' }))
    const backdrop = document.querySelector('.drawer-backdrop')
    expect(backdrop).not.toBeNull()
    await userEvent.click(backdrop as Element)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows filename and page without an external link for document sources', async () => {
    render(<CitedReport markdown={markdown} sources={[webSource, documentSource]} />)

    await userEvent.click(screen.getByRole('button', { name: 'View source 2' }))
    const drawer = screen.getByRole('dialog', { name: /Source 2/ })
    expect(drawer).toHaveTextContent('energy-memo.pdf, p. 4')
    expect(screen.queryByRole('link', { name: /Open source/ })).not.toBeInTheDocument()
  })

  it('renders evidence content as text, never as HTML', async () => {
    const hostile = makeEvidence({
      content: '<img src=x onerror="window.alert(1)"> plus <script>bad()</script>',
    })
    render(
      <CitedReport markdown={markdown} sources={[webSource, documentSource]} evidence={[hostile]} />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'View source 1' }))
    expect(
      screen.getByText('<img src=x onerror="window.alert(1)"> plus <script>bad()</script>'),
    ).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('script')).toBeNull()
  })
})
