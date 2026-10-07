import { useState } from 'react'
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { useRuns } from '../hooks/useRuns'
import type { Theme } from '../hooks/useTheme'
import { agoLabel, templateName, useI18n } from '../i18n'
import type { RunSummary } from '../types'
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
import { LanguageSwitcher } from './LanguageSwitcher'
import { ModeBadge, StatusDot } from './StatusBadge'

export interface SidebarProps {
  open: boolean
  onClose: () => void
  theme: Theme
  onToggleTheme: () => void
}

const NAV_ITEMS = [
  { to: '/', labelKey: 'nav.research', icon: SearchIcon, end: true },
  { to: '/projects', labelKey: 'nav.projects', icon: FolderIcon, end: false },
  { to: '/documents', labelKey: 'nav.documents', icon: FileTextIcon, end: false },
] as const

function HistoryRowBody({ run }: { run: RunSummary }) {
  const { t, format } = useI18n()
  return (
    <>
      <StatusDot status={run.status} />
      <span className="history-body">
        <span className="history-title">{run.title || run.query}</span>
        <span className="history-meta">
          <span className="history-time">{agoLabel(t, format, run.created_at)}</span>
          <ModeBadge mode={run.mode} />
          <span className="badge template-badge history-template">{templateName(t, run.template)}</span>
        </span>
      </span>
    </>
  )
}

/** Global left sidebar: brand, primary navigation, research history, plan card, theme. */
export function Sidebar({ open, onClose, theme, onToggleTheme }: SidebarProps) {
  const { runs, loading, error } = useRuns()
  const { t } = useI18n()
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
      <aside className={`sidebar${open ? ' open' : ''}`} aria-label={t('sidebar.label')}>
        <div className="sidebar-top">
          <Link to="/" className="wordmark" onClick={onClose}>
            <AtlasMark size={26} className="wordmark-mark" />
            <span>Atlas</span>
          </Link>
          <button type="button" className="icon-btn sidebar-close" onClick={onClose} aria-label={t('sidebar.closeSidebar')}>
            <XIcon size={18} />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label={t('nav.primary')}>
          {NAV_ITEMS.map(({ to, labelKey, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className="nav-link" onClick={onClose}>
              <Icon size={18} className="nav-icon" />
              <span className="nav-label">{t(labelKey)}</span>
              <ChevronRightIcon size={16} className="nav-chevron" />
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-history">
          <div className="sidebar-heading-row">
            <h2 className="sidebar-heading">{t('sidebar.history')}</h2>
            {hasComparableRuns && (
              <button
                type="button"
                className="link-btn sidebar-compare-toggle"
                onClick={() => (compareMode ? exitCompareMode() : setCompareMode(true))}
              >
                {compareMode ? t('sidebar.done') : t('sidebar.compare')}
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
                {compareBusy ? t('sidebar.comparing') : t('sidebar.compareRuns', { count: selected.length })}
              </button>
              {compareError && <p className="form-error">{compareError}</p>}
            </div>
          )}
          {loading && <p className="sidebar-note">{t('sidebar.loadingRuns')}</p>}
          {error && !loading && <p className="sidebar-note error-text">{error}</p>}
          {!loading && !error && runs.length === 0 && (
            <p className="sidebar-note">{t('sidebar.noResearch')}</p>
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
                        aria-label={t('common.selectForComparison', { name: run.title || run.query })}
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
              {t('sidebar.planTitleLine1')}
              <br />
              {t('sidebar.planTitleLine2')}
            </span>
            <span className="plan-card-text">
              {t('sidebar.planText')}
            </span>
            <span className="plan-card-cta">{t('sidebar.planCta')}</span>
          </div>
          <div className="sidebar-footer-controls">
            <button
              type="button"
              className="theme-toggle"
              onClick={onToggleTheme}
              aria-label={theme === 'dark' ? t('sidebar.switchToLight') : t('sidebar.switchToDark')}
            >
              {theme === 'dark' ? <SunIcon size={17} /> : <MoonIcon size={17} />}
              <span>{theme === 'dark' ? t('sidebar.lightTheme') : t('sidebar.darkTheme')}</span>
            </button>
            <LanguageSwitcher />
          </div>
        </div>
      </aside>
    </>
  )
}
