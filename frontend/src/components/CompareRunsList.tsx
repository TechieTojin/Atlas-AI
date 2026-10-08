import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { agoLabel, languageName, useI18n, useOutputLanguage } from '../i18n'
import type { RunSummary } from '../types'
import { ModeBadge, StatusDot, TemplateBadge } from './StatusBadge'

export const MIN_COMPARE = 2
export const MAX_COMPARE = 5

/**
 * A runs list where completed runs can be multi-selected (2–5) and compared.
 */
export function CompareRunsList({
  runs,
  projectId,
  emptyNote,
}: {
  runs: RunSummary[]
  projectId?: string
  emptyNote?: string
}) {
  const navigate = useNavigate()
  const { t, format, language: ui } = useI18n()
  const output = useOutputLanguage('comparison')
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
        output_language: output.effective,
      })
      navigate(`/comparisons/${comparison.id}`)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  if (runs.length === 0) {
    return <p className="empty-note">{emptyNote ?? t('compareRuns.empty')}</p>
  }

  return (
    <div className="compare-runs">
      <div className="compare-bar">
        <span className="hint-text">{t('compareRuns.hint')}</span>
        <button
          type="button"
          className="btn primary"
          disabled={!canCompare}
          onClick={() => void handleCompare()}
        >
          {busy
            ? t('compareRuns.comparing')
            : selected.length > 0
              ? t('compareRuns.compareCount', { count: selected.length })
              : t('compareRuns.compare')}
        </button>
      </div>
      {output.fellBack && !output.loading && (
        <p className="hint-text compare-language-note" role="note">
          {t('outputLanguage.comparisonInEnglish', { preferred: languageName(output.preferred, ui.locale) })}
        </p>
      )}
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
                aria-label={t('common.selectForComparison', { name: run.title || run.query })}
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
                <span className="history-meta">{agoLabel(t, format, run.created_at)}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
