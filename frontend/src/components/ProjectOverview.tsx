import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { agoLabel, statusLabel, useI18n } from '../i18n'
import type { KnowledgeGap, ProjectFindingItem, ProjectOverview as Overview } from '../types'
import { ModeBadge, StatusDot } from './StatusBadge'

/** One snapshot number. Zero is shown plainly, never as a placeholder. */
function StatCard({ label, value, hint }: { label: string; value: number; hint?: string }) {
  const { format } = useI18n()
  return (
    <div className="metric-card">
      <span className="metric-value">{format.number(value)}</span>
      <span className="metric-label">{label}</span>
      {hint && <span className="metric-hint">{hint}</span>}
    </div>
  )
}

/** A finding, always traceable to the research that produced it. */
function FindingCard({ finding }: { finding: ProjectFindingItem }) {
  const { t } = useI18n()
  return (
    <li className="finding-card">
      <p className="finding-text">{finding.text}</p>
      <p className="finding-meta">
        {finding.section && <span className="finding-section">{finding.section}</span>}
        <Link to={`/runs/${finding.run_id}`} className="finding-source-link">
          {finding.question || t('common.previousResearch')}
        </Link>
        {finding.support > 1 && (
          <span className="finding-support" title={t('overview.supportTitle')}>
            {t('overview.supportRuns', { count: finding.support })}
          </span>
        )}
        {finding.sources && finding.sources.length > 0 && (
          <span className="finding-cites">{t('overview.sourceCount', { count: finding.sources.length })}</span>
        )}
      </p>
    </li>
  )
}

function GapRow({ gap }: { gap: KnowledgeGap }) {
  const { t } = useI18n()
  return (
    <li className="gap-row">
      <p className="gap-text">{gap.text}</p>
      <p className="gap-meta">
        {gap.reason}{' '}
        <Link to={`/runs/${gap.run_id}`} className="finding-source-link">
          {t('overview.viewResearch')}
        </Link>
      </p>
    </li>
  )
}

export function ProjectOverview({
  projectId,
  onStartResearch,
}: {
  projectId: string
  onStartResearch: () => void
}) {
  const { t, format } = useI18n()
  const [overview, setOverview] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAllFindings, setShowAllFindings] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setOverview(await api.getProjectOverview(projectId))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('overview.loading')}</p>
      </div>
    )
  }

  if (error || !overview) {
    return (
      <div className="page-state">
        <p className="error-text" role="alert">
          {error ?? t('overview.loadFailed')}
        </p>
        <button type="button" className="btn" onClick={() => void load()}>
          {t('common.tryAgain')}
        </button>
      </div>
    )
  }

  const { stats, current_understanding, key_findings, knowledge_gaps, recent_runs } = overview
  const allFindings = [...current_understanding, ...key_findings]
  const hasResearch = stats.runs > 0

  return (
    <div className="project-overview">
      {overview.project.description && (
        <p className="project-description">{overview.project.description}</p>
      )}

      <div className="metric-grid">
        <StatCard
          label={t('overview.runs')}
          value={stats.runs}
          hint={
            stats.runs > 0 && stats.completed_runs !== stats.runs
              ? t('overview.completed', { count: stats.completed_runs })
              : undefined
          }
        />
        <StatCard label={t('overview.findings')} value={stats.findings} />
        <StatCard label={t('overview.sources')} value={stats.unique_sources} hint={t('overview.unique')} />
        <StatCard label={t('overview.documents')} value={stats.documents} />
      </div>

      {!hasResearch && stats.documents === 0 && (
        <section className="card empty-project">
          <h3>{t('overview.firstResearchTitle')}</h3>
          <p className="hint-text">{t('overview.firstResearchText')}</p>
          <button type="button" className="btn primary" onClick={onStartResearch}>
            {t('common.startResearch')}
          </button>
        </section>
      )}

      {!hasResearch && stats.documents > 0 && (
        <section className="card empty-project">
          <h3>{t('overview.documentsReadyTitle')}</h3>
          <p className="hint-text">{t('overview.documentsReadyText', { count: stats.documents })}</p>
          <button type="button" className="btn primary" onClick={onStartResearch}>
            {t('common.startResearch')}
          </button>
        </section>
      )}

      {current_understanding.length > 0 && (
        <section className="overview-section">
          <h3 className="panel-heading">{t('overview.currentUnderstanding')}</h3>
          <p className="section-hint">{t('overview.currentHint')}</p>
          <ul className="finding-list">
            {current_understanding.map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </ul>
        </section>
      )}

      {key_findings.length > 0 && (
        <section className="overview-section">
          <h3 className="panel-heading">{t('overview.keyFindings')}</h3>
          <ul className="finding-list">
            {(showAllFindings ? allFindings : key_findings).map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </ul>
          {stats.findings > allFindings.length && (
            <p className="section-hint">
              {t('overview.shownOf', { shown: allFindings.length, total: stats.findings })}
            </p>
          )}
          <button
            type="button"
            className="btn ghost"
            onClick={() => setShowAllFindings((shown) => !shown)}
            aria-expanded={showAllFindings}
          >
            {showAllFindings ? t('overview.showFewer') : t('overview.viewAll')}
          </button>
        </section>
      )}

      {hasResearch && current_understanding.length === 0 && (
        <section className="overview-section">
          <h3 className="panel-heading">{t('overview.currentUnderstanding')}</h3>
          <p className="hint-text">{t('overview.noFindings')}</p>
        </section>
      )}

      <section className="overview-section">
        <h3 className="panel-heading">{t('overview.knowledgeGaps')}</h3>
        {knowledge_gaps.length === 0 ? (
          <p className="hint-text">{t('overview.noGaps')}</p>
        ) : (
          <ul className="gap-list">
            {knowledge_gaps.map((gap) => (
              <GapRow key={`${gap.run_id}-${gap.text.slice(0, 32)}`} gap={gap} />
            ))}
          </ul>
        )}
      </section>

      {recent_runs.length > 0 && (
        <section className="overview-section">
          <h3 className="panel-heading">{t('overview.recentResearch')}</h3>
          <ul className="run-rows">
            {recent_runs.map((run) => (
              <li
                key={run.id}
                className={`run-row${
                  run.status === 'FAILED' || run.status === 'CANCELLED' ? ' inactive' : ''
                }`}
              >
                <StatusDot status={run.status} />
                <Link to={`/runs/${run.id}`} className="run-row-title">
                  {run.title || run.query}
                </Link>
                <span className="run-row-meta">
                  <ModeBadge mode={run.mode} />
                  <span className="history-meta">{statusLabel(t, run.status)}</span>
                  {run.findings_added > 0 && (
                    <span className="history-meta">
                      {t('overview.findingsAdded', { count: run.findings_added })}
                    </span>
                  )}
                  <span className="history-meta">{agoLabel(t, format, run.created_at)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
