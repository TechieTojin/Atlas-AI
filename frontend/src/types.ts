export type RunMode = 'FAST' | 'DEEP'

export type SourceScope = 'WEB' | 'DOCUMENTS' | 'WEB_AND_DOCUMENTS'

export type RunStatus =
  | 'PENDING'
  | 'PLANNING'
  | 'AWAITING_APPROVAL'
  | 'RESEARCHING'
  | 'CRITIQUING'
  | 'SYNTHESIZING'
  | 'CANCELLING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export const EVENT_TYPES = [
  'RUN_STARTED',
  'PLANNING_STARTED',
  'PLANNING_REPAIR_STARTED',
  'PLAN_CREATED',
  'WAITING_FOR_PLAN_APPROVAL',
  'PLAN_APPROVED',
  'PLAN_EDITED',
  'SEARCH_STARTED',
  'SEARCH_QUERY_STARTED',
  'SEARCH_QUERY_COMPLETED',
  'EVIDENCE_COLLECTED',
  'PAGE_FETCH_STARTED',
  'PAGE_FETCH_COMPLETED',
  'PAGE_FETCH_FAILED',
  'CRITIC_STARTED',
  'CRITIC_COMPLETED',
  'MORE_RESEARCH_REQUESTED',
  'SYNTHESIS_STARTED',
  'CITATION_REPAIR_STARTED',
  'CITATION_REPAIR_COMPLETED',
  'REPORT_REGENERATED',
  'RUN_COMPLETED',
  'RUN_FAILED',
  'RUN_CANCELLED',
  'CANCEL_REQUESTED',
  'FOLLOWUP_STARTED',
  'FOLLOWUP_COMPLETED',
  'FOLLOWUP_FAILED',
  'COMPARISON_STARTED',
  'COMPARISON_COMPLETED',
  'COMPARISON_FAILED',
  'KNOWLEDGE_GRAPH_STARTED',
  'KNOWLEDGE_GRAPH_COMPLETED',
  'KNOWLEDGE_GRAPH_FAILED',
] as const

export type EventType = (typeof EVENT_TYPES)[number]

export interface RunSummary {
  id: string
  query: string
  title: string
  mode: RunMode
  status: RunStatus
  source_scope: SourceScope
  created_at: string
  completed_at: string | null
  duration_ms: number
  project_id: string | null
  template: string
  /** Language the report is written in; absent from older payloads (English). */
  output_language?: string
}

export interface Plan {
  objective: string
  subquestions: string[]
  search_queries: string[]
}

export type QualityTier = 'high' | 'medium' | 'low' | 'unknown'

export interface SourceQuality {
  category: string
  tier: QualityTier
  score: number
  signals: string[]
  warnings: string[]
}

export interface Source {
  index: number
  title: string
  url: string
  domain: string
  kind: 'web' | 'document'
  filename: string | null
  page: number | null
  quality?: SourceQuality | null
}

export type ExtractionKind = 'snippet' | 'full_page' | 'fallback_snippet'

export interface Evidence {
  content: string
  query: string
  origin: 'web' | 'document' | 'memory'
  source_title: string
  source_url: string
  source_kind: string
  filename: string | null
  page: number | null
  relevance_score: number | null
  extraction?: ExtractionKind
  fetched_at?: string
  quality_tier?: string | null
}

export interface LlmStageStats {
  calls: number
  ms: number
  input_chars: number
  prompt_tokens: number
  output_tokens: number
  errors: number
  /** False when a call ended without Ollama's statistics (e.g. aborted). */
  tokens_available?: boolean
  outcomes?: string[]
  suspended_ms?: number
}

export interface MemoryItem {
  text: string
  question: string
  run_id: string
  score: number
  sources?: { url: string; title: string }[]
}

export interface NodeTiming {
  node: string
  ms: number
  iteration: number
}

export interface Metrics {
  planner_ms: number
  search_ms: number
  critic_ms: number
  synthesis_ms: number
  citation_repair_ms: number
  total_ms: number
  iterations: number
  search_queries_executed: number
  sources_collected: number
  sources_selected: number
  sources_cited: number
  citation_coverage: number
  memory_hits: number
  document_chunks_retrieved: number
  web_sources_reused: number
  critic_scores: number[]
  critic_decisions: string[]
  node_timings: NodeTiming[]
  errors: string[]
  planner_attempts?: number
  pages_attempted?: number
  pages_fetched?: number
  pages_failed?: number
  snippet_fallbacks?: number
  source_quality_tiers?: Record<string, number>
  llm_calls?: number
  llm_prompt_tokens?: number
  llm_output_tokens?: number
  llm_tokens_complete?: boolean
  memory_enabled?: boolean
  memory_scope?: 'PROJECT' | 'NONE'
  memory_candidates?: number
  project_memory_hits?: number
  memory_threshold?: number
  memory_error?: string
  memory_items?: MemoryItem[]
  suspended_ms?: number
  llm_stage_stats?: Record<string, LlmStageStats>
  budget_seconds?: number
  critic_fallback?: string
  synthesis_fallback?: boolean
  repair_skipped?: boolean
}

export interface Evaluation {
  has_citations: boolean
  citations_valid: boolean
  single_sources_section: boolean
  citation_coverage: number
  no_reasoning_markers: boolean
  provenance_valid: boolean
  passed: boolean
  notes: string[]
}

export interface RunDetail {
  id: string
  query: string
  title: string
  mode: RunMode
  status: RunStatus
  source_scope: SourceScope
  approval_required: boolean
  created_at: string
  started_at: string
  completed_at: string
  iterations: number
  executed_queries: string[]
  plan: Plan | null
  sources: Source[]
  evidence: Evidence[]
  final_report: string
  error: string
  document_ids: string[]
  metrics: Metrics
  evaluation: Evaluation | null
  project_id?: string | null
  template?: string
  custom_template?: string | null
  use_memory?: boolean
  regenerated_from?: string | null
  /** Language the report is written in; fixed at creation, never the UI language. */
  output_language?: string
}

export interface RunEvent {
  type: EventType
  run_id: string
  seq: number
  timestamp: string
  agent: string
  message: string
  iteration: number
  payload: Record<string, unknown>
}

export type DocumentStatus = 'PROCESSING' | 'READY' | 'FAILED'

export interface DocumentRecord {
  id: string
  filename: string
  content_type: string
  file_type: string
  size_bytes: number
  checksum: string
  status: DocumentStatus
  error: string
  chunk_count: number
  page_count: number
  uploaded_at: string
  project_id?: string | null
}

export interface HealthResponse {
  status: string
  version: string
  model: string
  database: string
}

export interface TemplateInfo {
  id: string
  name: string
  description: string
}

export interface Claim {
  text: string
  citations: number[]
  section: string
}

export interface Project {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
}

export interface ProjectCounts {
  runs: number
  documents: number
  comparisons: number
}

export interface ProjectFindingItem {
  id: string
  text: string
  section: string
  run_id: string
  question: string
  created_at: string
  /** How many distinct runs independently produced this finding. */
  support: number
  run_ids: string[]
  sources?: { url: string; title: string }[]
}

export interface KnowledgeGap {
  text: string
  reason: string
  run_id: string
  question: string
}

export interface OverviewRecentRun {
  id: string
  query: string
  title: string
  status: RunStatus
  mode: RunMode
  created_at: string
  findings_added: number
}

export interface ProjectOverview {
  project: Project
  stats: {
    runs: number
    completed_runs: number
    findings: number
    unique_sources: number
    documents: number
  }
  current_understanding: ProjectFindingItem[]
  key_findings: ProjectFindingItem[]
  knowledge_gaps: KnowledgeGap[]
  recent_runs: OverviewRecentRun[]
}

export interface ProjectWithCounts extends Project {
  counts: ProjectCounts
}

export type FollowUpStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export type FollowUpKind = 'ANALYTICAL' | 'RESEARCH'

export type FollowUpMode = 'auto' | 'analytical' | 'research'

export interface FollowUp {
  id: string
  run_id: string
  project_id: string | null
  question: string
  kind: FollowUpKind
  status: FollowUpStatus
  answer: string
  sources: Source[]
  parent_source_count: number
  new_source_count: number
  cited: number[]
  searched: boolean
  error: string
  duration_ms: number
  created_at: string
  completed_at: string | null
  /** The parent run's language; the answer is written in it. */
  output_language?: string
}

export type ComparisonStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'CANCELLING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'TIMED_OUT'

/** Execution metrics. Token counts are null when Ollama never reported them,
 *  which is what happens when a request is aborted; they are never shown as 0. */
export interface ComparisonMetrics {
  model?: string
  outcome?: string
  phase?: string
  llm_calls?: number
  repair_calls?: number
  elapsed_ms?: number
  prompt_tokens?: number | null
  output_tokens?: number | null
  /** Ollama's prompt_eval_duration: time spent reading the prompt. */
  prefill_ms?: number | null
  /** Ollama's eval_duration: time spent writing the answer. */
  generation_ms?: number | null
  time_to_first_token_ms?: number | null
  validation_ms?: number | null
  /** null when the model never reported why it stopped. */
  output_cap_reached?: boolean | null
  deadline_reached?: boolean | null
}

export interface ComparisonSource {
  source: Source
  run_ids: string[]
}

export interface OverlapStats {
  total_sources: number
  shared_sources: number
  unique_per_run: Record<string, number>
}

export interface Comparison {
  id: string
  project_id: string | null
  run_ids: string[]
  run_queries: string[]
  title: string
  status: ComparisonStatus
  report: string
  sources: ComparisonSource[]
  overlap_stats: OverlapStats
  error: string
  duration_ms: number
  created_at: string
  started_at: string | null
  completed_at: string | null
  metrics: ComparisonMetrics
  /** Language the comparison is written in; fixed at creation. */
  output_language?: string
}

/** A node in the project knowledge graph, derived from stored findings. */
export interface ProjectGraphNode {
  id: string
  label: string
  type: 'project' | 'concept' | 'finding'
  project_id: string
  /** Distinct completed runs that evidence this node. */
  support_count: number
  finding_count: number
  /** Finding nodes only: full provenance back to the research that produced them. */
  text?: string
  section?: string
  source_run_id?: string
  source_question?: string
  created_at?: string
  sources?: { url: string; title: string }[]
}

export type ProjectGraphRelation = 'HAS_TOPIC' | 'SUPPORTED_BY' | 'RELATED_TO'

export interface ProjectGraphEdge {
  id: string
  source: string
  target: string
  relation: ProjectGraphRelation
  weight: number
}

export interface ProjectGraph {
  project: { id: string; name: string }
  stats: { concepts: number; findings: number; runs: number }
  nodes: ProjectGraphNode[]
  edges: ProjectGraphEdge[]
}

export type KnowledgeGraphStatus = 'NONE' | 'RUNNING' | 'READY' | 'FAILED'

export interface GraphNode {
  id: string
  run_id: string
  name: string
  norm_name: string
  type: string
  description: string
}

export interface GraphEdgeSupport {
  source_url: string
  source_title: string
}

export interface GraphEdge {
  id: string
  run_id: string
  source_node_id: string
  target_node_id: string
  relation: string
  support: GraphEdgeSupport[]
}

export interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  status: KnowledgeGraphStatus
  error: string | null
}

export const ACTIVE_STATUSES: RunStatus[] = [
  'PENDING',
  'PLANNING',
  'AWAITING_APPROVAL',
  'RESEARCHING',
  'CRITIQUING',
  'SYNTHESIZING',
  // Still active: the worker is aborting; the stream ends with RUN_CANCELLED.
  'CANCELLING',
]

/** Event types that terminate a run's own SSE stream. */
export const RUN_TERMINAL_EVENT_TYPES: EventType[] = [
  'RUN_COMPLETED',
  'RUN_FAILED',
  'RUN_CANCELLED',
]

/** All terminal event types across run, follow-up, comparison, and graph streams. */
export const TERMINAL_EVENT_TYPES: EventType[] = [
  ...RUN_TERMINAL_EVENT_TYPES,
  'FOLLOWUP_COMPLETED',
  'FOLLOWUP_FAILED',
  'COMPARISON_COMPLETED',
  'COMPARISON_FAILED',
  'KNOWLEDGE_GRAPH_COMPLETED',
  'KNOWLEDGE_GRAPH_FAILED',
]

export function isActiveStatus(status: RunStatus): boolean {
  return ACTIVE_STATUSES.includes(status)
}

// --- Website Chat ------------------------------------------------------------

export type WebsiteStatus =
  | 'PENDING'
  | 'FETCHING'
  | 'EXTRACTING'
  | 'CHUNKING'
  | 'EMBEDDING'
  | 'READY'
  | 'FAILED'
  | 'CANCELLED'

/** One indexed webpage (never a crawl). */
export interface WebsiteSource {
  id: string
  submitted_url: string
  normalized_url: string
  final_url: string
  page_title: string
  domain: string
  status: WebsiteStatus
  content_hash: string
  /** Language the page declares (`<html lang>`), '' when absent. */
  content_language: string
  word_count: number
  chunk_count: number
  index_version: number
  is_indexed: boolean
  error: string
  /** Stable machine code for `error`; the UI translates it. */
  error_code: string
  fetched_at: string | null
  indexed_at: string | null
  created_at: string
  updated_at: string
  metrics: Record<string, unknown>
  /** Present on create: the URL was already indexed. */
  existing?: boolean
}

export interface WebsiteConversation {
  id: string
  website_id: string
  title: string
  /** Authoritative for every answer; the UI language never changes it. */
  output_language: string
  created_at: string
  updated_at: string
}

/** One [n] marker, frozen with the exact passage it was based on. */
export interface WebsiteCitation {
  index: number
  chunk_id: string
  index_version: number
  chunk_index: number
  section_title: string
  heading_path: string[]
  text: string
  score: number
  url: string
  page_title: string
}

export type WebsiteMessageStatus = 'PENDING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

/** The real backend step of a PENDING answer ('' = queued / not started). */
export type WebsiteAnswerStage = '' | 'RETRIEVING' | 'GENERATING' | 'VALIDATING'

export interface WebsiteMessage {
  id: string
  conversation_id: string
  seq: number
  role: 'user' | 'assistant'
  content: string
  status: WebsiteMessageStatus
  stage?: WebsiteAnswerStage
  error: string
  error_code: string
  insufficient_evidence: boolean
  citations: WebsiteCitation[]
  cited: number[]
  output_language: string
  metrics: Record<string, unknown>
  created_at: string
  completed_at: string | null
}

export interface WebsiteConversationDetail {
  conversation: WebsiteConversation
  messages: WebsiteMessage[]
}
