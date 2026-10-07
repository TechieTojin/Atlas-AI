import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, comparisonExportUrl, errorMessage } from '../api/client'
import { CitedReport } from '../components/CitedReport'
import { DownloadIcon, TrashIcon } from '../components/icons'
import { useEventStream } from '../hooks/useEventStream'
import type { Comparison, ComparisonStatus } from '../types'

/** A compact execution summary. Deliberately small: enough to tell why a
 *  comparison took the time it did, without a metrics page. */
function ComparisonMetricsRow({ comparison }: { comparison: Comparison }) {
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
    typeof value === 'number' ? value.toLocaleString() : 'unavailable'

  if (!metrics.model && seconds === null) return null

  return (
    <dl className="comparison-metrics" role="group" aria-label="Execution details">
      {seconds !== null && (
        <div>
          <dt>Elapsed</dt>
          <dd>{seconds < 60 ? `${seconds.toFixed(1)}s` : `${(seconds / 60).toFixed(1)}m`}</dd>
        </div>
      )}
      {metrics.model && (
        <div>
          <dt>Model</dt>
          <dd>{metrics.model}</dd>
        </div>
      )}
      {typeof metrics.prefill_ms === 'number' && (
        <div>
          <dt>Prompt read</dt>
          <dd>{(metrics.prefill_ms / 1000).toFixed(1)}s</dd>
        </div>
      )}
      {typeof metrics.generation_ms === 'number' && (
        <div>
          <dt>Writing</dt>
          <dd>{(metrics.generation_ms / 1000).toFixed(1)}s</dd>
        </div>
      )}
      <div>
        <dt>Output tokens</dt>
        <dd>
          {tokens(metrics.output_tokens)}
          {metrics.output_cap_reached === true && ' (cap reached)'}
        </dd>
      </div>
      <div>
        <dt>Prompt tokens</dt>
        <dd>{tokens(metrics.prompt_tokens)}</dd>
      </div>
      {typeof metrics.repair_calls === 'number' && metrics.repair_calls > 0 && (
        <div>
          <dt>Repairs</dt>
          <dd>{metrics.repair_calls}</dd>
        </div>
      )}
    </dl>
  )
}

export function ComparisonPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
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
        <p>Loading comparison…</p>
      </div>
    )
  }

  if (error || !comparison) {
    return (
      <div className="page-state">
        <h1>Comparison not found</h1>
        <p className="error-text">{error ?? 'This comparison does not exist.'}</p>
        <Link className="btn primary" to="/">
          Back to research
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
    if (!window.confirm('Delete this comparison? This cannot be undone.')) return
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
          <h1 className="run-query">{comparison.title || 'Comparison'}</h1>
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
              {comparison.status}
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
                {comparison.status === 'CANCELLING' ? 'Cancelling…' : 'Cancel'}
              </span>
            </button>
          )}
          {comparison.status === 'COMPLETED' && (
            <a className="btn" href={comparisonExportUrl(comparison.id)} download>
              <DownloadIcon size={14} />
              <span>Export</span>
            </a>
          )}
          <button
            type="button"
            className="btn danger-ghost"
            onClick={() => void handleDelete()}
            aria-label="Delete comparison"
          >
            <TrashIcon size={14} />
            <span>Delete</span>
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
              ? 'Stopping the comparison…'
              : `Comparing ${comparison.run_ids.length} runs…`}
          </p>
        </div>
      )}

      {comparison.status === 'TIMED_OUT' && (
        <section className="card failure-card">
          <h2>Comparison timed out</h2>
          <p className="error-text">
            {comparison.error || 'This comparison ran past its time limit and was stopped.'}
          </p>
        </section>
      )}

      {comparison.status === 'CANCELLED' && (
        <section className="card failure-card">
          <h2>Comparison cancelled</h2>
          <p className="hint-text">{comparison.error || 'This comparison was cancelled.'}</p>
        </section>
      )}

      {comparison.status === 'FAILED' && (
        <section className="card failure-card">
          <h2>Comparison failed</h2>
          <p className="error-text">{comparison.error || 'This comparison did not finish.'}</p>
        </section>
      )}

      {comparison.status !== 'PENDING' && <ComparisonMetricsRow comparison={comparison} />}

      {comparison.status === 'COMPLETED' && (
        <>
          <section aria-label="Source overlap">
            <h3 className="panel-heading">Source overlap</h3>
            <div className="metric-grid">
              <div className="metric-card">
                <span className="metric-value">{comparison.overlap_stats.total_sources}</span>
                <span className="metric-label">Total sources</span>
              </div>
              <div className="metric-card">
                <span className="metric-value">{comparison.overlap_stats.shared_sources}</span>
                <span className="metric-label">Shared sources</span>
              </div>
              {Object.entries(comparison.overlap_stats.unique_per_run).map(([runId, count]) => (
                <div key={runId} className="metric-card">
                  <span className="metric-value">{count}</span>
                  <span className="metric-label">Unique to {runLabel(runId)}</span>
                </div>
              ))}
            </div>
          </section>

          <CitedReport
            markdown={comparison.report}
            sources={sources}
            loadClaims={loadClaims}
            usageBySourceIndex={usageBySourceIndex}
            emptyNote="No comparison report was produced."
          />
        </>
      )}
    </div>
  )
}
