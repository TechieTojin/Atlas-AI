import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { makeProject } from '../test/fixtures'
import { installFetchMock, requestBody } from '../test/mockFetch'
import type { ProjectWithCounts } from '../types'
import { ProjectsPage } from './ProjectsPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects']}>
      <Routes>
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:id" element={<div>project workspace opened</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProjectsPage', () => {
  let projects: ProjectWithCounts[]
  let mock: ReturnType<typeof installFetchMock>

  beforeEach(() => {
    projects = [
      makeProject(),
      makeProject({
        id: 'proj-2',
        name: 'Health research',
        description: '',
        counts: { runs: 1, documents: 0, comparisons: 0 },
      }),
    ]
    mock = installFetchMock((url, init) => {
      if (url === '/api/projects' && init?.method === 'POST') {
        const body = requestBody(init) as { name: string; description: string }
        return {
          status: 201,
          body: makeProject({ id: 'proj-new', name: body.name, description: body.description }),
        }
      }
      if (url === '/api/projects') {
        return { body: { projects } }
      }
      return undefined
    })
  })

  it('lists project cards with name, description, counts, and updated time', async () => {
    renderPage()
    expect(await screen.findByText('Energy transition')).toBeInTheDocument()
    expect(screen.getByText('Research into renewables and grids')).toBeInTheDocument()
    expect(screen.getByText('3 runs · 2 documents · 1 comparison')).toBeInTheDocument()
    expect(screen.getByText('Health research')).toBeInTheDocument()
    expect(screen.getByText('1 run · 0 documents')).toBeInTheDocument()
  })

  it('creates a project from the inline dialog and opens its workspace', async () => {
    renderPage()
    await screen.findByText('Energy transition')

    await userEvent.click(screen.getByRole('button', { name: 'New project' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Grid storage')
    await userEvent.type(screen.getByLabelText('Description'), 'Battery economics')
    await userEvent.click(screen.getByRole('button', { name: 'Create project' }))

    expect(await screen.findByText('project workspace opened')).toBeInTheDocument()
    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/projects' && init?.method === 'POST',
    )
    expect(requestBody(postCall?.[1])).toEqual({ name: 'Grid storage', description: 'Battery economics' })
  })

  it('shows an empty state when there are no projects', async () => {
    projects = []
    renderPage()
    expect(await screen.findByText(/No projects yet/)).toBeInTheDocument()
  })
})
