import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useI18n } from '../i18n'
import type {
  ContradictionRecord,
  IntegrityClaim,
  QualityScore,
  RunIntegrity,
  VerificationStatus,
} from '../types'
import { AlertIcon, CheckIcon, QuoteIcon, ShieldCheckIcon } from './icons'

/** Semantic tone per verdict. Deliberately restrained — not a rainbow. */
const STATUS_TONE: Record<VerificationStatus, string> = {
  SUPPORTED: 'tone-success',
  PARTIALLY_SUPPORTED: 'tone-warning',
  UNSUPPORTED: 'tone-danger',
  CONTRADICTED: 'tone-danger',
  NOT_VERIFIABLE: 'tone-muted',
}

const STATUS_ORDER: VerificationStatus[] = [
  'SUPPORTED',
  'PARTIALLY_SUPPORTED',
  'UNSUPPORTED',
  'CONTRADICTED',
  'NOT_VERIFIABLE',
]


/** Known component/signal names -> message keys. Unknown names fall back to
 *  the raw backend name so a new dimension can never crash the panel. */
const COMPONENT_KEYS = {
  citation_coverage: 'integrity.component.citation_coverage',
  citation_support: 'integrity.component.citation_support',
  source_diversity: 'integrity.component.source_diversity',
  source_authority: 'integrity.component.source_authority',
  evidence_agreement: 'integrity.component.evidence_agreement',
  evidence_relevance: 'integrity.component.evidence_relevance',
} as const

const SIGNAL_KEYS = {
  term_overlap: 'integrity.signal.term_overlap',
  numeric_match: 'integrity.signal.numeric_match',
  evidence_available: 'integrity.signal.evidence_available',
  polarity_conflict: 'integrity.signal.polarity_conflict',
} as const

function componentKey(name: string) {
  return COMPONENT_KEYS[name as keyof typeof COMPONENT_KEYS]
}

function signalKey(name: string) {
  return SIGNAL_KEYS[name as keyof typeof SIGNAL_KEYS]
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}

function QualityBreakdown({ quality }: { quality: QualityScore }) {
  const { t } = useI18n()
  return (
    <section className="integrity-quality" aria-label={t('integrity.quality.title')}>
      <header className="integrity-quality-head">
        <div>
          <h3 className="panel-heading">{t('integrity.quality.title')}</h3>
          <p className="hint-text">
            {t('integrity.quality.formula', { version: String(quality.formula_version) })}
          </p>
        </div>
        <div className="integrity-quality-score">
          {quality.overall === null ? (
            <span className="integrity-na">{t('integrity.notAvailable')}</span>
          ) : (
            <span className="integrity-score-value">{percent(quality.overall)}</span>
          )}
        </div>
      </header>
      <ul className="integrity-components">
        {quality.components.map((component) => (
          <li key={component.name} className="integrity-component">
            <div className="integrity-component-head">
              <span className="integrity-component-name">
                {componentKey(component.name) ? t(componentKey(component.name)) : component.name}
              </span>
              {component.available && component.value !== null ? (
                <span className="integrity-component-value">{percent(component.value)}</span>
              ) : (
                <span className="integrity-na">{t('integrity.notAvailable')}</span>
              )}
            </div>
            {component.available && component.value !== null && (
              <div
                className="integrity-meter"
                role="img"
                aria-label={`${
                  componentKey(component.name) ? t(componentKey(component.name)) : component.name
                }: ${percent(component.value)}`}
              >
                <span style={{ width: percent(component.value) }} />
              </div>
            )}
            <p className="integrity-component-detail">{component.detail}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ContradictionCard({ item }: { item: ContradictionRecord }) {
  const { t } = useI18n()
  return (
    <article className="contradiction-card">
      <header className="contradiction-head">
        <AlertIcon size={15} />
        <span className="contradiction-kind">{t(`integrity.contradiction.${item.kind}`)}</span>
      </header>
      <p className="contradiction-explain">{item.explanation}</p>
      <div className="contradiction-pair">
        <blockquote>
          <cite>{t('integrity.sourceN', { n: String(item.source_a) })}</cite>
          <p>{item.excerpt_a}</p>
        </blockquote>
        <blockquote>
          <cite>{t('integrity.sourceN', { n: String(item.source_b) })}</cite>
          <p>{item.excerpt_b}</p>
        </blockquote>
      </div>
    </article>
  )
}

function ClaimRow({ claim }: { claim: IntegrityClaim }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const verification = claim.verification
  const status = verification?.status ?? 'NOT_VERIFIABLE'

  return (
    <li className={`matrix-row${open ? ' open' : ''}`}>
      <button
        type="button"
        className="matrix-row-main"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`badge ${STATUS_TONE[status]}`}>{t(`integrity.status.${status}`)}</span>
        <span className="matrix-claim-text">{claim.text}</span>
        <span className="matrix-meta">
          <span className="matrix-cites" title={t('integrity.citedSources')}>
            <QuoteIcon size={13} />
            {claim.citations.join(', ') || '—'}
          </span>
          {claim.contradictions.length > 0 && (
            <span className="matrix-conflict" title={t('integrity.contradictionsFound')}>
              <AlertIcon size={13} />
              {claim.contradictions.length}
            </span>
          )}
          {verification && (
            <span className="matrix-confidence">
              {t(`integrity.confidence.${verification.confidence}`)}
            </span>
          )}
        </span>
      </button>

      {open && verification && (
        <div className="matrix-detail">
          <p className="matrix-why">{verification.explanation}</p>
          <h4 className="matrix-subhead">{t('integrity.signals')}</h4>
          <ul className="matrix-signals">
            {verification.signals.map((signal) => (
              <li key={signal.name}>
                <span className="signal-name">
                  {signalKey(signal.name) ? t(signalKey(signal.name)) : signal.name}
                </span>
                {signal.value !== null && (
                  <span className="signal-value">{percent(signal.value)}</span>
                )}
                <span className="signal-detail">{signal.detail}</span>
              </li>
            ))}
          </ul>
          {claim.section && (
            <p className="hint-text">{t('integrity.inSection', { section: claim.section })}</p>
          )}
          {claim.contradictions.map((item) => (
            <ContradictionCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </li>
  )
}

export function IntegrityPanel({ runId }: { runId: string }) {
  const { t } = useI18n()
  const [data, setData] = useState<RunIntegrity | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    api
      .getRunIntegrity(runId)
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  const analyze = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      setData(await api.analyzeRunIntegrity(runId))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }, [runId])

  if (error) {
    return (
      <p className="alert tone-danger" role="alert">
        {error}
      </p>
    )
  }

  if (!data) {
    return (
      <div className="integrity-loading" aria-busy="true">
        <div className="skeleton skeleton-line wide" />
        <div className="skeleton skeleton-line medium" />
        <div className="skeleton skeleton-block" />
      </div>
    )
  }

  if (!data.analyzed) {
    return (
      <div className="empty-state">
        <span className="empty-state-icon" aria-hidden="true">
          <ShieldCheckIcon size={20} />
        </span>
        <h3 className="empty-state-title">{t('integrity.empty.title')}</h3>
        <p className="empty-state-body">{t('integrity.empty.body')}</p>
        <button
          type="button"
          className="btn primary empty-state-action"
          onClick={() => void analyze()}
          disabled={busy}
        >
          {busy ? t('integrity.analyzing') : t('integrity.analyze')}
        </button>
      </div>
    )
  }

  const { summary } = data
  return (
    <div className="integrity-panel">
      <section className="integrity-summary" aria-label={t('integrity.summary.title')}>
        <header className="integrity-summary-head">
          <h3 className="panel-heading">
            <ShieldCheckIcon size={15} /> {t('integrity.summary.title')}
          </h3>
          <p className="integrity-headline">
            {summary.support_rate === null
              ? t('integrity.summary.noneVerifiable')
              : t('integrity.summary.headline', {
                  supported: String(summary.supported),
                  verified: String(summary.verified_claims),
                })}
          </p>
          {/* Coverage and correctness are different things; say so. */}
          <p className="hint-text">{t('integrity.summary.coverageNote')}</p>
        </header>
        <ul className="integrity-status-row">
          {STATUS_ORDER.map((status) => {
            const count =
              status === 'SUPPORTED'
                ? summary.supported
                : status === 'PARTIALLY_SUPPORTED'
                  ? summary.partially_supported
                  : status === 'UNSUPPORTED'
                    ? summary.unsupported
                    : status === 'CONTRADICTED'
                      ? summary.contradicted
                      : summary.not_verifiable
            return (
              <li key={status}>
                <span className={`badge ${STATUS_TONE[status]}`}>
                  {t(`integrity.status.${status}`)}
                </span>
                <strong>{count}</strong>
              </li>
            )
          })}
        </ul>
        <button type="button" className="btn compact" onClick={() => void analyze()} disabled={busy}>
          {busy ? t('integrity.analyzing') : t('integrity.reanalyze')}
        </button>
      </section>

      {data.quality && <QualityBreakdown quality={data.quality} />}

      <section className="integrity-matrix" aria-label={t('integrity.matrix.title')}>
        <h3 className="panel-heading">
          <CheckIcon size={15} /> {t('integrity.matrix.title')}
        </h3>
        <p className="hint-text">{t('integrity.matrix.hint')}</p>
        {data.claims.length === 0 ? (
          <p className="empty-note">{t('integrity.matrix.empty')}</p>
        ) : (
          <ul className="matrix-list">
            {data.claims.map((claim) => (
              <ClaimRow key={claim.id} claim={claim} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
