import { modeBadge, statusLabel, templateName, useI18n } from '../i18n'
import type { RunMode, RunStatus } from '../types'
import { isActiveStatus } from '../types'

function statusTone(status: RunStatus): string {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED' || status === 'CANCELLING') return 'muted'
  if (status === 'AWAITING_APPROVAL') return 'warning'
  return 'active'
}

export function StatusBadge({ status }: { status: RunStatus }) {
  const { t } = useI18n()
  return (
    <span className={`badge status-badge tone-${statusTone(status)}`} data-status={status}>
      {isActiveStatus(status) && <span className="badge-pulse" aria-hidden="true" />}
      {statusLabel(t, status)}
    </span>
  )
}

export function StatusDot({ status }: { status: RunStatus }) {
  const { t } = useI18n()
  const label = statusLabel(t, status)
  return (
    <span
      className={`status-dot tone-${statusTone(status)}${isActiveStatus(status) ? ' pulsing' : ''}`}
      role="img"
      aria-label={label}
      title={label}
    />
  )
}

export function ModeBadge({ mode }: { mode: RunMode }) {
  const { t } = useI18n()
  return <span className={`badge mode-badge mode-${mode.toLowerCase()}`}>{modeBadge(t, mode)}</span>
}

/** Report-template badge; renders nothing for the standard template. */
export function TemplateBadge({ template }: { template: string | undefined | null }) {
  const { t } = useI18n()
  if (!template || template === 'STANDARD') return null
  return <span className="badge template-badge">{templateName(t, template)}</span>
}
