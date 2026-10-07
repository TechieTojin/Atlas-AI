import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeEvent, resetEventSeq } from '../test/fixtures'
import { RunStatChips, Timeline } from './Timeline'

describe('Timeline', () => {
  beforeEach(() => {
    resetEventSeq()
  })

  const events = [
    makeEvent('RUN_STARTED'),
    makeEvent('PLANNING_STARTED'),
    makeEvent('PLAN_CREATED'),
    makeEvent('SEARCH_QUERY_STARTED', {
      payload: { index: 2, total: 5, query: 'solar capacity 2026' },
    }),
    makeEvent('EVIDENCE_COLLECTED', { payload: { total_items: 12, memory_hits: 3 } }),
    makeEvent('CRITIC_COMPLETED', {
      payload: { score: 0.82, reasoning: 'INTERNAL-CHAIN-OF-THOUGHT' },
    }),
  ]

  it('renders derived steps in event order', () => {
    render(<Timeline events={events} status="RESEARCHING" />)
    const items = screen.getAllByRole('listitem').map((item) => item.textContent ?? '')
    const planningIndex = items.findIndex((text) => text.includes('Planning research'))
    const searchIndex = items.findIndex((text) => text.includes('Searching 2/5'))
    const evidenceIndex = items.findIndex((text) => text.includes('Evidence collected (12 items)'))
    expect(planningIndex).toBeGreaterThanOrEqual(0)
    expect(searchIndex).toBeGreaterThan(planningIndex)
    expect(evidenceIndex).toBeGreaterThan(searchIndex)
  })

  it('renders a planner repair step without leaking plan problems payload', () => {
    render(
      <Timeline
        events={[
          makeEvent('PLANNING_STARTED'),
          makeEvent('PLANNING_REPAIR_STARTED', {
            message: 'Initial plan was unusable; repairing the research plan...',
            payload: { problems: ['it contained no usable (non-empty) search queries'] },
          }),
          makeEvent('PLAN_CREATED'),
        ]}
        status="PLANNING"
      />,
    )
    expect(screen.getByText('Repairing research plan')).toBeInTheDocument()
    expect(screen.queryByText(/non-empty/)).not.toBeInTheDocument()
  })

  it('shows the per-query progress label and critic score', () => {
    render(<Timeline events={events} status="RESEARCHING" />)
    expect(screen.getByText('Searching 2/5: solar capacity 2026')).toBeInTheDocument()
    expect(screen.getByText('Critic review complete')).toBeInTheDocument()
    expect(screen.getByText('Score 0.82')).toBeInTheDocument()
  })

  it('never renders reasoning text from event payloads', () => {
    render(<Timeline events={events} status="RESEARCHING" />)
    expect(screen.queryByText(/INTERNAL-CHAIN-OF-THOUGHT/)).not.toBeInTheDocument()
  })

  it('marks earlier steps complete and the latest step current while running', () => {
    const { container } = render(<Timeline events={events} status="RESEARCHING" />)
    const complete = container.querySelectorAll('.timeline-step.complete')
    const current = container.querySelectorAll('.timeline-step.current')
    expect(complete.length).toBeGreaterThanOrEqual(4)
    expect(current.length).toBe(1)
    expect(current[0].textContent).toContain('Critic review complete')
  })

  it('shows muted pending phases for work not yet started', () => {
    const { container } = render(<Timeline events={events} status="RESEARCHING" />)
    const pending = Array.from(container.querySelectorAll('.timeline-step.pending')).map(
      (node) => node.textContent,
    )
    expect(pending).toContain('Synthesis')
    expect(pending).toContain('Complete')
  })

  it('marks every step complete once the run has finished', () => {
    const finished = [
      ...events,
      makeEvent('SYNTHESIS_STARTED', { seq: 100 }),
      makeEvent('RUN_COMPLETED', { seq: 101 }),
    ]
    const { container } = render(<Timeline events={finished} status="COMPLETED" />)
    expect(container.querySelectorAll('.timeline-step.current').length).toBe(0)
    expect(container.querySelectorAll('.timeline-step.pending').length).toBe(0)
    expect(screen.getByText('Research complete')).toBeInTheDocument()
  })
})

describe('RunStatChips', () => {
  beforeEach(() => {
    resetEventSeq()
  })

  it('derives stat chips from event payloads', () => {
    const events = [
      makeEvent('EVIDENCE_COLLECTED', { payload: { total_items: 12, memory_hits: 3 } }),
      makeEvent('CRITIC_COMPLETED', { payload: { score: 0.82 }, iteration: 1 }),
    ]
    render(<RunStatChips events={events} iterations={1} />)
    expect(screen.getByText('Sources').nextSibling).toHaveTextContent('12')
    expect(screen.getByText('Critic score').nextSibling).toHaveTextContent('0.82')
    expect(screen.getByText('Memory hits').nextSibling).toHaveTextContent('3')
    expect(screen.getByText('Iteration').nextSibling).toHaveTextContent('1')
  })
})
