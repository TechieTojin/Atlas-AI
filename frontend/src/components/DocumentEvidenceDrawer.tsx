import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import type { DocumentCitation } from '../types'
import { FileTextIcon, XIcon } from './icons'

/**
 * The exact stored passage behind one Document Chat citation: document,
 * page, and the verbatim excerpt the model was shown. Rendered as text,
 * never markup. Portalled to <body> like the website drawer so no page
 * stacking context can cover it.
 */
export function DocumentEvidenceDrawer({
  citation,
  onClose,
  onSave,
}: {
  citation: DocumentCitation
  onClose: () => void
  onSave?: React.ReactNode
}) {
  const { t } = useI18n()
  const drawerRef = useRef<HTMLElement>(null)

  useEffect(() => {
    drawerRef.current?.focus()
  }, [citation.index, citation.document_id])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return createPortal(
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside
        ref={drawerRef}
        className="drawer website-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={t('documentChat.drawer.label', { index: String(citation.index) })}
        tabIndex={-1}
      >
        <header className="drawer-header">
          <span className="source-index" aria-hidden="true">
            {citation.index}
          </span>
          <h2 className="drawer-title">{citation.filename || t('documentChat.drawer.document')}</h2>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label={t('documentChat.drawer.close')}
          >
            <XIcon size={15} />
          </button>
        </header>
        <div className="drawer-body">
          <dl className="website-drawer-meta">
            <div>
              <dt>{t('documentChat.drawer.document')}</dt>
              <dd>
                <FileTextIcon size={13} className="source-icon" /> {citation.filename}
              </dd>
            </div>
            {citation.page !== null && (
              <div>
                <dt>{t('documentChat.drawer.page')}</dt>
                <dd>{citation.page}</dd>
              </div>
            )}
          </dl>
          <section className="drawer-section">
            <h3 className="panel-heading">{t('documentChat.drawer.passage')}</h3>
            <blockquote className="website-passage">{citation.text}</blockquote>
          </section>
          {onSave}
        </div>
      </aside>
    </>,
    document.body,
  )
}
