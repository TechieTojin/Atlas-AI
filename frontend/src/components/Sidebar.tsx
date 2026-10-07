import { useState } from 'react'
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { useRuns } from '../hooks/useRuns'
import type { Theme } from '../hooks/useTheme'
import type { RunSummary } from '../types'
import { relativeTime } from '../utils/format'
import { MAX_COMPARE, MIN_COMPARE } from './CompareRunsList'
import {
  AtlasMark,
  ChevronRightIcon,
  CrownIcon,
  FileTextIcon,
  FolderIcon,
  MoonIcon,
  SearchIcon,
  SparklesIcon,
  SunIcon,
  XIcon,
} from './icons'
import { ModeBadge, StatusDot, templateLabel } from './StatusBadge'

export interface SidebarProps {
  open: boolean
  onClose: () => void
  theme: Theme
  onToggleTheme: () => void
}

const NAV_ITEMS = [
  { to: '/', label: 'Research', icon: SearchIcon, end: true },
  { to: '/projects', label: 'Projects', icon: FolderIcon, end: false },
  { to: '/documents', label: 'Documents', icon: FileTextIcon, end: false },
] as const

function HistoryRowBody({ run }: { run: RunSummary }) {
  return (
    <>
      <StatusDot status={run.status} />
      <span className="history-body">
        <span className="history-title">{run.title || run.query}</span>
        <span className="history-meta">
          <span className="history-time">{relativeTime(run.created_at)}</span>
          <ModeBadge mode={run.mode} />
          <span className="badge template-badge history-template">{templateLabel(run.template)}</span>
        </span>
      </span>
    </>
  )
}

/** Global left sidebar: brand, primary navigation, research history, plan card, theme. */
export function Sidebar({ open, onClose, theme, onToggleTheme }: SidebarProps) {
  const { runs, loading, error } = useRuns()
  const navigate = useNavigate()
  const location = useLocation()
  const [compareMode, setCompareMode] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [compareBusy, setCompareBusy] = useState(false)
  const [compareError, setCompareError] = useState<string | null>(null)

  const hasComparableRuns = runs.filter((run) => run.status === 'COMPLETED').length >= MIN_COMPARE

  const toggleSelected = (id: string) => {
    setSelected((previous) =>
      previous.includes(id) ? previous.filter((existing) => existing !== id) : [...previous, id],
    )
  }

  const exitCompareMode = () => {
    setCompareMode(false)
    setSelected([])
    setCompareError(null)
  }

  const canCompare = selected.length >= MIN_COMPARE && selected.length <= MAX_COMPARE && !compareBusy

  const handleCompare = async () => {
    if (!canCompare) return
    setCompareBusy(true)
    setCompareError(null)
    try {
      const comparison = await api.createComparison({ run_ids: selected })
      exitCompareMode()
      onClose()
      navigate(`/comparisons/${comparison.id}`)
    } catch (err) {
      setCompareError(errorMessage(err))
    } finally {
      setCompareBusy(false)
    }
  }

  return (
    <>
      {open && <div className="sidebar-scrim" onClick={onClose} aria-hidden="true" />}
      <aside className={`sidebar${open ? ' open' : ''}`} aria-label="Navigation and research history">
        <div className="sidebar-top">
          <Link to="/" className="wordmark" onClick={onClose}>
            <AtlasMark size={26} className="wordmark-mark" />
            <span>Atlas</span>
          </Link>
          <button type="button" className="icon-btn sidebar-close" onClick={onClose} aria-label="Close sidebar">
            <XIcon size={18} />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Primary">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className="nav-link" onClick={onClose}>
              <Icon size={18} className="nav-icon" />
              <span className="nav-label">{label}</span>
              <ChevronRightIcon size={16} className="nav-chevron" />
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-history">
          <div className="sidebar-heading-row">
            <h2 className="sidebar-heading">History</h2>
            {hasComparableRuns && (
              <button
                type="button"
                className="link-btn sidebar-compare-toggle"
                onClick={() => (compareMode ? exitCompareMode() : setCompareMode(true))}
              >
                {compareMode ? 'Done' : 'Compare'}
              </button>
            )}
          </div>
          {compareMode && (
            <div className="sidebar-compare-bar">
              <button
                type="button"
                className="btn primary compact"
                disabled={!canCompare}
                onClick={() => void handleCompare()}
              >
                {compareBusy ? 'Comparing…' : `Compare ${selected.length} runs`}
              </button>
              {compareError && <p className="form-error">{compareError}</p>}
            </div>
          )}
          {loading && <p className="sidebar-note">Loading runs…</p>}
          {error && !loading && <p className="sidebar-note error-text">{error}</p>}
          {!loading && !error && runs.length === 0 && (
            <p className="sidebar-note">No research yet.</p>
          )}
          <ul className="history-list">
            {runs.map((run) => {
              const isCurrent = location.pathname === `/runs/${run.id}`
              if (compareMode) {
                const completed = run.status === 'COMPLETED'
                const checked = selected.includes(run.id)
                return (
                  <li key={run.id}>
                    <label className={`history-item compare${completed ? '' : ' disabled'}`}>
                      <input
                        type="checkbox"
                        className="compare-checkbox"
                        aria-label={`Select ${run.title || run.query} for comparison`}
                        checked={checked}
                        disabled={!completed || (!checked && selected.length >= MAX_COMPARE)}
                        onChange={() => toggleSelected(run.id)}
                      />
                      <HistoryRowBody run={run} />
                    </label>
                  </li>
                )
              }
              return (
                <li key={run.id}>
                  <Link
                    to={`/runs/${run.id}`}
                    className={`history-item${isCurrent ? ' current' : ''}`}
                    aria-current={isCurrent ? 'page' : undefined}
                    onClick={onClose}
                  >
                    <HistoryRowBody run={run} />
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>

        <div className="sidebar-footer">
          {/* Presentational plan card from the reference design; Atlas has no billing. */}
          <div className="plan-card" aria-hidden="true">
            <span className="plan-card-icon">
              <CrownIcon size={16} />
            </span>
            <SparklesIcon size={18} className="plan-card-sparkle" />
            <span className="plan-card-title">
              Unlock
              <br />
              More Power
            </span>
            <span className="plan-card-text">
              Get deeper insights, larger context and more sources.
            </span>
            <span className="plan-card-cta">Upgrade Plan →</span>
          </div>
          <button
            type="button"
            className="theme-toggle"
            onClick={onToggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? <SunIcon size={17} /> : <MoonIcon size={17} />}
            <span>{theme === 'dark' ? 'Light theme' : 'Dark theme'}</span>
          </button>
        </div>
      </aside>
    </>
  )
}
