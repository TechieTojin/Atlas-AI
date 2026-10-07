import { useMemo, useState } from 'react'
import type { QualityTier, Source } from '../types'
import { QualityBadge, TIER_LABELS, tierRank } from './QualityBadge'
import { ExternalIcon, FileIcon } from './icons'

type SortKey = 'index' | 'quality'

const TIER_ORDER: QualityTier[] = ['high', 'medium', 'low', 'unknown']

function qualityScore(source: Source): number {
  const quality = source.quality
  if (!quality) return -1
  return tierRank(quality.tier) * 1000 + quality.score
}

function sourceTier(source: Source): QualityTier | null {
  return source.quality?.tier ?? null
}

export function SourceRow({ source, trailing }: { source: Source; trailing?: React.ReactNode }) {
  return (
    <li className="source-item">
      <span className="source-index" aria-hidden="true">
        {source.index}
      </span>
      {source.kind === 'document' ? (
        <span className="source-body">
          <span className="source-title">
            <FileIcon className="source-icon" />
            {source.filename ?? source.title}
            {source.page !== null ? `, p. ${source.page}` : ''}
          </span>
          <span className="badge origin-document">Document</span>
          {trailing}
        </span>
      ) : (
        <span className="source-body">
          <span className="source-title">{source.title}</span>
          <span className="source-meta">
            <span className="source-domain">{source.domain}</span>
            {source.url && (
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="source-link"
                aria-label={`Open ${source.title} in a new tab`}
              >
                <ExternalIcon size={13} />
                <span>Open</span>
              </a>
            )}
          </span>
          <QualityBadge quality={source.quality} expandable />
          {trailing}
        </span>
      )}
    </li>
  )
}

export function SourcesList({ sources }: { sources: Source[] }) {
  const [sort, setSort] = useState<SortKey>('index')
  const [tierFilter, setTierFilter] = useState<QualityTier | null>(null)

  const tierCounts = useMemo(() => {
    const counts = new Map<QualityTier, number>()
    for (const source of sources) {
      const tier = sourceTier(source)
      if (tier) counts.set(tier, (counts.get(tier) ?? 0) + 1)
    }
    return counts
  }, [sources])

  const visible = useMemo(() => {
    let list = sources
    if (tierFilter) list = list.filter((source) => sourceTier(source) === tierFilter)
    if (sort === 'quality') {
      list = [...list].sort((a, b) => qualityScore(b) - qualityScore(a))
    }
    return list
  }, [sources, sort, tierFilter])

  if (sources.length === 0) {
    return <p className="empty-note">No sources were collected for this run.</p>
  }

  const hasQuality = tierCounts.size > 0

  return (
    <div className="sources-panel">
      {hasQuality && (
        <div className="sources-toolbar">
          <label className="sort-label">
            Sort by{' '}
            <select
              className="select-input compact"
              value={sort}
              onChange={(event) => setSort(event.target.value as SortKey)}
              aria-label="Sort sources"
            >
              <option value="index">Number</option>
              <option value="quality">Quality</option>
            </select>
          </label>
          <div className="tier-chips" role="group" aria-label="Filter sources by quality tier">
            <button
              type="button"
              className={`chip${tierFilter === null ? ' selected' : ''}`}
              aria-pressed={tierFilter === null}
              onClick={() => setTierFilter(null)}
            >
              All
            </button>
            {TIER_ORDER.filter((tier) => tierCounts.has(tier)).map((tier) => (
              <button
                key={tier}
                type="button"
                className={`chip${tierFilter === tier ? ' selected' : ''}`}
                aria-pressed={tierFilter === tier}
                onClick={() => setTierFilter(tierFilter === tier ? null : tier)}
              >
                <span className={`quality-dot tier-${tier}`} aria-hidden="true" />
                {TIER_LABELS[tier]} ({tierCounts.get(tier)})
              </button>
            ))}
          </div>
        </div>
      )}
      <ol className="sources-list" aria-label="Sources">
        {visible.map((source) => (
          <SourceRow key={source.index} source={source} />
        ))}
      </ol>
      {visible.length === 0 && <p className="empty-note">No sources match this filter.</p>}
    </div>
  )
}
