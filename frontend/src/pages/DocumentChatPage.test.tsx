import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import type { LanguageCapabilities } from '../api/client'
import { languageName, loadMessages, resetLanguageCapabilities } from '../i18n'
import { makePreference, writePreference } from '../i18n/preference'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { renderWithLocale } from '../test/renderWithLocale'
import type { DocumentChatMessage, DocumentConversation } from '../types'
import { DocumentChatPage } from './DocumentChatPage'

const DOCS = [
  { id: 'doc-a', filename: 'alpha.txt', content_type: 'text/plain', file_type: 'txt', size_bytes: 10, checksum: '', status: 'READY', error: '', chunk_count: 2, page_count: 0, project_id: '', uploaded_at: '2026-10-09T10:00:00Z' },
  { id: 'doc-b', filename: 'beta.pdf', content_type: 'application/pdf', file_type: 'pdf', size_bytes: 10, checksum: '', status: 'READY', error: '', chunk_count: 3, page_count: 4, project_id: '', uploaded_at: '2026-10-09T10:00:00Z' },
]

function message(partial: Partial<DocumentChatMessage> & Pick<DocumentChatMessage, 'id' | 'role' | 'seq'>): DocumentChatMessage {
  return {
    conversation_id: 'conv-1',
    content: '',
    status: 'COMPLETED',
    error: '',
    error_code: '',
    insufficient_evidence: false,
    citations: [],
    cited: [],
    output_language: 'en',
    metrics: {},
    created_at: '2026-10-09T10:01:00Z',
    completed_at: '2026-10-09T10:01:30Z',
    ...partial,
  }
}

function conversation(overrides: Partial<DocumentConversation> = {}): DocumentConversation {
  return {
    id: 'conv-1',
    title: 'Capacity?',
    document_ids: ['doc-a', 'doc-b'],
    output_language: 'en',
    project_id: '',
    created_at: '2026-10-09T10:00:30Z',
    updated_at: '2026-10-09T10:01:30Z',
    ...overrides,
  }
}

const ANSWER = message({
  id: 'a1',
  role: 'assistant',
  seq: 2,
  content: 'The Alpha prototype retained 88% capacity after 800 cycles [1].',
  citations: [
    { index: 1, document_id: 'doc-a', filename: 'alpha.txt', page: 2, text: 'Alpha retained 88% capacity after 800 cycles.', score: 0.8 },
  ],
  cited: [1],
})
const QUESTION = message({ id: 'q1', role: 'user', seq: 1, content: 'How much capacity?' })

function capabilities(status: 'supported' | 'unsupported' = 'supported'): LanguageCapabilities {
  return {
    default_output_language: 'en',
    model: 'qwen3:4b',
    languages: ['en', 'ml'].map((code) => ({
      code,
      english_name: code,
      native_name: code,
      model: 'qwen3:4b',
      status: code === 'en' ? 'supported' : status,
      supported: code === 'en' || status === 'supported',
      reason: '',
      features: {
        document_chat: {
          status: code === 'en' ? 'supported' : 'unsupported',
          supported: code === 'en',
          reason: '',
        },
      },
    })),
  }
}

interface State {
  conversations: DocumentConversation[]
  messages: DocumentChatMessage[]
}

function backend(state: Partial<State> = {}, overrides: Record<string, unknown> = {}) {
  const current: State = {
    conversations: state.conversations ?? [],
    messages: state.messages ?? [],
  }
  const mock = installFetchMock((url, init) => {
    const method = init?.method ?? 'GET'
    if (url === '/api/capabilities/languages') return { body: capabilities() }
    if (url === '/api/documents' && method === 'GET') return { body: { documents: DOCS } }
    if (url === '/api/document-conversations' && method === 'GET')
      return { body: { conversations: current.conversations } }
    if (url === '/api/document-conversations' && method === 'POST') {
      const created = conversation({ title: '' })
      current.conversations = [created]
      return { status: 201, body: { conversation: created, messages: [] } }
    }
    if (url === '/api/document-conversations/conv-1' && method === 'GET')
      return { body: { conversation: current.conversations[0] ?? conversation(), messages: current.messages } }
    if (url === '/api/document-conversations/conv-1' && method === 'DELETE') return { status: 204 }
    if (url === '/api/document-conversations/conv-1/messages' && method === 'POST') {
      current.messages = [...current.messages, QUESTION, ANSWER]
      return { status: 202, body: { user: QUESTION, answer: ANSWER } }
    }
    if (url.startsWith('/api/documents/relationships'))
      return {
        body: {
          documents: [
            { id: 'doc-a', filename: 'alpha.txt', top_terms: ['capacity'] },
            { id: 'doc-b', filename: 'beta.pdf', top_terms: ['capacity'] },
          ],
          links: [{ a: 'doc-a', b: 'doc-b', type: 'SHARES_CONCEPT', terms: ['capacity', 'cycles'], strength: 4 }],
          method: 'deterministic',
        },
      }
    if (url === '/api/collections' && method === 'GET') return { body: { collections: [] } }
    for (const [prefix, value] of Object.entries(overrides)) {
      if (url.startsWith(prefix)) return value as { status?: number; body?: unknown }
    }
    return undefined
  })
  return { mock, current }
}

const route = { route: '/documents/chat?ids=doc-a,doc-b', path: '/documents/chat' }

beforeAll(async () => {
  await Promise.all(['de', 'ml'].map((code) => loadMessages(code)))
})

beforeEach(() => {
  window.localStorage.clear()
  resetLanguageCapabilities()
})

describe('Document Chat', () => {
  it('asks across the selected documents and cites the exact passage', async () => {
    const user = userEvent.setup()
    const { mock } = backend()
    const { t } = await renderWithLocale(<DocumentChatPage />, route)
    expect(await screen.findByText('alpha.txt')).toBeInTheDocument()
    expect(screen.getByText('beta.pdf')).toBeInTheDocument()

    const composer = screen.getByLabelText(t('documentChat.composerLabel'), { selector: 'textarea' })
    await user.type(composer, 'How much capacity?')
    await user.click(screen.getByRole('button', { name: t('websiteChat.send') }))

    const created = mock.mock.calls.find(
      ([url, init]) => url === '/api/document-conversations' && (init as RequestInit)?.method === 'POST',
    )
    expect(requestBody(created?.[1] as RequestInit)).toEqual({
      document_ids: ['doc-a', 'doc-b'],
      output_language: 'en',
    })
    const citation = await screen.findByRole('button', { name: t('report.viewSource', { index: '1' }) })
    await user.click(citation)
    const drawer = screen.getByRole('dialog', { name: t('documentChat.drawer.label', { index: '1' }) })
    expect(drawer).toHaveTextContent('alpha.txt')
    expect(drawer).toHaveTextContent('Alpha retained 88% capacity after 800 cycles.')
    expect(within(drawer).getByText('2')).toBeInTheDocument() // page number
    expect(within(drawer).getByRole('button', { name: t('collections.save') })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows insufficient evidence clearly, without citations', async () => {
    const insufficient = message({
      id: 'a2', role: 'assistant', seq: 2, insufficient_evidence: true,
      content: 'The selected documents do not provide enough information to answer this question.',
    })
    backend({ conversations: [conversation()], messages: [QUESTION, insufficient] })
    const { t } = await renderWithLocale(<DocumentChatPage />, { ...route, route: '/documents/chat?c=conv-1' })
    expect(await screen.findByText(t('documentChat.insufficient'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('report.viewSource', { index: '1' }) })).toBeNull()
  })

  it('shows a running answer with Cancel and keeps the composer disabled', async () => {
    const running = message({
      id: 'a3', role: 'assistant', seq: 2, status: 'PENDING', stage: 'GENERATING',
      created_at: new Date(Date.now() - 5_000).toISOString(), completed_at: null,
    })
    const { mock, current } = backend(
      { conversations: [conversation()], messages: [QUESTION, running] },
      {
        '/api/document-messages/a3/cancel': { body: running },
      },
    )
    const { t } = await renderWithLocale(<DocumentChatPage />, { ...route, route: '/documents/chat?c=conv-1' })
    await screen.findByText(t('websiteChat.answering.GENERATING'))
    expect(screen.getByLabelText(t('documentChat.composerLabel'), { selector: 'textarea' })).toBeDisabled()
    current.messages = [QUESTION, { ...running, status: 'CANCELLED', stage: '' }]
    await userEvent.setup().click(screen.getByRole('button', { name: t('websiteChat.answering.cancel') }))
    expect(
      mock.mock.calls.some(([url, init]) => url === '/api/document-messages/a3/cancel' && (init as RequestInit)?.method === 'POST'),
    ).toBe(true)
    expect(await screen.findByText(t('websiteChat.answering.cancelled'))).toBeInTheDocument()
  })

  it('requires an explicit English choice for unsupported languages and sends nothing', async () => {
    writePreference(makePreference('ml'))
    const user = userEvent.setup()
    const { mock } = backend()
    const { t } = await renderWithLocale(<DocumentChatPage />, { ...route, language: 'ml' })
    expect(
      await screen.findByText(t('documentChat.languageUnsupported', { preferred: languageName('ml', 'ml') })),
    ).toBeInTheDocument()
    const composer = screen.getByLabelText(t('documentChat.composerLabel'), { selector: 'textarea' })
    await user.type(composer, 'Question?{Enter}')
    expect(
      mock.mock.calls.some(([url, init]) => String(url).endsWith('/messages') && (init as RequestInit)?.method === 'POST'),
    ).toBe(false)
    await user.click(screen.getByRole('button', { name: t('documentChat.continueInEnglish') }))
    expect(screen.getByText(t('documentChat.continuingInEnglish'))).toBeInTheDocument()
  })

  it('shows deterministic relationships on demand', async () => {
    const user = userEvent.setup()
    backend()
    const { t } = await renderWithLocale(<DocumentChatPage />, route)
    await screen.findByText('alpha.txt')
    await user.click(screen.getByRole('button', { name: t('documentChat.relationships.title') }))
    const panel = await screen.findByRole('region', { name: t('documentChat.relationships.title') })
    expect(panel).toHaveTextContent('alpha.txt ↔ beta.pdf')
    expect(panel).toHaveTextContent(t('documentChat.relationships.sharesConcept'))
    expect(panel).toHaveTextContent('capacity · cycles')
    expect(panel).toHaveTextContent(t('documentChat.relationships.method'))
  })

  it('offers to choose documents when nothing is selected', async () => {
    backend()
    const { t } = await renderWithLocale(<DocumentChatPage />, { ...route, route: '/documents/chat' })
    expect(await screen.findByText(t('documentChat.noSelection'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: t('documentChat.chooseDocuments') })).toHaveAttribute(
      'href',
      '/documents',
    )
  })

  it('translates the static UI but never the stored answer (de)', async () => {
    backend({ conversations: [conversation()], messages: [QUESTION, ANSWER] })
    const { t } = await renderWithLocale(<DocumentChatPage />, {
      ...route,
      route: '/documents/chat?c=conv-1',
      language: 'de',
    })
    expect(await screen.findByText(t('documentChat.title'))).toBeInTheDocument()
    expect(t('documentChat.title')).toBe('Dokumenten-Chat')
    expect(screen.getByText(/The Alpha prototype retained 88% capacity/)).toBeInTheDocument()
    await waitFor(() => expect(document.body.textContent).not.toContain('�'))
  })
})
