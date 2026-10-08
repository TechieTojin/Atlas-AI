import { useId, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, errorMessage, notifyRunsChanged } from '../api/client'
import { useDocuments } from '../hooks/useDocuments'
import { useTemplates } from '../hooks/useTemplates'
import { languageName, templateDescription, templateEntryName, useI18n, useOutputLanguage } from '../i18n'
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

const MODES: { value: RunMode; icon: typeof BoltIcon }[] = [
  { value: 'FAST', icon: BoltIcon },
  { value: 'DEEP', icon: SparkleIcon },
]

const SCOPES: { value: SourceScope; icon: typeof GlobeIcon }[] = [
  { value: 'WEB', icon: GlobeIcon },
  { value: 'DOCUMENTS', icon: FileTextIcon },
  { value: 'WEB_AND_DOCUMENTS', icon: LayersIcon },
]

export const CUSTOM_TEMPLATE_MAX_LENGTH = 2000

export function QueryForm({ projectId }: { projectId?: string }) {
  const navigate = useNavigate()
  const { t, uiLanguage, language: ui } = useI18n()
  const output = useOutputLanguage()
  const nameOf = (code: string) => languageName(code, ui.locale)
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
  // Explicit, per-research consent to write in English when the preferred
  // language cannot be generated. Never stored; the preference is unchanged.
  const [englishChosenFor, setEnglishChosenFor] = useState<string | null>(null)
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
  const needsLanguageChoice = output.fellBack && !output.loading
  const englishChosen = englishChosenFor === output.preferred
  // English never waits for capabilities: every model writes it.
  const languageReady =
    output.preferred === 'en' || (!output.loading && (!needsLanguageChoice || englishChosen))
  const canSubmit =
    languageReady &&
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
        // The effective (supported) language, not the raw preference.
        output_language: output.effective,
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
    <form className="query-form" onSubmit={handleSubmit} aria-label={t('queryForm.label')}>
      <div className="query-panel">
        <label className="visually-hidden" htmlFor={queryId}>
          {t('queryForm.questionLabel')}
        </label>
        <textarea
          id={queryId}
          className="query-input"
          placeholder={t('queryForm.placeholder')}
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
              aria-label={t('queryForm.attachFilesLabel')}
              disabled={submitting}
            >
              <PaperclipIcon size={15} />
              <span>{t('queryForm.attachFiles')}</span>
              {selectedDocs.length > 0 && (
                <span className="tool-pill-count">{selectedDocs.length}</span>
              )}
            </button>
            <span className="tool-pill select-pill">
              <ScopeIcon size={15} />
              <label className="visually-hidden" htmlFor={scopeMenuId}>
                {t('queryForm.scopeLabel')}
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
                    {t(`scopes.${option.value}.menu`)}
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
            aria-label={t('queryForm.submitLabel')}
          >
            <ArrowUpIcon size={22} />
          </button>
        </div>
      </div>

      <section className="form-section" aria-label={t('queryForm.modeSection')}>
        <h2 className="form-section-title">{t('queryForm.modeTitle')}</h2>
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
                  <span className="mode-card-label">{t(`modes.${option.value}.label`)}</span>
                  <span className="mode-card-desc">{t(`modes.${option.value}.description`)}</span>
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
        <section className="form-section" aria-label={t('queryForm.sourcesSection')}>
          <h2 className="form-section-title">{t('queryForm.sourcesTitle')}</h2>
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
                  <span>{t(`scopes.${option.value}.label`)}</span>
                </button>
              )
            })}
          </div>
        </section>

        <section className="form-section template-section">
          <h2 className="form-section-title" id={`${templateId}-title`}>
            {t('queryForm.templateTitle')}
          </h2>
          <div className="template-card">
            <FileTextIcon size={17} className="template-card-icon" />
            <select
              id={templateId}
              className="template-select"
              aria-label={t('queryForm.templateLabel')}
              value={template}
              onChange={(event) => setTemplate(event.target.value)}
              disabled={submitting}
            >
              {templates.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {templateEntryName(t, uiLanguage, entry)}
                </option>
              ))}
            </select>
            <ChevronDownIcon size={18} className="template-card-chevron" />
          </div>
          {selectedTemplate && (
            <p className="template-hint">
              {templateDescription(t, uiLanguage, selectedTemplate, CUSTOM_TEMPLATE_MAX_LENGTH)}
            </p>
          )}
        </section>
      </div>

      {isCustomTemplate && (
        <div className="control-group custom-template" aria-label={t('queryForm.customSection')}>
          <label className="control-label" htmlFor={customId}>
            {t('queryForm.customLabel')}
          </label>
          <textarea
            id={customId}
            className="text-input"
            rows={4}
            required
            maxLength={CUSTOM_TEMPLATE_MAX_LENGTH}
            placeholder={t('queryForm.customPlaceholder')}
            value={customTemplate}
            onChange={(event) => setCustomTemplate(event.target.value)}
            disabled={submitting}
          />
          <p className="hint-text">
            {t('common.characterCount', {
              count: String(customTemplate.length),
              max: String(CUSTOM_TEMPLATE_MAX_LENGTH),
            })}
          </p>
        </div>
      )}

      {showDocumentPicker && (
        <div className="control-group document-picker" aria-label={t('queryForm.documentPicker')}>
          <span className="control-label">
            {docsRequired ? t('queryForm.documentsRequired') : t('queryForm.documents')}
          </span>
          {readyDocuments.length === 0 ? (
            <p className="hint-text">
              {t('queryForm.noReadyDocuments')}
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
            <span>{t('queryForm.reviewPlan')}</span>
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
              <span>{t('queryForm.useMemory')}</span>
            </label>
            <span className="toggle-hint">{t('queryForm.useMemoryHint')}</span>
          </div>
        </div>
        <div className="start-stack">
          <button type="submit" className="btn primary glow large start-btn" disabled={!canSubmit}>
            <span>{submitting ? t('queryForm.starting') : t('queryForm.start')}</span>
            <ArrowRightIcon size={16} />
          </button>
          <p className="output-language-note" aria-live="polite">
            <GlobeIcon size={13} className="output-language-icon" />
            <span>
              {t('outputLanguage.label', {
                language: nameOf(output.effective),
                model: output.model ?? t('outputLanguage.currentModel'),
              })}
            </span>
          </p>
          {output.limited && !output.fellBack && (
            <p className="output-language-hint" role="note">
              {t('outputLanguage.limited', { language: nameOf(output.effective) })}
            </p>
          )}
          {needsLanguageChoice && (
            <div className="output-language-fallback" role="note">
              <p>
                {output.unavailable
                  ? t('outputLanguage.unavailable')
                  : t('outputLanguage.unsupported', { preferred: nameOf(output.preferred) })}
              </p>
              {englishChosen ? (
                <p className="output-language-chosen">{t('outputLanguage.continuingInEnglish')}</p>
              ) : (
                <button
                  type="button"
                  className="btn light compact"
                  onClick={() => setEnglishChosenFor(output.preferred)}
                  disabled={submitting}
                >
                  {t('outputLanguage.continueInEnglish')}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
