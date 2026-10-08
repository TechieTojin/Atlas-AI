import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeDocument, makeRun, TEMPLATE_FIXTURES } from '../test/fixtures'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { QueryForm } from './QueryForm'

function renderForm(projectId?: string) {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<QueryForm projectId={projectId} />} />
        <Route path="/runs/:id" element={<div>run page opened</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('QueryForm', () => {
  let mock: ReturnType<typeof installFetchMock>

  beforeEach(() => {
    mock = installFetchMock((url, init) => {
      if (url === '/api/documents') {
        return { body: { documents: [makeDocument({ id: 'doc-1', filename: 'notes.md' })] } }
      }
      if (url === '/api/runs' && init?.method === 'POST') {
        return { status: 201, body: makeRun({ id: 'new-run' }) }
      }
      return undefined
    })
  })

  it('renders the query input and disables submit while the query is empty', async () => {
    renderForm()
    expect(screen.getByLabelText('Research question')).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Start Research' })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByLabelText('Research question'), 'solar growth')
    expect(submit).toBeEnabled()
  })

  it('defaults to FAST and switches the mode via the segmented control', async () => {
    renderForm()
    const fast = screen.getByRole('button', { name: /Fast/ })
    const deep = screen.getByRole('button', { name: /Deep/ })
    expect(fast).toHaveAttribute('aria-pressed', 'true')
    expect(deep).toHaveAttribute('aria-pressed', 'false')

    await userEvent.click(deep)
    expect(deep).toHaveAttribute('aria-pressed', 'true')
    expect(fast).toHaveAttribute('aria-pressed', 'false')
  })

  it('submits a run with the selected mode and navigates to the run page', async () => {
    renderForm()
    await userEvent.type(screen.getByLabelText('Research question'), 'solar growth rate')
    await userEvent.click(screen.getByRole('button', { name: /Deep/ }))
    await userEvent.click(screen.getByLabelText(/Review plan before research/))
    await userEvent.click(screen.getByRole('button', { name: 'Start Research' }))

    await screen.findByText('run page opened')

    const postCall = mock.mock.calls.find(([url, init]) => url === '/api/runs' && init?.method === 'POST')
    expect(postCall).toBeDefined()
    expect(requestBody(postCall?.[1])).toEqual({
      query: 'solar growth rate',
      mode: 'DEEP',
      source_scope: 'WEB',
      document_ids: [],
      approval_required: true,
      template: 'STANDARD',
      use_memory: true,
      // Capabilities are not mocked here, so only English is known to be supported.
      output_language: 'en',
    })
  })

  it('requires a document selection when the scope is Documents only', async () => {
    renderForm()
    await userEvent.type(screen.getByLabelText('Research question'), 'summarize my notes')
    await userEvent.click(screen.getByRole('button', { name: 'Documents' }))

    const submit = screen.getByRole('button', { name: 'Start Research' })
    expect(submit).toBeDisabled()

    const chip = await screen.findByRole('button', { name: 'notes.md' })
    await userEvent.click(chip)
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    expect(submit).toBeEnabled()

    await userEvent.click(submit)
    await waitFor(() => {
      const postCall = mock.mock.calls.find(
        ([url, init]) => url === '/api/runs' && init?.method === 'POST',
      )
      expect(requestBody(postCall?.[1])).toMatchObject({
        source_scope: 'DOCUMENTS',
        document_ids: ['doc-1'],
      })
    })
  })

  it('shows the API error when run creation fails', async () => {
    mock.mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/documents') {
        return {
          ok: true,
          status: 200,
          json: async () => ({ documents: [] }),
        } as unknown as Response
      }
      return {
        ok: false,
        status: 422,
        json: async () => ({ detail: 'Query too short' }),
      } as unknown as Response
    })

    renderForm()
    await userEvent.type(screen.getByLabelText('Research question'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Start Research' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Query too short')
  })
})

describe('QueryForm templates and memory', () => {
  let mock: ReturnType<typeof installFetchMock>

  beforeEach(() => {
    mock = installFetchMock((url, init) => {
      if (url === '/api/templates') {
        return { body: { templates: TEMPLATE_FIXTURES } }
      }
      if (url === '/api/documents') {
        return { body: { documents: [] } }
      }
      if (url === '/api/runs' && init?.method === 'POST') {
        return { status: 201, body: makeRun({ id: 'new-run' }) }
      }
      return undefined
    })
  })

  it('renders the fetched template options with the selected description', async () => {
    renderForm()
    const select = await screen.findByLabelText('Report template')
    const options = within(select).getAllByRole('option').map((option) => option.textContent)
    expect(options).toEqual([
      'Standard',
      'Academic',
      'Technical',
      'Executive',
      'Literature review',
      'Comparison',
      'Custom',
    ])
    expect(select).toHaveValue('STANDARD')
    expect(screen.getByText('Balanced research report')).toBeInTheDocument()

    await userEvent.selectOptions(select, 'ACADEMIC')
    expect(screen.getByText('Formal style with methodology notes')).toBeInTheDocument()
  })

  it('reveals a required custom-template textarea for CUSTOM and blocks submit until filled', async () => {
    renderForm()
    await userEvent.type(screen.getByLabelText('Research question'), 'solar growth')
    const select = await screen.findByLabelText('Report template')
    expect(
      screen.queryByLabelText('Custom template instructions (required)'),
    ).not.toBeInTheDocument()

    await userEvent.selectOptions(select, 'CUSTOM')
    const textarea = screen.getByLabelText('Custom template instructions (required)')
    expect(textarea).toBeRequired()
    expect(textarea).toHaveAttribute('maxlength', '2000')

    const submit = screen.getByRole('button', { name: 'Start Research' })
    expect(submit).toBeDisabled()

    await userEvent.type(textarea, 'Write it as a two-part briefing.')
    expect(submit).toBeEnabled()
  })

  it('submits template, custom instructions, memory choice, and project id', async () => {
    renderForm('proj-7')
    await userEvent.type(screen.getByLabelText('Research question'), 'solar growth')
    await userEvent.selectOptions(await screen.findByLabelText('Report template'), 'CUSTOM')
    await userEvent.type(
      screen.getByLabelText('Custom template instructions (required)'),
      'Two-part briefing.',
    )
    await userEvent.click(screen.getByLabelText('Use research memory'))
    await userEvent.click(screen.getByRole('button', { name: 'Start Research' }))
    await screen.findByText('run page opened')

    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/runs' && init?.method === 'POST',
    )
    expect(requestBody(postCall?.[1])).toEqual({
      query: 'solar growth',
      mode: 'FAST',
      source_scope: 'WEB',
      document_ids: [],
      approval_required: false,
      template: 'CUSTOM',
      custom_template: 'Two-part briefing.',
      use_memory: false,
      project_id: 'proj-7',
      output_language: 'en',
    })
  })
})
