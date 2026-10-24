import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api, errorMessage } from '../api/client'
import { CitedMarkdown } from '../components/CitedReport'
import { DocumentEvidenceDrawer } from '../components/DocumentEvidenceDrawer'
import { SaveToCollection } from '../components/SaveToCollection'
import {
  ArrowLeftIcon,
  ArrowUpIcon,
  FileTextIcon,
  GlobeIcon,
  PlusIcon,
  ShareIcon,
  TrashIcon,
} from '../components/icons'
import { AnswerProblem, AnsweringCard, websiteErrorText } from './WebsiteChatPage'
import { artifactLang, agoLabel, languageName, useI18n, useOutputLanguage, type Translate } from '../i18n'
import type {
  DocumentChatMessage,
  DocumentCitation,
  DocumentConversation,
  DocumentRecord,
  DocumentRelationships,
  Source,
} from '../types'

const ANSWER_POLL_MS = 1500

function errorFrom(t: Translate, error: unknown): string {
  if (error instanceof ApiError && error.code) return websiteErrorText(t, error.code)
  return errorMessage(error)
}

function citationSources(message: DocumentChatMessage): Source[] {
  return message.citations.map((citation) => ({
    index: citation.index,
    title: citation.filename,
    url: '',
    domain: '',
    kind: 'document' as const,
    filename: citation.filename,
    page: citation.page,
  }))
}

function useDocumentConversation(conversationId: string | null) {
  const [messages, setMessages] = useState<DocumentChatMessage[]>([])
  const [conversation, setConversation] = useState<DocumentConversation | null>(null)
  const [error, setError] = useState<unknown>(null)
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
      const detail = await api.getDocumentConversation(id)
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
  const merge = useCallback((incoming: DocumentChatMessage[]) => {
    latest.current += 1
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

export function DocumentChatPage() {
  const { t, format, language: ui } = useI18n()
  const [searchParams, setSearchParams] = useSearchParams()
  const conversationId = searchParams.get('c')
  const scopeIds = useMemo(
    () => (searchParams.get('ids') ?? '').split(',').filter(Boolean),
    [searchParams],
  )
  const { conversation, messages, error, reload, merge, pending } = useDocumentConversation(conversationId)
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [conversations, setConversations] = useState<DocumentConversation[]>([])
  const output = useOutputLanguage('document_chat')
  const [englishChosenFor, setEnglishChosenFor] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [submitted, setSubmitted] = useState<{ text: string; at: number; error: string | null } | null>(null)
  const [cancelling, setCancelling] = useState<string | null>(null)
  const [openCitation, setOpenCitation] = useState<DocumentCitation | null>(null)
  const [showRelationships, setShowRelationships] = useState(false)
  const composerId = useId()
  const threadEnd = useRef<HTMLDivElement>(null)
  const nameOf = (code: string) => languageName(code, ui.locale)

  const loadConversations = useCallback(async () => {
    try {
      setConversations((await api.listDocumentConversations()).conversations)
    } catch {
      // the list is a convenience; the thread itself reports real errors
    }
  }, [])

  useEffect(() => {
    void loadConversations()
    api
      .listDocuments()
      .then((body) => setDocuments(body.documents))
      .catch(() => setDocuments([]))
  }, [loadConversations])

  useEffect(() => {
    threadEnd.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length, pending, submitted])

  useEffect(() => {
    if (cancelling && !messages.some((m) => m.id === cancelling && m.status === 'PENDING')) setCancelling(null)
  }, [cancelling, messages])

  const activeIds = conversation?.document_ids ?? scopeIds
  const filenameOf = (id: string) =>
    documents.find((document) => document.id === id)?.filename ?? t('documentChat.missingDocument')

  const needsChoice = !conversation && output.fellBack && !output.loading
  const englishChosen = englishChosenFor === output.preferred
  const languageReady =
    conversation !== null || output.preferred === 'en' || (!output.loading && (!needsChoice || englishChosen))
  const answerLanguage = conversation?.output_language ?? output.effective
  const answering = pending || sending || (submitted !== null && submitted.error === null)

  const submit = async (text: string) => {
    if (!text || answering || !languageReady || activeIds.length === 0) return
    setSubmitted({ text, at: Date.now(), error: null })
    setQuestion('')
    setSending(true)
    try {
      let id = conversationId
      if (!id) {
        const created = await api.createDocumentConversation(activeIds, output.effective)
        id = created.conversation.id
        setSearchParams({ c: id }, { replace: false })
      }
      const posted = await api.askDocuments(id, text)
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

  const cancelAnswer = async (message: DocumentChatMessage) => {
    setCancelling(message.id)
    try {
      await api.cancelDocumentMessage(message.id)
    } catch {
      // already finished
    }
    await reload()
  }

  const deleteConversation = async (target: DocumentConversation) => {
    if (!window.confirm(t('documentChat.confirmDelete'))) return
    try {
      await api.deleteDocumentConversation(target.id)
      if (target.id === conversationId) setSearchParams({}, { replace: false })
      void loadConversations()
    } catch {
      // surfaced on next load
    }
  }

  const questionFor = (answer: DocumentChatMessage) =>
    [...messages].reverse().find((m) => m.role === 'user' && m.seq < answer.seq)?.content ?? ''
  const lastId = messages.at(-1)?.id

  if (activeIds.length === 0 && !conversationId) {
    return (
      <div className="website-page document-chat-page">
        <Link className="back-link" to="/documents">
          <ArrowLeftIcon size={14} /> {t('documentChat.backToDocuments')}
        </Link>
        <div className="empty-state">
          <span className="empty-state-icon" aria-hidden="true">
            <FileTextIcon size={20} />
          </span>
          <h2 className="empty-state-title">{t('documentChat.title')}</h2>
          <p className="empty-state-body">{t('documentChat.noSelection')}</p>
          <Link className="btn primary empty-state-action" to="/documents">
            {t('documentChat.chooseDocuments')}
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="website-page document-chat-page">
      <Link className="back-link" to="/documents">
        <ArrowLeftIcon size={14} /> {t('documentChat.backToDocuments')}
      </Link>
      <header className="website-header glass-card">
        <div className="website-header-main">
          <span className="website-card-icon" aria-hidden="true">
            <FileTextIcon size={20} />
          </span>
          <div className="website-header-text">
            <h1 className="website-title">{t('documentChat.title')}</h1>
            <div className="document-chat-chips" aria-label={t('documentChat.scopeLabel')}>
              {activeIds.map((id) => (
                <span key={id} className="badge tone-muted document-chip">
                  <FileTextIcon size={11} /> {filenameOf(id)}
                </span>
              ))}
            </div>
          </div>
        </div>
        {activeIds.length > 1 && (
          <div className="website-actions">
            <button
              type="button"
              className="btn light compact"
              aria-expanded={showRelationships}
              onClick={() => setShowRelationships((value) => !value)}
            >
              <ShareIcon size={14} />
              <span>{t('documentChat.relationships.title')}</span>
            </button>
          </div>
        )}
      </header>

      {showRelationships && activeIds.length > 1 && (
        <RelationshipsPanel ids={activeIds} filenameOf={filenameOf} />
      )}

      <div className="website-chat-layout">
        <aside className="website-conversations glass-card" aria-label={t('documentChat.conversations')}>
          <div className="website-conversations-head">
            <h2 className="panel-heading">{t('documentChat.conversations')}</h2>
            <Link className="btn light compact" to="/documents">
              <PlusIcon size={14} />
              <span>{t('documentChat.newConversation')}</span>
            </Link>
          </div>
          {conversations.length > 0 && (
            <ul className="website-conversation-list">
              {conversations.map((item) => (
                <li
                  key={item.id}
                  className={`website-conversation${item.id === conversationId ? ' selected' : ''}`}
                >
                  <button
                    type="button"
                    className="website-conversation-button"
                    aria-current={item.id === conversationId ? 'true' : undefined}
                    onClick={() => setSearchParams({ c: item.id })}
                  >
                    <span className="website-conversation-title">
                      {item.title || t('documentChat.untitled')}
                    </span>
                    <span className="history-meta">
                      {t('documentChat.documentCount', { count: String(item.document_ids.length) })} ·{' '}
                      {agoLabel(t, format, item.updated_at)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="icon-btn danger"
                    aria-label={t('documentChat.deleteConversation')}
                    onClick={() => void deleteConversation(item)}
                  >
                    <TrashIcon size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="website-chat glass-card" aria-label={t('documentChat.composerLabel')}>
          <p className="website-chat-language">
            <GlobeIcon size={13} className="output-language-icon" />
            <span>{t('documentChat.answersIn', { language: nameOf(answerLanguage) })}</span>
          </p>
          {needsChoice && (
            <div className="output-language-fallback website-language-choice" role="note">
              <p>{t('documentChat.languageUnsupported', { preferred: nameOf(output.preferred) })}</p>
              {englishChosen ? (
                <p className="output-language-chosen">{t('documentChat.continuingInEnglish')}</p>
              ) : (
                <button
                  type="button"
                  className="btn light compact"
                  onClick={() => setEnglishChosenFor(output.preferred)}
                >
                  {t('documentChat.continueInEnglish')}
                </button>
              )}
            </div>
          )}

          <div className="website-thread" aria-live="polite">
            {error ? <p className="error-text">{errorFrom(t, error)}</p> : null}
            {messages.length === 0 && !submitted && !error && (
              <p className="empty-note">{t('documentChat.emptyChat')}</p>
            )}
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
                      onRetry={
                        message.id === lastId && !answering
                          ? () => void submit(questionFor(message))
                          : undefined
                      }
                    />
                  )}
                  {message.status === 'COMPLETED' && message.insufficient_evidence && (
                    <div className="website-insufficient" lang={artifactLang(message.output_language)}>
                      <span className="badge tone-muted">{t('documentChat.insufficient')}</span>
                      <p>{message.content}</p>
                    </div>
                  )}
                  {message.status === 'COMPLETED' && !message.insufficient_evidence && (
                    <div className="website-answer report" lang={artifactLang(message.output_language)}>
                      <CitedMarkdown
                        markdown={message.content}
                        sources={citationSources(message)}
                        onCite={(index) =>
                          setOpenCitation(
                            message.citations.find((citation) => citation.index === index) ?? null,
                          )
                        }
                      />
                    </div>
                  )}
                </article>
              ),
            )}
            {submitted && (
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
              {t('documentChat.composerLabel')}
            </label>
            <textarea
              id={composerId}
              className="website-composer-input"
              rows={2}
              placeholder={t('documentChat.composerPlaceholder')}
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
        </section>
      </div>

      {openCitation && (
        <DocumentEvidenceDrawer
          citation={openCitation}
          onClose={() => setOpenCitation(null)}
          onSave={
            <SaveToCollection
              itemType="document_passage"
              data={{
                text: openCitation.text,
                filename: openCitation.filename,
                page: openCitation.page,
                document_id: openCitation.document_id,
                citation: openCitation.index,
              }}
            />
          }
        />
      )}
    </div>
  )
}

/** Deterministic shared-vocabulary links between the selected documents. */
function RelationshipsPanel({
  ids,
  filenameOf,
}: {
  ids: string[]
  filenameOf: (id: string) => string
}) {
  const { t } = useI18n()
  const [relationships, setRelationships] = useState<DocumentRelationships | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    let active = true
    api
      .getDocumentRelationships(ids)
      .then((body) => {
        if (active) setRelationships(body)
      })
      .catch((err) => {
        if (active) setError(err)
      })
    return () => {
      active = false
    }
  }, [ids])
  return (
    <section className="document-relationships glass-card" aria-label={t('documentChat.relationships.title')}>
      <h2 className="panel-heading">{t('documentChat.relationships.title')}</h2>
      <p className="hint-text">{t('documentChat.relationships.method')}</p>
      {error ? <p className="error-text">{errorMessage(error)}</p> : null}
      {relationships && relationships.links.length === 0 && (
        <p className="empty-note">{t('documentChat.relationships.none')}</p>
      )}
      {relationships && relationships.links.length > 0 && (
        <ul className="document-relationships-list">
          {relationships.links.map((link) => (
            <li key={`${link.a}-${link.b}`}>
              <span className="document-relationship-docs">
                {filenameOf(link.a)} ↔ {filenameOf(link.b)}
              </span>
              <span className="badge tone-muted">{t('documentChat.relationships.sharesConcept')}</span>
              <span className="document-relationship-terms">{link.terms.join(' · ')}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
