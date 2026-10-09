import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError, api, errorMessage } from '../api/client'
import { CitedMarkdown } from '../components/CitedReport'
import {
  ArrowLeftIcon,
  ArrowUpIcon,
  CheckIcon,
  ExternalIcon,
  GlobeIcon,
  LinkIcon,
  PlusIcon,
  RefreshIcon,
  ShieldCheckIcon,
  SparkleIcon,
  TrashIcon,
  XIcon,
} from '../components/icons'
import { EyebrowPill, FeaturePill } from '../components/PageHero'
import { WebsiteEvidenceDrawer } from '../components/WebsiteEvidenceDrawer'
import { agoLabel, artifactLang, languageName, useI18n, useOutputLanguage, type Translate } from '../i18n'
import type {
  Source,
  WebsiteAnswerStage,
  WebsiteCitation,
  WebsiteConversation,
  WebsiteMessage,
  WebsiteSource,
  WebsiteStatus,
} from '../types'
import { safeHttpUrl } from '../utils/safeUrl'

const SITE_POLL_MS = 1000
const ANSWER_POLL_MS = 1500

export const STAGES = ['FETCHING', 'EXTRACTING', 'CHUNKING', 'EMBEDDING', 'READY'] as const
const ACTIVE: WebsiteStatus[] = ['PENDING', 'FETCHING', 'EXTRACTING', 'CHUNKING', 'EMBEDDING']

const ERROR_CODES = [
  'invalid_url',
  'unsupported_scheme',
  'credentials_in_url',
  'blocked_address',
  'dns_failure',
  'redirect_blocked',
  'too_many_redirects',
  'timeout',
  'connection_failed',
  'too_large',
  'pdf_content',
  'unsupported_content',
  'http_error',
  'access_restricted',
  'empty_content',
  'js_required',
  'too_long',
  'embedding_failed',
  'llm_failed',
  'unusable_answer',
  'interrupted',
  'cancelled',
  'answer_timeout',
  'processing_failed',
  'not_ready',
  'busy',
  'empty_question',
  'question_too_long',
  'not_found',
] as const
type WebsiteErrorCode = (typeof ERROR_CODES)[number] | 'unknown'

/** A page's declared language named in the UI locale; the raw tag if unknown. */
function pageLanguageName(code: string, uiLocale: string): string {
  try {
    return new Intl.DisplayNames([uiLocale], { type: 'language' }).of(code) || code
  } catch {
    return code
  }
}

function isActive(status: WebsiteStatus): boolean {
  return ACTIVE.includes(status)
}

/** A backend error code in the UI language (never a raw stack trace). */
export function websiteErrorText(t: Translate, code: string | undefined): string {
  const known = (ERROR_CODES as readonly string[]).includes(code ?? '')
  const key: WebsiteErrorCode = known ? (code as WebsiteErrorCode) : 'unknown'
  return t(`websiteChat.errors.${key}`)
}

function errorFrom(t: Translate, error: unknown): string {
  if (error instanceof ApiError && error.code) return websiteErrorText(t, error.code)
  return errorMessage(error)
}

const FEATURES = [
  {
    icon: SparkleIcon,
    label: 'websiteChat.features.grounded',
    detail: 'websiteChat.features.groundedDetail',
  },
  {
    icon: ShieldCheckIcon,
    label: 'websiteChat.features.secure',
    detail: 'websiteChat.features.secureDetail',
  },
  {
    icon: GlobeIcon,
    label: 'websiteChat.features.private',
    detail: 'websiteChat.features.privateDetail',
  },
] as const

export function WebsiteChatPage() {
  const { id } = useParams<{ id: string }>()
  return id ? <WebsiteDetail key={id} websiteId={id} /> : <WebsiteHome />
}

// --- home: hero, URL form, indexed pages ----------------------------------------

function WebsiteHome() {
  const { t, format } = useI18n()
  const navigate = useNavigate()
  const [websites, setWebsites] = useState<WebsiteSource[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api
      .listWebsites()
      .then((body) => active && setWebsites(body.websites))
      .catch((err) => active && setListError(errorFrom(t, err)))
    return () => {
      active = false
    }
  }, [t])

  return (
    <div className="website-page">
      <header className="page-hero website-hero">
        <div className="page-hero-copy">
          <div className="page-hero-eyebrow">
            <EyebrowPill icon={GlobeIcon} uppercase>
              {t('websiteChat.eyebrow')}
            </EyebrowPill>
          </div>
          <h1 className="display-title">{t('websiteChat.title')}</h1>
          <p className="page-hero-subtitle">{t('websiteChat.subtitle')}</p>
          <ul className="feature-pill-row" aria-label={t('websiteChat.featuresLabel')}>
            {FEATURES.map(({ icon, label, detail }) => (
              <li key={label}>
                <FeaturePill icon={icon} label={t(label)} detail={t(detail)} variant="square" />
              </li>
            ))}
          </ul>
        </div>
      </header>

      <UrlForm
        onIndexed={(site) =>
          navigate(`/websites/${site.id}`, {
            state: { existing: !!site.existing },
          })
        }
      />

      <section className="website-list-section" aria-labelledby="website-list-heading">
        <h2 id="website-list-heading" className="section-heading">
          {t('websiteChat.indexedPages')}
        </h2>
        {listError && <p className="error-text">{listError}</p>}
        {websites === null && !listError && (
          <p className="hint-text" role="status">
            <span className="spinner small" aria-hidden="true" /> {t('websiteChat.loading')}
          </p>
        )}
        {websites !== null && websites.length === 0 && <p className="empty-note">{t('websiteChat.noPages')}</p>}
        {websites !== null && websites.length > 0 && (
          <ul className="website-list">
            {websites.map((site) => (
              <li key={site.id}>
                <Link to={`/websites/${site.id}`} className="website-card glass-card">
                  <span className="website-card-icon" aria-hidden="true">
                    <GlobeIcon size={18} />
                  </span>
                  <span className="website-card-body">
                    <span className="website-card-title">{site.page_title || site.domain}</span>
                    <span className="website-card-url">{site.final_url || site.normalized_url}</span>
                  </span>
                  <span className={`badge website-status status-${site.status.toLowerCase()}`}>
                    {site.status === 'READY' || site.is_indexed
                      ? t('websiteChat.stages.READY')
                      : isActive(site.status)
                        ? t('websiteChat.processing')
                        : site.status === 'CANCELLED'
                          ? t('websiteChat.errors.cancelled')
                          : t('websiteChat.failedTitle')}
                  </span>
                  <span className="history-meta">{agoLabel(t, format, site.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function UrlForm({ onIndexed }: { onIndexed: (site: WebsiteSource) => void }) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorCode, setErrorCode] = useState('')
  const inputId = useId()
  const errorId = useId()

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!url.trim() || busy) return
    setBusy(true)
    setError(null)
    setErrorCode('')
    try {
      onIndexed(await api.createWebsite(url.trim()))
    } catch (err) {
      setError(errorFrom(t, err))
      setErrorCode(err instanceof ApiError ? err.code : '')
      setBusy(false)
    }
  }

  return (
    <form className="website-url-form glass-card" onSubmit={submit} aria-label={t('websiteChat.title')}>
      <label htmlFor={inputId} className="website-url-label">
        {t('websiteChat.urlLabel')}
      </label>
      <div className="website-url-row">
        <span className="website-url-input-wrap">
          <LinkIcon size={17} className="website-url-icon" />
          <input
            id={inputId}
            type="url"
            inputMode="url"
            autoComplete="url"
            spellCheck={false}
            className="website-url-input"
            placeholder={t('websiteChat.urlPlaceholder')}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            disabled={busy}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
          />
        </span>
        <button type="submit" className="btn primary glow" disabled={!url.trim() || busy}>
          <span>{busy ? t('websiteChat.processing') : t('websiteChat.process')}</span>
        </button>
      </div>
      <p className="website-scope-note">{t('websiteChat.scopeNote')}</p>
      {error && (
        <p id={errorId} className="form-error" role="alert">
          {error}
          {errorCode === 'pdf_content' && (
            <>
              {' '}
              <Link to="/documents">{t('websiteChat.goToDocuments')}</Link>
            </>
          )}
        </p>
      )}
    </form>
  )
}

// --- detail: progress, metadata, chat ---------------------------------------------

function StageProgress({ status }: { status: WebsiteStatus }) {
  const { t } = useI18n()
  const current = status === 'PENDING' ? -1 : STAGES.indexOf(status as (typeof STAGES)[number])
  const label = current >= 0 ? t(`websiteChat.stages.${STAGES[current]}`) : t('websiteChat.queued')
  return (
    <div className="website-progress">
      <ol className="website-stages" aria-label={t('websiteChat.stagesLabel')}>
        {STAGES.map((stage, index) => {
          const state = index < current ? 'done' : index === current ? 'current' : 'pending'
          return (
            <li
              key={stage}
              className={`website-stage ${state}`}
              aria-current={state === 'current' ? 'step' : undefined}
            >
              <span className="website-stage-dot" aria-hidden="true">
                {state === 'done' ? <CheckIcon size={12} /> : index + 1}
              </span>
              <span className="website-stage-label">{t(`websiteChat.stages.${stage}`)}</span>
              <span className="visually-hidden">{t(`websiteChat.stageState.${state}`)}</span>
            </li>
          )
        })}
      </ol>
      <p className="website-progress-now" role="status" aria-live="polite">
        {current >= 0 ? t('websiteChat.nowStage', { stage: label }) : label}
      </p>
    </div>
  )
}

function useWebsite(websiteId: string) {
  const [site, setSite] = useState<WebsiteSource | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(async () => {
    try {
      setSite(await api.getWebsite(websiteId))
      setError(null)
    } catch (err) {
      setError(err)
    }
  }, [websiteId])
  useEffect(() => {
    void load()
  }, [load])
  const active = site ? isActive(site.status) : false
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => void load(), SITE_POLL_MS)
    return () => window.clearInterval(timer)
  }, [active, load])
  return { site, error, reload: load, setSite }
}

function WebsiteDetail({ websiteId }: { websiteId: string }) {
  const { t, format, language: ui } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const { site, error, reload, setSite } = useWebsite(websiteId)
  const [actionError, setActionError] = useState<string | null>(null)
  const [refreshNote, setRefreshNote] = useState<'requested' | null>(null)
  const existingNote = (location.state as { existing?: boolean } | null)?.existing === true

  if (error && !site) {
    return (
      <div className="website-page">
        <BackLink />
        <p className="error-text" role="alert">
          {errorFrom(t, error)}
        </p>
      </div>
    )
  }
  if (!site) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('websiteChat.loading')}</p>
      </div>
    )
  }

  const active = isActive(site.status)
  const outcome = site.metrics?.refresh_outcome as string | undefined
  const finalUrl = safeHttpUrl(site.final_url || site.normalized_url)

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null)
    try {
      await fn()
      await reload()
    } catch (err) {
      setActionError(errorFrom(t, err))
    }
  }
  const remove = () => {
    if (
      !window.confirm(
        t('websiteChat.confirmDelete', {
          title: site.page_title || site.domain,
        }),
      )
    )
      return
    void act(async () => {
      await api.deleteWebsite(site.id)
      navigate('/websites')
    })
  }

  return (
    <div className="website-page website-detail">
      <BackLink />
      <header className="website-header glass-card">
        <div className="website-header-main">
          <span className="website-card-icon" aria-hidden="true">
            <GlobeIcon size={20} />
          </span>
          <div className="website-header-text">
            <h1 className="website-title" lang={site.content_language || undefined}>
              {site.page_title || site.domain}
            </h1>
            {finalUrl ? (
              <a className="website-url" href={finalUrl} target="_blank" rel="noopener noreferrer">
                {site.final_url || site.normalized_url}
                <ExternalIcon size={12} />
              </a>
            ) : (
              <span className="website-url">{site.normalized_url}</span>
            )}
          </div>
        </div>
        <div className="website-actions">
          {site.is_indexed && !active && (
            <button
              type="button"
              className="btn light compact"
              onClick={() => {
                setRefreshNote('requested')
                void act(async () => setSite(await api.refreshWebsite(site.id)))
              }}
            >
              <RefreshIcon size={14} />
              <span>{t('websiteChat.refresh')}</span>
            </button>
          )}
          {active && (
            <button
              type="button"
              className="btn light compact"
              onClick={() => void act(() => api.cancelWebsite(site.id))}
            >
              <XIcon size={14} />
              <span>{t('websiteChat.cancel')}</span>
            </button>
          )}
          <button type="button" className="btn danger-ghost compact" onClick={remove}>
            <TrashIcon size={14} />
            <span>{t('websiteChat.delete')}</span>
          </button>
        </div>
      </header>

      {existingNote && site.is_indexed && <p className="website-notice">{t('websiteChat.existing')}</p>}
      {actionError && (
        <p className="form-error" role="alert">
          {actionError}
        </p>
      )}

      {active && <StageProgress status={site.status} />}

      {!active && refreshNote && site.is_indexed && (
        <p className="website-notice" role="status">
          {site.error_code
            ? `${t('websiteChat.refreshFailed')} ${websiteErrorText(t, site.error_code)}`
            : outcome === 'unchanged'
              ? t('websiteChat.refreshUnchanged')
              : t('websiteChat.refreshChanged')}
        </p>
      )}

      {!active && !site.is_indexed && (
        <section className="website-failed glass-card" role="alert">
          <h2 className="website-failed-title">
            {site.status === 'CANCELLED' ? t('websiteChat.cancelledTitle') : t('websiteChat.failedTitle')}
          </h2>
          <p>{websiteErrorText(t, site.error_code)}</p>
          <div className="website-actions">
            {site.error_code === 'pdf_content' && (
              <Link to="/documents" className="btn light compact">
                {t('websiteChat.goToDocuments')}
              </Link>
            )}
            <button
              type="button"
              className="btn primary compact"
              onClick={() => void act(async () => setSite(await api.createWebsite(site.submitted_url)))}
            >
              <RefreshIcon size={14} />
              <span>{t('websiteChat.retry')}</span>
            </button>
          </div>
        </section>
      )}

      {site.is_indexed && (
        <>
          <dl className="website-meta" aria-label={t('websiteChat.metaLabel')}>
            <div>
              <dt>{t('websiteChat.meta.domain')}</dt>
              <dd>{site.domain}</dd>
            </div>
            <div>
              <dt>{t('websiteChat.meta.indexed')}</dt>
              <dd>{site.indexed_at ? format.dateTime(site.indexed_at) : '—'}</dd>
            </div>
            <div>
              <dt>{t('websiteChat.meta.words')}</dt>
              <dd>{format.number(site.word_count)}</dd>
            </div>
            <div>
              <dt>{t('websiteChat.meta.chunks')}</dt>
              <dd>{format.number(site.chunk_count)}</dd>
            </div>
            {site.content_language && (
              <div>
                <dt>{t('websiteChat.meta.language')}</dt>
                <dd>{pageLanguageName(site.content_language, ui.locale)}</dd>
              </div>
            )}
          </dl>
          <WebsiteChat site={site} />
        </>
      )}
    </div>
  )
}

function BackLink() {
  const { t } = useI18n()
  return (
    <Link to="/websites" className="back-link">
      <ArrowLeftIcon size={14} />
      <span>{t('websiteChat.allPages')}</span>
    </Link>
  )
}

// --- chat ----------------------------------------------------------------------------

function citationSources(message: WebsiteMessage, site: WebsiteSource): Source[] {
  return message.citations.map((citation) => ({
    index: citation.index,
    title: citation.section_title || citation.page_title || site.page_title,
    url: citation.url,
    domain: site.domain,
    kind: 'web' as const,
    filename: null,
    page: null,
  }))
}

/** "mm:ss" (or "h:mm:ss") since the answer started: elapsed time, never an estimate. */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const sec = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${String(m).padStart(2, '0')}:${sec}`
}

function ElapsedTimer({ since }: { since: number }) {
  const { t } = useI18n()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  // The ticking value is not announced every second (the status line is).
  return (
    <span className="website-answering-timer" aria-live="off">
      {t('websiteChat.answering.elapsed', { time: formatElapsed(now - since) })}
    </span>
  )
}

/** The temporary Atlas reply while an answer is written: real stage, elapsed time, Cancel. */
function AnsweringCard({
  stage,
  since,
  sending = false,
  cancelling = false,
  onCancel,
}: {
  stage: WebsiteAnswerStage
  since: number
  sending?: boolean
  cancelling?: boolean
  onCancel?: () => void
}) {
  const { t } = useI18n()
  const step = sending ? t('websiteChat.answering.sending') : stage ? t(`websiteChat.answering.${stage}`) : null
  return (
    <div className="website-answering" role="status">
      <span className="spinner small" aria-hidden="true" />
      <div className="website-answering-text">
        <p className="website-answering-title">{t('websiteChat.answering.finding')}</p>
        {step && <p className="website-answering-stage">{step}</p>}
        <ElapsedTimer since={since} />
      </div>
      {onCancel && (
        <button type="button" className="btn light compact" onClick={onCancel} disabled={cancelling}>
          <XIcon size={13} />
          <span>{cancelling ? t('websiteChat.answering.cancelling') : t('websiteChat.answering.cancel')}</span>
        </button>
      )}
    </div>
  )
}

/** An answer that could not be completed: the question stays, with a reason and a retry. */
function AnswerProblem({ title, detail, onRetry }: { title: string; detail: string | null; onRetry?: () => void }) {
  const { t } = useI18n()
  return (
    <div className="website-answer-problem" role="alert">
      <p className="website-answer-problem-title">{title}</p>
      {detail && <p className="website-answer-problem-detail">{detail}</p>}
      {onRetry && (
        <button type="button" className="btn light compact" onClick={onRetry}>
          <RefreshIcon size={13} />
          <span>{t('websiteChat.answering.tryAgain')}</span>
        </button>
      )}
    </div>
  )
}

function useConversation(conversationId: string | null) {
  const [messages, setMessages] = useState<WebsiteMessage[]>([])
  const [conversation, setConversation] = useState<WebsiteConversation | null>(null)
  const [error, setError] = useState<unknown>(null)
  // Only the newest request may update the thread: a fetch issued before a
  // question was posted must never overwrite the thread that includes it.
  const latest = useRef(0)
  const current = useRef(conversationId)
  current.current = conversationId
  const load = useCallback(async (id: string | null = current.current) => {
    const ticket = ++latest.current
    if (!id) {
      setMessages([])
      setConversation(null)
      return
    }
    try {
      const detail = await api.getWebsiteConversation(id)
      if (ticket !== latest.current || id !== current.current) return
      setConversation(detail.conversation)
      setMessages(detail.messages)
      setError(null)
    } catch (err) {
      if (ticket === latest.current) setError(err)
    }
  }, [])
  useEffect(() => {
    void load(conversationId)
  }, [conversationId, load])
  /** Show messages the server just returned, without waiting for the next poll. */
  const merge = useCallback((incoming: WebsiteMessage[]) => {
    latest.current += 1 // an in-flight older fetch must not undo this
    setMessages((previous) => {
      const byId = new Map(previous.map((message) => [message.id, message]))
      for (const message of incoming) byId.set(message.id, message)
      return [...byId.values()].sort((x, y) => x.seq - y.seq)
    })
  }, [])
  const pending = messages.some((message) => message.status === 'PENDING')
  useEffect(() => {
    if (!pending) return
    const timer = window.setInterval(() => void load(), ANSWER_POLL_MS)
    return () => window.clearInterval(timer)
  }, [pending, load])
  return { conversation, messages, error, reload: load, merge, pending }
}

function WebsiteChat({ site }: { site: WebsiteSource }) {
  const { t, format, language: ui } = useI18n()
  const [searchParams, setSearchParams] = useSearchParams()
  const [conversations, setConversations] = useState<WebsiteConversation[]>([])
  const conversationId = searchParams.get('c')
  const { conversation, messages, error, reload, merge, pending } = useConversation(conversationId)
  const output = useOutputLanguage('website_chat')
  const [englishChosenFor, setEnglishChosenFor] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  // The question the user just sent, shown at once (before any server round
  // trip) and kept visible with an inline error if sending fails.
  const [submitted, setSubmitted] = useState<{ text: string; at: number; error: string | null } | null>(null)
  const [cancelling, setCancelling] = useState<string | null>(null)
  const [openCitation, setOpenCitation] = useState<WebsiteCitation | null>(null)
  const composerId = useId()
  const threadEnd = useRef<HTMLDivElement>(null)
  const nameOf = (code: string) => languageName(code, ui.locale)

  const loadConversations = useCallback(async () => {
    try {
      const body = await api.listWebsiteConversations(site.id)
      setConversations(body.conversations)
      return body.conversations
    } catch {
      return []
    }
  }, [site.id])

  useEffect(() => {
    void loadConversations().then((list) => {
      if (!searchParams.get('c') && list.length > 0) {
        setSearchParams({ c: list[0].id }, { replace: true })
      }
    })
    // Only on mount / site change: later selection is the user's.
  }, [loadConversations])

  useEffect(() => {
    threadEnd.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length, pending, submitted])

  // A new conversation is written in the effective language; an unsupported
  // preference needs an explicit choice first. An existing conversation keeps
  // its own language whatever the UI language is now.
  const needsChoice = !conversation && output.fellBack && !output.loading
  const englishChosen = englishChosenFor === output.preferred
  const languageReady =
    conversation !== null || output.preferred === 'en' || (!output.loading && (!needsChoice || englishChosen))
  const answerLanguage = conversation?.output_language ?? output.effective
  const limited = conversation
    ? conversation.output_language === output.effective && output.limited
    : output.limited && !output.fellBack

  const startNew = () => {
    setSearchParams({}, { replace: false })
    setOpenCitation(null)
    setSendError(null)
    setSubmitted(null)
  }

  // One answer at a time: while one is being written (or the question is
  // still being sent) the composer stays visible but disabled.
  const answering = pending || sending || (submitted !== null && submitted.error === null)

  useEffect(() => {
    if (cancelling && !messages.some((m) => m.id === cancelling && m.status === 'PENDING')) setCancelling(null)
  }, [cancelling, messages])

  const submit = async (text: string) => {
    if (!text || answering || !languageReady) return
    setSubmitted({ text, at: Date.now(), error: null })
    setQuestion('')
    setSending(true)
    setSendError(null)
    try {
      let id = conversationId
      if (!id) {
        const created = await api.createWebsiteConversation(site.id, output.effective)
        id = created.conversation.id
        setSearchParams({ c: id }, { replace: false })
      }
      const posted = await api.askWebsite(id, text)
      // Render the stored question and its PENDING answer right away; polling
      // takes over from here (it starts because the answer is PENDING).
      merge([posted.user, posted.answer])
      setSubmitted(null)
      void loadConversations()
    } catch (err) {
      setSubmitted({ text, at: Date.now(), error: errorFrom(t, err) })
    } finally {
      setSending(false)
    }
  }

  const send = (event: React.FormEvent) => {
    event.preventDefault()
    void submit(question.trim())
  }

  const deleteConversation = async (target: WebsiteConversation) => {
    if (!window.confirm(t('websiteChat.confirmDeleteConversation'))) return
    try {
      await api.deleteWebsiteConversation(target.id)
      if (target.id === conversationId) startNew()
      void loadConversations()
    } catch (err) {
      setSendError(errorFrom(t, err))
    }
  }

  const cancelAnswer = async (message: WebsiteMessage) => {
    setCancelling(message.id)
    try {
      await api.cancelWebsiteMessage(message.id)
    } catch {
      // already finished: the reload below shows how
    }
    await reload()
  }

  /** The question an assistant message answered (for "Try again"). */
  const questionFor = (answer: WebsiteMessage) =>
    [...messages].reverse().find((m) => m.role === 'user' && m.seq < answer.seq)?.content ?? ''
  const lastId = messages.at(-1)?.id


  const conversationList = conversations.map((item) => (
    <li key={item.id} className={`website-conversation${item.id === conversationId ? ' selected' : ''}`}>
      <button
        type="button"
        className="website-conversation-button"
        aria-current={item.id === conversationId ? 'true' : undefined}
        onClick={() => setSearchParams({ c: item.id })}
      >
        <span className="website-conversation-title">{item.title || t('websiteChat.untitled')}</span>
        <span className="history-meta">
          {nameOf(item.output_language)} · {agoLabel(t, format, item.updated_at)}
        </span>
      </button>
      <button
        type="button"
        className="icon-btn danger"
        aria-label={t('websiteChat.deleteConversation')}
        onClick={() => void deleteConversation(item)}
      >
        <TrashIcon size={14} />
      </button>
    </li>
  ))

  return (
    <div className="website-chat-layout">
      <aside className="website-conversations glass-card" aria-label={t('websiteChat.conversations')}>
        <div className="website-conversations-head">
          <h2 className="panel-heading">{t('websiteChat.conversations')}</h2>
          <button type="button" className="btn light compact" onClick={startNew}>
            <PlusIcon size={14} />
            <span>{t('websiteChat.newConversation')}</span>
          </button>
        </div>
        {conversations.length > 0 && <ul className="website-conversation-list">{conversationList}</ul>}
      </aside>

      <section className="website-chat glass-card" aria-label={t('websiteChat.composerLabel')}>
        <p className="website-chat-language">
          <GlobeIcon size={13} className="output-language-icon" />
          <span>{t('websiteChat.answersIn', { language: nameOf(answerLanguage) })}</span>
        </p>
        {limited && (
          <p className="output-language-hint">
            {t('websiteChat.languageLimited', {
              language: nameOf(answerLanguage),
            })}
          </p>
        )}
        {needsChoice && (
          <div className="output-language-fallback website-language-choice" role="note">
            <p>
              {t('websiteChat.languageUnsupported', {
                preferred: nameOf(output.preferred),
              })}
            </p>
            {englishChosen ? (
              <p className="output-language-chosen">{t('websiteChat.continuingInEnglish')}</p>
            ) : (
              <button type="button" className="btn light compact" onClick={() => setEnglishChosenFor(output.preferred)}>
                {t('websiteChat.continueInEnglish')}
              </button>
            )}
          </div>
        )}

        <div className="website-thread" aria-live="polite">
          {error ? <p className="error-text">{errorFrom(t, error)}</p> : null}
          {messages.length === 0 && !submitted && !error && <p className="empty-note">{t('websiteChat.emptyChat')}</p>}
          {messages.map((message) =>
            message.role === 'user' ? (
              <article key={message.id} className="website-message user">
                <span className="website-message-author">{t('websiteChat.you')}</span>
                <p className="website-message-text">{message.content}</p>
              </article>
            ) : (
              <article
                key={message.id}
                className={`website-message assistant${message.insufficient_evidence ? ' insufficient' : ''}`}
              >
                <span className="website-message-author">{t('websiteChat.atlas')}</span>
                {message.status === 'PENDING' && (
                  <AnsweringCard
                    stage={message.stage ?? ''}
                    since={Date.parse(message.created_at)}
                    cancelling={cancelling === message.id}
                    onCancel={() => void cancelAnswer(message)}
                  />
                )}
                {message.status === 'CANCELLED' && (
                  <p className="website-answer-note">{t('websiteChat.answering.cancelled')}</p>
                )}
                {message.status === 'FAILED' && (
                  <AnswerProblem
                    title={
                      message.error_code === 'interrupted'
                        ? t('websiteChat.answering.interrupted')
                        : t('websiteChat.answering.failed')
                    }
                    detail={message.error_code === 'interrupted' ? null : websiteErrorText(t, message.error_code)}
                    onRetry={message.id === lastId && !answering ? () => void submit(questionFor(message)) : undefined}
                  />
                )}
                {message.status === 'COMPLETED' && message.insufficient_evidence && (
                  <div className="website-insufficient" lang={artifactLang(message.output_language)}>
                    <span className="badge tone-muted">{t('websiteChat.insufficient')}</span>
                    <p>{message.content}</p>
                  </div>
                )}
                {message.status === 'COMPLETED' && !message.insufficient_evidence && (
                  <div className="website-answer report" lang={artifactLang(message.output_language)}>
                    <CitedMarkdown
                      markdown={message.content}
                      sources={citationSources(message, site)}
                      onCite={(index) =>
                        setOpenCitation(message.citations.find((citation) => citation.index === index) ?? null)
                      }
                    />
                  </div>
                )}
              </article>
            ),
          )}
          {submitted && (
            // Sent but not yet stored: shown immediately, never silently lost.
            <>
              <article className="website-message user">
                <span className="website-message-author">{t('websiteChat.you')}</span>
                <p className="website-message-text">{submitted.text}</p>
              </article>
              <article className="website-message assistant">
                <span className="website-message-author">{t('websiteChat.atlas')}</span>
                {submitted.error === null ? (
                  <AnsweringCard stage="" since={submitted.at} sending />
                ) : (
                  <AnswerProblem
                    title={t('websiteChat.answering.failed')}
                    detail={submitted.error}
                    onRetry={() => void submit(submitted.text)}
                  />
                )}
              </article>
            </>
          )}
          <div ref={threadEnd} />
        </div>

        <form className={`website-composer${answering ? ' is-busy' : ''}`} onSubmit={send}>
          <label htmlFor={composerId} className="visually-hidden">
            {t('websiteChat.composerLabel')}
          </label>
          <textarea
            id={composerId}
            className="website-composer-input"
            rows={2}
            placeholder={t('websiteChat.composerPlaceholder')}
            value={question}
            maxLength={2000}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            disabled={answering}
            aria-describedby={answering ? `${composerId}-busy` : undefined}
          />
          <button
            type="submit"
            className="query-submit"
            aria-label={t('websiteChat.send')}
            disabled={!question.trim() || answering || !languageReady}
          >
            <ArrowUpIcon size={18} />
          </button>
        </form>
        {answering && (
          <p id={`${composerId}-busy`} className="website-composer-busy">
            {t('websiteChat.answering.busyComposer')}
          </p>
        )}
        {sendError && (
          <p className="form-error" role="alert">
            {sendError}
          </p>
        )}
      </section>

      {openCitation && (
        <WebsiteEvidenceDrawer citation={openCitation} website={site} onClose={() => setOpenCitation(null)} />
      )}
    </div>
  )
}
