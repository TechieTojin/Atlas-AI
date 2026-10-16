import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it } from 'vitest'
import { loadMessages } from '../i18n'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { renderWithLocale } from '../test/renderWithLocale'
import type { Collection, CollectionItem } from '../types'
import { CollectionPage, CollectionsPage } from './CollectionsPage'
import { SaveToCollection } from '../components/SaveToCollection'

function collection(overrides: Partial<Collection> = {}): Collection {
  return {
    id: 'col-1',
    title: 'Battery notes',
    description: 'Everything about degradation',
    project_id: '',
    created_at: '2026-10-09T10:00:00Z',
    updated_at: '2026-10-09T11:00:00Z',
    item_count: 2,
    ...overrides,
  }
}

function item(partial: Partial<CollectionItem> & Pick<CollectionItem, 'id' | 'type'>): CollectionItem {
  return {
    collection_id: 'col-1',
    position: 1,
    note: '',
    data: {},
    created_at: '2026-10-09T10:30:00Z',
    origin_exists: true,
    ...partial,
  }
}

const EVIDENCE = item({
  id: 'i1',
  type: 'evidence',
  data: { text: 'It retained 91% capacity.', title: 'Battery report', run_id: 'run-9', citation: 2 },
  note: 'Key number for the intro.',
})
const NOTE = item({ id: 'i2', type: 'note', position: 2, note: 'My own hypothesis: humidity drives this.' })

function backend(state: { items?: CollectionItem[]; collections?: Collection[] } = {}) {
  const current = {
    collections: state.collections ?? [collection()],
    items: state.items ?? [EVIDENCE, NOTE],
  }
  const mock = installFetchMock((url, init) => {
    const method = init?.method ?? 'GET'
    if (url === '/api/collections' && method === 'GET') return { body: { collections: current.collections } }
    if (url === '/api/collections' && method === 'POST') {
      const body = requestBody(init) as { title: string }
      const created = collection({ id: 'col-new', title: body.title, item_count: 0 })
      current.collections = [created, ...current.collections]
      return { status: 201, body: created }
    }
    if (url === '/api/collections/col-1' && method === 'GET')
      return { body: { collection: current.collections[0], items: current.items } }
    if (url === '/api/collections/col-1' && method === 'DELETE') return { status: 204 }
    if (url === '/api/collections/col-1/items' && method === 'POST') {
      const body = requestBody(init) as { type: string; note: string }
      const added = item({ id: `i${current.items.length + 1}`, type: body.type as CollectionItem['type'], note: body.note, position: current.items.length + 1 })
      current.items = [...current.items, added]
      return { status: 201, body: { ...added, existing: false } }
    }
    if (url === '/api/collection-items/i1' && method === 'DELETE') {
      current.items = current.items.filter((entry) => entry.id !== 'i1')
      return { status: 204 }
    }
    if (url === '/api/collections/col-new/items' && method === 'POST')
      return { status: 201, body: { ...item({ id: 'ix', type: 'source' }), existing: false } }
    return undefined
  })
  return { mock, current }
}

beforeAll(async () => {
  await loadMessages('hi')
})

describe('Collections', () => {
  it('lists collections and creates a new one', async () => {
    const user = userEvent.setup()
    const { mock } = backend()
    const { t } = await renderWithLocale(<CollectionsPage />, { route: '/collections' })
    expect(await screen.findByText('Battery notes')).toBeInTheDocument()
    expect(screen.getByText(new RegExp(t('collections.itemCount', { count: '2' })))).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText(t('collections.newPlaceholder')), 'Field notes')
    await user.click(screen.getByRole('button', { name: t('collections.create') }))
    const created = mock.mock.calls.find(
      ([url, init]) => url === '/api/collections' && (init as RequestInit)?.method === 'POST',
    )
    expect(requestBody(created?.[1] as RequestInit)).toEqual({ title: 'Field notes' })
  })

  it('shows items with provenance and keeps notes visually distinct from evidence', async () => {
    backend()
    const { t } = await renderWithLocale(<CollectionPage />, {
      route: '/collections/col-1',
      path: '/collections/:id',
    })
    expect(await screen.findByText('Battery notes')).toBeInTheDocument()
    const items = screen.getAllByRole('listitem')
    const evidenceCard = items.find((candidate) => candidate.textContent?.includes('91% capacity'))!
    const noteCard = items.find((candidate) => candidate.textContent?.includes('humidity drives'))!
    expect(evidenceCard).toHaveTextContent(t('collections.type.evidence'))
    expect(evidenceCard).toHaveTextContent('[2]')
    expect(evidenceCard).toHaveTextContent('Battery report')
    expect(within(evidenceCard).getByRole('link', { name: t('collections.openOrigin') })).toHaveAttribute(
      'href',
      '/runs/run-9',
    )
    expect(noteCard.className).toContain('is-note')
    expect(evidenceCard.className).not.toContain('is-note')
    expect(noteCard).toHaveTextContent(t('collections.type.note'))
  })

  it('marks items whose origin was deleted, keeping the snapshot', async () => {
    backend({
      items: [
        item({
          id: 'i1',
          type: 'website_passage',
          origin_exists: false,
          data: { text: 'Saved passage.', title: 'Old site', website_id: 'w-gone', url: 'https://site.example/x' },
        }),
      ],
    })
    const { t } = await renderWithLocale(<CollectionPage />, {
      route: '/collections/col-1',
      path: '/collections/:id',
    })
    expect(await screen.findByText(t('collections.originGone'))).toBeInTheDocument()
    expect(screen.getByText('Saved passage.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: t('collections.openOrigin') })).toBeNull()
    // The safe external source link still works.
    expect(screen.getByRole('link', { name: t('collections.openSource') })).toHaveAttribute(
      'href',
      'https://site.example/x',
    )
  })

  it('adds a user note and removes an item', async () => {
    const user = userEvent.setup()
    const { mock } = backend()
    const { t } = await renderWithLocale(<CollectionPage />, {
      route: '/collections/col-1',
      path: '/collections/:id',
    })
    await screen.findByText('Battery notes')
    await user.type(screen.getByPlaceholderText(t('collections.notePlaceholder')), 'Follow up tomorrow')
    await user.click(screen.getByRole('button', { name: t('collections.saveNote') }))
    const posted = mock.mock.calls.find(
      ([url, init]) => url === '/api/collections/col-1/items' && (init as RequestInit)?.method === 'POST',
    )
    expect(requestBody(posted?.[1] as RequestInit)).toEqual({ type: 'note', note: 'Follow up tomorrow', data: {} })
    const evidenceCard = screen.getAllByRole('listitem').find((c) => c.textContent?.includes('91% capacity'))!
    await user.click(within(evidenceCard).getByRole('button', { name: t('collections.removeItem') }))
    expect(
      mock.mock.calls.some(([url, init]) => url === '/api/collection-items/i1' && (init as RequestInit)?.method === 'DELETE'),
    ).toBe(true)
  })

  it('filters by type when several types exist', async () => {
    const user = userEvent.setup()
    backend()
    const { t } = await renderWithLocale(<CollectionPage />, {
      route: '/collections/col-1',
      path: '/collections/:id',
    })
    await screen.findByText('Battery notes')
    await user.click(screen.getByRole('button', { name: t('collections.type.note') }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: t('collections.filterAll') }))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('SaveToCollection saves into an existing collection or an inline new one', async () => {
    const user = userEvent.setup()
    const { mock } = backend()
    const { t } = await renderWithLocale(
      <SaveToCollection itemType="evidence" data={{ text: 'Excerpt', run_id: 'run-1' }} />,
    )
    await user.click(screen.getByRole('button', { name: t('collections.save') }))
    await user.click(await screen.findByRole('menuitem', { name: /Battery notes/ }))
    expect(await screen.findByText(t('collections.saved'))).toBeInTheDocument()
    const saved = mock.mock.calls.find(
      ([url, init]) => url === '/api/collections/col-1/items' && (init as RequestInit)?.method === 'POST',
    )
    expect(requestBody(saved?.[1] as RequestInit)).toEqual({
      type: 'evidence',
      note: '',
      data: { text: 'Excerpt', run_id: 'run-1' },
    })
  })

  it('translates the static UI (hi) and leaves saved content as stored', async () => {
    backend()
    const { t } = await renderWithLocale(<CollectionPage />, {
      route: '/collections/col-1',
      path: '/collections/:id',
      language: 'hi',
    })
    expect(await screen.findByText('Battery notes')).toBeInTheDocument()
    expect(screen.getByText('It retained 91% capacity.')).toBeInTheDocument()
    expect(t('collections.type.note')).toBe('टिप्पणी')
    expect(screen.getAllByText(t('collections.type.note')).length).toBeGreaterThan(0)
  })
})
