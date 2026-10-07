import { useEffect, useState } from 'react'
import { exportUrl } from '../api/client'
import { templateName, useI18n } from '../i18n'
import type { RunDetail } from '../types'
import { readingMinutes, splitSections } from '../utils/report'
import {
  ArrowRightIcon,
  DownloadIcon,
  FileTextIcon,
  InfoIcon,
  LinkIcon,
  ListTreeIcon,
  RocketIcon,
  ShareIcon,
} from './icons'

const DATE_TIME: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
}

/** Sticky table of contents built from the report's own headings. */
export function ReportContents({ markdown }: { markdown: string }) {
  const { t } = useI18n()
  const sections = splitSections(markdown).filter((section) => section.title)
  const [active, setActive] = useState<string | null>(sections[0]?.id ?? null)

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined' || sections.length === 0) return
    const elements = sections
      .map((section) => document.getElementById(`section-${section.id}`))
      .filter((element): element is HTMLElement => element !== null)
    if (elements.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) {
          setActive(visible[0].target.getAttribute('data-report-section'))
        }
      },
      { rootMargin: '-15% 0px -65% 0px', threshold: [0, 0.25, 0.5] },
    )
    elements.forEach((element) => observer.observe(element))
    return () => observer.disconnect()
    // The section list is derived from markdown; re-observe when it changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markdown])

  if (sections.length === 0) return null

  const scrollTo = (id: string) => {
    const element = document.getElementById(`section-${id}`)
    if (!element) return
    setActive(id)
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <nav className="side-card report-contents" aria-label={t('reportSidebar.contentsLabel')}>
      <h2 className="side-card-title">
        <ListTreeIcon size={17} />
        {t('reportSidebar.contents')}
      </h2>
      <ol className="contents-list">
        {sections.map((section, index) => {
          const label = String(index + 1)
          return (
            <li key={section.id}>
              <button
                type="button"
                className={`contents-item${active === section.id ? ' active' : ''}`}
                title={section.title}
                aria-current={active === section.id ? 'location' : undefined}
                onClick={() => scrollTo(section.id)}
              >
                <span className="contents-number" aria-hidden="true">
                  {label}
                </span>
                <span className="contents-label">{section.title}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** Export and link actions wired to the run's real export endpoints. */
export function QuickActions({ runId }: { runId: string }) {
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard unavailable; the button simply does not confirm.
    }
  }

  return (
    <section className="side-card quick-actions" aria-label={t('reportSidebar.quickActionsLabel')}>
      <h2 className="side-card-title">
        <RocketIcon size={17} />
        {t('reportSidebar.quickActions')}
      </h2>
      <ul className="action-list">
        <li>
          <a className="action-row" href={exportUrl(runId, 'pdf')} download>
            <DownloadIcon size={16} />
            <span>{t('reportSidebar.exportPdf')}</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </a>
        </li>
        <li>
          <a className="action-row" href={exportUrl(runId, 'markdown')} download>
            <FileTextIcon size={16} />
            <span>{t('reportSidebar.exportMarkdown')}</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </a>
        </li>
        <li>
          <button type="button" className="action-row" onClick={() => void copyLink()}>
            <LinkIcon size={16} />
            <span>{copied ? t('common.linkCopied') : t('reportSidebar.copyLink')}</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </button>
        </li>
        <li>
          {/* Atlas is local-first and has no sharing service; shown disabled rather than faked. */}
          <button type="button" className="action-row" disabled title={t('reportSidebar.shareUnavailable')}>
            <ShareIcon size={16} />
            <span>{t('reportSidebar.shareReport')}</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </button>
        </li>
      </ul>
    </section>
  )
}

/** Run metadata from the API plus a client-side reading-time estimate. */
export function DocumentInfo({ run, projectName }: { run: RunDetail; projectName: string | null }) {
  const { t, format } = useI18n()
  const dateTime = (iso: string | null | undefined) => (iso ? format.date(iso, DATE_TIME) || '—' : '—')
  const minutes = readingMinutes(run.final_report)
  const rows: [string, string][] = [
    [t('reportSidebar.created'), dateTime(run.created_at)],
    [t('reportSidebar.lastUpdated'), dateTime(run.completed_at || run.started_at || run.created_at)],
    [t('reportSidebar.project'), projectName ?? (run.project_id ? t('reportSidebar.loading') : '—')],
    [t('reportSidebar.reportType'), templateName(t, run.template)],
    [t('reportSidebar.readingTime'), minutes === null ? '—' : format.minutes(minutes)],
    [t('reportSidebar.totalSources'), format.number(run.sources.length)],
    [t('reportSidebar.totalEvidence'), format.number(run.evidence.length)],
  ]
  return (
    <section className="side-card document-info" aria-label={t('reportSidebar.documentInfoLabel')}>
      <h2 className="side-card-title">
        <InfoIcon size={17} />
        {t('reportSidebar.documentInfo')}
      </h2>
      <dl className="info-list">
        {rows.map(([label, value]) => (
          <div key={label} className="info-row">
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
