import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { SaveToCollection } from '../components/SaveToCollection'
import {
  ArrowLeftIcon,
  BookmarkIcon,
  FileTextIcon,
  GlobeIcon,
  LayersIcon,
  NotebookIcon,
  PlusIcon,
  QuoteIcon,
  SearchIcon,
  TrashIcon,
} from '../components/icons'
import { agoLabel, useI18n, type Translate } from '../i18n'
import type { Collection, CollectionItem, CollectionItemType } from '../types'
import { safeHttpUrl } from '../utils/safeUrl'

export { SaveToCollection }

const TYPE_ICONS: Record<CollectionItemType, typeof QuoteIcon> = {
  run: SearchIcon,
  source: LayersIcon,
  evidence: QuoteIcon,
  document: FileTextIcon,
  document_passage: FileTextIcon,
  website_passage: GlobeIcon,
  note: BookmarkIcon,
}

/** Where an item's origin lives in the app ("" when it no longer exists). */
function originLink(item: CollectionItem): string {
  const d = item.data
  if (item.origin_exists === false) return ''
  if (typeof d.run_id === 'string' && d.run_id) return `/runs/${d.run_id}`
  if (typeof d.website_id === 'string' && d.website_id) return `/websites/${d.website_id}`
  if (typeof d.document_id === 'string' && d.document_id) return '/documents'
  return ''
}

export function CollectionsPage() {
  const { t, format } = useI18n()
  const [collections, setCollections] = useState<Collection[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const inputId = useId()

  const load = useCallback(() => {
    api
      .listCollections()
      .then((body) => setCollections(body.collections))
      .catch(setError)
  }, [])
  useEffect(() => {
    load()
  }, [load])

  const create = async (event: React.FormEvent) => {
    event.preventDefault()
    const name = title.trim()
    if (!name || busy) return
    setBusy(true)
    try {
      const collection = await api.createCollection({ title: name })
      navigate(`/collections/${collection.id}`)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <div className="website-page collections-page">
      <header className="page-hero website-hero">
        <div className="page-hero-copy">
          <p className="page-hero-eyebrow">{t('collections.eyebrow')}</p>
          <h1 className="display-title">{t('collections.title')}</h1>
          <p className="page-hero-subtitle">{t('collections.subtitle')}</p>
        </div>
      </header>

      <form className="website-url-form glass-card collections-create" onSubmit={create}>
        <label htmlFor={inputId} className="website-url-label">
          {t('collections.createLabel')}
        </label>
        <div className="website-url-row">
          <span className="website-url-input-wrap">
            <NotebookIcon size={17} className="website-url-icon" />
            <input
              id={inputId}
              type="text"
              maxLength={160}
              className="website-url-input"
              placeholder={t('collections.newPlaceholder')}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              disabled={busy}
            />
          </span>
          <button type="submit" className="btn primary glow" disabled={!title.trim() || busy}>
            <span>{t('collections.create')}</span>
          </button>
        </div>
      </form>

      {error ? (
        <p className="error-text" role="alert">
          {errorMessage(error)}
        </p>
      ) : null}
      {collections === null && !error && (
        <div className="page-state" role="status">
          <span className="spinner" aria-hidden="true" />
          <p>{t('collections.loading')}</p>
        </div>
      )}
      {collections !== null && collections.length === 0 && (
        <p className="empty-note">{t('collections.empty')}</p>
      )}
      {collections !== null && collections.length > 0 && (
        <ul className="website-list collections-list">
          {collections.map((collection) => (
            <li key={collection.id}>
              <Link className="website-card glass-card" to={`/collections/${collection.id}`}>
                <span className="website-card-icon" aria-hidden="true">
                  <NotebookIcon size={18} />
                </span>
                <span className="website-card-body">
                  <span className="website-card-title">{collection.title}</span>
                  <span className="website-card-url">
                    {t('collections.itemCount', { count: String(collection.item_count ?? 0) })} ·{' '}
                    {agoLabel(t, format, collection.updated_at)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function CollectionPage() {
  const { t, format } = useI18n()
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [collection, setCollection] = useState<Collection | null>(null)
  const [items, setItems] = useState<CollectionItem[]>([])
  const [error, setError] = useState<unknown>(null)
  const [filter, setFilter] = useState<'all' | CollectionItemType>('all')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const noteId = useId()

  const load = useCallback(() => {
    api
      .getCollection(id)
      .then((body) => {
        setCollection(body.collection)
        setItems(body.items)
        setError(null)
      })
      .catch(setError)
  }, [id])
  useEffect(() => {
    load()
  }, [load])

  const visible = useMemo(
    () => (filter === 'all' ? items : items.filter((item) => item.type === filter)),
    [items, filter],
  )
  const presentTypes = useMemo(() => [...new Set(items.map((item) => item.type))], [items])

  const addNote = async (event: React.FormEvent) => {
    event.preventDefault()
    const text = note.trim()
    if (!text || busy) return
    setBusy(true)
    try {
      await api.addCollectionItem(id, { type: 'note', note: text, data: {} })
      setNote('')
      load()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const removeItem = async (item: CollectionItem) => {
    try {
      await api.deleteCollectionItem(item.id)
      load()
    } catch (err) {
      setError(err)
    }
  }

  const removeCollection = async () => {
    if (!collection) return
    if (!window.confirm(t('collections.confirmDelete', { title: collection.title }))) return
    try {
      await api.deleteCollection(collection.id)
      navigate('/collections')
    } catch (err) {
      setError(err)
    }
  }

  if (error && !collection) {
    return (
      <div className="website-page">
        <Link className="back-link" to="/collections">
          <ArrowLeftIcon size={14} /> {t('collections.back')}
        </Link>
        <p className="error-text" role="alert">
          {errorMessage(error)}
        </p>
      </div>
    )
  }
  if (!collection) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('collections.loading')}</p>
      </div>
    )
  }

  return (
    <div className="website-page collection-page">
      <Link className="back-link" to="/collections">
        <ArrowLeftIcon size={14} /> {t('collections.back')}
      </Link>
      <header className="website-header glass-card">
        <div className="website-header-main">
          <span className="website-card-icon" aria-hidden="true">
            <NotebookIcon size={20} />
          </span>
          <div className="website-header-text">
            <h1 className="website-title">{collection.title}</h1>
            {collection.description && <p className="hint-text">{collection.description}</p>}
          </div>
        </div>
        <div className="website-actions">
          <button type="button" className="btn danger-ghost compact" onClick={() => void removeCollection()}>
            <TrashIcon size={14} />
            <span>{t('collections.delete')}</span>
          </button>
        </div>
      </header>

      {error ? (
        <p className="error-text" role="alert">
          {errorMessage(error)}
        </p>
      ) : null}

      <form className="collection-note-form glass-card" onSubmit={addNote}>
        <label htmlFor={noteId} className="panel-heading">
          {t('collections.addNote')}
        </label>
        <div className="collection-note-row">
          <textarea
            id={noteId}
            rows={2}
            maxLength={4000}
            placeholder={t('collections.notePlaceholder')}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            disabled={busy}
          />
          <button type="submit" className="btn primary compact" disabled={!note.trim() || busy}>
            <PlusIcon size={14} />
            <span>{t('collections.saveNote')}</span>
          </button>
        </div>
      </form>

      {presentTypes.length > 1 && (
        <div className="collection-filters" role="group" aria-label={t('collections.filterLabel')}>
          <button
            type="button"
            className={`tier-chip${filter === 'all' ? ' active' : ''}`}
            onClick={() => setFilter('all')}
          >
            {t('collections.filterAll')}
          </button>
          {presentTypes.map((type) => (
            <button
              key={type}
              type="button"
              className={`tier-chip${filter === type ? ' active' : ''}`}
              onClick={() => setFilter(type)}
            >
              {t(`collections.type.${type}`)}
            </button>
          ))}
        </div>
      )}

      {items.length === 0 && <p className="empty-note">{t('collections.noItems')}</p>}
      <ul className="collection-items">
        {visible.map((item) => (
          <ItemCard key={item.id} item={item} t={t} format={format} onDelete={() => void removeItem(item)} />
        ))}
      </ul>
    </div>
  )
}

function ItemCard({
  item,
  t,
  format,
  onDelete,
}: {
  item: CollectionItem
  t: Translate
  format: ReturnType<typeof useI18n>['format']
  onDelete: () => void
}) {
  const Icon = TYPE_ICONS[item.type]
  const d = item.data
  const title =
    (typeof d.title === 'string' && d.title) ||
    (typeof d.filename === 'string' && d.filename) ||
    (typeof d.question === 'string' && d.question) ||
    t(`collections.type.${item.type}`)
  const text = typeof d.text === 'string' ? d.text : ''
  const link = originLink(item)
  const url = typeof d.url === 'string' ? safeHttpUrl(d.url) : null
  const isNote = item.type === 'note'
  return (
    <li className={`collection-item glass-card${isNote ? ' is-note' : ''}`}>
      <div className="collection-item-head">
        <span className={`collection-item-kind${isNote ? ' note' : ''}`}>
          <Icon size={13} />
          {t(`collections.type.${item.type}`)}
          {typeof d.citation === 'number' ? ` [${d.citation}]` : ''}
        </span>
        <span className="history-meta">{agoLabel(t, format, item.created_at)}</span>
        <button type="button" className="icon-btn danger" aria-label={t('collections.removeItem')} onClick={onDelete}>
          <TrashIcon size={13} />
        </button>
      </div>
      {!isNote && <p className="collection-item-title">{title}</p>}
      {isNote ? (
        <p className="collection-item-note-text">{item.note}</p>
      ) : (
        <>
          {text && <blockquote className="collection-item-text">{text}</blockquote>}
          {item.note && (
            <p className="collection-item-annotation">
              <span className="collection-item-kind note">
                <BookmarkIcon size={11} /> {t('collections.type.note')}
              </span>{' '}
              {item.note}
            </p>
          )}
        </>
      )}
      <div className="collection-item-footer">
        {item.origin_exists === false && (
          <span className="collection-item-missing">{t('collections.originGone')}</span>
        )}
        {link && (
          <Link className="link-btn" to={link}>
            {t('collections.openOrigin')}
          </Link>
        )}
        {url && (
          <a className="link-btn" href={url} target="_blank" rel="noopener noreferrer">
            {t('collections.openSource')}
          </a>
        )}
      </div>
    </li>
  )
}
