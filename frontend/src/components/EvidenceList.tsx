import { useState } from 'react'
import type { Evidence } from '../types'
import { TIER_LABELS, TierDot } from './QualityBadge'
import type { QualityTier } from '../types'

const CLAMP_LENGTH = 280

const ORIGIN_LABELS: Record<Evidence['origin'], string> = {
  web: 'WEB',
  document: 'DOCUMENT',
  memory: 'MEMORY',
}

export function ExtractionBadge({ extraction }: { extraction: Evidence['extraction'] }) {
  if (extraction === 'full_page') {
    return <span className="badge extraction-badge full-page">Full page</span>
  }
  if (extraction === 'fallback_snippet') {
    return <span className="badge extraction-badge fallback">Snippet fallback</span>
  }
  return null
}

export function EvidenceTierBadge({ tier }: { tier: string | null | undefined }) {
  if (!tier) return null
  const label = TIER_LABELS[tier as QualityTier] ?? tier
  return (
    <span className={`quality-badge tier-${tier}`}>
      <TierDot tier={tier} />
      {label}
    </span>
  )
}

function EvidenceCard({ item }: { item: Evidence }) {
  const [expanded, setExpanded] = useState(false)
  const needsClamp = item.content.length > CLAMP_LENGTH
  const snippet =
    !needsClamp || expanded ? item.content : `${item.content.slice(0, CLAMP_LENGTH).trimEnd()}…`

  return (
    <article className="evidence-card">
      <header className="evidence-header">
        <span className="evidence-badges">
          <span className={`badge origin-${item.origin}`}>{ORIGIN_LABELS[item.origin]}</span>
          <ExtractionBadge extraction={item.extraction} />
          <EvidenceTierBadge tier={item.quality_tier} />
        </span>
        {item.relevance_score !== null && (
          <span className="evidence-score" title="Relevance score">
            Relevance {item.relevance_score.toFixed(2)}
          </span>
        )}
      </header>
      <p className="evidence-source">
        {item.source_title}
        {item.filename ? ` — ${item.filename}${item.page !== null ? `, p. ${item.page}` : ''}` : ''}
      </p>
      <p className="evidence-query">Found by: “{item.query}”</p>
      <p className="evidence-snippet">{snippet}</p>
      {needsClamp && (
        <button type="button" className="link-btn" onClick={() => setExpanded((value) => !value)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </article>
  )
}

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) {
    return <p className="empty-note">No evidence was collected for this run.</p>
  }
  return (
    <div className="evidence-list">
      {evidence.map((item, index) => (
        <EvidenceCard key={index} item={item} />
      ))}
    </div>
  )
}
