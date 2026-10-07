import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import {
  makeProject,
  makeProjectOverview,
  makeRunSummary,
  TEMPLATE_FIXTURES,
} from '../test/fixtures'
import { installFetchMock } from '../test/mockFetch'
import { ProjectPage } from './ProjectPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/proj-1']}>
      <Routes>
        <Route path="/projects/:id" element={<ProjectPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProjectPage', () => {
  beforeEach(() => {
    installFetchMock((url) => {
      if (url === '/api/projects/proj-1/overview') {
        return { body: makeProjectOverview() }
      }
      if (url === '/api/projects/proj-1') {
        return { body: makeProject() }
      }
      if (url.startsWith('/api/runs')) {
        return {
          body: {
            runs: [
              makeRunSummary({ id: 'r1', title: 'Solar growth', project_id: 'proj-1' }),
              makeRunSummary({ id: 'r2', title: 'Battery costs', project_id: 'proj-1' }),
            ],
            total: 2,
            limit: 50,
            offset: 0,
          },
        }
      }
      if (url.startsWith('/api/documents')) {
        return { body: { documents: [] } }
      }
      if (url === '/api/templates') {
        return { body: { templates: TEMPLATE_FIXTURES } }
      }
      if (url.startsWith('/api/comparisons')) {
        return { body: { comparisons: [] } }
      }
      return undefined
    })
  })

  it('renders the workspace header, counts, and all five tabs', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Energy transition' })).toBeInTheDocument()

    for (const name of ['Overview', 'Research', 'Documents', 'Comparisons', 'Knowledge Graph']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument()
    }

    // The header offers the primary way to keep researching this project.
    expect(screen.getByRole('button', { name: 'Continue research' })).toBeInTheDocument()

    // Overview is active by default and renders the project knowledge dashboard.
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText('Current understanding')).toBeInTheDocument()
    expect(screen.getByText('Runs')).toBeInTheDocument()
    expect(screen.getByText(/Grid storage is the binding constraint/)).toBeInTheDocument()
    expect(screen.getByText('Solar growth')).toBeInTheDocument()
  })

  it('shows the project-scoped query form and runs list on the Research tab', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Energy transition' })

    await userEvent.click(screen.getByRole('tab', { name: 'Research' }))
    expect(screen.getByLabelText('Research question')).toBeInTheDocument()
    expect(await screen.findByText('Battery costs')).toBeInTheDocument()
    // Completed project runs are selectable for comparison.
    expect(
      screen.getByRole('checkbox', { name: 'Select Solar growth for comparison' }),
    ).toBeInTheDocument()
  })

  it('shows project documents and the assignable list on the Documents tab', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Energy transition' })

    await userEvent.click(screen.getByRole('tab', { name: 'Documents' }))
    expect(screen.getByLabelText('Upload document to project')).toBeInTheDocument()
    expect(await screen.findByText('No documents in this project yet.')).toBeInTheDocument()
  })
})
