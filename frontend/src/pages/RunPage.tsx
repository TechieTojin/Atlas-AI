import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, errorMessage, notifyRunsChanged } from '../api/client'
import { ReportHeroArt } from '../components/art/ReportHeroArt'
import { FollowUpPanel } from '../components/FollowUpPanel'
import { PlanApproval } from '../components/PlanApproval'
import { ExportMenu, RegenerateAction } from '../components/RunActions'
import { RunTabs } from '../components/RunTabs'
import { StatusBadge } from '../components/StatusBadge'
import { RunStatChips, Timeline } from '../components/Timeline'
import {
  ArrowLeftIcon,
  BoltIcon,
  ChevronRightIcon,
  FolderIcon,
  LinkIcon,
  MoreVerticalIcon,
  SparkleIcon,
  TrashIcon,
} from '../components/icons'
import { useRun } from '../hooks/useRun'
import { useRunEvents } from '../hooks/useRunEvents'
import { agoLabel, modeBadge, templateName, useI18n } from '../i18n'
import type { EventType, RunDetail } from '../types'
import { isActiveStatus } from '../types'
import { formatClock } from '../utils/format'
import { emphasiseTitle, splitSections } from '../utils/report'

const REFRESH_EVENT_TYPES: EventType[] = [
  'PLAN_CREATED',
  'WAITING_FOR_PLAN_APPROVAL',
  'PLAN_APPROVED',
  'SEARCH_STARTED',
  'CRITIC_STARTED',
  'SYNTHESIS_STARTED',
]

function ElapsedTime({ run, frozenAt }: { run: RunDetail; frozenAt: number | null }) {
  const { t } = useI18n()
  const active = isActiveStatus(run.status) && frozenAt === null
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])

  const start = Date.parse(run.started_at || run.created_at)
  if (Number.isNaN(start)) return null
  const end = run.completed_at ? Date.parse(run.completed_at) : (frozenAt ?? now)
  const elapsed = Math.max(0, (Number.isNaN(end) ? now : end) - start)

  return (
    <span className="elapsed" title={t('time.elapsed')}>
      {formatClock(elapsed)}
    </span>
  )
}

/** Resolves the project's display name for the breadcrumb and info card. */
function useProjectName(projectId: string | null | undefined): string | null {
  const [name, setName] = useState<string | null>(null)
  useEffect(() => {
    setName(null)
    if (!projectId) return
    let cancelled = false
    api
      .getProject(projectId)
      .then((project) => {
        if (!cancelled) setName(project.name)
      })
      .catch(() => {
        if (!cancelled) setName(null)
      })
    return () => {
      cancelled = true
    }
  }, [projectId])
  return name
}

function MoreMenu({ runId }: { runId: string }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/runs/${runId}`)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard unavailable.
    }
  }

  return (
    <div className="menu-wrap" ref={ref}>
      <button
        type="button"
        className="icon-btn framed"
        aria-label={t('common.moreActions')}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <MoreVerticalIcon size={18} />
      </button>
      {open && (
        <div className="menu align-end" role="menu" aria-label={t('common.moreActions')}>
          <button type="button" role="menuitem" className="menu-item" onClick={() => void copyLink()}>
            <LinkIcon size={14} />
            {copied ? t('common.linkCopied') : t('common.copyLink')}
          </button>
        </div>
      )}
    </div>
  )
}

export function RunPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { t, format } = useI18n()
  const { run, loading, error, refetch, setRun } = useRun(id)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Set the instant Cancel is clicked; cleared again if the request fails.
  const [cancelRequestedAt, setCancelRequestedAt] = useState<number | null>(null)
  const projectName = useProjectName(run?.project_id)

  const active = run !== null && isActiveStatus(run.status)

  const showsTimeline =
    run !== null && (active || run.status === 'CANCELLED' || run.status === 'FAILED')
  const events = useRunEvents(id, {
    enabled: showsTimeline,
    onEvent: (event) => {
      if (REFRESH_EVENT_TYPES.includes(event.type)) void refetch()
    },
    onTerminal: () => {
      void refetch()
      notifyRunsChanged()
    },
  })

  const titleSegments = useMemo(() => {
    if (!run) return []
    const headings = splitSections(run.final_report)
      .map((section) => section.title)
      .filter(Boolean)
    return emphasiseTitle(run.query || run.title, headings)
  }, [run])

  if (loading) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('run.loading')}</p>
      </div>
    )
  }

  if (error || !run) {
    return (
      <div className="page-state">
        <h1>{t('run.notFound')}</h1>
        <p className="error-text">{error ?? t('run.notExist')}</p>
        <Link className="btn primary" to="/">
          {t('common.startNewResearch')}
        </Link>
      </div>
    )
  }

  const terminal = !active
  const cancelling = cancelRequestedAt !== null || run.status === 'CANCELLING'
  const ModeIcon = run.mode === 'FAST' ? BoltIcon : SparkleIcon
  const updatedAt = run.completed_at || run.started_at || run.created_at

  const handleCancel = async () => {
    if (cancelling) return
    setCancelRequestedAt(Date.now())
    setActionError(null)
    try {
      // Backend aborts the in-flight model request; status becomes
      // CANCELLING and the event stream then delivers RUN_CANCELLED.
      setRun(await api.cancelRun(run.id))
      notifyRunsChanged()
    } catch (err) {
      setCancelRequestedAt(null)
      if (err instanceof ApiError && err.status === 409) {
        await refetch()
        setActionError(t('run.cancelRaced'))
      } else {
        setActionError(t('run.cancelFailed', { error: errorMessage(err) }))
      }
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(t('run.confirmDelete'))) return
    setBusy(true)
    setActionError(null)
    try {
      await api.deleteRun(run.id)
      notifyRunsChanged()
      navigate('/')
    } catch (err) {
      setActionError(errorMessage(err))
      setBusy(false)
    }
  }

  const backTarget = run.project_id ? `/projects/${run.project_id}` : '/'

  return (
    <div className="run-page report-page">
      <div className="run-topbar">
        <nav className="breadcrumb" aria-label={t('common.breadcrumb')}>
          <Link to={backTarget} className="icon-btn breadcrumb-back" aria-label={t('common.back')}>
            <ArrowLeftIcon size={18} />
          </Link>
          <ol className="breadcrumb-list">
            {run.project_id ? (
              <>
                <li>
                  <Link to="/projects">{t('nav.projects')}</Link>
                </li>
                <li aria-hidden="true" className="breadcrumb-sep">
                  <ChevronRightIcon size={14} />
                </li>
                <li>
                  <Link to={`/projects/${run.project_id}`}>{projectName ?? t('common.project')}</Link>
                </li>
              </>
            ) : (
              <li>
                <Link to="/">{t('nav.research')}</Link>
              </li>
            )}
            <li aria-hidden="true" className="breadcrumb-sep">
              <ChevronRightIcon size={14} />
            </li>
            <li className="breadcrumb-current" aria-current="page">
              {run.title || run.query}
            </li>
          </ol>
        </nav>
        <div className="run-actions">
          {active && (
            <button
              type="button"
              className="btn danger-ghost"
              onClick={() => void handleCancel()}
              disabled={busy || cancelling}
              aria-busy={cancelling}
            >
              {cancelling ? t('common.cancelling') : t('common.cancel')}
            </button>
          )}
          {run.status === 'COMPLETED' && (
            <>
              <ExportMenu runId={run.id} />
              <RegenerateAction run={run} />
            </>
          )}
          {terminal && (
            <button
              type="button"
              className="btn danger-ghost"
              onClick={() => void handleDelete()}
              disabled={busy}
              aria-label={t('run.deleteLabel')}
            >
              <TrashIcon size={14} />
              <span>{t('common.delete')}</span>
            </button>
          )}
          <MoreMenu runId={run.id} />
        </div>
      </div>

      <header className="report-hero">
        <div className="report-hero-copy">
          <h1 className="report-title">
            {titleSegments.map((segment, index) =>
              segment.emphasised ? (
                <em key={index} className="report-title-em">
                  {segment.text}
                </em>
              ) : (
                <span key={index}>{segment.text}</span>
              ),
            )}
          </h1>
          <div className="run-meta">
            {run.project_id && (
              <Link to={`/projects/${run.project_id}`} className="meta-pill project">
                <FolderIcon size={13} />
                <span>{projectName ?? t('common.project')}</span>
              </Link>
            )}
            <span className={`meta-pill mode mode-${run.mode.toLowerCase()}`}>
              <ModeIcon size={13} />
              <span>{modeBadge(t, run.mode)}</span>
            </span>
            <span className="meta-pill template">{templateName(t, run.template)}</span>
            {run.status !== 'COMPLETED' && <StatusBadge status={run.status} />}
            {run.regenerated_from && (
              <Link className="chip regenerated-chip" to={`/runs/${run.regenerated_from}`}>
                {t('run.regeneratedFrom')}
              </Link>
            )}
            {run.status === 'COMPLETED' ? (
              <span className="meta-updated">
                <span aria-hidden="true">•</span>{' '}
                {t('time.updated', { time: agoLabel(t, format, updatedAt) })}
              </span>
            ) : (
              <ElapsedTime run={run} frozenAt={run.completed_at ? null : cancelRequestedAt} />
            )}
          </div>
        </div>
        {run.status === 'COMPLETED' && <ReportHeroArt label={templateName(t, run.template)} />}
      </header>

      {actionError && (
        <p className="form-error" role="alert">
          {actionError}
        </p>
      )}

      {active && (
        <div className="glass-card panel-card progress-card">
          <RunStatChips events={events} iterations={run.iterations} />
          {run.status === 'AWAITING_APPROVAL' && (
            <PlanApproval
              run={run}
              onUpdated={(updated) => {
                setRun(updated)
                notifyRunsChanged()
              }}
            />
          )}
          <Timeline events={events} status={run.status} />
        </div>
      )}

      {run.status === 'COMPLETED' && (
        <>
          <RunTabs run={run} projectName={projectName} />
          <FollowUpPanel runId={run.id} />
        </>
      )}

      {(run.status === 'FAILED' || run.status === 'CANCELLED') && (
        <section className="card failure-card glass-card">
          <h2>{run.status === 'FAILED' ? t('run.failedTitle') : t('run.cancelledTitle')}</h2>
          {run.error ? <p className="error-text">{run.error}</p> : <p>{t('run.didNotFinish')}</p>}
          {events.length > 0 && <Timeline events={events} status={run.status} />}
          <Link className="btn primary" to="/">
            {t('common.startNewResearch')}
          </Link>
        </section>
      )}
    </div>
  )
}
