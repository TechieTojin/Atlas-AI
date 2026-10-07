import { useEffect, useState } from 'react'
import { exportUrl } from '../api/client'
import type { RunDetail } from '../types'
import { readingTimeLabel, splitSections } from '../utils/report'
import { templateLabel } from './StatusBadge'
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

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return '—'
  return new Date(then).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** Sticky table of contents built from the report's own headings. */
export function ReportContents({ markdown }: { markdown: string }) {
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
    <nav className="side-card report-contents" aria-label="Report contents">
      <h2 className="side-card-title">
        <ListTreeIcon size={17} />
        Report Contents
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
    <section className="side-card quick-actions" aria-label="Quick actions">
      <h2 className="side-card-title">
        <RocketIcon size={17} />
        Quick Actions
      </h2>
      <ul className="action-list">
        <li>
          <a className="action-row" href={exportUrl(runId, 'pdf')} download>
            <DownloadIcon size={16} />
            <span>Export as PDF</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </a>
        </li>
        <li>
          <a className="action-row" href={exportUrl(runId, 'markdown')} download>
            <FileTextIcon size={16} />
            <span>Export as Markdown</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </a>
        </li>
        <li>
          <button type="button" className="action-row" onClick={() => void copyLink()}>
            <LinkIcon size={16} />
            <span>{copied ? 'Link copied' : 'Copy Link'}</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </button>
        </li>
        <li>
          {/* Atlas is local-first and has no sharing service; shown disabled rather than faked. */}
          <button type="button" className="action-row" disabled title="Sharing is not available in Atlas">
            <ShareIcon size={16} />
            <span>Share Report</span>
            <ArrowRightIcon size={15} className="action-arrow" />
          </button>
        </li>
      </ul>
    </section>
  )
}

/** Run metadata from the API plus a client-side reading-time estimate. */
export function DocumentInfo({ run, projectName }: { run: RunDetail; projectName: string | null }) {
  const rows: [string, string][] = [
    ['Created', formatDateTime(run.created_at)],
    ['Last Updated', formatDateTime(run.completed_at || run.started_at || run.created_at)],
    ['Project', projectName ?? (run.project_id ? 'Loading…' : '—')],
    ['Report Type', templateLabel(run.template)],
    ['Estimated Reading', readingTimeLabel(run.final_report)],
    ['Total Sources', String(run.sources.length)],
    ['Total Evidence', String(run.evidence.length)],
  ]
  return (
    <section className="side-card document-info" aria-label="Document info">
      <h2 className="side-card-title">
        <InfoIcon size={17} />
        Document Info
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
