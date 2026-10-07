import { useState } from 'react'
import type { QualityTier, SourceQuality } from '../types'

export const TIER_LABELS: Record<QualityTier, string> = {
  high: 'High authority',
  medium: 'Medium authority',
  low: 'Low authority',
  unknown: 'Unverified',
}

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
  const [expanded, setExpanded] = useState(false)
  if (!quality) return null

  const label = `${quality.category} · ${TIER_LABELS[quality.tier] ?? quality.tier}`

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
          <span className="quality-score">Quality score {quality.score.toFixed(2)}</span>
          {quality.signals.length > 0 && (
            <ul className="quality-signals" aria-label="Quality signals">
              {quality.signals.map((signal, index) => (
                <li key={index}>{signal}</li>
              ))}
            </ul>
          )}
          {quality.warnings.length > 0 && (
            <ul className="quality-warnings" aria-label="Quality warnings">
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
