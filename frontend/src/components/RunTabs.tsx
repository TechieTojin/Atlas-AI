import { useCallback, useState } from 'react'
import { api } from '../api/client'
import type { RunDetail } from '../types'
import { EvidenceList } from './EvidenceList'
import { KnowledgeGraphTab, runKnowledgeGraphTabProps } from './KnowledgeGraph'
import { MetricsPanel } from './MetricsPanel'
import { ReportSections } from './ReportSections'
import { DocumentInfo, QuickActions, ReportContents } from './ReportSidebar'
import { SourcesList } from './SourcesList'
import { BarChartIcon, FileTextIcon, LayersIcon, NetworkIcon, QuoteIcon } from './icons'

type TabId = 'report' | 'sources' | 'evidence' | 'metrics' | 'graph'

const TABS: { id: TabId; label: string; icon: typeof FileTextIcon }[] = [
  { id: 'report', label: 'Report', icon: FileTextIcon },
  { id: 'sources', label: 'Sources', icon: LayersIcon },
  { id: 'evidence', label: 'Evidence', icon: QuoteIcon },
  { id: 'metrics', label: 'Metrics', icon: BarChartIcon },
  { id: 'graph', label: 'Graph', icon: NetworkIcon },
]

export function RunTabs({ run, projectName = null }: { run: RunDetail; projectName?: string | null }) {
  const [active, setActive] = useState<TabId>('report')

  const loadClaims = useCallback(
    () => api.getRunClaims(run.id).then((response) => response.claims),
    [run.id],
  )

  return (
    <div className="run-tabs">
      <div className="tab-list" role="tablist" aria-label="Run results">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const count =
            tab.id === 'sources'
              ? run.sources.length
              : tab.id === 'evidence'
                ? run.evidence.length
                : null
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={active === tab.id}
              aria-controls={`panel-${tab.id}`}
              className={`tab${active === tab.id ? ' active' : ''}`}
              onClick={() => setActive(tab.id)}
            >
              <Icon size={17} className="tab-icon" />
              <span>{tab.label}</span>
              {count !== null && count > 0 && <span className="tab-count">{count}</span>}
            </button>
          )
        })}
      </div>

      <div
        id={`panel-${active}`}
        role="tabpanel"
        aria-labelledby={`tab-${active}`}
        className={`tab-panel${active === 'report' ? ' report-layout' : ''}`}
      >
        {active === 'report' && (
          <>
            <div className="report-main">
              <ReportSections
                markdown={run.final_report}
                sources={run.sources}
                evidence={run.evidence}
                loadClaims={loadClaims}
              />
            </div>
            <aside className="report-side" aria-label="Report tools">
              <ReportContents markdown={run.final_report} />
              <QuickActions runId={run.id} />
              <DocumentInfo run={run} projectName={projectName} />
            </aside>
          </>
        )}
        {active === 'sources' && (
          <div className="glass-card panel-card">
            <SourcesList sources={run.sources} />
          </div>
        )}
        {active === 'evidence' && (
          <div className="glass-card panel-card">
            <EvidenceList evidence={run.evidence} />
          </div>
        )}
        {active === 'metrics' && (
          <div className="glass-card panel-card">
            <MetricsPanel metrics={run.metrics} evaluation={run.evaluation} />
          </div>
        )}
        {active === 'graph' && (
          <div className="glass-card panel-card">
            <KnowledgeGraphTab {...runKnowledgeGraphTabProps(run.id)} />
          </div>
        )}
      </div>
    </div>
  )
}
