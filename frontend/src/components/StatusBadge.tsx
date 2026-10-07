import type { RunMode, RunStatus } from '../types'
import { isActiveStatus } from '../types'

const STATUS_LABELS: Record<RunStatus, string> = {
  PENDING: 'Pending',
  PLANNING: 'Planning',
  AWAITING_APPROVAL: 'Awaiting approval',
  RESEARCHING: 'Researching',
  CRITIQUING: 'Critiquing',
  SYNTHESIZING: 'Synthesizing',
  CANCELLING: 'Cancelling…',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
}

function statusTone(status: RunStatus): string {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED' || status === 'CANCELLING') return 'muted'
  if (status === 'AWAITING_APPROVAL') return 'warning'
  return 'active'
}

export function statusLabel(status: RunStatus): string {
  return STATUS_LABELS[status]
}

export function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={`badge status-badge tone-${statusTone(status)}`} data-status={status}>
      {isActiveStatus(status) && <span className="badge-pulse" aria-hidden="true" />}
      {STATUS_LABELS[status]}
    </span>
  )
}

export function StatusDot({ status }: { status: RunStatus }) {
  return (
    <span
      className={`status-dot tone-${statusTone(status)}${isActiveStatus(status) ? ' pulsing' : ''}`}
      role="img"
      aria-label={STATUS_LABELS[status]}
      title={STATUS_LABELS[status]}
    />
  )
}

export function ModeBadge({ mode }: { mode: RunMode }) {
  return <span className={`badge mode-badge mode-${mode.toLowerCase()}`}>{mode}</span>
}

/** "LITERATURE_REVIEW" → "Literature Review"; blank templates read as Standard. */
export function templateLabel(template: string | undefined | null): string {
  return (template || 'STANDARD')
    .toLowerCase()
    .split('_')
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(' ')
}

/** Report-template badge; renders nothing for the standard template. */
export function TemplateBadge({ template }: { template: string | undefined | null }) {
  if (!template || template === 'STANDARD') return null
  return <span className="badge template-badge">{templateLabel(template)}</span>
}
