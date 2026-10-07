import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import type { RunSummary } from '../types'
import { ModeBadge, StatusDot, TemplateBadge } from './StatusBadge'
import { relativeTime } from '../utils/format'

export const MIN_COMPARE = 2
export const MAX_COMPARE = 5

/**
 * A runs list where completed runs can be multi-selected (2–5) and compared.
 */
export function CompareRunsList({
  runs,
  projectId,
  emptyNote = 'No research runs yet.',
}: {
  runs: RunSummary[]
  projectId?: string
  emptyNote?: string
}) {
  const navigate = useNavigate()
  const [selected, setSelected] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggle = (id: string) => {
    setSelected((previous) =>
      previous.includes(id) ? previous.filter((existing) => existing !== id) : [...previous, id],
    )
  }

  const canCompare = selected.length >= MIN_COMPARE && selected.length <= MAX_COMPARE && !busy

  const handleCompare = async () => {
    if (!canCompare) return
    setBusy(true)
    setError(null)
    try {
      const comparison = await api.createComparison({
        run_ids: selected,
        ...(projectId ? { project_id: projectId } : {}),
      })
      navigate(`/comparisons/${comparison.id}`)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  if (runs.length === 0) {
    return <p className="empty-note">{emptyNote}</p>
  }

  return (
    <div className="compare-runs">
      <div className="compare-bar">
        <span className="hint-text">Select 2–5 completed runs to compare.</span>
        <button
          type="button"
          className="btn primary"
          disabled={!canCompare}
          onClick={() => void handleCompare()}
        >
          {busy ? 'Comparing…' : `Compare${selected.length > 0 ? ` (${selected.length})` : ''}`}
        </button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <ul className="run-rows">
        {runs.map((run) => {
          const completed = run.status === 'COMPLETED'
          const checked = selected.includes(run.id)
          return (
            <li key={run.id} className="run-row">
              <input
                type="checkbox"
                className="compare-checkbox"
                aria-label={`Select ${run.title || run.query} for comparison`}
                checked={checked}
                disabled={!completed || (!checked && selected.length >= MAX_COMPARE)}
                onChange={() => toggle(run.id)}
              />
              <StatusDot status={run.status} />
              <Link to={`/runs/${run.id}`} className="run-row-title">
                {run.title || run.query}
              </Link>
              <span className="run-row-meta">
                <TemplateBadge template={run.template} />
                <ModeBadge mode={run.mode} />
                <span className="history-meta">{relativeTime(run.created_at)}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
