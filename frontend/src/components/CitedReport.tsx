import {
  Children,
  createElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import { useI18n, type Translate } from '../i18n'
import type { Claim, Evidence, Source } from '../types'
import { ExtractionBadge } from './EvidenceList'
import { QualityBadge } from './QualityBadge'
import { ExternalIcon, FileIcon, XIcon } from './icons'

const CITATION_PATTERN = /\[(\d+)\]/g

function splitCitations(
  text: string,
  validIndexes: Set<number>,
  onCite: (index: number) => void,
  t: Translate,
): ReactNode[] {
  const parts: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0
  CITATION_PATTERN.lastIndex = 0
  while ((match = CITATION_PATTERN.exec(text)) !== null) {
    const index = Number(match[1])
    if (!validIndexes.has(index)) continue
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index))
    const citation = index
    parts.push(
      <button
        key={`cite-${key++}`}
        type="button"
        className="citation"
        aria-label={t('report.viewSource', { index: String(citation) })}
        onClick={() => onCite(citation)}
      >
        [{citation}]
      </button>,
    )
    lastIndex = match.index + match[0].length
  }
  if (parts.length === 0) return [text]
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return parts
}

const CITED_TAGS = [
  'p',
  'li',
  'strong',
  'em',
  'td',
  'th',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
] as const

function buildComponents(
  validIndexes: Set<number>,
  onCite: (index: number) => void,
  t: Translate,
): Components {
  const components: Record<string, unknown> = {}
  for (const tag of CITED_TAGS) {
    components[tag] = (props: { children?: ReactNode } & Record<string, unknown>) => {
      const rest: Record<string, unknown> = { ...props }
      delete rest.children
      delete rest.node
      const children = Children.map(props.children, (child) =>
        typeof child === 'string' ? splitCitations(child, validIndexes, onCite, t) : child,
      )
      return createElement(tag, rest, children)
    }
  }
  return components as Components
}

/** Markdown with inline [n] citation markers rendered as accessible buttons. */
export function CitedMarkdown({
  markdown,
  sources,
  onCite,
}: {
  markdown: string
  sources: Source[]
  onCite: (index: number) => void
}) {
  const { t } = useI18n()
  const validIndexes = useMemo(() => new Set(sources.map((source) => source.index)), [sources])
  const components = useMemo(
    () => buildComponents(validIndexes, onCite, t),
    [validIndexes, onCite, t],
  )
  return <ReactMarkdown components={components}>{markdown}</ReactMarkdown>
}

function evidenceForSource(source: Source, evidence: Evidence[]): Evidence[] {
  return evidence.filter((item) => {
    if (source.url) return item.source_url === source.url
    if (source.filename) return item.filename === source.filename
    return item.source_title === source.title
  })
}

export interface SourceDrawerProps {
  source: Source
  evidence: Evidence[]
  claims: Claim[] | null
  claimsLoading?: boolean
  /** Labels of runs that used this source (comparison drawers). */
  usageLabels?: string[]
  isNewSource?: boolean
  onClose: () => void
}

export function SourceDrawer({
  source,
  evidence,
  claims,
  claimsLoading = false,
  usageLabels,
  isNewSource = false,
  onClose,
}: SourceDrawerProps) {
  const { t, format } = useI18n()
  const drawerRef = useRef<HTMLElement>(null)

  useEffect(() => {
    drawerRef.current?.focus()
  }, [source.index])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const matchingEvidence = evidenceForSource(source, evidence)
  const matchingClaims = claims?.filter((claim) => claim.citations.includes(source.index)) ?? null

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside
        ref={drawerRef}
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={t('sourceDrawer.label', {
          index: String(source.index),
          title: source.title || source.filename || t('sourceDrawer.fallbackTitle'),
        })}
        tabIndex={-1}
      >
        <header className="drawer-header">
          <span className="source-index" aria-hidden="true">
            {source.index}
          </span>
          <h2 className="drawer-title">
            {source.kind === 'document' ? (source.filename ?? source.title) : source.title}
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t('sourceDrawer.close')}>
            <XIcon size={15} />
          </button>
        </header>

        <div className="drawer-body">
          <div className="drawer-meta">
            {isNewSource && <span className="badge tone-active">{t('common.new')}</span>}
            <QualityBadge quality={source.quality} expandable />
            {source.kind === 'document' ? (
              <p className="drawer-document-ref">
                <FileIcon size={14} className="source-icon" />
                {source.filename ?? source.title}
                {source.page !== null ? t('sourceDrawer.page', { page: String(source.page) }) : ''}
              </p>
            ) : (
              source.url && (
                <a className="btn drawer-open-link" href={source.url} target="_blank" rel="noreferrer">
                  <ExternalIcon size={13} />
                  <span>{t('sourceDrawer.openSource')}</span>
                </a>
              )
            )}
            {source.kind !== 'document' && source.domain && (
              <span className="source-domain">{source.domain}</span>
            )}
          </div>

          {usageLabels && usageLabels.length > 0 && (
            <section className="drawer-section">
              <h3 className="panel-heading">{t('sourceDrawer.usedByRuns')}</h3>
              <div className="doc-chips">
                {usageLabels.map((label, index) => (
                  <span key={index} className="chip">
                    {label}
                  </span>
                ))}
              </div>
            </section>
          )}

          <section className="drawer-section">
            <h3 className="panel-heading">{t('sourceDrawer.evidence')}</h3>
            {matchingEvidence.length === 0 ? (
              <p className="hint-text">{t('sourceDrawer.noEvidence')}</p>
            ) : (
              <div className="evidence-list">
                {matchingEvidence.map((item, index) => (
                  <article key={index} className="evidence-card compact">
                    <header className="evidence-header">
                      <span className="evidence-badges">
                        <span className={`badge origin-${item.origin}`}>
                          {t(`evidence.origin.${item.origin}`)}
                        </span>
                        <ExtractionBadge extraction={item.extraction} />
                      </span>
                    </header>
                    <p className="evidence-query">{t('sourceDrawer.foundBy', { query: item.query })}</p>
                    <p className="evidence-snippet">{item.content}</p>
                    {item.fetched_at && (
                      <p className="evidence-fetched">
                        {t('sourceDrawer.fetched', { date: format.date(item.fetched_at) || '—' })}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="drawer-section">
            <h3 className="panel-heading">{t('sourceDrawer.claims')}</h3>
            {claimsLoading && (
              <p className="hint-text" role="status">
                <span className="spinner small" aria-hidden="true" />
                {t('sourceDrawer.loadingClaims')}
              </p>
            )}
            {!claimsLoading && matchingClaims !== null && matchingClaims.length === 0 && (
              <p className="hint-text">{t('sourceDrawer.noClaims')}</p>
            )}
            {!claimsLoading && matchingClaims === null && (
              <p className="hint-text">{t('sourceDrawer.claimsUnavailable')}</p>
            )}
            {!claimsLoading && matchingClaims !== null && matchingClaims.length > 0 && (
              <ul className="claims-list">
                {matchingClaims.map((claim, index) => (
                  <li key={index} className="claim-item">
                    <span className="claim-text">{claim.text}</span>
                    {claim.section && <span className="claim-section">{claim.section}</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </aside>
    </>
  )
}

export interface SourceDrawerState {
  /** Pass to CitedMarkdown's onCite. */
  onCite: (index: number) => void
  /** The drawer element (or null when closed); render it once. */
  drawer: ReactNode
}

/**
 * Citation drawer state shared by every markdown block of a report: which
 * source is open, lazily-loaded claims, and the drawer element itself.
 */
export function useSourceDrawer({
  sources,
  evidence = [],
  loadClaims,
  usageBySourceIndex,
  parentSourceCount,
}: {
  sources: Source[]
  evidence?: Evidence[]
  loadClaims?: () => Promise<Claim[]>
  usageBySourceIndex?: Map<number, string[]>
  parentSourceCount?: number
}): SourceDrawerState {
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const [claims, setClaims] = useState<Claim[] | null>(null)
  const [claimsLoading, setClaimsLoading] = useState(false)
  const claimsRequested = useRef(false)

  const onCite = useCallback(
    (index: number) => {
      setActiveIndex(index)
      if (loadClaims && !claimsRequested.current) {
        claimsRequested.current = true
        setClaimsLoading(true)
        loadClaims()
          .then((loaded) => setClaims(loaded))
          .catch(() => setClaims(null))
          .finally(() => setClaimsLoading(false))
      }
    },
    [loadClaims],
  )

  const close = useCallback(() => setActiveIndex(null), [])

  const activeSource =
    activeIndex !== null ? sources.find((source) => source.index === activeIndex) : undefined

  const drawer = activeSource ? (
    <SourceDrawer
      source={activeSource}
      evidence={evidence}
      claims={claims}
      claimsLoading={claimsLoading}
      usageLabels={usageBySourceIndex?.get(activeSource.index)}
      isNewSource={parentSourceCount !== undefined && activeSource.index > parentSourceCount}
      onClose={close}
    />
  ) : null

  return { onCite, drawer }
}

export interface CitedReportProps {
  markdown: string
  sources: Source[]
  evidence?: Evidence[]
  /** Lazy claims loader, called once when the first citation drawer opens. */
  loadClaims?: () => Promise<Claim[]>
  /** Comparison: labels of the runs that used each source index. */
  usageBySourceIndex?: Map<number, string[]>
  /** Follow-ups: sources with an index greater than this are newly found. */
  parentSourceCount?: number
  emptyNote?: string
  className?: string
}

/**
 * Renders a markdown report whose [n] citation markers open a source
 * drawer with quality, evidence, and supported claims for that source.
 */
export function CitedReport({
  markdown,
  sources,
  evidence = [],
  loadClaims,
  usageBySourceIndex,
  parentSourceCount,
  emptyNote,
  className = 'report',
}: CitedReportProps) {
  const { t } = useI18n()
  const { onCite, drawer } = useSourceDrawer({
    sources,
    evidence,
    loadClaims,
    usageBySourceIndex,
    parentSourceCount,
  })

  if (!markdown) {
    return <p className="empty-note">{emptyNote ?? t('report.noReport')}</p>
  }

  return (
    <div className={className}>
      <CitedMarkdown markdown={markdown} sources={sources} onCite={onCite} />
      {drawer}
    </div>
  )
}
