import { Link } from 'react-router-dom'
import { tierLabel, useI18n, type MessageKey, type Translate } from '../i18n'
import type { Evaluation, Metrics, QualityTier } from '../types'
import { TierDot } from './QualityBadge'
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

const OUTCOMES = ['ok', 'timed_out', 'skipped', 'cancelled', 'failed'] as const

function outcomeText(t: Translate, outcomes: string[] | undefined): string {
  if (!outcomes || outcomes.length === 0) return '—'
  return outcomes
    .map((o) => ((OUTCOMES as readonly string[]).includes(o) ? t(`metrics.outcome.${o as (typeof OUTCOMES)[number]}`) : o))
    .join(', ')
}

/** Project memory: what was reused, from which earlier research. */
function ResearchMemory({ metrics }: { metrics: Metrics }) {
  const { t, format } = useI18n()
  const items = metrics.memory_items ?? []
  const enabled = metrics.memory_enabled
  if (enabled === undefined) return null // run predates project memory

  let summary: string
  if (!enabled) summary = t('metrics.memory.disabled')
  else if (metrics.memory_error) summary = t('metrics.memory.failed')
  else if (metrics.memory_scope !== 'PROJECT') summary = t('metrics.memory.notProject')
  else if (items.length === 0) summary = t('metrics.memory.none', { count: metrics.memory_candidates ?? 0 })
  else summary = t('metrics.memory.reused', { used: items.length, count: metrics.memory_candidates ?? 0 })

  return (
    <div className="research-memory">
      <h3 className="panel-heading">{t('metrics.memory.title')}</h3>
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
                {t('metrics.memory.from')}{' '}
                <Link to={`/runs/${item.run_id}`} className="memory-source-link">
                  {item.question || t('common.previousResearch')}
                </Link>
                <span className="memory-score">
                  {t('metrics.memory.relevance', {
                    score: format.number(item.score, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
                  })}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const STAGES = ['planner', 'critic', 'synthesis', 'repair'] as const

function stageLabel(t: Translate, stage: string): string {
  return (STAGES as readonly string[]).includes(stage)
    ? t(`metrics.stage.${stage as (typeof STAGES)[number]}`)
    : stage
}

/** LLM call/token diagnostics and any performance-budget outcomes. */
function LlmDiagnostics({ metrics }: { metrics: Metrics }) {
  const { t, format } = useI18n()
  const stages = Object.entries(metrics.llm_stage_stats ?? {})
  const tokensComplete = metrics.llm_tokens_complete !== false
  const notices = [
    metrics.suspended_ms && metrics.suspended_ms >= 5000
      ? t('metrics.asleep', { duration: format.duration(metrics.suspended_ms) })
      : '',
    // The fallback reason is backend prose and is quoted as sent.
    metrics.critic_fallback ? t('metrics.criticSkipped', { reason: metrics.critic_fallback }) : '',
    metrics.synthesis_fallback ? t('metrics.synthesisFallback') : '',
    metrics.repair_skipped ? t('metrics.repairSkipped') : '',
  ].filter(Boolean)
  if (!metrics.llm_calls && notices.length === 0) return null
  const unavailable = t('common.unavailable')

  return (
    <div className="llm-diagnostics">
      <h3 className="panel-heading">{t('metrics.modelUsage')}</h3>
      <div className="metric-grid">
        <MetricCard label={t('metrics.llmCalls')} value={format.number(metrics.llm_calls ?? 0)} />
        <MetricCard
          label={tokensComplete ? t('metrics.promptTokens') : t('metrics.promptTokensPartial')}
          value={format.number(metrics.llm_prompt_tokens ?? 0)}
        />
        <MetricCard
          label={tokensComplete ? t('metrics.outputTokens') : t('metrics.outputTokensPartial')}
          value={format.number(metrics.llm_output_tokens ?? 0)}
        />
        {metrics.budget_seconds ? (
          <MetricCard label={t('metrics.runBudget')} value={format.duration(metrics.budget_seconds * 1000)} />
        ) : null}
      </div>
      {stages.length > 0 && (
        <table className="stage-table" aria-label={t('metrics.stageTable')}>
          <thead>
            <tr>
              <th scope="col">{t('metrics.colStage')}</th>
              <th scope="col">{t('metrics.colCalls')}</th>
              <th scope="col">{t('metrics.colTime')}</th>
              <th scope="col">{t('metrics.colContext')}</th>
              <th scope="col">{t('metrics.colPromptTokens')}</th>
              <th scope="col">{t('metrics.colOutputTokens')}</th>
              <th scope="col">{t('metrics.colOutcome')}</th>
            </tr>
          </thead>
          <tbody>
            {stages.map(([stage, s]) => (
              <tr key={stage}>
                <th scope="row">{stageLabel(t, stage)}</th>
                <td>{format.number(s.calls)}</td>
                <td>{format.duration(s.ms)}</td>
                <td>{t('metrics.chars', { count: s.input_chars })}</td>
                <td>{s.tokens_available === false ? unavailable : format.number(s.prompt_tokens)}</td>
                <td>{s.tokens_available === false ? unavailable : format.number(s.output_tokens)}</td>
                <td>{outcomeText(t, s.outcomes)}</td>
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

const EVALUATION_CHECKS: { key: keyof Evaluation; label: MessageKey }[] = [
  { key: 'has_citations', label: 'metrics.check.has_citations' },
  { key: 'citations_valid', label: 'metrics.check.citations_valid' },
  { key: 'single_sources_section', label: 'metrics.check.single_sources_section' },
  { key: 'no_reasoning_markers', label: 'metrics.check.no_reasoning_markers' },
  { key: 'provenance_valid', label: 'metrics.check.provenance_valid' },
]

export function MetricsPanel({
  metrics,
  evaluation,
}: {
  metrics: Metrics
  evaluation: Evaluation | null
}) {
  const { t, format } = useI18n()
  return (
    <div className="metrics-panel">
      <h3 className="panel-heading">{t('metrics.performance')}</h3>
      <div className="metric-grid">
        <MetricCard label={t('metrics.totalRuntime')} value={format.duration(metrics.total_ms)} />
        <MetricCard label={t('metrics.planner')} value={format.duration(metrics.planner_ms)} />
        <MetricCard label={t('metrics.search')} value={format.duration(metrics.search_ms)} />
        <MetricCard label={t('metrics.critic')} value={format.duration(metrics.critic_ms)} />
        <MetricCard label={t('metrics.synthesis')} value={format.duration(metrics.synthesis_ms)} />
        <MetricCard label={t('metrics.citationRepair')} value={format.duration(metrics.citation_repair_ms)} />
        <MetricCard label={t('metrics.iterations')} value={format.number(metrics.iterations)} />
        <MetricCard label={t('metrics.queriesExecuted')} value={format.number(metrics.search_queries_executed)} />
        <MetricCard label={t('metrics.sourcesCollected')} value={format.number(metrics.sources_collected)} />
        <MetricCard label={t('metrics.sourcesSelected')} value={format.number(metrics.sources_selected)} />
        <MetricCard label={t('metrics.sourcesCited')} value={format.number(metrics.sources_cited)} />
        <MetricCard label={t('metrics.citationCoverage')} value={format.percentValue(metrics.citation_coverage)} />
        <MetricCard label={t('metrics.memoryHits')} value={format.number(metrics.memory_hits)} />
        <MetricCard label={t('metrics.documentChunks')} value={format.number(metrics.document_chunks_retrieved)} />
        {metrics.pages_attempted !== undefined && (
          <MetricCard
            label={t('metrics.pagesFetched')}
            value={`${format.number(metrics.pages_fetched ?? 0)}/${format.number(metrics.pages_attempted)}`}
          />
        )}
        {metrics.snippet_fallbacks !== undefined && (
          <MetricCard label={t('metrics.snippetFallbacks')} value={format.number(metrics.snippet_fallbacks)} />
        )}
        {metrics.planner_attempts !== undefined && metrics.planner_attempts > 1 && (
          <MetricCard label={t('metrics.plannerAttempts')} value={format.number(metrics.planner_attempts)} />
        )}
      </div>

      <LlmDiagnostics metrics={metrics} />

      <ResearchMemory metrics={metrics} />

      {metrics.source_quality_tiers &&
        Object.keys(metrics.source_quality_tiers).length > 0 && (
          <div className="tier-distribution">
            <h3 className="panel-heading">{t('metrics.sourceQuality')}</h3>
            <div className="tier-distribution-row" aria-label={t('metrics.sourceQualityLabel')}>
              {TIER_DISPLAY_ORDER.filter(
                (tier) => (metrics.source_quality_tiers?.[tier] ?? 0) > 0,
              ).map((tier) => (
                <span key={tier} className="tier-count">
                  <TierDot tier={tier} />
                  <span className="tier-count-value">{metrics.source_quality_tiers?.[tier]}</span>
                  <span className="tier-count-label">{tierLabel(t, tier)}</span>
                </span>
              ))}
            </div>
          </div>
        )}

      {metrics.errors.length > 0 && (
        <div className="metrics-errors">
          <h3 className="panel-heading">{t('metrics.errors')}</h3>
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
            {t('metrics.evaluation')}{' '}
            <span className={`badge ${evaluation.passed ? 'tone-success' : 'tone-danger'}`}>
              {evaluation.passed ? t('metrics.passed') : t('metrics.failed')}
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
                  <span>{t(label)}</span>
                  <span className="visually-hidden">{passed ? t('common.passed') : t('common.failed')}</span>
                </li>
              )
            })}
            <li className="evaluation-item neutral">
              <span className="evaluation-mark" aria-hidden="true">
                %
              </span>
              <span>{t('metrics.coverage', { value: format.percentValue(evaluation.citation_coverage) })}</span>
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
