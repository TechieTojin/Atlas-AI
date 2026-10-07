import { useId, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, errorMessage, notifyRunsChanged } from '../api/client'
import { useDocuments } from '../hooks/useDocuments'
import { useTemplates } from '../hooks/useTemplates'
import type { RunMode, SourceScope } from '../types'
import {
  ArrowRightIcon,
  ArrowUpIcon,
  BoltIcon,
  CheckCircleIcon,
  ChevronDownIcon,
  FileTextIcon,
  GlobeIcon,
  LayersIcon,
  PaperclipIcon,
  SparkleIcon,
} from './icons'

const MODES: {
  value: RunMode
  label: string
  description: string
  icon: typeof BoltIcon
}[] = [
  { value: 'FAST', label: 'Fast', description: 'Quick answers with trusted sources', icon: BoltIcon },
  {
    value: 'DEEP',
    label: 'Deep',
    description: 'In-depth, multi-agent research with detailed analysis',
    icon: SparkleIcon,
  },
]

const SCOPES: { value: SourceScope; label: string; menuLabel: string; icon: typeof GlobeIcon }[] = [
  { value: 'WEB', label: 'Web', menuLabel: 'Web Search', icon: GlobeIcon },
  { value: 'DOCUMENTS', label: 'Documents', menuLabel: 'Documents', icon: FileTextIcon },
  {
    value: 'WEB_AND_DOCUMENTS',
    label: 'Web + Documents',
    menuLabel: 'Web + Documents',
    icon: LayersIcon,
  },
]

export const CUSTOM_TEMPLATE_MAX_LENGTH = 2000

export function QueryForm({ projectId }: { projectId?: string }) {
  const navigate = useNavigate()
  const { documents } = useDocuments()
  const { templates } = useTemplates()
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<RunMode>('FAST')
  const [scope, setScope] = useState<SourceScope>('WEB')
  const [selectedDocs, setSelectedDocs] = useState<string[]>([])
  const [attachOpen, setAttachOpen] = useState(false)
  const [approvalRequired, setApprovalRequired] = useState(false)
  const [template, setTemplate] = useState('STANDARD')
  const [customTemplate, setCustomTemplate] = useState('')
  const [useMemory, setUseMemory] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const queryId = useId()
  const templateId = useId()
  const customId = useId()
  const scopeMenuId = useId()

  const readyDocuments = documents.filter((doc) => doc.status === 'READY')
  const scopeIncludesDocs = scope === 'DOCUMENTS' || scope === 'WEB_AND_DOCUMENTS'
  const docsRequired = scope === 'DOCUMENTS'
  const isCustomTemplate = template === 'CUSTOM'
  const customTemplateValid =
    !isCustomTemplate ||
    (customTemplate.trim().length > 0 && customTemplate.length <= CUSTOM_TEMPLATE_MAX_LENGTH)
  const canSubmit =
    query.trim().length > 0 &&
    !submitting &&
    !(docsRequired && selectedDocs.length === 0) &&
    customTemplateValid

  const selectedTemplate = templates.find((entry) => entry.id === template)
  const activeScope = SCOPES.find((entry) => entry.value === scope) ?? SCOPES[0]
  const ScopeIcon = activeScope.icon
  const showDocumentPicker = scopeIncludesDocs || attachOpen

  const toggleDocument = (id: string) => {
    setSelectedDocs((previous) => {
      const next = previous.includes(id)
        ? previous.filter((existing) => existing !== id)
        : [...previous, id]
      // Attaching a file while searching only the web widens the scope so the
      // attachment is actually used by the run.
      if (next.length > 0 && scope === 'WEB') setScope('WEB_AND_DOCUMENTS')
      return next
    })
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const run = await api.createRun({
        query: query.trim(),
        mode,
        source_scope: scope,
        document_ids: scopeIncludesDocs ? selectedDocs : [],
        approval_required: approvalRequired,
        template,
        use_memory: useMemory,
        ...(isCustomTemplate ? { custom_template: customTemplate.trim() } : {}),
        ...(projectId ? { project_id: projectId } : {}),
      })
      notifyRunsChanged()
      navigate(`/runs/${run.id}`)
    } catch (err) {
      setError(errorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <form className="query-form" onSubmit={handleSubmit} aria-label="Start research">
      <div className="query-panel">
        <label className="visually-hidden" htmlFor={queryId}>
          Research question
        </label>
        <textarea
          id={queryId}
          className="query-input"
          placeholder="What would you like to research?"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          rows={2}
          disabled={submitting}
        />
        <div className="query-panel-bar">
          <div className="query-panel-tools">
            <button
              type="button"
              className={`tool-pill${attachOpen ? ' active' : ''}`}
              onClick={() => setAttachOpen((value) => !value)}
              aria-pressed={attachOpen}
              aria-label="Attach files"
              disabled={submitting}
            >
              <PaperclipIcon size={15} />
              <span>Attach Files</span>
              {selectedDocs.length > 0 && (
                <span className="tool-pill-count">{selectedDocs.length}</span>
              )}
            </button>
            <span className="tool-pill select-pill">
              <ScopeIcon size={15} />
              <label className="visually-hidden" htmlFor={scopeMenuId}>
                Search scope
              </label>
              <select
                id={scopeMenuId}
                className="tool-select"
                value={scope}
                onChange={(event) => setScope(event.target.value as SourceScope)}
                disabled={submitting}
              >
                {SCOPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.menuLabel}
                  </option>
                ))}
              </select>
              <ChevronDownIcon size={14} className="tool-pill-chevron" />
            </span>
          </div>
          <button
            type="submit"
            className="query-submit"
            disabled={!canSubmit}
            aria-label="Submit research question"
          >
            <ArrowUpIcon size={22} />
          </button>
        </div>
      </div>

      <section className="form-section" aria-label="Research mode">
        <h2 className="form-section-title">Research Mode</h2>
        <div className="mode-cards" role="group">
          {MODES.map((option) => {
            const Icon = option.icon
            const selected = mode === option.value
            return (
              <button
                key={option.value}
                type="button"
                className={`mode-card${selected ? ' selected' : ''}`}
                aria-pressed={selected}
                onClick={() => setMode(option.value)}
                disabled={submitting}
              >
                <span className="mode-card-icon">
                  <Icon size={22} />
                </span>
                <span className="mode-card-body">
                  <span className="mode-card-label">{option.label}</span>
                  <span className="mode-card-desc">{option.description}</span>
                </span>
                <span className="mode-card-radio" aria-hidden="true">
                  {selected && <CheckCircleIcon size={22} />}
                </span>
              </button>
            )
          })}
        </div>
      </section>

      <div className="form-two-col">
        <section className="form-section" aria-label="Source scope">
          <h2 className="form-section-title">Sources</h2>
          <div className="source-buttons" role="group">
            {SCOPES.map((option) => {
              const Icon = option.icon
              const selected = scope === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  className={`source-btn${selected ? ' selected' : ''}`}
                  aria-pressed={selected}
                  onClick={() => setScope(option.value)}
                  disabled={submitting}
                >
                  <Icon size={16} />
                  <span>{option.label}</span>
                </button>
              )
            })}
          </div>
        </section>

        <section className="form-section template-section">
          <h2 className="form-section-title" id={`${templateId}-title`}>
            Report Template
          </h2>
          <div className="template-card">
            <FileTextIcon size={17} className="template-card-icon" />
            <select
              id={templateId}
              className="template-select"
              aria-label="Report template"
              value={template}
              onChange={(event) => setTemplate(event.target.value)}
              disabled={submitting}
            >
              {templates.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </select>
            <ChevronDownIcon size={18} className="template-card-chevron" />
          </div>
          {selectedTemplate && <p className="template-hint">{selectedTemplate.description}</p>}
        </section>
      </div>

      {isCustomTemplate && (
        <div className="control-group custom-template" aria-label="Custom template instructions">
          <label className="control-label" htmlFor={customId}>
            Custom template instructions (required)
          </label>
          <textarea
            id={customId}
            className="text-input"
            rows={4}
            required
            maxLength={CUSTOM_TEMPLATE_MAX_LENGTH}
            placeholder="Describe how the report should be structured and written…"
            value={customTemplate}
            onChange={(event) => setCustomTemplate(event.target.value)}
            disabled={submitting}
          />
          <p className="hint-text">
            {customTemplate.length}/{CUSTOM_TEMPLATE_MAX_LENGTH} characters
          </p>
        </div>
      )}

      {showDocumentPicker && (
        <div className="control-group document-picker" aria-label="Document picker">
          <span className="control-label">
            Documents{docsRequired ? ' (select at least one)' : ''}
          </span>
          {readyDocuments.length === 0 ? (
            <p className="hint-text">
              No ready documents. Upload some on the Documents page first.
            </p>
          ) : (
            <div className="doc-chips">
              {readyDocuments.map((doc) => {
                const selected = selectedDocs.includes(doc.id)
                return (
                  <button
                    key={doc.id}
                    type="button"
                    className={`chip${selected ? ' selected' : ''}`}
                    aria-pressed={selected}
                    onClick={() => toggleDocument(doc.id)}
                    disabled={submitting}
                  >
                    <FileTextIcon size={13} />
                    {doc.filename}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      <div className="submit-row">
        <div className="toggle-row">
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={approvalRequired}
              onChange={(event) => setApprovalRequired(event.target.checked)}
              disabled={submitting}
            />
            <span className="toggle-box" aria-hidden="true" />
            <span>Review plan before research</span>
          </label>
          <div className="toggle-stacked">
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={useMemory}
                onChange={(event) => setUseMemory(event.target.checked)}
                disabled={submitting}
              />
              <span className="toggle-box" aria-hidden="true" />
              <span>Use research memory</span>
            </label>
            <span className="toggle-hint">Get better results based on your past research</span>
          </div>
        </div>
        <button type="submit" className="btn primary glow large start-btn" disabled={!canSubmit}>
          <span>{submitting ? 'Starting…' : 'Start Research'}</span>
          <ArrowRightIcon size={16} />
        </button>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
