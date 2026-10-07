import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { makeRun, TEMPLATE_FIXTURES } from '../test/fixtures'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { ExportMenu, RegenerateAction } from './RunActions'

function withRouter(element: React.ReactElement) {
  return (
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={element} />
        <Route path="/runs/:id" element={<div>regenerated run opened</div>} />
      </Routes>
    </MemoryRouter>
  )
}

describe('ExportMenu', () => {
  beforeEach(() => {
    installFetchMock(() => undefined)
  })

  it('offers markdown and PDF export links', async () => {
    render(withRouter(<ExportMenu runId="run-1" />))
    await userEvent.click(screen.getByRole('button', { name: /Export/ }))

    expect(screen.getByRole('menuitem', { name: 'Markdown (.md)' })).toHaveAttribute(
      'href',
      '/api/runs/run-1/export?format=markdown',
    )
    expect(screen.getByRole('menuitem', { name: 'PDF (.pdf)' })).toHaveAttribute(
      'href',
      '/api/runs/run-1/export?format=pdf',
    )
  })
})

describe('RegenerateAction', () => {
  let mock: ReturnType<typeof installFetchMock>

  beforeEach(() => {
    mock = installFetchMock((url, init) => {
      if (url === '/api/templates') {
        return { body: { templates: TEMPLATE_FIXTURES } }
      }
      if (url === '/api/runs/run-1/regenerate' && init?.method === 'POST') {
        return { status: 201, body: makeRun({ id: 'run-2', regenerated_from: 'run-1' }) }
      }
      return undefined
    })
  })

  it('posts the chosen template and navigates to the new run', async () => {
    render(withRouter(<RegenerateAction run={makeRun()} />))
    await userEvent.click(screen.getByRole('button', { name: 'Regenerate report' }))

    const select = await screen.findByLabelText('Template')
    await userEvent.selectOptions(select, 'EXECUTIVE')
    await userEvent.click(screen.getByRole('button', { name: 'Regenerate' }))

    expect(await screen.findByText('regenerated run opened')).toBeInTheDocument()
    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/runs/run-1/regenerate' && init?.method === 'POST',
    )
    expect(requestBody(postCall?.[1])).toEqual({ template: 'EXECUTIVE' })
  })

  it('requires custom instructions when CUSTOM is chosen', async () => {
    render(withRouter(<RegenerateAction run={makeRun()} />))
    await userEvent.click(screen.getByRole('button', { name: 'Regenerate report' }))

    await userEvent.selectOptions(await screen.findByLabelText('Template'), 'CUSTOM')
    const confirm = screen.getByRole('button', { name: 'Regenerate' })
    expect(confirm).toBeDisabled()

    await userEvent.type(
      screen.getByLabelText('Custom instructions (required)'),
      'Focus on policy implications.',
    )
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)

    expect(await screen.findByText('regenerated run opened')).toBeInTheDocument()
    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/runs/run-1/regenerate' && init?.method === 'POST',
    )
    expect(requestBody(postCall?.[1])).toEqual({
      template: 'CUSTOM',
      custom_template: 'Focus on policy implications.',
    })
  })
})
