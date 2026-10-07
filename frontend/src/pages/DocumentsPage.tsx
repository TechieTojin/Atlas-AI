import { useId, useMemo, useRef, useState } from 'react'
import { errorMessage } from '../api/client'
import { DocumentsHeroArt } from '../components/art/DocumentsHeroArt'
import { DocumentStatus, DocumentTable, fileTypeLabel } from '../components/DocumentTable'
import {
  BookIcon,
  ChevronDownIcon,
  CloudUploadIcon,
  FileTextIcon,
  FolderIcon,
  GridIcon,
  ListIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparkleIcon,
  SparklesIcon,
  TrashIcon,
  UploadIcon,
} from '../components/icons'
import { EyebrowPill, FeaturePill } from '../components/PageHero'
import { useDocuments } from '../hooks/useDocuments'
import { agoLabel, useI18n } from '../i18n'
import type { DocumentRecord } from '../types'

const MAX_SIZE_BYTES = 25 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['.pdf', '.txt', '.md']

type TypeFilter = 'all' | 'pdf' | 'txt' | 'md'
type SortKey = 'uploaded' | 'name' | 'size'
type Layout = 'list' | 'grid'

const FEATURES = [
  { icon: FileTextIcon, label: 'documents.features.formats', detail: 'documents.features.formatsDetail' },
  { icon: ShieldCheckIcon, label: 'documents.features.private', detail: 'documents.features.privateDetail' },
  { icon: SparkleIcon, label: 'documents.features.analysis', detail: 'documents.features.analysisDetail' },
  { icon: FolderIcon, label: 'documents.features.workspace', detail: 'documents.features.workspaceDetail' },
] as const

const TYPE_FILTERS = [
  ['all', 'documents.typeAll'],
  ['pdf', null],
  ['txt', 'documents.typeText'],
  ['md', 'documents.typeMarkdown'],
] as const

function isAccepted(filename: string): boolean {
  const lower = filename.toLowerCase()
  return ACCEPTED_EXTENSIONS.some((extension) => lower.endsWith(extension))
}

function matchesType(document: DocumentRecord, filter: TypeFilter): boolean {
  if (filter === 'all') return true
  return document.file_type.toLowerCase() === filter
}

function sortDocuments(documents: DocumentRecord[], sort: SortKey): DocumentRecord[] {
  const copy = [...documents]
  if (sort === 'name') return copy.sort((a, b) => a.filename.localeCompare(b.filename))
  if (sort === 'size') return copy.sort((a, b) => b.size_bytes - a.size_bytes)
  return copy.sort((a, b) => Date.parse(b.uploaded_at) - Date.parse(a.uploaded_at))
}

export function DocumentsPage() {
  const { t, format } = useI18n()
  const { documents, loading, error, upload, remove } = useDocuments()
  const [uploading, setUploading] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [sort, setSort] = useState<SortKey>('uploaded')
  const [layout, setLayout] = useState<Layout>('list')
  const [selected, setSelected] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const searchId = useId()
  const sortId = useId()

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const filtered = documents.filter((document) => {
      if (!matchesType(document, typeFilter)) return false
      if (
        needle &&
        !`${document.filename} ${document.file_type} ${document.content_type}`
          .toLowerCase()
          .includes(needle)
      ) {
        return false
      }
      return true
    })
    return sortDocuments(filtered, sort)
  }, [documents, search, typeFilter, sort])

  const handleFile = async (file: File) => {
    setUploadError(null)
    if (!isAccepted(file.name)) {
      setUploadError(t('documents.unsupported'))
      return
    }
    if (file.size > MAX_SIZE_BYTES) {
      setUploadError(t('documents.tooLarge'))
      return
    }
    setUploading(file.name)
    try {
      await upload(file)
    } catch (err) {
      setUploadError(errorMessage(err))
    } finally {
      setUploading(null)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const handleDelete = async (document: DocumentRecord) => {
    if (!window.confirm(t('documents.confirmDelete', { name: document.filename }))) return
    setDeleteError(null)
    try {
      await remove(document.id)
      setSelected((previous) => previous.filter((id) => id !== document.id))
    } catch (err) {
      setDeleteError(errorMessage(err))
    }
  }

  const handleDeleteSelected = async () => {
    const targets = documents.filter((document) => selected.includes(document.id))
    if (targets.length === 0) return
    if (!window.confirm(t('documents.confirmDeleteMany', { count: targets.length }))) return
    setDeleteError(null)
    for (const document of targets) {
      try {
        await remove(document.id)
        setSelected((previous) => previous.filter((id) => id !== document.id))
      } catch (err) {
        setDeleteError(errorMessage(err))
        break
      }
    }
  }

  const toggleSelected = (id: string) => {
    setSelected((previous) =>
      previous.includes(id) ? previous.filter((existing) => existing !== id) : [...previous, id],
    )
  }

  const toggleAll = () => {
    setSelected((previous) =>
      visible.every((document) => previous.includes(document.id))
        ? previous.filter((id) => !visible.some((document) => document.id === id))
        : Array.from(new Set([...previous, ...visible.map((document) => document.id)])),
    )
  }

  const browse = () => inputRef.current?.click()

  return (
    <div className="documents-page">
      <header className="page-hero documents-hero">
        <div className="page-hero-copy">
          <div className="page-hero-eyebrow">
            <EyebrowPill icon={BookIcon} uppercase>
              {t('documents.eyebrow')}
            </EyebrowPill>
          </div>
          <h1 className="display-title">{t('documents.title')}</h1>
          <p className="page-hero-subtitle">{t('documents.subtitle')}</p>
          <ul className="feature-pill-row" aria-label={t('documents.featuresLabel')}>
            {FEATURES.map(({ icon, label, detail }) => (
              <li key={label}>
                <FeaturePill icon={icon} label={t(label)} detail={t(detail)} variant="square" />
              </li>
            ))}
          </ul>
        </div>
        <div className="page-hero-art" aria-hidden="true">
          <DocumentsHeroArt />
        </div>
      </header>

      <div
        className={`dropzone${dragging ? ' dragging' : ''}${uploading ? ' uploading' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          const file = event.dataTransfer.files[0]
          if (file) void handleFile(file)
        }}
      >
        <CloudUploadIcon size={30} className="dropzone-icon" />
        {uploading ? (
          <p className="dropzone-text" role="status">
            <span className="spinner small" aria-hidden="true" /> {t('documents.uploading', { name: uploading })}
          </p>
        ) : (
          <>
            <p className="dropzone-text">
              {t('documents.dropText')}{' '}
              <label className="file-label" htmlFor="document-upload">
                {t('documents.browse')}
              </label>
            </p>
            <p className="dropzone-hint">{t('documents.dropHint')}</p>
          </>
        )}
        <input
          ref={inputRef}
          id="document-upload"
          type="file"
          accept=".pdf,.txt,.md"
          className="visually-hidden"
          aria-label={t('documents.uploadLabel')}
          disabled={uploading !== null}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void handleFile(file)
          }}
        />
      </div>

      {uploadError && (
        <p className="form-error" role="alert">
          {uploadError}
        </p>
      )}
      {deleteError && (
        <p className="form-error" role="alert">
          {deleteError}
        </p>
      )}

      <section className="doc-toolbar" aria-label={t('documents.findLabel')}>
        <div className="search-field compact">
          <SearchIcon size={17} className="search-field-icon" />
          <label className="visually-hidden" htmlFor={searchId}>
            {t('documents.searchLabel')}
          </label>
          <input
            id={searchId}
            type="search"
            className="search-input"
            placeholder={t('documents.searchPlaceholder')}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="filter-tabs" role="group" aria-label={t('documents.typeLabel')}>
          {TYPE_FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`filter-tab${typeFilter === value ? ' selected' : ''}`}
              aria-pressed={typeFilter === value}
              onClick={() => setTypeFilter(value)}
            >
              {typeFilter === value && value === 'all' && <span aria-hidden="true">✓</span>}
              {label ? t(label) : 'PDF'}
            </button>
          ))}
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
                <option value="uploaded">{t('common.lastUpdated')}</option>
                <option value="name">{t('common.name')}</option>
                <option value="size">{t('documents.sortSize')}</option>
              </select>
              <ChevronDownIcon size={15} className="sort-select-chevron" />
            </span>
          </label>
          <div className="view-toggle" role="group" aria-label={t('common.layout')}>
            <button
              type="button"
              className={`view-btn${layout === 'list' ? ' selected' : ''}`}
              aria-pressed={layout === 'list'}
              aria-label={t('common.listView')}
              onClick={() => setLayout('list')}
            >
              <ListIcon size={17} />
            </button>
            <button
              type="button"
              className={`view-btn${layout === 'grid' ? ' selected' : ''}`}
              aria-pressed={layout === 'grid'}
              aria-label={t('common.gridView')}
              onClick={() => setLayout('grid')}
            >
              <GridIcon size={17} />
            </button>
          </div>
        </div>
      </section>

      {selected.length > 0 && (
        <div className="selection-bar" role="status">
          <span>{t('documents.selected', { count: selected.length })}</span>
          <button type="button" className="btn danger-ghost compact" onClick={() => void handleDeleteSelected()}>
            <TrashIcon size={14} />
            {t('documents.deleteSelected')}
          </button>
          <button type="button" className="link-btn" onClick={() => setSelected([])}>
            {t('common.clear')}
          </button>
        </div>
      )}

      {loading && (
        <div className="page-state" role="status">
          <span className="spinner" aria-hidden="true" />
          <p>{t('documents.loading')}</p>
        </div>
      )}
      {error && !loading && <p className="error-text">{error}</p>}

      {!loading && !error && documents.length === 0 && (
        <p className="empty-note">{t('documents.empty')}</p>
      )}
      {!loading && !error && documents.length > 0 && visible.length === 0 && (
        <p className="empty-note">{t('documents.noMatches')}</p>
      )}

      {visible.length > 0 && layout === 'list' && (
        <DocumentTable
          documents={visible}
          selected={selected}
          onToggleSelected={toggleSelected}
          onToggleAll={toggleAll}
          onDelete={(document) => void handleDelete(document)}
        />
      )}

      {visible.length > 0 && layout === 'grid' && (
        <div className="doc-grid">
          {visible.map((document) => (
            <article key={document.id} className="doc-card glass-card">
              <div className="doc-card-head">
                <span className="badge type-badge">{fileTypeLabel(document.file_type)}</span>
                <DocumentStatus document={document} />
              </div>
              <span className="doc-card-name">{document.filename}</span>
              <span className="doc-card-meta">
                {t('documents.cardMeta', {
                  size: format.bytes(document.size_bytes),
                  count: document.chunk_count || 0,
                  time: agoLabel(t, format, document.uploaded_at),
                })}
              </span>
              <div className="doc-card-actions">
                <button
                  type="button"
                  className="icon-btn danger"
                  aria-label={t('common.deleteNamed', { name: document.filename })}
                  onClick={() => void handleDelete(document)}
                >
                  <TrashIcon size={15} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <section className="promo-panel" aria-label={t('documents.promoLabel')}>
        <div className="promo-art" aria-hidden="true">
          <span className="promo-art-doc">
            <FileTextIcon size={28} />
          </span>
          <SparklesIcon size={22} className="promo-art-sparkle" />
        </div>
        <div className="promo-copy">
          <h2 className="promo-title">{t('documents.promoTitle')}</h2>
          <p className="promo-text">{t('documents.promoText')}</p>
        </div>
        <button type="button" className="btn primary glow large" onClick={browse} disabled={uploading !== null}>
          <UploadIcon size={16} />
          <span>{t('documents.uploadMore')}</span>
        </button>
      </section>
    </div>
  )
}
