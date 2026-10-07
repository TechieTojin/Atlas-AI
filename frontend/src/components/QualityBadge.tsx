import { useState } from 'react'
import { qualityCategoryLabel, tierLabel, useI18n } from '../i18n'
import type { QualityTier, SourceQuality } from '../types'

export function tierRank(tier: QualityTier | string): number {
  switch (tier) {
    case 'high':
      return 3
    case 'medium':
      return 2
    case 'low':
      return 1
    default:
      return 0
  }
}

export function TierDot({ tier }: { tier: QualityTier | string }) {
  return <span className={`quality-dot tier-${tier}`} aria-hidden="true" />
}

/**
 * Small source-quality badge: a tier-colored dot plus "Category · Tier".
 * When `expandable`, clicking it reveals the score, signals, and warnings.
 */
export function QualityBadge({
  quality,
  expandable = false,
}: {
  quality: SourceQuality | null | undefined
  expandable?: boolean
}) {
  const { t, format } = useI18n()
  const [expanded, setExpanded] = useState(false)
  if (!quality) return null

  const label = `${qualityCategoryLabel(t, quality.category)} · ${tierLabel(t, quality.tier)}`

  if (!expandable) {
    return (
      <span className={`quality-badge tier-${quality.tier}`}>
        <TierDot tier={quality.tier} />
        {label}
      </span>
    )
  }

  return (
    <span className="quality-wrap">
      <button
        type="button"
        className={`quality-badge expandable tier-${quality.tier}`}
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <TierDot tier={quality.tier} />
        {label}
      </button>
      {expanded && (
        <span className="quality-details">
          <span className="quality-score">
            {t('quality.score', {
              score: format.number(quality.score, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
            })}
          </span>
          {quality.signals.length > 0 && (
            <ul className="quality-signals" aria-label={t('quality.signals')}>
              {quality.signals.map((signal, index) => (
                <li key={index}>{signal}</li>
              ))}
            </ul>
          )}
          {quality.warnings.length > 0 && (
            <ul className="quality-warnings" aria-label={t('quality.warnings')}>
              {quality.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          )}
        </span>
      )}
    </span>
  )
}
