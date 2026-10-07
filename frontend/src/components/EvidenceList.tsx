import { useState } from 'react'
import { tierLabel, useI18n } from '../i18n'
import type { Evidence } from '../types'
import { TierDot } from './QualityBadge'

const CLAMP_LENGTH = 280

export function ExtractionBadge({ extraction }: { extraction: Evidence['extraction'] }) {
  const { t } = useI18n()
  if (extraction === 'full_page') {
    return <span className="badge extraction-badge full-page">{t('evidence.fullPage')}</span>
  }
  if (extraction === 'fallback_snippet') {
    return <span className="badge extraction-badge fallback">{t('evidence.snippetFallback')}</span>
  }
  return null
}

export function EvidenceTierBadge({ tier }: { tier: string | null | undefined }) {
  const { t } = useI18n()
  if (!tier) return null
  const label = tierLabel(t, tier)
  return (
    <span className={`quality-badge tier-${tier}`}>
      <TierDot tier={tier} />
      {label}
    </span>
  )
}

function EvidenceCard({ item }: { item: Evidence }) {
  const { t, format } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const needsClamp = item.content.length > CLAMP_LENGTH
  const snippet =
    !needsClamp || expanded ? item.content : `${item.content.slice(0, CLAMP_LENGTH).trimEnd()}…`

  return (
    <article className="evidence-card">
      <header className="evidence-header">
        <span className="evidence-badges">
          <span className={`badge origin-${item.origin}`}>{t(`evidence.origin.${item.origin}`)}</span>
          <ExtractionBadge extraction={item.extraction} />
          <EvidenceTierBadge tier={item.quality_tier} />
        </span>
        {item.relevance_score !== null && (
          <span className="evidence-score" title={t('evidence.relevanceTitle')}>
            {t('evidence.relevance', {
              score: format.number(item.relevance_score, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
            })}
          </span>
        )}
      </header>
      <p className="evidence-source">
        {item.source_title}
        {item.filename
          ? ` — ${item.filename}${item.page !== null ? t('sourceDrawer.page', { page: String(item.page) }) : ''}`
          : ''}
      </p>
      <p className="evidence-query">{t('sourceDrawer.foundBy', { query: item.query })}</p>
      <p className="evidence-snippet">{snippet}</p>
      {needsClamp && (
        <button type="button" className="link-btn" onClick={() => setExpanded((value) => !value)}>
          {expanded ? t('evidence.showLess') : t('evidence.showMore')}
        </button>
      )}
    </article>
  )
}

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  const { t } = useI18n()
  if (evidence.length === 0) {
    return <p className="empty-note">{t('evidence.empty')}</p>
  }
  return (
    <div className="evidence-list">
      {evidence.map((item, index) => (
        <EvidenceCard key={index} item={item} />
      ))}
    </div>
  )
}
