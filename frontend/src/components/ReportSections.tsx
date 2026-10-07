import { createElement, useMemo } from 'react'
import { useI18n } from '../i18n'
import type { Claim, Evidence, Source } from '../types'
import { isSourcesSection, isSummarySection, splitSections, type ReportSection } from '../utils/report'
import { CitedMarkdown, useSourceDrawer } from './CitedReport'
import { FileTextIcon, LayersIcon } from './icons'

export interface ReportSectionsProps {
  markdown: string
  sources: Source[]
  evidence?: Evidence[]
  loadClaims?: () => Promise<Claim[]>
  emptyNote?: string
}

function SectionHeading({ section, className }: { section: ReportSection; className: string }) {
  const level = section.level >= 1 && section.level <= 6 ? section.level : 2
  return createElement(`h${level}`, { className }, section.title)
}

/**
 * Renders a markdown report as premium cards: a summary card for the opening
 * summary section, numbered cards for every thematic section, and a compact
 * card for the sources list. All content comes from the report itself; the
 * cards only change presentation.
 */
export function ReportSections({
  markdown,
  sources,
  evidence = [],
  loadClaims,
  emptyNote,
}: ReportSectionsProps) {
  const { t } = useI18n()
  const sections = useMemo(() => splitSections(markdown), [markdown])
  const { onCite, drawer } = useSourceDrawer({ sources, evidence, loadClaims })

  if (!markdown || sections.length === 0) {
    return <p className="empty-note">{emptyNote ?? t('report.noReport')}</p>
  }

  let number = 0
  return (
    <div className="report-sections">
      {sections.map((section, index) => {
        const summary = index === 0 && (section.level === 0 || isSummarySection(section))
        const sourcesList = isSourcesSection(section)
        if (!summary && !sourcesList) number += 1
        const kind = summary ? 'summary' : sourcesList ? 'sources' : 'numbered'
        return (
          <section
            key={section.id}
            id={`section-${section.id}`}
            className={`report-card ${kind}`}
            data-report-section={section.id}
            aria-label={section.title || t('report.summary')}
          >
            <header className="report-card-head">
              <span className={`report-card-badge ${kind}`} aria-hidden="true">
                {summary ? (
                  <FileTextIcon size={22} />
                ) : sourcesList ? (
                  <LayersIcon size={20} />
                ) : (
                  <span className="report-card-number">{number}</span>
                )}
              </span>
              <div className="report-card-title-wrap">
                {section.title ? (
                  <SectionHeading section={section} className="report-card-title" />
                ) : (
                  <h2 className="report-card-title">{t('report.summary')}</h2>
                )}
              </div>
            </header>
            <div className={`report-card-body report${sourcesList ? ' report-sources' : ''}`}>
              <CitedMarkdown markdown={section.body} sources={sources} onCite={onCite} />
            </div>
          </section>
        )
      })}
      {drawer}
    </div>
  )
}
