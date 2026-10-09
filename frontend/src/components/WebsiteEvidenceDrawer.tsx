import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import type { WebsiteCitation, WebsiteSource } from '../types'
import { safeHttpUrl } from '../utils/safeUrl'
import { ExternalIcon, GlobeIcon, XIcon } from './icons'

/**
 * The exact passage behind one Website Chat citation, in the report
 * drawer's visual language (same classes, Escape/backdrop dismissal, focus).
 *
 * The passage is the extracted source text frozen when the answer was
 * written, rendered as plain text in the page's own language; it is never a
 * translation and never HTML.
 *
 * Rendered into ``document.body`` so no page stacking context (the Website
 * Chat page isolates its backdrop gradient) can put the app's sticky mobile
 * top bar over the drawer header and its close button.
 */
export function WebsiteEvidenceDrawer({
  citation,
  website,
  onClose,
}: {
  citation: WebsiteCitation
  website: WebsiteSource
  onClose: () => void
}) {
  const { t } = useI18n()
  const drawerRef = useRef<HTMLElement>(null)

  useEffect(() => {
    drawerRef.current?.focus()
  }, [citation.index, citation.chunk_id])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const url = citation.url || website.final_url || website.normalized_url
  const href = safeHttpUrl(url)
  const earlier = citation.index_version !== website.index_version
  const trail = citation.heading_path.length > 0 ? citation.heading_path : [citation.section_title].filter(Boolean)

  return createPortal(
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside
        ref={drawerRef}
        className="drawer website-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={t('websiteChat.drawer.label', { index: String(citation.index) })}
        tabIndex={-1}
      >
        <header className="drawer-header">
          <span className="source-index" aria-hidden="true">
            {citation.index}
          </span>
          <h2 className="drawer-title">{citation.page_title || website.page_title || website.domain}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t('websiteChat.drawer.close')}>
            <XIcon size={15} />
          </button>
        </header>
        <div className="drawer-body">
          <dl className="website-drawer-meta">
            <div>
              <dt>{t('websiteChat.drawer.website')}</dt>
              <dd>
                <GlobeIcon size={13} className="source-icon" /> {website.domain}
              </dd>
            </div>
            {trail.length > 0 && (
              <div>
                <dt>{t('websiteChat.drawer.section')}</dt>
                <dd lang={website.content_language || undefined}>{trail.join(' › ')}</dd>
              </div>
            )}
            <div>
              <dt>{t('websiteChat.drawer.url')}</dt>
              <dd className="website-url">{url}</dd>
            </div>
          </dl>
          <section className="drawer-section">
            <h3 className="panel-heading">{t('websiteChat.drawer.passage')}</h3>
            {earlier && <p className="hint-text">{t('websiteChat.drawer.earlierVersion')}</p>}
            {/* The page's own declared language, verbatim (it may be any language). */}
            <blockquote className="website-passage" lang={website.content_language || undefined}>
              {citation.text}
            </blockquote>
          </section>
          {href && (
            <a className="btn drawer-open-link" href={href} target="_blank" rel="noopener noreferrer">
              <ExternalIcon size={13} />
              <span>{t('websiteChat.openOriginal')}</span>
            </a>
          )}
        </div>
      </aside>
    </>,
    document.body,
  )
}
