import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useEventStream } from '../hooks/useEventStream'
import type { FollowUp, FollowUpMode, Source } from '../types'
import { CitedReport } from './CitedReport'
import { SourceRow } from './SourcesList'

const MODES: { value: FollowUpMode; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'analytical', label: 'Use existing evidence' },
  { value: 'research', label: 'Research further' },
]

const SUGGESTIONS = [
  'Explain this more simply',
  'What evidence is strongest?',
  'What contradicts this?',
  'Research this deeper',
]

function FollowUpSources({ followup }: { followup: FollowUp }) {
  const [open, setOpen] = useState(false)
  if (followup.sources.length === 0) return null
  return (
    <div className="followup-sources">
      <button type="button" className="link-btn" onClick={() => setOpen((value) => !value)}>
        {open ? 'Hide sources' : `Sources (${followup.sources.length})`}
      </button>
      {open && (
        <ol className="sources-list" aria-label={`Sources for follow-up: ${followup.question}`}>
          {followup.sources.map((source: Source) => (
            <SourceRow
              key={source.index}
              source={source}
              trailing={
                source.index > followup.parent_source_count ? (
                  <span className="badge tone-active new-source-badge">New</span>
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
  const active = followup.status === 'PENDING' || followup.status === 'RUNNING'
  return (
    <article className="followup-item" aria-label={`Follow-up: ${followup.question}`}>
      <header className="followup-question-row">
        <p className="followup-question">{followup.question}</p>
        <span className={`badge kind-badge kind-${followup.kind.toLowerCase()}`}>
          {followup.kind === 'RESEARCH' ? 'RESEARCH' : 'ANALYTICAL'}
        </span>
        {followup.new_source_count > 0 && (
          <span className="badge tone-active">+{followup.new_source_count} new sources</span>
        )}
      </header>
      {active && (
        <p className="followup-status" role="status">
          <span className="spinner small" aria-hidden="true" />
          {followup.status === 'PENDING' ? 'Queued…' : 'Answering…'}
        </p>
      )}
      {followup.status === 'FAILED' && (
        <p className="error-text">{followup.error || 'This follow-up failed.'}</p>
      )}
      {followup.status === 'CANCELLED' && <p className="hint-text">Cancelled.</p>}
      {followup.status === 'COMPLETED' && (
        <>
          <CitedReport
            markdown={followup.answer}
            sources={followup.sources}
            parentSourceCount={followup.parent_source_count}
            className="report followup-answer"
            emptyNote="No answer was produced."
          />
          <FollowUpSources followup={followup} />
        </>
      )}
    </article>
  )
}

export function FollowUpPanel({ runId }: { runId: string }) {
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
    <section className="followup-panel" aria-label="Ask Atlas">
      <h2 className="followup-heading">Ask Atlas</h2>
      <p className="page-subtitle">Follow up on this research with questions.</p>

      {followups.length > 0 && (
        <div className="followup-list">
          {followups.map((followup) => (
            <FollowUpItem key={followup.id} followup={followup} />
          ))}
        </div>
      )}

      <form className="followup-form" onSubmit={handleSubmit} aria-label="Ask a follow-up question">
        <div className="suggestion-chips">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="chip"
              onClick={() => setQuestion(suggestion)}
              disabled={submitting}
            >
              {suggestion}
            </button>
          ))}
        </div>
        <div className="followup-input-row">
          <input
            type="text"
            className="text-input"
            placeholder="Ask a follow-up question…"
            aria-label="Follow-up question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={submitting}
          />
          <select
            className="select-input"
            aria-label="Follow-up mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as FollowUpMode)}
            disabled={submitting}
          >
            {MODES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button type="submit" className="btn primary" disabled={!question.trim() || submitting}>
            {submitting ? 'Asking…' : 'Ask'}
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
