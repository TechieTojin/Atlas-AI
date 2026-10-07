import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import type { KnowledgeGap, ProjectFindingItem, ProjectOverview as Overview } from '../types'
import { relativeTime } from '../utils/format'
import { ModeBadge, StatusDot, statusLabel } from './StatusBadge'

/** One snapshot number. Zero is shown plainly, never as a placeholder. */
function StatCard({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="metric-card">
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
      {hint && <span className="metric-hint">{hint}</span>}
    </div>
  )
}

/** A finding, always traceable to the research that produced it. */
function FindingCard({ finding }: { finding: ProjectFindingItem }) {
  return (
    <li className="finding-card">
      <p className="finding-text">{finding.text}</p>
      <p className="finding-meta">
        {finding.section && <span className="finding-section">{finding.section}</span>}
        <Link to={`/runs/${finding.run_id}`} className="finding-source-link">
          {finding.question || 'previous research'}
        </Link>
        {finding.support > 1 && (
          <span className="finding-support" title="Independently found by several runs">
            {finding.support} runs
          </span>
        )}
        {finding.sources && finding.sources.length > 0 && (
          <span className="finding-cites">
            {finding.sources.length} source{finding.sources.length === 1 ? '' : 's'}
          </span>
        )}
      </p>
    </li>
  )
}

function GapRow({ gap }: { gap: KnowledgeGap }) {
  return (
    <li className="gap-row">
      <p className="gap-text">{gap.text}</p>
      <p className="gap-meta">
        {gap.reason}{' '}
        <Link to={`/runs/${gap.run_id}`} className="finding-source-link">
          View research
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
        <p>Loading overview…</p>
      </div>
    )
  }

  if (error || !overview) {
    return (
      <div className="page-state">
        <p className="error-text" role="alert">
          {error ?? 'This project overview could not be loaded.'}
        </p>
        <button type="button" className="btn" onClick={() => void load()}>
          Try again
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
          label="Runs"
          value={stats.runs}
          hint={
            stats.runs > 0 && stats.completed_runs !== stats.runs
              ? `${stats.completed_runs} completed`
              : undefined
          }
        />
        <StatCard label="Findings" value={stats.findings} />
        <StatCard label="Sources" value={stats.unique_sources} hint="unique" />
        <StatCard label="Documents" value={stats.documents} />
      </div>

      {!hasResearch && stats.documents === 0 && (
        <section className="card empty-project">
          <h3>Start your first research</h3>
          <p className="hint-text">
            Atlas builds this project's knowledge from the research you run here. Findings
            from each completed run become reusable context for later questions.
          </p>
          <button type="button" className="btn primary" onClick={onStartResearch}>
            Start research
          </button>
        </section>
      )}

      {!hasResearch && stats.documents > 0 && (
        <section className="card empty-project">
          <h3>Documents are ready</h3>
          <p className="hint-text">
            This project has {stats.documents} document{stats.documents === 1 ? '' : 's'} but
            no research yet. Run a question against them to start building knowledge.
          </p>
          <button type="button" className="btn primary" onClick={onStartResearch}>
            Start research
          </button>
        </section>
      )}

      {current_understanding.length > 0 && (
        <section className="overview-section">
          <h3 className="panel-heading">Current understanding</h3>
          <p className="section-hint">
            What this project's completed research has established, strongest first.
          </p>
          <ul className="finding-list">
            {current_understanding.map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </ul>
        </section>
      )}

      {key_findings.length > 0 && (
        <section className="overview-section">
          <h3 className="panel-heading">Key findings</h3>
          <ul className="finding-list">
            {(showAllFindings ? allFindings : key_findings).map((finding) => (
              <FindingCard key={finding.id} finding={finding} />
            ))}
          </ul>
          {stats.findings > allFindings.length && (
            <p className="section-hint">
              {allFindings.length} of {stats.findings} findings shown; near-duplicates are
              grouped.
            </p>
          )}
          <button
            type="button"
            className="btn ghost"
            onClick={() => setShowAllFindings((shown) => !shown)}
            aria-expanded={showAllFindings}
          >
            {showAllFindings ? 'Show fewer findings' : 'View all findings'}
          </button>
        </section>
      )}

      {hasResearch && current_understanding.length === 0 && (
        <section className="overview-section">
          <h3 className="panel-heading">Current understanding</h3>
          <p className="hint-text">
            No findings yet. Findings appear once a run completes with a cited report.
          </p>
        </section>
      )}

      <section className="overview-section">
        <h3 className="panel-heading">Knowledge gaps</h3>
        {knowledge_gaps.length === 0 ? (
          <p className="hint-text">No clear knowledge gaps have been identified yet.</p>
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
          <h3 className="panel-heading">Recent research</h3>
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
                  <span className="history-meta">{statusLabel(run.status)}</span>
                  {run.findings_added > 0 && (
                    <span className="history-meta">
                      {run.findings_added} finding{run.findings_added === 1 ? '' : 's'} added
                    </span>
                  )}
                  <span className="history-meta">{relativeTime(run.created_at)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
