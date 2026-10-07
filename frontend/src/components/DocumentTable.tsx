import { Fragment, useEffect, useRef, useState } from 'react'
import { useI18n, type LocaleFormatters } from '../i18n'
import type { DocumentRecord } from '../types'
import { EyeIcon, MoreVerticalIcon, TrashIcon } from './icons'

export function DocumentStatus({ document }: { document: DocumentRecord }) {
  const { t } = useI18n()
  if (document.status === 'PROCESSING') {
    return (
      <span className="doc-status processing">
        <span className="spinner small" aria-hidden="true" />
        {t('documentTable.processing')}
      </span>
    )
  }
  if (document.status === 'FAILED') {
    return (
      <span className="doc-status failed" title={document.error || t('documentTable.processingFailed')}>
        <span className="doc-status-mark" aria-hidden="true">
          ✕
        </span>
        {t('documentTable.failed')}
      </span>
    )
  }
  return (
    <span className="doc-status ready">
      <span className="doc-status-mark" aria-hidden="true">
        ✓
      </span>
      {t('documentTable.ready')}
    </span>
  )
}

function uploadedParts(format: LocaleFormatters, iso: string): { date: string; time: string } {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return { date: '—', time: '' }
  return { date: format.date(then), time: format.time(then) }
}

export function fileTypeLabel(fileType: string): string {
  return fileType.toUpperCase()
}

function TypeMark({ fileType }: { fileType: string }) {
  const kind = fileType.toLowerCase()
  const tone = kind === 'pdf' ? 'pdf' : kind === 'md' ? 'md' : 'txt'
  const label = kind === 'pdf' ? 'PDF' : kind === 'md' ? 'MD' : 'TXT'
  return (
    <span className={`doc-type-mark tone-${tone}`} aria-hidden="true">
      <svg viewBox="0 0 36 44" className="doc-type-sheet">
        <path d="M4 2h20l10 10v28a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" className="doc-type-page" />
        <path d="M24 2v8a2 2 0 0 0 2 2h8z" className="doc-type-fold" />
        <rect x="7" y="16" width="14" height="2.4" rx="1.2" className="doc-type-line" />
        <rect x="7" y="21" width="19" height="2.4" rx="1.2" className="doc-type-line" />
      </svg>
      <span className="doc-type-label">{label}</span>
    </span>
  )
}

function RowMenu({ document, onDelete }: { document: DocumentRecord; onDelete: () => void }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.document.addEventListener('mousedown', onDocClick)
    window.document.addEventListener('keydown', onKey)
    return () => {
      window.document.removeEventListener('mousedown', onDocClick)
      window.document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="menu-wrap" ref={ref}>
      <button
        type="button"
        className="icon-btn"
        aria-label={t('common.moreActionsFor', { name: document.filename })}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <MoreVerticalIcon size={17} />
      </button>
      {open && (
        <div className="menu align-end" role="menu" aria-label={t('common.actionsFor', { name: document.filename })}>
          <button
            type="button"
            role="menuitem"
            className="menu-item danger"
            onClick={() => {
              setOpen(false)
              onDelete()
            }}
            aria-label={t('common.deleteNamed', { name: document.filename })}
          >
            <TrashIcon size={14} />
            {t('common.delete')}
          </button>
        </div>
      )}
    </div>
  )
}

export interface DocumentTableProps {
  documents: DocumentRecord[]
  selected: string[]
  onToggleSelected: (id: string) => void
  onToggleAll: () => void
  onDelete: (document: DocumentRecord) => void
}

/** Real document records in the reference's table layout, with an expandable details row. */
export function DocumentTable({ documents, selected, onToggleSelected, onToggleAll, onDelete }: DocumentTableProps) {
  const { t, format } = useI18n()
  const [expanded, setExpanded] = useState<string | null>(null)
  const allSelected = documents.length > 0 && documents.every((doc) => selected.includes(doc.id))

  return (
    <div className="doc-table-wrap glass-card">
      <table className="doc-table">
        <thead>
          <tr>
            <th scope="col" className="doc-col-check">
              <input
                type="checkbox"
                className="atlas-checkbox"
                aria-label={t('documentTable.selectAll')}
                checked={allSelected}
                onChange={onToggleAll}
              />
            </th>
            <th scope="col">{t('common.name')}</th>
            <th scope="col">{t('documentTable.type')}</th>
            <th scope="col">{t('documentTable.size')}</th>
            <th scope="col">{t('documentTable.pages')}</th>
            <th scope="col">{t('documentTable.chunks')}</th>
            <th scope="col">{t('documentTable.status')}</th>
            <th scope="col">{t('documentTable.uploaded')}</th>
            <th scope="col" className="doc-col-actions">
              {t('documentTable.actions')}
            </th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => {
            const uploaded = uploadedParts(format, document.uploaded_at)
            const isExpanded = expanded === document.id
            return (
              <Fragment key={document.id}>
                <tr className={selected.includes(document.id) ? 'selected' : undefined}>
                  <td className="doc-col-check">
                    <input
                      type="checkbox"
                      className="atlas-checkbox"
                      aria-label={t('common.selectNamed', { name: document.filename })}
                      checked={selected.includes(document.id)}
                      onChange={() => onToggleSelected(document.id)}
                    />
                  </td>
                  <td className="doc-name">
                    <TypeMark fileType={document.file_type} />
                    <span className="doc-name-text">{document.filename}</span>
                  </td>
                  <td>
                    <span className="badge type-badge">{fileTypeLabel(document.file_type)}</span>
                  </td>
                  <td>{format.bytes(document.size_bytes)}</td>
                  <td>{document.page_count || '—'}</td>
                  <td>{document.chunk_count || '—'}</td>
                  <td>
                    <DocumentStatus document={document} />
                  </td>
                  <td className="doc-uploaded">
                    <span>{uploaded.date}</span>
                    {uploaded.time && <span className="doc-uploaded-time">{uploaded.time}</span>}
                  </td>
                  <td className="doc-col-actions">
                    <div className="doc-actions">
                      <button
                        type="button"
                        className={`icon-btn${isExpanded ? ' active' : ''}`}
                        aria-label={t(isExpanded ? 'documentTable.hideDetails' : 'documentTable.viewDetails', {
                          name: document.filename,
                        })}
                        aria-expanded={isExpanded}
                        onClick={() => setExpanded(isExpanded ? null : document.id)}
                      >
                        <EyeIcon size={17} />
                      </button>
                      <RowMenu document={document} onDelete={() => onDelete(document)} />
                    </div>
                  </td>
                </tr>
                {isExpanded && (
                  <tr className="doc-details-row">
                    <td colSpan={9}>
                      <dl className="doc-details">
                        <div>
                          <dt>{t('documentTable.contentType')}</dt>
                          <dd>{document.content_type || '—'}</dd>
                        </div>
                        <div>
                          <dt>{t('documentTable.checksum')}</dt>
                          <dd className="mono">{document.checksum || '—'}</dd>
                        </div>
                        <div>
                          <dt>{t('documentTable.documentId')}</dt>
                          <dd className="mono">{document.id}</dd>
                        </div>
                        {document.error && (
                          <div>
                            <dt>{t('documentTable.error')}</dt>
                            <dd className="error-text">{document.error}</dd>
                          </div>
                        )}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
