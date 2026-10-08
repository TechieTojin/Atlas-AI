import type {
  Claim,
  Comparison,
  DocumentRecord,
  Evaluation,
  FollowUp,
  FollowUpMode,
  HealthResponse,
  KnowledgeGraph,
  ProjectGraph,
  Metrics,
  Project,
  ProjectOverview,
  ProjectWithCounts,
  RunDetail,
  RunMode,
  RunSummary,
  SourceScope,
  TemplateInfo,
} from '../types'
import { activeTranslator } from '../i18n/labels'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const t = () => activeTranslator()

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, init)
  } catch {
    throw new ApiError(t()('errors.network'), 0)
  }
  if (!res.ok) {
    // A backend `detail` is shown as sent: it is server prose, not a UI string.
    let message = t()('errors.requestFailed', { status: res.status })
    try {
      const body: unknown = await res.json()
      if (body && typeof body === 'object' && 'detail' in body) {
        const detail = (body as { detail: unknown }).detail
        message = typeof detail === 'string' ? detail : JSON.stringify(detail)
      }
    } catch {
      // keep the default message
    }
    throw new ApiError(message, res.status)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export interface CreateRunRequest {
  query: string
  mode: RunMode
  source_scope: SourceScope
  document_ids: string[]
  approval_required: boolean
  project_id?: string
  template?: string
  custom_template?: string
  use_memory?: boolean
  /** Resolved, supported output language. The UI language is never sent. */
  output_language?: string
}

export interface LanguageCapability {
  code: string
  english_name: string
  native_name: string
  model: string
  /** ``limited``: generated acceptably, with a stated limitation (slower runs). */
  status: 'supported' | 'limited' | 'unsupported' | 'unvalidated'
  supported: boolean
  reason: string
  /** Per-artifact verdicts; a language can pass for reports but not comparisons. */
  features?: Partial<Record<OutputFeature, { status?: string; supported: boolean; reason: string }>>
}

export type OutputFeature = 'report' | 'followup' | 'comparison'

export interface LanguageCapabilities {
  default_output_language: string
  model: string
  languages: LanguageCapability[]
}

export interface PlanEditRequest {
  objective?: string
  subquestions?: string[]
  search_queries?: string[]
}

export interface RunListResponse {
  runs: RunSummary[]
  total: number
  limit: number
  offset: number
}

export interface RunMetricsResponse {
  metrics: Metrics
  evaluation: Evaluation | null
}

export interface DocumentListResponse {
  documents: DocumentRecord[]
}

export interface RegenerateRequest {
  template: string
  custom_template?: string
}

export interface CreateProjectRequest {
  name: string
  description: string
}

export interface CreateFollowUpRequest {
  question: string
  mode: FollowUpMode
}

export interface CreateComparisonRequest {
  run_ids: string[]
  project_id?: string
  output_language?: string
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  createRun: (body: CreateRunRequest) => request<RunDetail>('/runs', jsonInit('POST', body)),

  listRuns: (
    params: { limit?: number; offset?: number; search?: string; project_id?: string } = {},
  ) => {
    const search = new URLSearchParams()
    if (params.limit !== undefined) search.set('limit', String(params.limit))
    if (params.offset !== undefined) search.set('offset', String(params.offset))
    if (params.search) search.set('search', params.search)
    if (params.project_id) search.set('project_id', params.project_id)
    const qs = search.toString()
    return request<RunListResponse>(`/runs${qs ? `?${qs}` : ''}`)
  },

  getRun: (id: string) => request<RunDetail>(`/runs/${id}`),

  deleteRun: (id: string) => request<void>(`/runs/${id}`, { method: 'DELETE' }),

  approvePlan: (id: string) => request<RunDetail>(`/runs/${id}/plan/approve`, { method: 'POST' }),

  editPlan: (id: string, body: PlanEditRequest) =>
    request<RunDetail>(`/runs/${id}/plan/edit`, jsonInit('POST', body)),

  cancelRun: (id: string) => request<RunDetail>(`/runs/${id}/cancel`, { method: 'POST' }),

  getRunMetrics: (id: string) => request<RunMetricsResponse>(`/runs/${id}/metrics`),

  regenerateRun: (id: string, body: RegenerateRequest) =>
    request<RunDetail>(`/runs/${id}/regenerate`, jsonInit('POST', body)),

  getRunClaims: (id: string) => request<{ claims: Claim[] }>(`/runs/${id}/claims`),

  listTemplates: () => request<{ templates: TemplateInfo[] }>('/templates'),

  getLanguageCapabilities: () => request<LanguageCapabilities>('/capabilities/languages'),

  uploadDocument: (file: File, projectId?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (projectId) form.append('project_id', projectId)
    return request<DocumentRecord>('/documents', { method: 'POST', body: form })
  },

  listDocuments: (projectId?: string) =>
    request<DocumentListResponse>(
      projectId ? `/documents?project_id=${encodeURIComponent(projectId)}` : '/documents',
    ),

  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),

  // Projects

  createProject: (body: CreateProjectRequest) =>
    request<Project>('/projects', jsonInit('POST', body)),

  listProjects: () => request<{ projects: ProjectWithCounts[] }>('/projects'),

  getProject: (id: string) => request<ProjectWithCounts>(`/projects/${id}`),

  updateProject: (id: string, body: Partial<CreateProjectRequest>) =>
    request<ProjectWithCounts>(`/projects/${id}`, jsonInit('PATCH', body)),

  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),

  assignDocument: (projectId: string, documentId: string) =>
    request<void>(`/projects/${projectId}/documents/${documentId}`, { method: 'PUT' }),

  unassignDocument: (projectId: string, documentId: string) =>
    request<void>(`/projects/${projectId}/documents/${documentId}`, { method: 'DELETE' }),

  getProjectOverview: (id: string) => request<ProjectOverview>(`/projects/${id}/overview`),

  getProjectKnowledgeGraph: (projectId: string) =>
    request<ProjectGraph>(`/projects/${projectId}/knowledge-graph`),

  // Follow-ups

  createFollowUp: (runId: string, body: CreateFollowUpRequest) =>
    request<FollowUp>(`/runs/${runId}/followups`, jsonInit('POST', body)),

  listFollowUps: (runId: string) =>
    request<{ followups: FollowUp[] }>(`/runs/${runId}/followups`),

  getFollowUp: (id: string) => request<FollowUp>(`/followups/${id}`),

  cancelFollowUp: (id: string) => request<FollowUp>(`/followups/${id}/cancel`, { method: 'POST' }),

  // Comparisons

  createComparison: (body: CreateComparisonRequest) =>
    request<Comparison>('/comparisons', jsonInit('POST', body)),

  listComparisons: (projectId?: string) =>
    request<{ comparisons: Comparison[] }>(
      projectId ? `/comparisons?project_id=${encodeURIComponent(projectId)}` : '/comparisons',
    ),

  cancelComparison: (id: string) =>
    request<Comparison>(`/comparisons/${id}/cancel`, { method: 'POST' }),

  getComparison: (id: string) => request<Comparison>(`/comparisons/${id}`),

  deleteComparison: (id: string) => request<void>(`/comparisons/${id}`, { method: 'DELETE' }),

  getComparisonClaims: (id: string) => request<{ claims: Claim[] }>(`/comparisons/${id}/claims`),

  // Knowledge graph

  startKnowledgeGraph: (runId: string) =>
    request<{ status: string }>(`/runs/${runId}/knowledge-graph`, { method: 'POST' }),

  getKnowledgeGraph: (runId: string) =>
    request<KnowledgeGraph>(`/runs/${runId}/knowledge-graph`),
}

export type ExportFormat = 'markdown' | 'pdf'

export function exportUrl(id: string, format: ExportFormat = 'markdown'): string {
  return `${BASE}/runs/${id}/export?format=${format}`
}

export function comparisonExportUrl(id: string): string {
  return `${BASE}/comparisons/${id}/export`
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

/** Notify interested components (e.g. the sidebar history) that the run list changed. */
export function notifyRunsChanged(): void {
  window.dispatchEvent(new Event('atlas:runs-changed'))
}
