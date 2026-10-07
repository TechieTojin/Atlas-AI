import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeDocument } from '../test/fixtures'
import { installFetchMock } from '../test/mockFetch'
import type { DocumentRecord } from '../types'
import { DocumentsPage } from './DocumentsPage'

describe('DocumentsPage', () => {
  let documents: DocumentRecord[]

  beforeEach(() => {
    documents = [makeDocument({ id: 'doc-1', filename: 'energy-outlook.pdf' })]
  })

  function installHandlers(uploadSpec?: { status: number; body: unknown }) {
    return installFetchMock((url, init) => {
      if (url === '/api/documents' && init?.method === 'POST') {
        if (uploadSpec) return uploadSpec
        const record = makeDocument({ id: 'doc-2', filename: 'notes.md', file_type: 'md' })
        documents = [...documents, record]
        return { status: 201, body: record }
      }
      if (url === '/api/documents' && (!init?.method || init.method === 'GET')) {
        return { body: { documents } }
      }
      if (url.startsWith('/api/documents/') && init?.method === 'DELETE') {
        return { status: 204 }
      }
      return undefined
    })
  }

  it('lists documents with size, status, and metadata', async () => {
    installHandlers()
    render(<DocumentsPage />)
    expect(await screen.findByText('energy-outlook.pdf')).toBeInTheDocument()
    expect(screen.getByText('2.3 MB')).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('Ready')).toBeInTheDocument()
    expect(within(table).getByText('PDF', { selector: '.type-badge' })).toBeInTheDocument()
  })

  it('uploads a file and shows the new document', async () => {
    const mock = installHandlers()
    render(<DocumentsPage />)
    await screen.findByText('energy-outlook.pdf')

    const input = screen.getByLabelText('Upload document')
    const file = new File(['# notes'], 'notes.md', { type: 'text/markdown' })
    fireEvent.change(input, { target: { files: [file] } })

    expect(await screen.findByText('notes.md')).toBeInTheDocument()
    const postCall = mock.mock.calls.find(
      ([url, init]) => url === '/api/documents' && init?.method === 'POST',
    )
    expect(postCall).toBeDefined()
    expect(postCall?.[1]?.body).toBeInstanceOf(FormData)
  })

  it('shows the API error message when the upload fails', async () => {
    installHandlers({ status: 400, body: { detail: 'File is corrupted' } })
    render(<DocumentsPage />)
    await screen.findByText('energy-outlook.pdf')

    const file = new File(['x'], 'bad.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Upload document'), { target: { files: [file] } })

    expect(await screen.findByRole('alert')).toHaveTextContent('File is corrupted')
  })

  it('rejects unsupported file types client-side without calling the API', async () => {
    const mock = installHandlers()
    render(<DocumentsPage />)
    await screen.findByText('energy-outlook.pdf')

    const file = new File(['x'], 'image.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload document'), { target: { files: [file] } })

    expect(await screen.findByRole('alert')).toHaveTextContent('Unsupported file type')
    expect(
      mock.mock.calls.find(([url, init]) => url === '/api/documents' && init?.method === 'POST'),
    ).toBeUndefined()
  })

  it('deletes a document after confirmation', async () => {
    const mock = installHandlers()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<DocumentsPage />)
    await screen.findByText('energy-outlook.pdf')

    // Delete lives in the row's actions menu.
    await userEvent.click(screen.getByRole('button', { name: 'More actions for energy-outlook.pdf' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete energy-outlook.pdf' }))

    await waitFor(() => {
      expect(screen.queryByText('energy-outlook.pdf')).not.toBeInTheDocument()
    })
    const deleteCall = mock.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(deleteCall?.[0]).toBe('/api/documents/doc-1')
  })

  it('does not delete when the confirmation is dismissed', async () => {
    const mock = installHandlers()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<DocumentsPage />)
    await screen.findByText('energy-outlook.pdf')

    await userEvent.click(screen.getByRole('button', { name: 'More actions for energy-outlook.pdf' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete energy-outlook.pdf' }))

    expect(screen.getByText('energy-outlook.pdf')).toBeInTheDocument()
    expect(mock.mock.calls.find(([, init]) => init?.method === 'DELETE')).toBeUndefined()
  })
})
