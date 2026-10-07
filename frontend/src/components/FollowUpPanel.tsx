import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useEventStream } from '../hooks/useEventStream'
import { followUpKindLabel, useI18n } from '../i18n'
import type { FollowUp, FollowUpMode, Source } from '../types'
import { CitedReport } from './CitedReport'
import { SourceRow } from './SourcesList'

const MODES: FollowUpMode[] = ['auto', 'analytical', 'research']

// The chip label follows the UI language, but the question it inserts stays
// English: generation is English-only until output language is supported, and a
// translated question would quietly ask the model for another language.
const SUGGESTIONS = [
  { label: 'followUp.suggestions.simpler', question: 'Explain this more simply' },
  { label: 'followUp.suggestions.strongest', question: 'What evidence is strongest?' },
  { label: 'followUp.suggestions.contradicts', question: 'What contradicts this?' },
  { label: 'followUp.suggestions.deeper', question: 'Research this deeper' },
] as const

function FollowUpSources({ followup }: { followup: FollowUp }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (followup.sources.length === 0) return null
  return (
    <div className="followup-sources">
      <button type="button" className="link-btn" onClick={() => setOpen((value) => !value)}>
        {open ? t('followUp.hideSources') : t('followUp.showSources', { count: followup.sources.length })}
      </button>
      {open && (
        <ol className="sources-list" aria-label={t('followUp.sourcesFor', { question: followup.question })}>
          {followup.sources.map((source: Source) => (
            <SourceRow
              key={source.index}
              source={source}
              trailing={
                source.index > followup.parent_source_count ? (
                  <span className="badge tone-active new-source-badge">{t('common.new')}</span>
                ) : undefined
              }
            />
          ))}
        </ol>
      )}
    </div>
  )
}

function FollowUpItem({ followup }: { followup: FollowUp }) {
  const { t } = useI18n()
  const active = followup.status === 'PENDING' || followup.status === 'RUNNING'
  return (
    <article className="followup-item" aria-label={t('followUp.itemLabel', { question: followup.question })}>
      <header className="followup-question-row">
        <p className="followup-question">{followup.question}</p>
        <span className={`badge kind-badge kind-${followup.kind.toLowerCase()}`}>
          {followUpKindLabel(t, followup.kind)}
        </span>
        {followup.new_source_count > 0 && (
          <span className="badge tone-active">
            {t('followUp.newSources', { count: followup.new_source_count })}
          </span>
        )}
      </header>
      {active && (
        <p className="followup-status" role="status">
          <span className="spinner small" aria-hidden="true" />
          {followup.status === 'PENDING' ? t('followUp.queued') : t('followUp.answering')}
        </p>
      )}
      {followup.status === 'FAILED' && (
        <p className="error-text">{followup.error || t('followUp.failed')}</p>
      )}
      {followup.status === 'CANCELLED' && <p className="hint-text">{t('followUp.cancelled')}</p>}
      {followup.status === 'COMPLETED' && (
        <>
          <CitedReport
            markdown={followup.answer}
            sources={followup.sources}
            parentSourceCount={followup.parent_source_count}
            className="report followup-answer"
            emptyNote={t('followUp.noAnswer')}
          />
          <FollowUpSources followup={followup} />
        </>
      )}
    </article>
  )
}

export function FollowUpPanel({ runId }: { runId: string }) {
  const { t } = useI18n()
  const [followups, setFollowups] = useState<FollowUp[]>([])
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<FollowUpMode>('auto')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [streamingId, setStreamingId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const response = await api.listFollowUps(runId)
      setFollowups(response.followups)
    } catch {
      // Follow-ups are an optional panel; keep whatever we have.
    }
  }, [runId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEventStream(streamingId ? `/api/followups/${streamingId}/events` : undefined, {
    enabled: streamingId !== null,
    onTerminal: () => {
      setStreamingId(null)
      void refresh()
    },
  })

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const followup = await api.createFollowUp(runId, { question: trimmed, mode })
      setQuestion('')
      setFollowups((previous) => [...previous, followup])
      setStreamingId(followup.id)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="followup-panel" aria-label={t('followUp.label')}>
      <h2 className="followup-heading">{t('followUp.heading')}</h2>
      <p className="page-subtitle">{t('followUp.subtitle')}</p>

      {followups.length > 0 && (
        <div className="followup-list">
          {followups.map((followup) => (
            <FollowUpItem key={followup.id} followup={followup} />
          ))}
        </div>
      )}

      <form className="followup-form" onSubmit={handleSubmit} aria-label={t('followUp.formLabel')}>
        <div className="suggestion-chips">
          {SUGGESTIONS.map(({ label, question: suggestion }) => (
            <button
              key={label}
              type="button"
              className="chip"
              onClick={() => setQuestion(suggestion)}
              disabled={submitting}
            >
              {t(label)}
            </button>
          ))}
        </div>
        <div className="followup-input-row">
          <input
            type="text"
            className="text-input"
            placeholder={t('followUp.placeholder')}
            aria-label={t('followUp.questionLabel')}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={submitting}
          />
          <select
            className="select-input"
            aria-label={t('followUp.modeLabel')}
            value={mode}
            onChange={(event) => setMode(event.target.value as FollowUpMode)}
            disabled={submitting}
          >
            {MODES.map((option) => (
              <option key={option} value={option}>
                {t(`followUp.modes.${option}`)}
              </option>
            ))}
          </select>
          <button type="submit" className="btn primary" disabled={!question.trim() || submitting}>
            {submitting ? t('followUp.asking') : t('followUp.ask')}
          </button>
        </div>
      </form>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
