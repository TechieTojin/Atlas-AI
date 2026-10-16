import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useI18n } from '../i18n'
import type { RunTimeline, TimelineEntry } from '../types'
import { formatElapsed } from '../pages/WebsiteChatPage'
import { PauseIcon, PlayIcon, RefreshIcon, SkipBackIcon, SkipForwardIcon } from './icons'

/**
 * Research Timeline: the run's stored events in chronological order, with a
 * replay that simply steps through them. Replay reveals STORED entries one by
 * one — it never reruns models, estimates timings or invents steps.
 */

const KNOWN_KINDS = [
  'RUN_STARTED',
  'PLANNING_STARTED',
  'PLANNING_REPAIR_STARTED',
  'PLAN_CREATED',
  'WAITING_FOR_PLAN_APPROVAL',
  'PLAN_APPROVED',
  'PLAN_EDITED',
  'SEARCH_STARTED',
  'SEARCH_QUERY_STARTED',
  'SEARCH_QUERY_COMPLETED',
  'EVIDENCE_COLLECTED',
  'PAGE_FETCH_STARTED',
  'PAGE_FETCH_COMPLETED',
  'PAGE_FETCH_FAILED',
  'CRITIC_STARTED',
  'CRITIC_COMPLETED',
  'MORE_RESEARCH_REQUESTED',
  'SYNTHESIS_STARTED',
  'CITATION_REPAIR_STARTED',
  'CITATION_REPAIR_COMPLETED',
  'REPORT_REGENERATED',
  'RUN_COMPLETED',
  'RUN_FAILED',
  'RUN_CANCELLED',
  'CANCEL_REQUESTED',
] as const

type KnownKind = (typeof KNOWN_KINDS)[number]

const SPEEDS = [1, 2, 4] as const
const BASE_STEP_MS = 900

function isKnown(kind: string): kind is KnownKind {
  return (KNOWN_KINDS as readonly string[]).includes(kind)
}

/** The stored details worth showing inline, as plain text (never markup). */
function detailText(entry: TimelineEntry): string {
  const d = entry.detail
  const parts: string[] = []
  if (typeof d.query === 'string') parts.push(`“${d.query}”`)
  if (typeof d.results === 'number') parts.push(`${d.results} ✕`)
  if (Array.isArray(d.queries)) parts.push(d.queries.map((q) => `“${String(q)}”`).join(' · '))
  if (Array.isArray(d.subquestions)) parts.push(`${d.subquestions.length} ?`)
  if (typeof d.score === 'number') parts.push(`${d.score}/10`)
  if (typeof d.decision === 'string') parts.push(String(d.decision))
  if (typeof d.fallback === 'string') parts.push(String(d.fallback))
  if (Array.isArray(d.follow_up_queries))
    parts.push(d.follow_up_queries.map((q) => `“${String(q)}”`).join(' · '))
  if (typeof d.new_items === 'number') parts.push(`+${d.new_items} → ${String(d.total_items ?? '')}`)
  if (typeof d.url === 'string') parts.push(String(d.url))
  if (typeof d.cited === 'number') parts.push(`[${d.cited}]`)
  if (typeof d.message === 'string') parts.push(String(d.message))
  return parts.join('  ')
}

export function ResearchTimeline({ runId }: { runId: string }) {
  const { t } = useI18n()
  const [timeline, setTimeline] = useState<RunTimeline | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  // Replay state: how many stored entries are revealed. null = all (no replay).
  const [revealed, setRevealed] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1)
  const listRef = useRef<HTMLOListElement>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getRunTimeline(runId)
      .then(setTimeline)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [runId])

  useEffect(() => {
    load()
  }, [load])

  const total = timeline?.entries.length ?? 0
  const shown = revealed === null ? total : Math.min(revealed, total)

  useEffect(() => {
    if (!playing) return
    if (shown >= total) {
      setPlaying(false)
      return
    }
    const timer = window.setTimeout(() => {
      setRevealed((current) => Math.min((current ?? 0) + 1, total))
    }, BASE_STEP_MS / speed)
    return () => window.clearTimeout(timer)
  }, [playing, shown, total, speed])

  useEffect(() => {
    // Keep the newest revealed entry in view during replay.
    if (revealed !== null) {
      const last = listRef.current?.querySelector('li:last-of-type')
      last?.scrollIntoView?.({ block: 'nearest' })
    }
  }, [shown, revealed])

  const entries = useMemo(() => timeline?.entries.slice(0, shown) ?? [], [timeline, shown])

  if (loading && !timeline) {
    return (
      <div className="page-state research-map-state" role="status">
        <span className="spinner" aria-hidden="true" /> {t('runTimeline.loading')}
      </div>
    )
  }
  if (error || !timeline) {
    return (
      <div className="page-state research-map-state" role="alert">
        <p className="error-text">{t('runTimeline.error')}</p>
        <p className="hint-text">{errorMessage(error)}</p>
        <button type="button" className="btn light compact" onClick={load}>
          {t('researchMap.retry')}
        </button>
      </div>
    )
  }

  const start = () => {
    if (revealed === null || shown >= total) setRevealed(0)
    setPlaying(true)
  }

  return (
    <div className="research-timeline">
      <div className="research-timeline-toolbar" role="group" aria-label={t('runTimeline.replayControls')}>
        <button
          type="button"
          className="btn compact"
          onClick={() => (playing ? setPlaying(false) : start())}
          aria-label={playing ? t('runTimeline.pause') : t('runTimeline.start')}
        >
          {playing ? <PauseIcon size={13} /> : <PlayIcon size={13} />}
          <span>{playing ? t('runTimeline.pause') : t('runTimeline.start')}</span>
        </button>
        <button
          type="button"
          className="btn compact"
          onClick={() => {
            setPlaying(false)
            setRevealed((current) => Math.max(0, (current ?? total) - 1))
          }}
          disabled={shown === 0}
          aria-label={t('runTimeline.previous')}
        >
          <SkipBackIcon size={13} />
        </button>
        <button
          type="button"
          className="btn compact"
          onClick={() => {
            setPlaying(false)
            setRevealed((current) => Math.min(total, (current ?? 0) + 1))
          }}
          disabled={shown >= total}
          aria-label={t('runTimeline.next')}
        >
          <SkipForwardIcon size={13} />
        </button>
        <button
          type="button"
          className="btn compact"
          onClick={() => {
            setPlaying(false)
            setRevealed(0)
          }}
          aria-label={t('runTimeline.restart')}
        >
          <RefreshIcon size={13} />
          <span>{t('runTimeline.restart')}</span>
        </button>
        <button
          type="button"
          className="btn compact"
          onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])}
          aria-label={t('runTimeline.speed')}
        >
          {speed}×
        </button>
        <span className="research-timeline-progress" aria-live="polite">
          {t('runTimeline.progress', { shown: String(shown), total: String(total) })}
        </span>
      </div>

      {timeline.incomplete && <p className="research-map-note">{t('runTimeline.incomplete')}</p>}
      {!timeline.incomplete && total === 0 && <p className="empty-note">{t('runTimeline.empty')}</p>}

      <ol className="research-timeline-list" ref={listRef} aria-label={t('runTimeline.listLabel')}>
        {entries.map((entry) => (
          <li key={entry.seq} className={`research-timeline-entry kind-${entry.kind.toLowerCase()}`}>
            <span className="research-timeline-time">{formatElapsed(entry.offset_ms)}</span>
            <span className="research-timeline-dot" aria-hidden="true" />
            <span className="research-timeline-body">
              <span className="research-timeline-kind">
                {isKnown(entry.kind) ? t(`runTimeline.kind.${entry.kind}`) : entry.kind}
                {entry.iteration > 0 ? ` · ${t('researchMap.iteration', { n: String(entry.iteration) })}` : ''}
              </span>
              {detailText(entry) && <span className="research-timeline-detail">{detailText(entry)}</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
