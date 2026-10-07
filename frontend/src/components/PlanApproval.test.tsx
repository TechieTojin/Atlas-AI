import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeRun } from '../test/fixtures'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { PlanApproval } from './PlanApproval'

const run = makeRun({
  status: 'AWAITING_APPROVAL',
  plan: {
    objective: 'Assess solar growth',
    subquestions: ['How much was added in 2025?', 'What is forecast for 2026?'],
    search_queries: ['solar additions 2025', 'solar forecast 2026'],
  },
})

describe('PlanApproval', () => {
  let mock: ReturnType<typeof installFetchMock>
  const onUpdated = vi.fn()

  beforeEach(() => {
    onUpdated.mockReset()
    mock = installFetchMock((url, init) => {
      if (url === `/api/runs/${run.id}/plan/approve` && init?.method === 'POST') {
        return { body: makeRun({ status: 'RESEARCHING' }) }
      }
      if (url === `/api/runs/${run.id}/plan/edit` && init?.method === 'POST') {
        return { body: makeRun({ status: 'AWAITING_APPROVAL' }) }
      }
      if (url === `/api/runs/${run.id}/cancel` && init?.method === 'POST') {
        return { body: makeRun({ status: 'CANCELLED' }) }
      }
      return undefined
    })
  })

  it('renders the objective, numbered subquestions, and search queries', () => {
    render(<PlanApproval run={run} onUpdated={onUpdated} />)
    expect(screen.getByText('Assess solar growth')).toBeInTheDocument()
    expect(screen.getByText('How much was added in 2025?')).toBeInTheDocument()
    expect(screen.getByText('What is forecast for 2026?')).toBeInTheDocument()
    expect(screen.getByText('solar additions 2025')).toBeInTheDocument()
    const lists = screen.getAllByRole('list')
    expect(lists.length).toBeGreaterThanOrEqual(2)
  })

  it('calls the approve endpoint and reports the updated run', async () => {
    render(<PlanApproval run={run} onUpdated={onUpdated} />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    const approveCall = mock.mock.calls.find(([url]) => url === `/api/runs/${run.id}/plan/approve`)
    expect(approveCall?.[1]?.method).toBe('POST')
    expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: 'RESEARCHING' }))
  })

  it('validates that edited subquestions are non-empty before saving', async () => {
    render(<PlanApproval run={run} onUpdated={onUpdated} />)
    await userEvent.click(screen.getByRole('button', { name: 'Edit plan' }))

    const subquestions = screen.getByLabelText('Subquestions (one per line)')
    await userEvent.clear(subquestions)
    await userEvent.click(screen.getByRole('button', { name: 'Save plan' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Add at least one subquestion.')
    expect(
      mock.mock.calls.find(([url]) => url === `/api/runs/${run.id}/plan/edit`),
    ).toBeUndefined()
  })

  it('saves a valid edit via the plan/edit endpoint with one item per line', async () => {
    render(<PlanApproval run={run} onUpdated={onUpdated} />)
    await userEvent.click(screen.getByRole('button', { name: 'Edit plan' }))

    const queries = screen.getByLabelText('Search queries (one per line)')
    await userEvent.clear(queries)
    await userEvent.type(queries, 'rooftop solar stats{enter}utility-scale solar stats')
    await userEvent.click(screen.getByRole('button', { name: 'Save plan' }))

    const editCall = mock.mock.calls.find(([url]) => url === `/api/runs/${run.id}/plan/edit`)
    expect(editCall).toBeDefined()
    expect(requestBody(editCall?.[1])).toMatchObject({
      objective: 'Assess solar growth',
      search_queries: ['rooftop solar stats', 'utility-scale solar stats'],
    })
    expect(onUpdated).toHaveBeenCalled()
    // back to review mode after a successful save
    expect(await screen.findByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('cancels the run from the approval card', async () => {
    render(<PlanApproval run={run} onUpdated={onUpdated} />)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel run' }))
    expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: 'CANCELLED' }))
  })
})
