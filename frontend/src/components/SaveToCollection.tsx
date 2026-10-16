import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useI18n } from '../i18n'
import type { Collection, CollectionItemType } from '../types'
import { BookmarkIcon, CheckIcon, PlusIcon } from './icons'

/**
 * Compact "Save to collection" action: pick an existing collection or create
 * one inline. ``data`` is the frozen snapshot + origin reference built by the
 * caller from already-loaded truth (never re-fetched, never rewritten).
 */
export function SaveToCollection({
  itemType,
  data,
  note = '',
}: {
  itemType: CollectionItemType
  data: Record<string, unknown>
  note?: string
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [collections, setCollections] = useState<Collection[] | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<'saved' | 'existing' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    let active = true
    api
      .listCollections()
      .then((body) => {
        if (active) setCollections(body.collections)
      })
      .catch((err) => {
        if (active) setError(errorMessage(err))
      })
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onClick = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      active = false
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const save = async (collectionId: string) => {
    setBusy(true)
    setError(null)
    try {
      const item = await api.addCollectionItem(collectionId, { type: itemType, note, data })
      setDone(item.existing ? 'existing' : 'saved')
      window.setTimeout(() => {
        setOpen(false)
        setDone(null)
      }, 1200)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const createAndSave = async (event: React.FormEvent) => {
    event.preventDefault()
    const title = newTitle.trim()
    if (!title || busy) return
    setBusy(true)
    setError(null)
    try {
      const collection = await api.createCollection({ title })
      setNewTitle('')
      await save(collection.id)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div className="save-to-collection" ref={rootRef}>
      <button
        type="button"
        className="btn light compact"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((value) => !value)}
      >
        <BookmarkIcon size={13} />
        <span>{t('collections.save')}</span>
      </button>
      {open && (
        <div className="save-to-collection-panel" role="menu" aria-label={t('collections.pick')}>
          {done ? (
            <p className="save-to-collection-done" role="status">
              <CheckIcon size={13} />{' '}
              {done === 'saved' ? t('collections.saved') : t('collections.alreadySaved')}
            </p>
          ) : (
            <>
              <p className="panel-heading">{t('collections.pick')}</p>
              {collections === null && !error && (
                <p className="hint-text" role="status">
                  <span className="spinner small" aria-hidden="true" /> {t('collections.loading')}
                </p>
              )}
              {collections !== null && collections.length === 0 && (
                <p className="hint-text">{t('collections.none')}</p>
              )}
              {collections !== null && collections.length > 0 && (
                <ul className="save-to-collection-list">
                  {collections.map((collection) => (
                    <li key={collection.id}>
                      <button
                        type="button"
                        className="link-btn"
                        role="menuitem"
                        disabled={busy}
                        onClick={() => void save(collection.id)}
                      >
                        {collection.title}
                        {typeof collection.item_count === 'number'
                          ? ` (${collection.item_count})`
                          : ''}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <form className="save-to-collection-new" onSubmit={createAndSave}>
                <input
                  type="text"
                  maxLength={160}
                  placeholder={t('collections.newPlaceholder')}
                  aria-label={t('collections.newPlaceholder')}
                  value={newTitle}
                  onChange={(event) => setNewTitle(event.target.value)}
                  disabled={busy}
                />
                <button type="submit" className="btn compact" disabled={!newTitle.trim() || busy}>
                  <PlusIcon size={13} />
                  <span>{t('collections.create')}</span>
                </button>
              </form>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
