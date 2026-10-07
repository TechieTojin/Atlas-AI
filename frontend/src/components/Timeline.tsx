import type { RunEvent, RunStatus } from '../types'
import { asNumber, asString } from '../utils/format'
import { CheckIcon } from './icons'

interface TimelineStep {
  key: string
  label: string
  detail?: string
  failed?: boolean
}

function searchLabel(event: RunEvent): string {
  const index = asNumber(event.payload.index)
  const total = asNumber(event.payload.total)
  const query = asString(event.payload.query)
  if (index !== undefined && total !== undefined && query) {
    return `Searching ${index}/${total}: ${query}`
  }
  return event.message || 'Searching'
}

function stepFor(event: RunEvent): TimelineStep | null {
  const key = `${event.seq}`
  switch (event.type) {
    case 'RUN_STARTED':
      return { key, label: 'Run started' }
    case 'PLANNING_STARTED':
      return { key, label: 'Planning research' }
    case 'PLANNING_REPAIR_STARTED':
      return { key, label: 'Repairing research plan' }
    case 'PLAN_CREATED':
      return { key, label: 'Plan created' }
    case 'WAITING_FOR_PLAN_APPROVAL':
      return { key, label: 'Waiting for plan approval' }
    case 'PLAN_APPROVED':
      return { key, label: 'Plan approved' }
    case 'PLAN_EDITED':
      return { key, label: 'Plan edited' }
    case 'SEARCH_STARTED':
      return { key, label: 'Research started' }
    case 'SEARCH_QUERY_STARTED':
      return { key, label: searchLabel(event) }
    case 'SEARCH_QUERY_COMPLETED':
    case 'PAGE_FETCH_STARTED':
    case 'PAGE_FETCH_COMPLETED':
      return null
    case 'PAGE_FETCH_FAILED':
      return null
    case 'EVIDENCE_COLLECTED': {
      const total = asNumber(event.payload.total_items)
      return {
        key,
        label: total !== undefined ? `Evidence collected (${total} items)` : 'Evidence collected',
      }
    }
    case 'CRITIC_STARTED':
      return { key, label: 'Critic reviewing evidence' }
    case 'CRITIC_COMPLETED': {
      const score = asNumber(event.payload.score)
      return {
        key,
        label: 'Critic review complete',
        detail: score !== undefined ? `Score ${score}` : undefined,
      }
    }
    case 'MORE_RESEARCH_REQUESTED':
      return { key, label: `More research requested — iteration ${event.iteration + 1}` }
    case 'SYNTHESIS_STARTED':
      return { key, label: 'Synthesizing report' }
    case 'CITATION_REPAIR_STARTED':
      return { key, label: 'Repairing citations' }
    case 'CITATION_REPAIR_COMPLETED':
      return { key, label: 'Citations verified' }
    case 'REPORT_REGENERATED':
      return { key, label: 'Report regenerated' }
    case 'RUN_COMPLETED':
      return { key, label: 'Research complete' }
    case 'RUN_FAILED':
      return { key, label: 'Run failed', detail: event.message || undefined, failed: true }
    case 'CANCEL_REQUESTED':
      return { key, label: 'Cancelling…' }
    case 'RUN_CANCELLED':
      return { key, label: 'Cancelled by user', failed: true }
    default:
      // Follow-up, comparison, and knowledge-graph events never appear on run streams.
      return null
  }
}

type Phase = 'plan' | 'search' | 'critique' | 'synthesis' | 'done'

const PHASE_ORDER: Phase[] = ['plan', 'search', 'critique', 'synthesis', 'done']

const PHASE_LABELS: Record<Phase, string> = {
  plan: 'Planning',
  search: 'Searching sources',
  critique: 'Critique',
  synthesis: 'Synthesis',
  done: 'Complete',
}

function phaseOf(event: RunEvent): Phase {
  switch (event.type) {
    case 'RUN_STARTED':
    case 'PLANNING_STARTED':
    case 'PLANNING_REPAIR_STARTED':
    case 'PLAN_CREATED':
    case 'WAITING_FOR_PLAN_APPROVAL':
    case 'PLAN_APPROVED':
    case 'PLAN_EDITED':
      return 'plan'
    case 'SEARCH_STARTED':
    case 'SEARCH_QUERY_STARTED':
    case 'SEARCH_QUERY_COMPLETED':
    case 'PAGE_FETCH_STARTED':
    case 'PAGE_FETCH_COMPLETED':
    case 'PAGE_FETCH_FAILED':
    case 'EVIDENCE_COLLECTED':
    case 'MORE_RESEARCH_REQUESTED':
      return 'search'
    case 'CRITIC_STARTED':
    case 'CRITIC_COMPLETED':
      return 'critique'
    case 'SYNTHESIS_STARTED':
    case 'CITATION_REPAIR_STARTED':
    case 'CITATION_REPAIR_COMPLETED':
    case 'REPORT_REGENERATED':
      return 'synthesis'
    case 'RUN_COMPLETED':
    case 'RUN_FAILED':
    case 'RUN_CANCELLED':
    // Once cancellation is requested no later stage will run: show none pending.
    case 'CANCEL_REQUESTED':
      return 'done'
    default:
      return 'search'
  }
}

const TERMINAL_STATUSES: RunStatus[] = ['COMPLETED', 'FAILED', 'CANCELLED']

export function Timeline({ events, status }: { events: RunEvent[]; status: RunStatus }) {
  const steps = events
    .map((event) => ({ event, step: stepFor(event) }))
    .filter((entry): entry is { event: RunEvent; step: TimelineStep } => entry.step !== null)

  const terminal = TERMINAL_STATUSES.includes(status)
  const lastPhaseIndex =
    steps.length > 0
      ? Math.max(...steps.map(({ event }) => PHASE_ORDER.indexOf(phaseOf(event))))
      : -1
  const pendingPhases = terminal
    ? []
    : PHASE_ORDER.slice(Math.max(lastPhaseIndex + 1, 1)).filter((phase) => phase !== 'done' || true)

  return (
    <div className="timeline" aria-label="Research progress">
      <ol className="timeline-list">
        {steps.map(({ step }, index) => {
          const isLast = index === steps.length - 1
          const state = terminal || !isLast ? 'complete' : 'current'
          return (
            <li key={step.key} className={`timeline-step ${state}${step.failed ? ' failed' : ''}`}>
              <span className="step-marker" aria-hidden="true">
                {state === 'complete' && !step.failed ? (
                  <CheckIcon size={12} />
                ) : step.failed ? (
                  '✕'
                ) : (
                  <span className="pulse-dot" />
                )}
              </span>
              <span className="step-body">
                <span className="step-label">{step.label}</span>
                {step.detail && <span className="step-detail">{step.detail}</span>}
              </span>
            </li>
          )
        })}
        {pendingPhases.map((phase) => (
          <li key={phase} className="timeline-step pending">
            <span className="step-marker" aria-hidden="true">
              <span className="pending-dot" />
            </span>
            <span className="step-body">
              <span className="step-label">{PHASE_LABELS[phase]}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function RunStatChips({ events, iterations }: { events: RunEvent[]; iterations: number }) {
  const lastEvidence = [...events].reverse().find((event) => event.type === 'EVIDENCE_COLLECTED')
  const lastCritic = [...events].reverse().find((event) => event.type === 'CRITIC_COMPLETED')
  const sources = lastEvidence ? asNumber(lastEvidence.payload.total_items) : undefined
  const memoryHits = lastEvidence ? asNumber(lastEvidence.payload.memory_hits) : undefined
  const criticScore = lastCritic ? asNumber(lastCritic.payload.score) : undefined
  const maxIteration = events.reduce((max, event) => Math.max(max, event.iteration), 0)
  const iteration = Math.max(iterations, maxIteration, 1)

  return (
    <div className="stat-chips" aria-label="Run statistics">
      <span className="stat-chip">
        <span className="stat-chip-label">Iteration</span>
        <span className="stat-chip-value">{iteration}</span>
      </span>
      {sources !== undefined && (
        <span className="stat-chip">
          <span className="stat-chip-label">Sources</span>
          <span className="stat-chip-value">{sources}</span>
        </span>
      )}
      {criticScore !== undefined && (
        <span className="stat-chip">
          <span className="stat-chip-label">Critic score</span>
          <span className="stat-chip-value">{criticScore}</span>
        </span>
      )}
      {memoryHits !== undefined && (
        <span className="stat-chip">
          <span className="stat-chip-label">Memory hits</span>
          <span className="stat-chip-value">{memoryHits}</span>
        </span>
      )}
    </div>
  )
}
