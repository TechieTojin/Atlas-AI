import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { CompareRunsList } from '../components/CompareRunsList'
import { ProjectKnowledgeGraph } from '../components/ProjectKnowledgeGraph'
import { ProjectOverview } from '../components/ProjectOverview'
import { QueryForm } from '../components/QueryForm'
import { TrashIcon } from '../components/icons'
import { useDocuments } from '../hooks/useDocuments'
import { useProject } from '../hooks/useProjects'
import { useRuns } from '../hooks/useRuns'
import type { Comparison, DocumentRecord, ProjectWithCounts } from '../types'
import { formatBytes, relativeTime } from '../utils/format'

type TabId = 'overview' | 'research' | 'documents' | 'comparisons' | 'graph'

const TABS: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'research', label: 'Research' },
  { id: 'documents', label: 'Documents' },
  { id: 'comparisons', label: 'Comparisons' },
  { id: 'graph', label: 'Knowledge Graph' },
]

function ProjectHeader({
  project,
  onUpdated,
  onContinueResearch,
}: {
  project: ProjectWithCounts
  onUpdated: (project: ProjectWithCounts) => void
  onContinueResearch: () => void
}) {
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!name.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const updated = await api.updateProject(project.id, {
        name: name.trim(),
        description: description.trim(),
      })
      onUpdated(updated)
      setEditing(false)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    const message =
      `Delete project “${project.name}”?\n\n` +
      'Runs, documents, and comparisons in this project are detached, not deleted — ' +
      'they remain available outside the project.'
    if (!window.confirm(message)) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteProject(project.id)
      navigate('/projects')
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <form className="card project-dialog" onSubmit={handleSave} aria-label="Edit project">
        <label className="field-label" htmlFor="edit-project-name">
          Name
        </label>
        <input
          id="edit-project-name"
          className="text-input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={busy}
          maxLength={200}
        />
        <label className="field-label" htmlFor="edit-project-description">
          Description
        </label>
        <textarea
          id="edit-project-description"
          className="text-input"
          rows={3}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          disabled={busy}
        />
        <div className="btn-row">
          <button type="submit" className="btn primary" disabled={busy || !name.trim()}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="btn" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
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

  return (
    <header className="run-header">
      <div className="run-header-main">
        <h1 className="run-query">{project.name}</h1>
        {project.description && <p className="page-subtitle">{project.description}</p>}
      </div>
      <div className="run-actions">
        <button type="button" className="btn primary" onClick={onContinueResearch}>
          Continue research
        </button>
        <button type="button" className="btn" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button
          type="button"
          className="btn danger-ghost"
          onClick={() => void handleDelete()}
          disabled={busy}
        >
          <TrashIcon size={14} />
          <span>Delete</span>
        </button>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </header>
  )
}

function ProjectDocuments({ projectId }: { projectId: string }) {
  const { documents, loading, error, upload, refresh, remove } = useDocuments(projectId)
  const [allDocuments, setAllDocuments] = useState<DocumentRecord[]>([])
  const [actionError, setActionError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  const refreshAll = useCallback(async () => {
    try {
      const response = await api.listDocuments()
      setAllDocuments(response.documents)
    } catch {
      // the assignable list is optional
    }
  }, [])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  const projectDocIds = new Set(documents.map((doc) => doc.id))
  const assignable = allDocuments.filter((doc) => !projectDocIds.has(doc.id))

  const act = async (action: () => Promise<unknown>) => {
    setActionError(null)
    try {
      await action()
      await Promise.all([refresh(), refreshAll()])
    } catch (err) {
      setActionError(errorMessage(err))
    }
  }

  const handleUpload = async (file: File) => {
    setUploading(true)
    setActionError(null)
    try {
      await upload(file)
      await refreshAll()
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="project-documents">
      <div className="project-upload-row">
        <label className="btn" htmlFor="project-doc-upload">
          {uploading ? 'Uploading…' : 'Upload to project'}
        </label>
        <input
          id="project-doc-upload"
          type="file"
          accept=".pdf,.txt,.md"
          className="visually-hidden"
          aria-label="Upload document to project"
          disabled={uploading}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void handleUpload(file)
            event.target.value = ''
          }}
        />
      </div>

      {actionError && (
        <p className="form-error" role="alert">
          {actionError}
        </p>
      )}
      {loading && <p className="hint-text">Loading documents…</p>}
      {error && !loading && <p className="error-text">{error}</p>}

      {!loading && documents.length === 0 && (
        <p className="empty-note">No documents in this project yet.</p>
      )}
      {documents.length > 0 && (
        <ul className="project-doc-list" aria-label="Project documents">
          {documents.map((doc) => (
            <li key={doc.id} className="project-doc-item">
              <span className="doc-name">{doc.filename}</span>
              <span className="hint-text">{formatBytes(doc.size_bytes)}</span>
              <span className="project-doc-actions">
                <button
                  type="button"
                  className="btn"
                  onClick={() => void act(() => api.unassignDocument(projectId, doc.id))}
                >
                  Remove from project
                </button>
                <button
                  type="button"
                  className="icon-btn danger"
                  aria-label={`Delete ${doc.filename}`}
                  onClick={() => {
                    if (window.confirm(`Delete “${doc.filename}”? This cannot be undone.`)) {
                      void act(() => remove(doc.id))
                    }
                  }}
                >
                  <TrashIcon size={14} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {assignable.length > 0 && (
        <section className="assignable-docs">
          <h3 className="panel-heading">Add existing documents</h3>
          <ul className="project-doc-list" aria-label="Assignable documents">
            {assignable.map((doc) => (
              <li key={doc.id} className="project-doc-item">
                <span className="doc-name">{doc.filename}</span>
                <span className="hint-text">{formatBytes(doc.size_bytes)}</span>
                <button
                  type="button"
                  className="btn"
                  onClick={() => void act(() => api.assignDocument(projectId, doc.id))}
                >
                  Add to project
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function ProjectComparisons({ projectId }: { projectId: string }) {
  const { runs } = useRuns(50, projectId)
  const [comparisons, setComparisons] = useState<Comparison[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .listComparisons(projectId)
      .then((response) => {
        if (!cancelled) setComparisons(response.comparisons)
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  return (
    <div className="project-comparisons">
      {loading && <p className="hint-text">Loading comparisons…</p>}
      {error && <p className="error-text">{error}</p>}
      {!loading && !error && comparisons.length === 0 && (
        <p className="hint-text">No comparisons in this project yet.</p>
      )}
      {comparisons.length > 0 && (
        <ul className="comparison-list" aria-label="Comparisons">
          {comparisons.map((comparison) => (
            <li key={comparison.id} className="comparison-item">
              <Link to={`/comparisons/${comparison.id}`} className="run-row-title">
                {comparison.title || comparison.run_queries.join(' vs ')}
              </Link>
              <span className="history-meta">
                <span>{comparison.status}</span>
                <span>{relativeTime(comparison.created_at)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="panel-heading">New comparison</h3>
      <CompareRunsList
        runs={runs}
        projectId={projectId}
        emptyNote="No completed runs in this project to compare yet."
      />
    </div>
  )
}

export function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const { project, loading, error, setProject } = useProject(id)
  const [active, setActive] = useState<TabId>('overview')
  const { runs } = useRuns(50, active === 'research' ? id : undefined)

  if (loading) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>Loading project…</p>
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="page-state">
        <h1>Project not found</h1>
        <p className="error-text">{error ?? 'This project does not exist.'}</p>
        <Link className="btn primary" to="/projects">
          Back to projects
        </Link>
      </div>
    )
  }

  return (
    <div className="project-page">
      <ProjectHeader
        project={project}
        onUpdated={setProject}
        onContinueResearch={() => setActive('research')}
      />

      <div className="tab-list" role="tablist" aria-label="Project workspace">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`project-tab-${tab.id}`}
            aria-selected={active === tab.id}
            aria-controls={`project-panel-${tab.id}`}
            className={`tab${active === tab.id ? ' active' : ''}`}
            onClick={() => setActive(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        id={`project-panel-${active}`}
        role="tabpanel"
        aria-labelledby={`project-tab-${active}`}
        className="tab-panel"
      >
        {active === 'overview' && (
          <ProjectOverview projectId={project.id} onStartResearch={() => setActive('research')} />
        )}
        {active === 'research' && (
          <div className="project-research">
            <QueryForm projectId={project.id} />
            <h3 className="panel-heading">Runs in this project</h3>
            <CompareRunsList
              runs={runs}
              projectId={project.id}
              emptyNote="No research in this project yet."
            />
          </div>
        )}
        {active === 'documents' && <ProjectDocuments projectId={project.id} />}
        {active === 'comparisons' && <ProjectComparisons projectId={project.id} />}
        {active === 'graph' && (
          <ProjectKnowledgeGraph
            projectId={project.id}
            onStartResearch={() => setActive('research')}
          />
        )}
      </div>
    </div>
  )
}
