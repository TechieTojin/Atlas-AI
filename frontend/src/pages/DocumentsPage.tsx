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
import type { DocumentRecord } from '../types'
import { formatBytes, relativeTime } from '../utils/format'

const MAX_SIZE_BYTES = 25 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['.pdf', '.txt', '.md']

type TypeFilter = 'all' | 'pdf' | 'txt' | 'md'
type SortKey = 'uploaded' | 'name' | 'size'
type Layout = 'list' | 'grid'

const FEATURES = [
  { icon: FileTextIcon, label: 'Multiple Formats', detail: 'PDF, TXT, MD and more' },
  { icon: ShieldCheckIcon, label: 'Secure & Private', detail: 'Your data stays yours' },
  { icon: SparkleIcon, label: 'Instant Analysis', detail: 'Get insights in seconds' },
  { icon: FolderIcon, label: 'Organized Workspace', detail: 'Keep everything in one place' },
]

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
      setUploadError('Unsupported file type. Upload a .pdf, .txt, or .md file.')
      return
    }
    if (file.size > MAX_SIZE_BYTES) {
      setUploadError('File is too large. The maximum size is 25 MB.')
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
    if (!window.confirm(`Delete “${document.filename}”? This cannot be undone.`)) return
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
    if (
      !window.confirm(
        `Delete ${targets.length} document${targets.length === 1 ? '' : 's'}? This cannot be undone.`,
      )
    ) {
      return
    }
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
              Your Knowledge Library
            </EyebrowPill>
          </div>
          <h1 className="display-title">Documents</h1>
          <p className="page-hero-subtitle">
            Upload PDFs, text, or markdown files to research against your own sources.
          </p>
          <ul className="feature-pill-row" aria-label="Library features">
            {FEATURES.map(({ icon, label, detail }) => (
              <li key={label}>
                <FeaturePill icon={icon} label={label} detail={detail} variant="square" />
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
            <span className="spinner small" aria-hidden="true" /> Uploading {uploading}…
          </p>
        ) : (
          <>
            <p className="dropzone-text">
              Drag and drop a file here, or{' '}
              <label className="file-label" htmlFor="document-upload">
                browse
              </label>
            </p>
            <p className="dropzone-hint">PDF, TXT, MD — up to 25 MB</p>
          </>
        )}
        <input
          ref={inputRef}
          id="document-upload"
          type="file"
          accept=".pdf,.txt,.md"
          className="visually-hidden"
          aria-label="Upload document"
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

      <section className="doc-toolbar" aria-label="Find documents">
        <div className="search-field compact">
          <SearchIcon size={17} className="search-field-icon" />
          <label className="visually-hidden" htmlFor={searchId}>
            Search documents
          </label>
          <input
            id={searchId}
            type="search"
            className="search-input"
            placeholder="Search documents by name, type, or content..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="filter-tabs" role="group" aria-label="File type">
          {(
            [
              ['all', 'All Files'],
              ['pdf', 'PDF'],
              ['txt', 'Text'],
              ['md', 'Markdown'],
            ] as [TypeFilter, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`filter-tab${typeFilter === value ? ' selected' : ''}`}
              aria-pressed={typeFilter === value}
              onClick={() => setTypeFilter(value)}
            >
              {typeFilter === value && value === 'all' && <span aria-hidden="true">✓</span>}
              {label}
            </button>
          ))}
        </div>
        <div className="toolbar-end">
          <label className="sort-control" htmlFor={sortId}>
            <span className="sort-control-label">Sort by:</span>
            <span className="sort-select-wrap">
              <select
                id={sortId}
                className="sort-select"
                value={sort}
                onChange={(event) => setSort(event.target.value as SortKey)}
              >
                <option value="uploaded">Last Updated</option>
                <option value="name">Name</option>
                <option value="size">Size</option>
              </select>
              <ChevronDownIcon size={15} className="sort-select-chevron" />
            </span>
          </label>
          <div className="view-toggle" role="group" aria-label="Layout">
            <button
              type="button"
              className={`view-btn${layout === 'list' ? ' selected' : ''}`}
              aria-pressed={layout === 'list'}
              aria-label="List view"
              onClick={() => setLayout('list')}
            >
              <ListIcon size={17} />
            </button>
            <button
              type="button"
              className={`view-btn${layout === 'grid' ? ' selected' : ''}`}
              aria-pressed={layout === 'grid'}
              aria-label="Grid view"
              onClick={() => setLayout('grid')}
            >
              <GridIcon size={17} />
            </button>
          </div>
        </div>
      </section>

      {selected.length > 0 && (
        <div className="selection-bar" role="status">
          <span>
            {selected.length} selected
          </span>
          <button type="button" className="btn danger-ghost compact" onClick={() => void handleDeleteSelected()}>
            <TrashIcon size={14} />
            Delete selected
          </button>
          <button type="button" className="link-btn" onClick={() => setSelected([])}>
            Clear
          </button>
        </div>
      )}

      {loading && (
        <div className="page-state" role="status">
          <span className="spinner" aria-hidden="true" />
          <p>Loading documents…</p>
        </div>
      )}
      {error && !loading && <p className="error-text">{error}</p>}

      {!loading && !error && documents.length === 0 && (
        <p className="empty-note">No documents yet. Upload one to get started.</p>
      )}
      {!loading && !error && documents.length > 0 && visible.length === 0 && (
        <p className="empty-note">No documents match your filters.</p>
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
                {formatBytes(document.size_bytes)} · {document.chunk_count || 0} chunks · uploaded{' '}
                {relativeTime(document.uploaded_at)}
              </span>
              <div className="doc-card-actions">
                <button
                  type="button"
                  className="icon-btn danger"
                  aria-label={`Delete ${document.filename}`}
                  onClick={() => void handleDelete(document)}
                >
                  <TrashIcon size={15} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <section className="promo-panel" aria-label="Upload more">
        <div className="promo-art" aria-hidden="true">
          <span className="promo-art-doc">
            <FileTextIcon size={28} />
          </span>
          <SparklesIcon size={22} className="promo-art-sparkle" />
        </div>
        <div className="promo-copy">
          <h2 className="promo-title">Turn your documents into insights</h2>
          <p className="promo-text">
            Upload research papers, notes, or reports and ask questions to get instant, accurate
            answers powered by AI.
          </p>
        </div>
        <button type="button" className="btn primary glow large" onClick={browse} disabled={uploading !== null}>
          <UploadIcon size={16} />
          <span>Upload More Files</span>
        </button>
      </section>
    </div>
  )
}
