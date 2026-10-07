import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeEvent, makeFollowUp, makeSource, resetEventSeq } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock, requestBody } from '../test/mockFetch'
import type { FollowUp } from '../types'
import { FollowUpPanel } from './FollowUpPanel'

describe('FollowUpPanel', () => {
  let followups: FollowUp[]

  beforeEach(() => {
    MockEventSource.reset()
    resetEventSeq()
    vi.stubGlobal('EventSource', MockEventSource)
    followups = []
  })

  function installHandlers() {
    return installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/followups' && init?.method === 'POST') {
        const created = makeFollowUp({
          id: 'fu-9',
          status: 'RUNNING',
          answer: '',
          question: (requestBody(init) as { question: string }).question,
        })
        return { status: 201, body: created }
      }
      if (url === '/api/runs/run-1/followups') {
        return { body: { followups } }
      }
      return undefined
    })
  }

  it('renders completed follow-ups with kind badge and new-source markers', async () => {
    followups = [
      makeFollowUp({
        kind: 'RESEARCH',
        searched: true,
        question: 'Which regions lead deployment?',
        new_source_count: 1,
        parent_source_count: 1,
        answer: 'Deeper findings here. [2]',
        sources: [
          makeSource({ index: 1 }),
          makeSource({ index: 2, title: 'New deep source', url: 'https://example.org/deep' }),
        ],
      }),
    ]
    installHandlers()
    render(<FollowUpPanel runId="run-1" />)

    expect(await screen.findByText('Which regions lead deployment?')).toBeInTheDocument()
    expect(screen.getByText('RESEARCH')).toBeInTheDocument()
    expect(screen.getByText('+1 new sources')).toBeInTheDocument()
    expect(screen.getByText(/Deeper findings here\./)).toBeInTheDocument()

    // Expand the numbered source list: only the source beyond the parent
    // count carries a "New" badge.
    await userEvent.click(screen.getByRole('button', { name: 'Sources (2)' }))
    const newBadges = screen.getAllByText('New')
    expect(newBadges).toHaveLength(1)
    expect(screen.getByText('New deep source')).toBeInTheDocument()
  })

  it('submits a question, streams until terminal, then shows the refreshed answer', async () => {
    const mock = installHandlers()
    render(<FollowUpPanel runId="run-1" />)

    const input = screen.getByLabelText('Follow-up question')
    await userEvent.type(input, 'Why does this matter?')
    await userEvent.selectOptions(screen.getByLabelText('Follow-up mode'), 'research')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))

    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/runs/run-1/followups' && init?.method === 'POST',
    )
    expect(requestBody(postCall?.[1])).toEqual({ question: 'Why does this matter?', mode: 'research' })

    // Running state streams from the follow-up events endpoint.
    expect(await screen.findByText('Answering…')).toBeInTheDocument()
    const source = MockEventSource.latest()
    expect(source.url).toBe('/api/followups/fu-9/events')

    followups = [
      makeFollowUp({ id: 'fu-9', question: 'Why does this matter?', answer: 'Because grids. [1]' }),
    ]
    act(() => {
      source.emit('FOLLOWUP_COMPLETED', makeEvent('FOLLOWUP_COMPLETED'))
    })

    expect(await screen.findByText(/Because grids\./)).toBeInTheDocument()
    expect(screen.queryByText('Answering…')).not.toBeInTheDocument()
  })

  it('prefills the question from a suggestion chip', async () => {
    installHandlers()
    render(<FollowUpPanel runId="run-1" />)
    await userEvent.click(screen.getByRole('button', { name: 'What contradicts this?' }))
    expect(screen.getByLabelText('Follow-up question')).toHaveValue('What contradicts this?')
  })
})
