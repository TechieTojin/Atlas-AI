import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { makeComparison, makeRunSummary } from '../test/fixtures'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { CompareRunsList } from './CompareRunsList'

const runs = [
  makeRunSummary({ id: 'r1', title: 'Solar growth', status: 'COMPLETED' }),
  makeRunSummary({ id: 'r2', title: 'Battery costs', status: 'COMPLETED' }),
  makeRunSummary({ id: 'r3', title: 'Grid upgrades', status: 'RESEARCHING' }),
]

function renderList() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<CompareRunsList runs={runs} projectId="proj-1" />} />
        <Route path="/comparisons/:id" element={<div>comparison opened</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CompareRunsList', () => {
  let mock: ReturnType<typeof installFetchMock>

  beforeEach(() => {
    mock = installFetchMock((url, init) => {
      if (url === '/api/comparisons' && init?.method === 'POST') {
        return { status: 201, body: makeComparison({ id: 'cmp-9', status: 'RUNNING' }) }
      }
      return undefined
    })
  })

  it('enables Compare only once two completed runs are selected', async () => {
    renderList()
    const compare = screen.getByRole('button', { name: /^Compare/ })
    expect(compare).toBeDisabled()

    // Non-completed runs cannot be selected.
    expect(
      screen.getByRole('checkbox', { name: 'Select Grid upgrades for comparison' }),
    ).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Solar growth for comparison' }))
    expect(screen.getByRole('button', { name: /^Compare/ })).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Battery costs for comparison' }))
    expect(screen.getByRole('button', { name: 'Compare (2)' })).toBeEnabled()
  })

  it('posts the selected run ids and navigates to the comparison', async () => {
    renderList()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Solar growth for comparison' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Battery costs for comparison' }))
    await userEvent.click(screen.getByRole('button', { name: 'Compare (2)' }))

    expect(await screen.findByText('comparison opened')).toBeInTheDocument()
    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/comparisons' && init?.method === 'POST',
    )
    expect(requestBody(postCall?.[1])).toEqual({
      run_ids: ['r1', 'r2'],
      project_id: 'proj-1',
      output_language: 'en',
    })
  })
})
