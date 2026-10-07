import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, errorMessage, exportUrl, notifyRunsChanged } from '../api/client'
import { useTemplates } from '../hooks/useTemplates'
import type { RunDetail } from '../types'
import { DownloadIcon } from './icons'

/** Small export menu offering markdown and PDF downloads. */
export function ExportMenu({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="menu-wrap" ref={wrapRef}>
      <button
        type="button"
        className="btn"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <DownloadIcon size={14} />
        <span>Export</span>
      </button>
      {open && (
        <div className="menu" role="menu" aria-label="Export formats">
          <a
            role="menuitem"
            className="menu-item"
            href={exportUrl(runId, 'markdown')}
            download
            onClick={() => setOpen(false)}
          >
            Markdown (.md)
          </a>
          <a
            role="menuitem"
            className="menu-item"
            href={exportUrl(runId, 'pdf')}
            download
            onClick={() => setOpen(false)}
          >
            PDF (.pdf)
          </a>
        </div>
      )}
    </div>
  )
}

const CUSTOM_MAX_LENGTH = 2000

/** "Regenerate report" action: pick a template and re-run synthesis only. */
export function RegenerateAction({ run }: { run: RunDetail }) {
  const navigate = useNavigate()
  const { templates } = useTemplates()
  const [open, setOpen] = useState(false)
  const [template, setTemplate] = useState(run.template ?? 'STANDARD')
  const [custom, setCustom] = useState(run.custom_template ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isCustom = template === 'CUSTOM'
  const customValid = !isCustom || (custom.trim().length > 0 && custom.length <= CUSTOM_MAX_LENGTH)
  const selected = templates.find((entry) => entry.id === template)

  const handleRegenerate = async () => {
    if (!customValid || busy) return
    setBusy(true)
    setError(null)
    try {
      const newRun = await api.regenerateRun(run.id, {
        template,
        ...(isCustom ? { custom_template: custom.trim() } : {}),
      })
      notifyRunsChanged()
      setOpen(false)
      navigate(`/runs/${newRun.id}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="menu-wrap">
      <button type="button" className="btn" onClick={() => setOpen((value) => !value)}>
        Regenerate report
      </button>
      {open && (
        <div className="regenerate-card card" role="dialog" aria-label="Regenerate report">
          <h2>Regenerate report</h2>
          <p className="hint-text">
            Re-run synthesis over the same evidence with a different report template.
          </p>
          <label className="field-label" htmlFor="regen-template">
            Template
          </label>
          <select
            id="regen-template"
            className="select-input"
            value={template}
            onChange={(event) => setTemplate(event.target.value)}
            disabled={busy}
          >
            {templates.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
          </select>
          {selected && <p className="hint-text">{selected.description}</p>}
          {isCustom && (
            <>
              <label className="field-label" htmlFor="regen-custom">
                Custom instructions (required)
              </label>
              <textarea
                id="regen-custom"
                className="text-input"
                rows={4}
                maxLength={CUSTOM_MAX_LENGTH}
                value={custom}
                onChange={(event) => setCustom(event.target.value)}
                disabled={busy}
              />
              <p className="hint-text">
                {custom.length}/{CUSTOM_MAX_LENGTH} characters
              </p>
            </>
          )}
          <div className="btn-row">
            <button
              type="button"
              className="btn primary"
              onClick={() => void handleRegenerate()}
              disabled={busy || !customValid}
            >
              {busy ? 'Regenerating…' : 'Regenerate'}
            </button>
            <button type="button" className="btn" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </button>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
