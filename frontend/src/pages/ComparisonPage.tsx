import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, comparisonExportUrl, errorMessage } from '../api/client'
import { CitedReport } from '../components/CitedReport'
import { DownloadIcon, TrashIcon } from '../components/icons'
import { useEventStream } from '../hooks/useEventStream'
import { useI18n } from '../i18n'
import type { Comparison, ComparisonStatus } from '../types'

/** A compact execution summary. Deliberately small: enough to tell why a
 *  comparison took the time it did, without a metrics page. */
function ComparisonMetricsRow({ comparison }: { comparison: Comparison }) {
  const { t, format } = useI18n()
  const metrics = comparison.metrics ?? {}
  const seconds =
    comparison.duration_ms > 0
      ? comparison.duration_ms / 1000
      : metrics.elapsed_ms
        ? metrics.elapsed_ms / 1000
        : null
  // A null token count means Ollama never reported one, which is what happens
  // when a request is aborted. Showing 0 would claim the model wrote nothing.
  const tokens = (value: number | null | undefined) =>
    typeof value === 'number' ? format.number(value) : t('common.unavailable')
  const oneDecimal = (value: number, unit: 'second' | 'minute') =>
    format.number(value, {
      style: 'unit',
      unit,
      unitDisplay: 'narrow',
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })

  if (!metrics.model && seconds === null) return null

  return (
    <dl className="comparison-metrics" role="group" aria-label={t('comparison.detailsLabel')}>
      {seconds !== null && (
        <div>
          <dt>{t('comparison.elapsed')}</dt>
          <dd>{seconds < 60 ? oneDecimal(seconds, 'second') : oneDecimal(seconds / 60, 'minute')}</dd>
        </div>
      )}
      {metrics.model && (
        <div>
          <dt>{t('comparison.model')}</dt>
          <dd>{metrics.model}</dd>
        </div>
      )}
      {typeof metrics.prefill_ms === 'number' && (
        <div>
          <dt>{t('comparison.promptRead')}</dt>
          <dd>{oneDecimal(metrics.prefill_ms / 1000, 'second')}</dd>
        </div>
      )}
      {typeof metrics.generation_ms === 'number' && (
        <div>
          <dt>{t('comparison.writing')}</dt>
          <dd>{oneDecimal(metrics.generation_ms / 1000, 'second')}</dd>
        </div>
      )}
      <div>
        <dt>{t('comparison.outputTokens')}</dt>
        <dd>
          {tokens(metrics.output_tokens)}
          {metrics.output_cap_reached === true && t('comparison.capReached')}
        </dd>
      </div>
      <div>
        <dt>{t('comparison.promptTokens')}</dt>
        <dd>{tokens(metrics.prompt_tokens)}</dd>
      </div>
      {typeof metrics.repair_calls === 'number' && metrics.repair_calls > 0 && (
        <div>
          <dt>{t('comparison.repairs')}</dt>
          <dd>{format.number(metrics.repair_calls)}</dd>
        </div>
      )}
    </dl>
  )
}

export function ComparisonPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { t, format } = useI18n()
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)

  const refetch = useCallback(async () => {
    if (!id) return
    try {
      setComparison(await api.getComparison(id))
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    setComparison(null)
    setLoading(true)
    void refetch()
  }, [refetch])

  const TERMINAL: ComparisonStatus[] = ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT']
  const active = Boolean(comparison) && !TERMINAL.includes(comparison!.status)

  useEventStream(id ? `/api/comparisons/${id}/events` : undefined, {
    enabled: Boolean(id) && active,
    onTerminal: () => void refetch(),
  })

  const runLabel = useCallback(
    (runId: string): string => {
      if (!comparison) return runId
      const index = comparison.run_ids.indexOf(runId)
      return comparison.run_queries[index] ?? runId
    },
    [comparison],
  )

  const sources = useMemo(
    () => (comparison ? comparison.sources.map((entry) => entry.source) : []),
    [comparison],
  )

  const usageBySourceIndex = useMemo(() => {
    const map = new Map<number, string[]>()
    if (comparison) {
      for (const entry of comparison.sources) {
        map.set(
          entry.source.index,
          entry.run_ids.map((runId) => runLabel(runId)),
        )
      }
    }
    return map
  }, [comparison, runLabel])

  const loadClaims = useCallback(
    () => api.getComparisonClaims(id as string).then((response) => response.claims),
    [id],
  )

  if (loading) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('comparison.loading')}</p>
      </div>
    )
  }

  if (error || !comparison) {
    return (
      <div className="page-state">
        <h1>{t('comparison.notFound')}</h1>
        <p className="error-text">{error ?? t('comparison.notExist')}</p>
        <Link className="btn primary" to="/">
          {t('common.backToResearch')}
        </Link>
      </div>
    )
  }

  const handleCancel = async () => {
    setActionError(null)
    setCancelling(true)
    try {
      setComparison(await api.cancelComparison(comparison.id))
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setCancelling(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(t('comparison.confirmDelete'))) return
    setActionError(null)
    try {
      await api.deleteComparison(comparison.id)
      navigate(comparison.project_id ? `/projects/${comparison.project_id}` : '/')
    } catch (err) {
      setActionError(errorMessage(err))
    }
  }

  return (
    <div className="run-page comparison-page">
      <header className="run-header">
        <div className="run-header-main">
          <h1 className="run-query">{comparison.title || t('comparison.fallbackTitle')}</h1>
          <div className="run-meta">
            <span
              className={`badge ${
                comparison.status === 'COMPLETED'
                  ? 'tone-success'
                  : comparison.status === 'FAILED' || comparison.status === 'TIMED_OUT'
                    ? 'tone-danger'
                    : comparison.status === 'CANCELLED'
                      ? 'tone-muted'
                      : 'tone-active'
              }`}
            >
              {t(`comparison.status.${comparison.status}`)}
            </span>
          </div>
          <div className="doc-chips comparison-run-chips">
            {comparison.run_ids.map((runId, index) => (
              <Link key={runId} to={`/runs/${runId}`} className="chip">
                {comparison.run_queries[index] ?? runId}
              </Link>
            ))}
          </div>
        </div>
        <div className="run-actions">
          {active && (
            <button
              type="button"
              className="btn"
              onClick={() => void handleCancel()}
              disabled={cancelling || comparison.status === 'CANCELLING'}
            >
              <span>
                {comparison.status === 'CANCELLING' ? t('common.cancelling') : t('common.cancel')}
              </span>
            </button>
          )}
          {comparison.status === 'COMPLETED' && (
            <a className="btn" href={comparisonExportUrl(comparison.id)} download>
              <DownloadIcon size={14} />
              <span>{t('common.export')}</span>
            </a>
          )}
          <button
            type="button"
            className="btn danger-ghost"
            onClick={() => void handleDelete()}
            aria-label={t('comparison.deleteLabel')}
          >
            <TrashIcon size={14} />
            <span>{t('common.delete')}</span>
          </button>
        </div>
      </header>

      {actionError && (
        <p className="form-error" role="alert">
          {actionError}
        </p>
      )}

      {active && (
        <div className="page-state" role="status">
          <span className="spinner" aria-hidden="true" />
          <p>
            {comparison.status === 'CANCELLING'
              ? t('comparison.stopping')
              : t('comparison.comparingRuns', { count: comparison.run_ids.length })}
          </p>
        </div>
      )}

      {comparison.status === 'TIMED_OUT' && (
        <section className="card failure-card">
          <h2>{t('comparison.timedOutTitle')}</h2>
          <p className="error-text">{comparison.error || t('comparison.timedOutText')}</p>
        </section>
      )}

      {comparison.status === 'CANCELLED' && (
        <section className="card failure-card">
          <h2>{t('comparison.cancelledTitle')}</h2>
          <p className="hint-text">{comparison.error || t('comparison.cancelledText')}</p>
        </section>
      )}

      {comparison.status === 'FAILED' && (
        <section className="card failure-card">
          <h2>{t('comparison.failedTitle')}</h2>
          <p className="error-text">{comparison.error || t('comparison.failedText')}</p>
        </section>
      )}

      {comparison.status !== 'PENDING' && <ComparisonMetricsRow comparison={comparison} />}

      {comparison.status === 'COMPLETED' && (
        <>
          <section aria-label={t('comparison.overlap')}>
            <h3 className="panel-heading">{t('comparison.overlap')}</h3>
            <div className="metric-grid">
              <div className="metric-card">
                <span className="metric-value">{format.number(comparison.overlap_stats.total_sources)}</span>
                <span className="metric-label">{t('comparison.totalSources')}</span>
              </div>
              <div className="metric-card">
                <span className="metric-value">{format.number(comparison.overlap_stats.shared_sources)}</span>
                <span className="metric-label">{t('comparison.sharedSources')}</span>
              </div>
              {Object.entries(comparison.overlap_stats.unique_per_run).map(([runId, count]) => (
                <div key={runId} className="metric-card">
                  <span className="metric-value">{format.number(count)}</span>
                  <span className="metric-label">{t('comparison.uniqueTo', { run: runLabel(runId) })}</span>
                </div>
              ))}
            </div>
          </section>

          <CitedReport
            markdown={comparison.report}
            sources={sources}
            loadClaims={loadClaims}
            usageBySourceIndex={usageBySourceIndex}
            emptyNote={t('comparison.noReport')}
          />
        </>
      )}
    </div>
  )
}
