import { useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { ProjectsHeroArt } from '../components/art/ProjectsHeroArt'
import {
  ArrowRightIcon,
  ChevronDownIcon,
  ClockIcon,
  FileTextIcon,
  FolderIcon,
  GridIcon,
  ListIcon,
  LayersIcon,
  PlusIcon,
  SearchIcon,
  UsersIcon,
  XIcon,
  AtlasMark,
} from '../components/icons'
import { EyebrowPill, FeaturePill } from '../components/PageHero'
import { ProjectCard } from '../components/ProjectCard'
import { useProjects } from '../hooks/useProjects'
import { useI18n } from '../i18n'
import type { ProjectWithCounts } from '../types'

type Filter = 'all' | 'recent'
type SortKey = 'updated' | 'name' | 'created'
type Layout = 'grid' | 'list'

const FEATURES = [
  { icon: FolderIcon, label: 'projects.features.organization' },
  { icon: FileTextIcon, label: 'projects.features.documents' },
  { icon: ClockIcon, label: 'projects.features.resume' },
  { icon: UsersIcon, label: 'projects.features.collaborate' },
] as const

const RECENT_WINDOW_MS = 7 * 24 * 60 * 60 * 1000

function sortProjects(projects: ProjectWithCounts[], sort: SortKey): ProjectWithCounts[] {
  const copy = [...projects]
  if (sort === 'name') return copy.sort((a, b) => a.name.localeCompare(b.name))
  if (sort === 'created') {
    return copy.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  }
  return copy.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
}

export function ProjectsPage() {
  const navigate = useNavigate()
  const { t } = useI18n()
  const { projects, loading, error, create } = useProjects()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<SortKey>('updated')
  const [layout, setLayout] = useState<Layout>('grid')
  const searchId = useId()
  const sortId = useId()

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const now = Date.now()
    const filtered = projects.filter((project) => {
      if (needle && !`${project.name} ${project.description}`.toLowerCase().includes(needle)) {
        return false
      }
      if (filter === 'recent' && now - Date.parse(project.updated_at) > RECENT_WINDOW_MS) return false
      return true
    })
    return sortProjects(filtered, sort)
  }, [projects, search, filter, sort])

  const openCreate = () => {
    setCreateError(null)
    setCreating(true)
  }

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!name.trim() || busy) return
    setBusy(true)
    setCreateError(null)
    try {
      const project = await create({ name: name.trim(), description: description.trim() })
      setCreating(false)
      setName('')
      setDescription('')
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setCreateError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="projects-page">
      <header className="page-hero projects-hero">
        <div className="page-hero-copy">
          <div className="page-hero-eyebrow">
            <EyebrowPill icon={AtlasMark}>{t('projects.eyebrow')}</EyebrowPill>
          </div>
          <h1 className="display-title">{t('projects.title')}</h1>
          <p className="page-hero-subtitle">
            {t('projects.subtitleLine1')}
            <br />
            {t('projects.subtitleLine2')}
          </p>
          <ul className="feature-chip-row" aria-label={t('projects.featuresLabel')}>
            {FEATURES.map(({ icon, label }) => (
              <li key={label}>
                <FeaturePill icon={icon} label={t(label)} variant="chip" />
              </li>
            ))}
          </ul>
        </div>
        <div className="page-hero-actions">
          <button type="button" className="btn light new-project-btn" onClick={openCreate}>
            <PlusIcon size={16} />
            <span>{t('projects.newProject')}</span>
            <span className="btn-divider" aria-hidden="true" />
            <ChevronDownIcon size={15} />
          </button>
        </div>
        <div className="page-hero-art" aria-hidden="true">
          <ProjectsHeroArt />
        </div>
      </header>

      {creating && (
        <div className="dialog-scrim" role="presentation">
          <form className="card project-dialog glass-card" onSubmit={handleCreate} aria-label={t('projects.createLabel')}>
            <div className="dialog-head">
              <h2>{t('projects.newProject')}</h2>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setCreating(false)}
                disabled={busy}
                aria-label={t('projects.closeDialog')}
              >
                <XIcon size={16} />
              </button>
            </div>
            <label className="field-label" htmlFor="project-name">
              {t('common.name')}
            </label>
            <input
              id="project-name"
              className="text-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
              maxLength={200}
              autoFocus
            />
            <label className="field-label" htmlFor="project-description">
              {t('common.description')}
            </label>
            <textarea
              id="project-description"
              className="text-input"
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              disabled={busy}
            />
            <div className="btn-row">
              <button type="submit" className="btn primary glow" disabled={busy || !name.trim()}>
                {busy ? t('projects.creating') : t('projects.create')}
              </button>
              <button type="button" className="btn" onClick={() => setCreating(false)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
            {createError && (
              <p className="form-error" role="alert">
                {createError}
              </p>
            )}
          </form>
        </div>
      )}

      <section className="toolbar-panel glass-card" aria-label={t('projects.findLabel')}>
        <div className="search-field">
          <SearchIcon size={18} className="search-field-icon" />
          <label className="visually-hidden" htmlFor={searchId}>
            {t('projects.searchLabel')}
          </label>
          <input
            id={searchId}
            type="search"
            className="search-input"
            placeholder={t('projects.searchPlaceholder')}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="toolbar-row">
          <div className="filter-tabs" role="group" aria-label={t('projects.filtersLabel')}>
            <button
              type="button"
              className={`filter-tab${filter === 'all' ? ' selected' : ''}`}
              aria-pressed={filter === 'all'}
              onClick={() => setFilter('all')}
            >
              {t('projects.filterAll')}
            </button>
            <button
              type="button"
              className={`filter-tab${filter === 'recent' ? ' selected' : ''}`}
              aria-pressed={filter === 'recent'}
              onClick={() => setFilter('recent')}
            >
              <ClockIcon size={15} />
              {t('projects.filterRecent')}
            </button>
            {/* Atlas is single-user and local-first: no ownership or sharing exists. */}
            <button type="button" className="filter-tab" disabled title={t('projects.filterMineTitle')}>
              <UsersIcon size={15} />
              {t('projects.filterMine')}
            </button>
            <button type="button" className="filter-tab" disabled title={t('projects.filterSharedTitle')}>
              <LayersIcon size={15} />
              {t('projects.filterShared')}
            </button>
          </div>
          <div className="toolbar-end">
            <label className="sort-control" htmlFor={sortId}>
              <span className="sort-control-label">{t('common.sortBy')}</span>
              <span className="sort-select-wrap">
                <select
                  id={sortId}
                  className="sort-select"
                  value={sort}
                  onChange={(event) => setSort(event.target.value as SortKey)}
                >
                  <option value="updated">{t('common.lastUpdated')}</option>
                  <option value="created">{t('projects.sortCreated')}</option>
                  <option value="name">{t('common.name')}</option>
                </select>
                <ChevronDownIcon size={15} className="sort-select-chevron" />
              </span>
            </label>
            <div className="view-toggle" role="group" aria-label={t('common.layout')}>
              <button
                type="button"
                className={`view-btn${layout === 'grid' ? ' selected' : ''}`}
                aria-pressed={layout === 'grid'}
                aria-label={t('common.gridView')}
                onClick={() => setLayout('grid')}
              >
                <GridIcon size={17} />
              </button>
              <button
                type="button"
                className={`view-btn${layout === 'list' ? ' selected' : ''}`}
                aria-pressed={layout === 'list'}
                aria-label={t('common.listView')}
                onClick={() => setLayout('list')}
              >
                <ListIcon size={17} />
              </button>
            </div>
          </div>
        </div>
      </section>

      {loading && (
        <div className="page-state" role="status">
          <span className="spinner" aria-hidden="true" />
          <p>{t('projects.loading')}</p>
        </div>
      )}
      {error && !loading && <p className="error-text">{error}</p>}

      {!loading && !error && projects.length === 0 && (
        <p className="empty-note">{t('projects.empty')}</p>
      )}
      {!loading && !error && projects.length > 0 && visible.length === 0 && (
        <p className="empty-note">{t('projects.noMatches')}</p>
      )}

      {!loading && !error && (
        <div className={`project-grid ${layout}`}>
          <button type="button" className={`new-project-card ${layout}`} onClick={openCreate}>
            <span className="new-project-plus">
              <PlusIcon size={30} />
            </span>
            <span className="new-project-title">{t('projects.cardTitle')}</span>
            <span className="new-project-text">
              {t('projects.cardTextLine1')}
              <br />
              {t('projects.cardTextLine2')}
            </span>
            <span className="btn primary glow new-project-cta">
              {t('projects.cardCta')}
              <ArrowRightIcon size={16} />
            </span>
          </button>
          {visible.map((project, index) => (
            <ProjectCard key={project.id} project={project} index={index} layout={layout} />
          ))}
        </div>
      )}
    </div>
  )
}
