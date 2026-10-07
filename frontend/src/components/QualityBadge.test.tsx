import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeQuality } from '../test/fixtures'
import { QualityBadge } from './QualityBadge'

describe('QualityBadge', () => {
  it('renders the category and tier label with a tier-colored dot', () => {
    const { container } = render(<QualityBadge quality={makeQuality()} />)
    expect(screen.getByText('Academic · High authority')).toBeInTheDocument()
    expect(container.querySelector('.quality-dot.tier-high')).not.toBeNull()
  })

  it('renders nothing when quality is missing', () => {
    const { container } = render(<QualityBadge quality={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('expands to show the score, signals, and warnings', async () => {
    render(
      <QualityBadge
        quality={makeQuality({
          category: 'Blog',
          tier: 'low',
          score: 0.31,
          signals: ['Self-published domain'],
          warnings: ['No author attribution'],
        })}
        expandable
      />,
    )
    const toggle = screen.getByRole('button', { name: 'Blog · Low authority' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Quality score 0.31')).not.toBeInTheDocument()

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Quality score 0.31')).toBeInTheDocument()
    expect(screen.getByText('Self-published domain')).toBeInTheDocument()
    expect(screen.getByText('No author attribution')).toBeInTheDocument()
  })
})
