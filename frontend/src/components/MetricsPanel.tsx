import { Link } from 'react-router-dom'
import type { Evaluation, Metrics, QualityTier } from '../types'
import { formatDuration, formatPercent } from '../utils/format'
import { TIER_LABELS, TierDot } from './QualityBadge'
import { CheckIcon, XIcon } from './icons'

const TIER_DISPLAY_ORDER: QualityTier[] = ['high', 'medium', 'low', 'unknown']

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric-card">
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  )
}

const OUTCOME_LABELS: Record<string, string> = {
  ok: 'Completed',
  timed_out: 'Timed out',
  skipped: 'Skipped (budget exhausted)',
  cancelled: 'Cancelled',
  failed: 'Failed',
}

function outcomeText(outcomes: string[] | undefined): string {
  if (!outcomes || outcomes.length === 0) return '—'
  return outcomes.map((o) => OUTCOME_LABELS[o] ?? o).join(', ')
}

const UNAVAILABLE = 'unavailable'

/** Project memory: what was reused, from which earlier research. */
function ResearchMemory({ metrics }: { metrics: Metrics }) {
  const items = metrics.memory_items ?? []
  const enabled = metrics.memory_enabled
  if (enabled === undefined) return null // run predates project memory

  let summary: string
  if (!enabled) summary = 'Disabled for this run'
  else if (metrics.memory_error) summary = 'Retrieval failed'
  else if (metrics.memory_scope !== 'PROJECT') summary = 'Not a project run'
  else if (items.length === 0)
    summary = `No relevant findings (${metrics.memory_candidates ?? 0} considered)`
  else
    summary = `${items.length} of ${metrics.memory_candidates ?? 0} previous findings reused`

  return (
    <div className="research-memory">
      <h3 className="panel-heading">Research memory</h3>
      <p className="memory-summary">{summary}</p>
      {metrics.memory_error && (
        <p className="error-text" role="alert">
          {metrics.memory_error}
        </p>
      )}
      {items.length > 0 && (
        <ul className="memory-items">
          {items.map((item) => (
            <li key={`${item.run_id}-${item.text.slice(0, 24)}`}>
              <p className="memory-text">{item.text}</p>
              <p className="memory-meta">
                From:{' '}
                <Link to={`/runs/${item.run_id}`} className="memory-source-link">
                  {item.question || 'previous research'}
                </Link>
                <span className="memory-score">Relevance {item.score.toFixed(2)}</span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const STAGE_LABELS: Record<string, string> = {
  planner: 'Planner',
  critic: 'Critic',
  synthesis: 'Synthesis',
  repair: 'Citation repair',
}

/** LLM call/token diagnostics and any performance-budget outcomes. */
function LlmDiagnostics({ metrics }: { metrics: Metrics }) {
  const stages = Object.entries(metrics.llm_stage_stats ?? {})
  const tokensComplete = metrics.llm_tokens_complete !== false
  const notices = [
    metrics.suspended_ms && metrics.suspended_ms >= 5000
      ? `The computer was asleep for ${formatDuration(metrics.suspended_ms)} during this run; ` +
        'that time is excluded from the time budget.'
      : '',
    metrics.critic_fallback ? `Critic skipped: ${metrics.critic_fallback}.` : '',
    metrics.synthesis_fallback
      ? 'Synthesis exceeded its time budget; the report is a cited evidence summary.'
      : '',
    metrics.repair_skipped ? 'Citation repair skipped to stay within the time budget.' : '',
  ].filter(Boolean)
  if (!metrics.llm_calls && notices.length === 0) return null

  return (
    <div className="llm-diagnostics">
      <h3 className="panel-heading">Model usage</h3>
      <div className="metric-grid">
        <MetricCard label="LLM calls" value={metrics.llm_calls ?? 0} />
        <MetricCard
          label={tokensComplete ? 'Prompt tokens' : 'Prompt tokens (partial)'}
          value={metrics.llm_prompt_tokens ?? 0}
        />
        <MetricCard
          label={tokensComplete ? 'Output tokens' : 'Output tokens (partial)'}
          value={metrics.llm_output_tokens ?? 0}
        />
        {metrics.budget_seconds ? (
          <MetricCard label="Run budget" value={formatDuration(metrics.budget_seconds * 1000)} />
        ) : null}
      </div>
      {stages.length > 0 && (
        <table className="stage-table" aria-label="Per-stage model usage">
          <thead>
            <tr>
              <th scope="col">Stage</th>
              <th scope="col">Calls</th>
              <th scope="col">Time</th>
              <th scope="col">Context</th>
              <th scope="col">Prompt tok</th>
              <th scope="col">Output tok</th>
              <th scope="col">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {stages.map(([stage, s]) => (
              <tr key={stage}>
                <th scope="row">{STAGE_LABELS[stage] ?? stage}</th>
                <td>{s.calls}</td>
                <td>{formatDuration(s.ms)}</td>
                <td>{s.input_chars.toLocaleString()} chars</td>
                <td>{s.tokens_available === false ? UNAVAILABLE : s.prompt_tokens}</td>
                <td>{s.tokens_available === false ? UNAVAILABLE : s.output_tokens}</td>
                <td>{outcomeText(s.outcomes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {notices.length > 0 && (
        <ul className="budget-notices">
          {notices.map((notice) => (
            <li key={notice}>{notice}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

const EVALUATION_CHECKS: { key: keyof Evaluation; label: string }[] = [
  { key: 'has_citations', label: 'Report has citations' },
  { key: 'citations_valid', label: 'Citations are valid' },
  { key: 'single_sources_section', label: 'Single sources section' },
  { key: 'no_reasoning_markers', label: 'No reasoning markers' },
  { key: 'provenance_valid', label: 'Provenance is valid' },
]

export function MetricsPanel({
  metrics,
  evaluation,
}: {
  metrics: Metrics
  evaluation: Evaluation | null
}) {
  return (
    <div className="metrics-panel">
      <h3 className="panel-heading">Performance</h3>
      <div className="metric-grid">
        <MetricCard label="Total runtime" value={formatDuration(metrics.total_ms)} />
        <MetricCard label="Planner" value={formatDuration(metrics.planner_ms)} />
        <MetricCard label="Search" value={formatDuration(metrics.search_ms)} />
        <MetricCard label="Critic" value={formatDuration(metrics.critic_ms)} />
        <MetricCard label="Synthesis" value={formatDuration(metrics.synthesis_ms)} />
        <MetricCard label="Citation repair" value={formatDuration(metrics.citation_repair_ms)} />
        <MetricCard label="Iterations" value={metrics.iterations} />
        <MetricCard label="Queries executed" value={metrics.search_queries_executed} />
        <MetricCard label="Sources collected" value={metrics.sources_collected} />
        <MetricCard label="Sources selected" value={metrics.sources_selected} />
        <MetricCard label="Sources cited" value={metrics.sources_cited} />
        <MetricCard label="Citation coverage" value={formatPercent(metrics.citation_coverage)} />
        <MetricCard label="Memory hits" value={metrics.memory_hits} />
        <MetricCard label="Document chunks" value={metrics.document_chunks_retrieved} />
        {metrics.pages_attempted !== undefined && (
          <MetricCard
            label="Pages fetched"
            value={`${metrics.pages_fetched ?? 0}/${metrics.pages_attempted}`}
          />
        )}
        {metrics.snippet_fallbacks !== undefined && (
          <MetricCard label="Snippet fallbacks" value={metrics.snippet_fallbacks} />
        )}
        {metrics.planner_attempts !== undefined && metrics.planner_attempts > 1 && (
          <MetricCard label="Planner attempts" value={metrics.planner_attempts} />
        )}
      </div>

      <LlmDiagnostics metrics={metrics} />

      <ResearchMemory metrics={metrics} />

      {metrics.source_quality_tiers &&
        Object.keys(metrics.source_quality_tiers).length > 0 && (
          <div className="tier-distribution">
            <h3 className="panel-heading">Source quality</h3>
            <div className="tier-distribution-row" aria-label="Source quality distribution">
              {TIER_DISPLAY_ORDER.filter(
                (tier) => (metrics.source_quality_tiers?.[tier] ?? 0) > 0,
              ).map((tier) => (
                <span key={tier} className="tier-count">
                  <TierDot tier={tier} />
                  <span className="tier-count-value">{metrics.source_quality_tiers?.[tier]}</span>
                  <span className="tier-count-label">{TIER_LABELS[tier]}</span>
                </span>
              ))}
            </div>
          </div>
        )}

      {metrics.errors.length > 0 && (
        <div className="metrics-errors">
          <h3 className="panel-heading">Errors</h3>
          <ul>
            {metrics.errors.map((error, index) => (
              <li key={index} className="error-text">
                {error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {evaluation && (
        <div className="evaluation">
          <h3 className="panel-heading">
            Evaluation{' '}
            <span className={`badge ${evaluation.passed ? 'tone-success' : 'tone-danger'}`}>
              {evaluation.passed ? 'Passed' : 'Failed'}
            </span>
          </h3>
          <ul className="evaluation-list">
            {EVALUATION_CHECKS.map(({ key, label }) => {
              const passed = Boolean(evaluation[key])
              return (
                <li key={key} className={`evaluation-item ${passed ? 'passed' : 'failed'}`}>
                  <span className="evaluation-mark" aria-hidden="true">
                    {passed ? <CheckIcon size={13} /> : <XIcon size={13} />}
                  </span>
                  <span>{label}</span>
                  <span className="visually-hidden">{passed ? 'passed' : 'failed'}</span>
                </li>
              )
            })}
            <li className="evaluation-item neutral">
              <span className="evaluation-mark" aria-hidden="true">
                %
              </span>
              <span>Citation coverage {formatPercent(evaluation.citation_coverage)}</span>
            </li>
          </ul>
          {evaluation.notes.length > 0 && (
            <ul className="evaluation-notes">
              {evaluation.notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
