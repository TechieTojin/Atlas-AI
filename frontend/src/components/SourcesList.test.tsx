import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeEvidence, makeQuality, makeSource } from '../test/fixtures'
import { EvidenceList } from './EvidenceList'
import { SourcesList } from './SourcesList'

const sources = [
  makeSource({
    index: 1,
    title: 'Low blog post',
    url: 'https://blog.example/post',
    domain: 'blog.example',
    quality: makeQuality({ category: 'Blog', tier: 'low', score: 0.3 }),
  }),
  makeSource({
    index: 2,
    title: 'Peer-reviewed study',
    url: 'https://journal.example/study',
    domain: 'journal.example',
    quality: makeQuality({ category: 'Academic', tier: 'high', score: 0.95 }),
  }),
]

describe('SourcesList quality controls', () => {
  it('sorts sources by quality', async () => {
    render(<SourcesList sources={sources} />)
    const list = screen.getByRole('list', { name: 'Sources' })
    let titles = within(list)
      .getAllByText(/Low blog post|Peer-reviewed study/)
      .map((node) => node.textContent)
    expect(titles).toEqual(['Low blog post', 'Peer-reviewed study'])

    await userEvent.selectOptions(screen.getByLabelText('Sort sources'), 'quality')
    titles = within(screen.getByRole('list', { name: 'Sources' }))
      .getAllByText(/Low blog post|Peer-reviewed study/)
      .map((node) => node.textContent)
    expect(titles).toEqual(['Peer-reviewed study', 'Low blog post'])
  })

  it('filters sources by tier chips', async () => {
    render(<SourcesList sources={sources} />)
    await userEvent.click(screen.getByRole('button', { name: /High authority \(1\)/ }))
    expect(screen.getByText('Peer-reviewed study')).toBeInTheDocument()
    expect(screen.queryByText('Low blog post')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getByText('Low blog post')).toBeInTheDocument()
  })
})

describe('EvidenceList extraction badges', () => {
  it('labels full-page and fallback extractions but not plain snippets', () => {
    render(
      <EvidenceList
        evidence={[
          makeEvidence({ extraction: 'full_page', quality_tier: 'high' }),
          makeEvidence({ extraction: 'fallback_snippet', quality_tier: null }),
          makeEvidence({ extraction: 'snippet', quality_tier: null }),
        ]}
      />,
    )
    expect(screen.getAllByText('Full page')).toHaveLength(1)
    expect(screen.getAllByText('Snippet fallback')).toHaveLength(1)
    expect(screen.getAllByText('High authority')).toHaveLength(1)
  })
})
