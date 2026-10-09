import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LanguageCapabilities } from '../api/client'
import { languageName, loadMessages, resetLanguageCapabilities } from '../i18n'
import { makePreference, writePreference } from '../i18n/preference'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { renderWithLocale } from '../test/renderWithLocale'
import type { WebsiteCitation, WebsiteConversation, WebsiteMessage, WebsiteSource } from '../types'
import { en } from '../i18n/messages/en'
import { formatElapsed, WebsiteChatPage } from './WebsiteChatPage'

function site(overrides: Partial<WebsiteSource> = {}): WebsiteSource {
  return {
    id: 'site-1',
    submitted_url: 'https://example.com/report',
    normalized_url: 'https://example.com/report',
    final_url: 'https://example.com/report',
    page_title: 'Example Battery Report',
    domain: 'example.com',
    status: 'READY',
    content_hash: 'abc',
    content_language: 'en',
    word_count: 1234,
    chunk_count: 7,
    index_version: 1,
    is_indexed: true,
    error: '',
    error_code: '',
    fetched_at: '2026-10-08T10:00:00Z',
    indexed_at: '2026-10-08T10:00:05Z',
    created_at: '2026-10-08T10:00:00Z',
    updated_at: '2026-10-08T10:00:05Z',
    metrics: {},
    ...overrides,
  }
}

const CITATION: WebsiteCitation = {
  index: 1,
  chunk_id: 'chunk-1',
  index_version: 1,
  chunk_index: 0,
  section_title: 'Battery Life',
  heading_path: ['Example Battery Report', 'Battery Life'],
  text: 'The cell retained 91% capacity after 1,000 cycles.',
  score: 0.83,
  url: 'https://example.com/report',
  page_title: 'Example Battery Report',
}

function message(overrides: Partial<WebsiteMessage>): WebsiteMessage {
  return {
    id: 'm',
    conversation_id: 'conv-1',
    seq: 1,
    role: 'assistant',
    content: '',
    status: 'COMPLETED',
    error: '',
    error_code: '',
    insufficient_evidence: false,
    citations: [],
    cited: [],
    output_language: 'en',
    metrics: {},
    created_at: '2026-10-08T10:01:00Z',
    completed_at: '2026-10-08T10:01:30Z',
    ...overrides,
  }
}

function conversation(overrides: Partial<WebsiteConversation> = {}): WebsiteConversation {
  return {
    id: 'conv-1',
    website_id: 'site-1',
    title: 'capacity?',
    output_language: 'en',
    created_at: '2026-10-08T10:01:00Z',
    updated_at: '2026-10-08T10:01:30Z',
    ...overrides,
  }
}

function capabilities(chat: Record<string, 'supported' | 'limited' | 'unsupported' | 'unvalidated'>): LanguageCapabilities {
  return {
    default_output_language: 'en',
    model: 'qwen3:4b',
    languages: ['en', 'ml', 'hi', 'es', 'fr', 'de'].map((code) => {
      const status = chat[code] ?? (code === 'en' ? 'supported' : 'unsupported')
      const supported = status === 'supported' || status === 'limited'
      return {
        code,
        english_name: code,
        native_name: code,
        model: code === 'hi' || code === 'de' ? 'gemma4:e4b' : 'qwen3:4b',
        status: supported ? (code === 'hi' || code === 'de' ? 'limited' : 'supported') : 'unsupported',
        supported,
        reason: '',
        features: { website_chat: { status, supported, reason: '' } },
      }
    }),
  }
}

const ANSWER = message({
  id: 'a1',
  seq: 2,
  content: 'The cell retained 91% capacity after 1,000 cycles [1].',
  citations: [CITATION],
  cited: [1],
})
const QUESTION = message({ id: 'q1', role: 'user', content: 'How much capacity remained?' })

interface Backend {
  site?: WebsiteSource
  conversations?: WebsiteConversation[]
  messages?: WebsiteMessage[]
  caps?: LanguageCapabilities
  createResponse?: { status?: number; body: unknown }
  /** Override the question POST (may hold the response with a promise). */
  onAsk?: (current: { messages: WebsiteMessage[] }, text: string) => MockSpec | Promise<MockSpec>
  onCancel?: (current: { messages: WebsiteMessage[] }, id: string) => MockSpec
}

type MockSpec = { status?: number; body?: unknown }

function backend(state: Backend = {}) {
  const current = {
    site: state.site ?? site(),
    conversations: state.conversations ?? [],
    messages: state.messages ?? [],
  }
  const mock = installFetchMock((url, init) => {
    const method = init?.method ?? 'GET'
    if (url === '/api/capabilities/languages') return { body: state.caps ?? capabilities({}) }
    if (url === '/api/websites' && method === 'GET') return { body: { websites: [current.site] } }
    if (url === '/api/websites' && method === 'POST') return state.createResponse ?? { status: 201, body: current.site }
    if (url === '/api/websites/site-1' && method === 'GET') return { body: current.site }
    if (url === '/api/websites/site-1' && method === 'DELETE') return { status: 204 }
    if (url === '/api/websites/site-1/refresh') {
      current.site = { ...current.site, metrics: { refresh_outcome: 'unchanged' } }
      return { body: current.site }
    }
    if (url === '/api/websites/site-1/conversations' && method === 'GET') {
      return { body: { conversations: current.conversations } }
    }
    if (url === '/api/websites/site-1/conversations' && method === 'POST') {
      const language = (requestBody(init) as { output_language: string }).output_language
      const created = conversation({ output_language: language, title: '' })
      current.conversations = [created]
      return { status: 201, body: { conversation: created, messages: [] } }
    }
    if (url === '/api/website-conversations/conv-1' && method === 'GET') {
      return { body: { conversation: current.conversations[0] ?? conversation(), messages: current.messages } }
    }
    if (url === '/api/website-conversations/conv-1/messages' && method === 'POST' && state.onAsk) {
      return state.onAsk(current, (requestBody(init) as { question: string }).question)
    }
    const cancel = url.match(/^\/api\/website-messages\/([^/]+)\/cancel$/)
    if (cancel && method === 'POST' && state.onCancel) return state.onCancel(current, cancel[1])
    if (url === '/api/website-conversations/conv-1/messages' && method === 'POST') {
      current.messages = [...current.messages, QUESTION, ANSWER]
      return { status: 202, body: { user: QUESTION, answer: ANSWER } }
    }
    return undefined
  })
  return { mock, current }
}

const detail = { route: '/websites/site-1', path: '/websites/:id' }

beforeAll(async () => {
  await Promise.all(['ml', 'hi', 'es', 'fr', 'de'].map((code) => loadMessages(code)))
})

beforeEach(() => {
  window.localStorage.clear()
  resetLanguageCapabilities()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Website Chat — ingestion', () => {
  it('shows the empty state with a labelled URL field', async () => {
    installFetchMock((url) => (url === '/api/websites' ? { body: { websites: [] } } : undefined))
    const { t } = await renderWithLocale(<WebsiteChatPage />, { route: '/websites', path: '/websites' })
    expect(screen.getByRole('heading', { level: 1, name: t('websiteChat.title') })).toBeInTheDocument()
    expect(screen.getByLabelText(t('websiteChat.urlLabel'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('websiteChat.process') })).toBeDisabled()
    expect(await screen.findByText(t('websiteChat.noPages'))).toBeInTheDocument()
  })

  it('submits the URL and opens the indexed page', async () => {
    const { mock } = backend({ site: site({ status: 'PENDING', is_indexed: false }) })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { route: '/websites', path: '/websites/*' })
    await userEvent.type(screen.getByLabelText(t('websiteChat.urlLabel')), 'https://example.com/report')
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.process') }))
    await waitFor(() => {
      const post = mock.mock.calls.find(([url, init]) => url === '/api/websites' && init?.method === 'POST')
      expect(requestBody(post?.[1])).toEqual({ url: 'https://example.com/report' })
    })
  })

  it('shows a translated, specific error for blocked addresses', async () => {
    backend({
      createResponse: { status: 422, body: { detail: 'blocked', code: 'blocked_address' } },
    })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { language: 'de', route: '/websites', path: '/websites' })
    await userEvent.type(screen.getByLabelText(t('websiteChat.urlLabel')), 'http://127.0.0.1/')
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.process') }))
    expect(await screen.findByRole('alert')).toHaveTextContent(t('websiteChat.errors.blocked_address'))
  })

  it('renders the real backend stage with completed and pending steps', async () => {
    backend({ site: site({ status: 'EMBEDDING', is_indexed: false, index_version: 0 }) })
    const { t } = await renderWithLocale(<WebsiteChatPage />, detail)
    const stages = await screen.findByRole('list', { name: t('websiteChat.stagesLabel') })
    const items = within(stages).getAllByRole('listitem')
    expect(items.map((item) => item.className)).toEqual([
      'website-stage done', 'website-stage done', 'website-stage done', 'website-stage current', 'website-stage pending',
    ])
    expect(items[3]).toHaveAttribute('aria-current', 'step')
    expect(screen.getByRole('status')).toHaveTextContent(t('websiteChat.stages.EMBEDDING'))
  })

  it('a failed PDF URL points to Documents', async () => {
    backend({ site: site({ status: 'FAILED', is_indexed: false, index_version: 0, error_code: 'pdf_content' }) })
    const { t } = await renderWithLocale(<WebsiteChatPage />, detail)
    expect(await screen.findByText(t('websiteChat.errors.pdf_content'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: t('websiteChat.goToDocuments') })).toHaveAttribute('href', '/documents')
  })

  it('shows metadata for a ready page', async () => {
    backend()
    const { t } = await renderWithLocale(<WebsiteChatPage />, detail)
    expect(await screen.findByRole('heading', { level: 1, name: 'Example Battery Report' })).toBeInTheDocument()
    const meta = screen.getByLabelText(t('websiteChat.metaLabel'))
    expect(meta).toHaveTextContent('1,234')
    expect(meta).toHaveTextContent('7')
    expect(meta).toHaveTextContent('example.com')
    expect(screen.getByRole('link', { name: /https:\/\/example\.com\/report/ })).toHaveAttribute(
      'href', 'https://example.com/report',
    )
  })
})

describe('Website Chat — conversation', () => {
  it('asks a question, renders the cited answer, and opens the exact passage', async () => {
    const { mock } = backend()
    const { t } = await renderWithLocale(<WebsiteChatPage />, detail)
    const composer = await screen.findByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' })
    await userEvent.type(composer, 'How much capacity remained?')
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.send') }))

    const created = mock.mock.calls.find(([url, init]) => url === '/api/websites/site-1/conversations' && init?.method === 'POST')
    expect(requestBody(created?.[1])).toEqual({ output_language: 'en' })
    const citation = await screen.findByRole('button', { name: t('report.viewSource', { index: '1' }) })
    expect(screen.getByText(/91% capacity after 1,000 cycles/, { selector: 'p' })).toBeInTheDocument()

    await userEvent.click(citation)
    const drawer = screen.getByRole('dialog', { name: t('websiteChat.drawer.label', { index: '1' }) })
    // Portalled to <body>: the page's isolated stacking context must not put
    // the sticky mobile top bar over the drawer header (live 390 px bug).
    expect(drawer.parentElement).toBe(document.body)
    expect(drawer.closest('.website-page')).toBeNull()
    expect(drawer).toHaveTextContent('Example Battery Report › Battery Life')
    expect(within(drawer).getByText(CITATION.text)).toHaveAttribute('lang', 'en')
    expect(within(drawer).getByRole('link', { name: t('websiteChat.openOriginal') })).toHaveAttribute(
      'href', 'https://example.com/report',
    )
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows insufficient evidence without citations', async () => {
    backend({
      conversations: [conversation()],
      messages: [
        QUESTION,
        message({ id: 'a2', seq: 2, insufficient_evidence: true, content: 'The indexed page does not provide enough information to answer this question.' }),
      ],
    })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: '/websites/site-1?c=conv-1' })
    expect(await screen.findByText(t('websiteChat.insufficient'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /\[\d\]/ })).toBeNull()
  })

  it('an existing Hindi conversation stays Hindi in an English UI', async () => {
    const { mock } = backend({
      conversations: [conversation({ output_language: 'hi' })],
      messages: [QUESTION, { ...ANSWER, output_language: 'hi', content: 'सेल ने 91% क्षमता बनाए रखी [1]।' }],
    })
    const { t, container } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: '/websites/site-1?c=conv-1' })
    expect(await screen.findByText(t('websiteChat.answersIn', { language: languageName('hi', 'en') }))).toBeInTheDocument()
    expect(container.querySelector('.website-answer')).toHaveAttribute('lang', 'hi')
    expect(document.documentElement.lang).toBe('en')
    await userEvent.type(screen.getByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' }), 'And temperature?')
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.send') }))
    await waitFor(() =>
      expect(mock.mock.calls.some(([url]) => url === '/api/website-conversations/conv-1/messages')).toBe(true),
    )
    // No new conversation, so no new language: the stored Hindi one is reused.
    expect(mock.mock.calls.some(([url, init]) => url === '/api/websites/site-1/conversations' && init?.method === 'POST')).toBe(false)
  })

  it('an unsupported language asks before starting an English conversation', async () => {
    const { mock } = backend({ caps: capabilities({}) })
    writePreference(makePreference('ml'))
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, language: 'ml' })
    expect(
      await screen.findByText(t('websiteChat.languageUnsupported', { preferred: languageName('ml', 'ml') })),
    ).toBeInTheDocument()
    const composer = screen.getByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' })
    await userEvent.type(composer, 'capacity?')
    expect(screen.getByRole('button', { name: t('websiteChat.send') })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.continueInEnglish') }))
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.send') }))
    await waitFor(() => {
      const created = mock.mock.calls.find(([url, init]) => url === '/api/websites/site-1/conversations' && init?.method === 'POST')
      expect(requestBody(created?.[1])).toEqual({ output_language: 'en' })
    })
    expect(JSON.parse(window.localStorage.getItem('atlas.language-preference') ?? '{}').defaultOutputLanguage).toBe('ml')
  })

  it('a LIMITED language says it is slower and is used directly', async () => {
    const { mock } = backend({ caps: capabilities({ hi: 'limited' }) })
    writePreference(makePreference('hi'))
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, language: 'hi' })
    expect(
      await screen.findByText(t('websiteChat.languageLimited', { language: languageName('hi', 'hi') })),
    ).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' }), 'क्षमता?')
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.send') }))
    await waitFor(() => {
      const created = mock.mock.calls.find(([url, init]) => url === '/api/websites/site-1/conversations' && init?.method === 'POST')
      expect(requestBody(created?.[1])).toEqual({ output_language: 'hi' })
    })
  })

  it('new conversation clears the thread without re-indexing', async () => {
    const { mock } = backend({ conversations: [conversation()], messages: [QUESTION, ANSWER] })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: '/websites/site-1?c=conv-1' })
    await screen.findByRole('button', { name: t('report.viewSource', { index: '1' }) })
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.newConversation') }))
    expect(await screen.findByText(t('websiteChat.emptyChat'))).toBeInTheDocument()
    expect(mock.mock.calls.some(([url]) => String(url).endsWith('/refresh'))).toBe(false)
    expect(mock.mock.calls.filter(([url, init]) => url === '/api/websites' && init?.method === 'POST')).toEqual([])
  })
})

describe('Website Chat — actions', () => {
  it('re-indexes and reports unchanged content', async () => {
    const { mock } = backend()
    const { t } = await renderWithLocale(<WebsiteChatPage />, detail)
    await userEvent.click(await screen.findByRole('button', { name: t('websiteChat.refresh') }))
    expect(await screen.findByText(t('websiteChat.refreshUnchanged'))).toBeInTheDocument()
    expect(mock.mock.calls.some(([url, init]) => url === '/api/websites/site-1/refresh' && init?.method === 'POST')).toBe(true)
  })

  it('deletes after confirmation', async () => {
    const { mock } = backend()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { t } = await renderWithLocale(<WebsiteChatPage />, detail)
    await userEvent.click(await screen.findByRole('button', { name: t('websiteChat.delete') }))
    await waitFor(() =>
      expect(mock.mock.calls.some(([url, init]) => url === '/api/websites/site-1' && init?.method === 'DELETE')).toBe(true),
    )
  })

  it('never renders a non-http URL as a link', async () => {
    backend({ site: site({ final_url: 'javascript:alert(1)', normalized_url: 'javascript:alert(1)' }) })
    await renderWithLocale(<WebsiteChatPage />, detail)
    await screen.findByRole('heading', { level: 1, name: 'Example Battery Report' })
    expect(document.querySelector('a[href^="javascript"]')).toBeNull()
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

const secondsAgo = (s: number) => new Date(Date.now() - s * 1000).toISOString()
const POLL = { timeout: 5000 }
const inThread = '/websites/site-1?c=conv-1'
const isAsk = ([url, init]: [string, RequestInit?]) => url.endsWith('/messages') && init?.method === 'POST'

describe('Website Chat — answering state', () => {
  it('shows the question and an answering card at once, then the real stage, then the answer', async () => {
    const gate = deferred<void>()
    const asked = message({ id: 'q9', seq: 1, role: 'user', content: 'What was the efficiency in 2009?' })
    const running = message({
      id: 'a9', seq: 2, status: 'PENDING', stage: 'RETRIEVING', created_at: secondsAgo(0), completed_at: null,
    })
    const { mock, current } = backend({
      onAsk: async (state) => {
        await gate.promise
        state.messages = [asked, running]
        return { status: 202, body: { user: asked, answer: running } }
      },
    })
    const { t } = await renderWithLocale(<WebsiteChatPage />, detail)
    const composer = await screen.findByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' })
    await userEvent.type(composer, 'What was the efficiency in 2009?')
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.send') }))

    // Before the server has replied: question, answering card, timer, busy composer.
    expect(screen.getByText('What was the efficiency in 2009?', { selector: 'p' })).toBeInTheDocument()
    const card = screen.getByRole('status')
    expect(card).toHaveTextContent(t('websiteChat.answering.finding'))
    expect(card).toHaveTextContent(t('websiteChat.answering.sending'))
    expect(card).toHaveTextContent(/00:0\d/)
    expect(composer).toBeDisabled()
    expect(screen.getByRole('button', { name: t('websiteChat.send') })).toBeDisabled()
    expect(screen.getByText(t('websiteChat.answering.busyComposer'))).toBeInTheDocument()

    gate.resolve()
    expect(await screen.findByText(t('websiteChat.answering.RETRIEVING'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('websiteChat.answering.cancel') })).toBeInTheDocument()
    // One copy of the question: the optimistic one was replaced by the stored one.
    expect(screen.getAllByText('What was the efficiency in 2009?', { selector: 'p' })).toHaveLength(1)

    current.messages = [asked, { ...running, stage: 'GENERATING' }]
    expect(await screen.findByText(t('websiteChat.answering.GENERATING'), {}, POLL)).toBeInTheDocument()

    current.messages = [
      asked,
      message({
        id: 'a9', seq: 2, content: 'Perovskites reached 3.8% efficiency in 2009 [1].', citations: [CITATION], cited: [1],
      }),
    ]
    const citation = await screen.findByRole('button', { name: t('report.viewSource', { index: '1' }) }, POLL)
    expect(screen.queryByRole('status')).toBeNull()
    expect(composer).toBeEnabled()
    await userEvent.click(citation)
    expect(screen.getByRole('dialog')).toHaveTextContent(CITATION.text)
    expect(mock.mock.calls.filter((call) => isAsk(call as [string, RequestInit?]))).toHaveLength(1)
  })

  it('prevents a second question while one is being answered', async () => {
    const running = message({
      id: 'a1', seq: 2, status: 'PENDING', stage: 'GENERATING', created_at: secondsAgo(5), completed_at: null,
    })
    const { mock } = backend({ conversations: [conversation()], messages: [QUESTION, running] })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: inThread })
    await screen.findByText(t('websiteChat.answering.GENERATING'))
    const composer = screen.getByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' })
    expect(composer).toBeDisabled()
    expect(screen.getByRole('button', { name: t('websiteChat.send') })).toBeDisabled()
    expect(screen.getByText(t('websiteChat.answering.busyComposer'))).toBeInTheDocument()
    await userEvent.type(composer, 'What is a perovskite solar cell?{Enter}')
    expect(mock.mock.calls.some((call) => isAsk(call as [string, RequestInit?]))).toBe(false)
    expect(screen.queryByText(t('websiteChat.errors.busy'))).toBeNull()
  })

  it('a running answer survives a page refresh with its stage and elapsed time', async () => {
    const running = message({
      id: 'a1', seq: 2, status: 'PENDING', stage: 'GENERATING', created_at: secondsAgo(75), completed_at: null,
    })
    backend({ conversations: [conversation()], messages: [QUESTION, running] })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: inThread })
    expect(await screen.findByText(QUESTION.content, { selector: 'p' })).toBeInTheDocument()
    const card = await screen.findByRole('status')
    expect(card).toHaveTextContent(t('websiteChat.answering.GENERATING'))
    expect(card).toHaveTextContent(/01:1[5-9]/)
  })

  it('an answer interrupted by a server restart says so and keeps the question', async () => {
    const failed = message({ id: 'a1', seq: 2, status: 'FAILED', error_code: 'interrupted' })
    backend({ conversations: [conversation()], messages: [QUESTION, failed] })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: inThread })
    expect(await screen.findByText(t('websiteChat.answering.interrupted'))).toBeInTheDocument()
    expect(screen.getByText(QUESTION.content, { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('websiteChat.answering.tryAgain') })).toBeInTheDocument()
  })

  it('Cancel stops the answer, keeps the question and re-enables the composer', async () => {
    const running = message({
      id: 'a1', seq: 2, status: 'PENDING', stage: 'GENERATING', created_at: secondsAgo(10), completed_at: null,
    })
    const { mock } = backend({
      conversations: [conversation()],
      messages: [QUESTION, running],
      onCancel: (state, id) => {
        state.messages = [QUESTION, { ...running, id, status: 'CANCELLED', error_code: 'cancelled', stage: '' }]
        return { body: running }
      },
    })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: inThread })
    await userEvent.click(await screen.findByRole('button', { name: t('websiteChat.answering.cancel') }))
    expect(
      mock.mock.calls.some(([url, init]) => url === '/api/website-messages/a1/cancel' && init?.method === 'POST'),
    ).toBe(true)
    expect(await screen.findByText(t('websiteChat.answering.cancelled'))).toBeInTheDocument()
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByText(QUESTION.content, { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' })).toBeEnabled()
  })

  it('a failed answer keeps the question with the reason and a working Try again', async () => {
    const failed = message({ id: 'a1', seq: 2, status: 'FAILED', error_code: 'answer_timeout' })
    const retried = message({ id: 'a2', seq: 4, status: 'PENDING', created_at: secondsAgo(0), completed_at: null })
    const { mock } = backend({
      conversations: [conversation()],
      messages: [QUESTION, failed],
      onAsk: (state, text) => {
        const again = message({ id: 'q2', seq: 3, role: 'user', content: text })
        state.messages = [...state.messages, again, retried]
        return { status: 202, body: { user: again, answer: retried } }
      },
    })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: inThread })
    expect(await screen.findByText(t('websiteChat.answering.failed'))).toBeInTheDocument()
    expect(screen.getByText(t('websiteChat.errors.answer_timeout'))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: t('websiteChat.answering.tryAgain') }))
    const posted = mock.mock.calls.find((call) => isAsk(call as [string, RequestInit?]))
    expect(requestBody(posted?.[1])).toEqual({ question: QUESTION.content })
    expect(await screen.findByRole('status')).toHaveTextContent(t('websiteChat.answering.finding'))
  })

  it('a question that could not be sent stays visible with an inline error', async () => {
    backend({
      conversations: [conversation()],
      messages: [],
      onAsk: () => ({ status: 409, body: { detail: 'busy', code: 'busy' } }),
    })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, route: inThread })
    const composer = await screen.findByLabelText(t('websiteChat.composerLabel'), { selector: 'textarea' })
    await userEvent.type(composer, 'Where was it made?{Enter}')
    expect(await screen.findByText(t('websiteChat.answering.failed'))).toBeInTheDocument()
    expect(screen.getByText('Where was it made?', { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('websiteChat.answering.tryAgain') })).toBeInTheDocument()
    expect(composer).toBeEnabled()
  })

  it.each(['hi', 'de', 'ml'])('the answering state is translated (%s UI)', async (language) => {
    const running = message({
      id: 'a1', seq: 2, status: 'PENDING', stage: 'VALIDATING', created_at: secondsAgo(3), completed_at: null,
    })
    backend({ conversations: [conversation()], messages: [QUESTION, running] })
    const { t } = await renderWithLocale(<WebsiteChatPage />, { ...detail, language, route: inThread })
    const card = await screen.findByRole('status')
    expect(card).toHaveTextContent(t('websiteChat.answering.finding'))
    expect(card).toHaveTextContent(t('websiteChat.answering.VALIDATING'))
    expect(t('websiteChat.answering.finding')).not.toBe(en.websiteChat.answering.finding)
  })
})

describe('formatElapsed', () => {
  it.each([
    [7_000, '00:07'],
    [48_000, '00:48'],
    [134_000, '02:14'],
    [303_000, '05:03'],
    [3_725_000, '1:02:05'],
    [-500, '00:00'],
  ])('%i ms is %s', (ms, text) => {
    expect(formatElapsed(ms)).toBe(text)
  })
})
