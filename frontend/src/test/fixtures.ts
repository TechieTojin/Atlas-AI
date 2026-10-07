import type {
  Comparison,
  DocumentRecord,
  Evaluation,
  EventType,
  Evidence,
  FollowUp,
  GraphEdge,
  GraphNode,
  KnowledgeGraph,
  Metrics,
  ProjectOverview,
  ProjectWithCounts,
  RunDetail,
  RunEvent,
  RunSummary,
  Source,
  SourceQuality,
  TemplateInfo,
} from '../types'

export function makeMetrics(overrides: Partial<Metrics> = {}): Metrics {
  return {
    planner_ms: 1200,
    search_ms: 8400,
    critic_ms: 2100,
    synthesis_ms: 5100,
    citation_repair_ms: 600,
    total_ms: 17400,
    iterations: 2,
    search_queries_executed: 5,
    sources_collected: 18,
    sources_selected: 9,
    sources_cited: 7,
    citation_coverage: 0.85,
    memory_hits: 3,
    document_chunks_retrieved: 4,
    web_sources_reused: 1,
    critic_scores: [0.7, 0.85],
    critic_decisions: ['MORE_RESEARCH', 'SUFFICIENT'],
    node_timings: [{ node: 'planner', ms: 1200, iteration: 0 }],
    errors: [],
    planner_attempts: 1,
    pages_attempted: 10,
    pages_fetched: 8,
    pages_failed: 2,
    snippet_fallbacks: 1,
    source_quality_tiers: { high: 4, medium: 3, low: 1, unknown: 1 },
    ...overrides,
  }
}

export function makeEvaluation(overrides: Partial<Evaluation> = {}): Evaluation {
  return {
    has_citations: true,
    citations_valid: true,
    single_sources_section: true,
    citation_coverage: 0.85,
    no_reasoning_markers: true,
    provenance_valid: true,
    passed: true,
    notes: ['All checks passed'],
    ...overrides,
  }
}

let seqCounter = 0

export function makeEvent(type: EventType, overrides: Partial<RunEvent> = {}): RunEvent {
  seqCounter += 1
  return {
    type,
    run_id: 'run-1',
    seq: seqCounter,
    timestamp: '2026-10-02T10:00:00Z',
    agent: 'orchestrator',
    message: '',
    iteration: 0,
    payload: {},
    ...overrides,
  }
}

export function resetEventSeq(): void {
  seqCounter = 0
}

export function makeRun(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 'run-1',
    query: 'How fast is global solar capacity growing?',
    title: 'Global solar capacity growth',
    mode: 'DEEP',
    status: 'COMPLETED',
    source_scope: 'WEB',
    approval_required: false,
    created_at: '2026-10-02T10:00:00Z',
    started_at: '2026-10-02T10:00:01Z',
    completed_at: '2026-10-02T10:02:00Z',
    iterations: 2,
    executed_queries: ['solar capacity growth 2026'],
    plan: {
      objective: 'Assess the growth rate of global solar capacity',
      subquestions: ['How much capacity was added in 2025?', 'What are the forecasts for 2026?'],
      search_queries: ['solar capacity additions 2025', 'solar forecast 2026'],
    },
    sources: [],
    evidence: [],
    final_report: '# Findings\n\nSolar capacity **grew** rapidly. [1]',
    error: '',
    document_ids: [],
    metrics: makeMetrics(),
    evaluation: makeEvaluation(),
    project_id: null,
    template: 'STANDARD',
    custom_template: null,
    use_memory: true,
    regenerated_from: null,
    ...overrides,
  }
}

export function makeRunSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 'run-1',
    query: 'How fast is global solar capacity growing?',
    title: 'Global solar capacity growth',
    mode: 'DEEP',
    status: 'COMPLETED',
    source_scope: 'WEB',
    created_at: '2026-10-02T10:00:00Z',
    completed_at: '2026-10-02T10:02:00Z',
    duration_ms: 119000,
    project_id: null,
    template: 'STANDARD',
    ...overrides,
  }
}

export function makeQuality(overrides: Partial<SourceQuality> = {}): SourceQuality {
  return {
    category: 'Academic',
    tier: 'high',
    score: 0.92,
    signals: ['Peer-reviewed domain', 'Recent publication'],
    warnings: [],
    ...overrides,
  }
}

export function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    index: 1,
    title: 'IEA Renewables Report',
    url: 'https://iea.org/renewables-2026',
    domain: 'iea.org',
    kind: 'web',
    filename: null,
    page: null,
    quality: makeQuality(),
    ...overrides,
  }
}

export function makeEvidence(overrides: Partial<Evidence> = {}): Evidence {
  return {
    content: 'Solar capacity additions reached a record 600 GW in 2025.',
    query: 'solar capacity additions 2025',
    origin: 'web',
    source_title: 'IEA Renewables Report',
    source_url: 'https://iea.org/renewables-2026',
    source_kind: 'web',
    filename: null,
    page: null,
    relevance_score: 0.91,
    extraction: 'full_page',
    fetched_at: '2026-10-02T10:01:00Z',
    quality_tier: 'high',
    ...overrides,
  }
}

export function makeProject(overrides: Partial<ProjectWithCounts> = {}): ProjectWithCounts {
  return {
    id: 'proj-1',
    name: 'Energy transition',
    description: 'Research into renewables and grids',
    created_at: '2026-09-20T09:00:00Z',
    updated_at: '2026-10-01T09:00:00Z',
    counts: { runs: 3, documents: 2, comparisons: 1 },
    ...overrides,
  }
}

export function makeProjectOverview(overrides: Partial<ProjectOverview> = {}): ProjectOverview {
  const { counts: _counts, ...project } = makeProject()
  return {
    project,
    stats: { runs: 3, completed_runs: 2, findings: 9, unique_sources: 7, documents: 2 },
    current_understanding: [
      {
        id: 'f1',
        text: 'Grid storage is the binding constraint on renewable deployment.',
        section: 'Storage',
        run_id: 'r1',
        question: 'What limits renewable deployment?',
        created_at: '2026-10-01T09:00:00Z',
        support: 2,
        run_ids: ['r1', 'r2'],
        sources: [{ url: 'https://iea.org/x', title: 'IEA' }],
      },
    ],
    key_findings: [],
    knowledge_gaps: [],
    recent_runs: [
      {
        id: 'r1',
        query: 'Solar growth',
        title: 'Solar growth',
        status: 'COMPLETED',
        mode: 'FAST',
        created_at: '2026-10-01T09:00:00Z',
        findings_added: 5,
      },
    ],
    ...overrides,
  }
}

export function makeFollowUp(overrides: Partial<FollowUp> = {}): FollowUp {
  return {
    id: 'fu-1',
    run_id: 'run-1',
    project_id: null,
    question: 'What evidence is strongest?',
    kind: 'ANALYTICAL',
    status: 'COMPLETED',
    answer: 'The strongest evidence is the IEA dataset. [1]',
    sources: [makeSource()],
    parent_source_count: 1,
    new_source_count: 0,
    cited: [1],
    searched: false,
    error: '',
    duration_ms: 4200,
    created_at: '2026-10-02T11:00:00Z',
    completed_at: '2026-10-02T11:00:05Z',
    ...overrides,
  }
}

export function makeComparison(overrides: Partial<Comparison> = {}): Comparison {
  return {
    id: 'cmp-1',
    project_id: null,
    run_ids: ['run-1', 'run-2'],
    run_queries: ['Solar growth', 'Battery costs'],
    title: 'Solar growth vs Battery costs',
    status: 'COMPLETED',
    report: '# Comparison\n\nBoth topics share a grid focus. [1]',
    sources: [
      { source: makeSource(), run_ids: ['run-1', 'run-2'] },
      {
        source: makeSource({ index: 2, title: 'BNEF Battery Survey', url: 'https://bnef.com/battery', domain: 'bnef.com' }),
        run_ids: ['run-2'],
      },
    ],
    overlap_stats: {
      total_sources: 2,
      shared_sources: 1,
      unique_per_run: { 'run-1': 0, 'run-2': 1 },
    },
    error: '',
    duration_ms: 8000,
    created_at: '2026-10-02T12:00:00Z',
    started_at: '2026-10-02T12:00:00Z',
    completed_at: '2026-10-02T12:00:08Z',
    metrics: {
      model: 'qwen3:4b',
      outcome: 'completed',
      phase: 'done',
      llm_calls: 1,
      elapsed_ms: 8000,
      prompt_tokens: 2300,
      output_tokens: 640,
    },
    ...overrides,
  }
}

export function makeGraphNode(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: 'node-1',
    run_id: 'run-1',
    name: 'Solar PV',
    norm_name: 'solar pv',
    type: 'Technology',
    description: 'Photovoltaic solar generation',
    ...overrides,
  }
}

export function makeGraphEdge(overrides: Partial<GraphEdge> = {}): GraphEdge {
  return {
    id: 'edge-1',
    run_id: 'run-1',
    source_node_id: 'node-1',
    target_node_id: 'node-2',
    relation: 'drives growth of',
    support: [{ source_url: 'https://iea.org/renewables-2026', source_title: 'IEA Renewables Report' }],
    ...overrides,
  }
}

export function makeKnowledgeGraph(overrides: Partial<KnowledgeGraph> = {}): KnowledgeGraph {
  return {
    nodes: [
      makeGraphNode(),
      makeGraphNode({ id: 'node-2', name: 'Grid storage', norm_name: 'grid storage', type: 'Infrastructure' }),
      makeGraphNode({ id: 'node-3', name: 'IEA', norm_name: 'iea', type: 'Organization' }),
    ],
    edges: [
      makeGraphEdge(),
      makeGraphEdge({ id: 'edge-2', source_node_id: 'node-3', target_node_id: 'node-1', relation: 'tracks' }),
    ],
    status: 'READY',
    error: null,
    ...overrides,
  }
}

export const TEMPLATE_FIXTURES: TemplateInfo[] = [
  { id: 'STANDARD', name: 'Standard', description: 'Balanced research report' },
  { id: 'ACADEMIC', name: 'Academic', description: 'Formal style with methodology notes' },
  { id: 'TECHNICAL', name: 'Technical', description: 'Implementation-focused deep dive' },
  { id: 'EXECUTIVE', name: 'Executive', description: 'Short summary for decision makers' },
  { id: 'LITERATURE_REVIEW', name: 'Literature review', description: 'Survey of existing work' },
  { id: 'COMPARISON', name: 'Comparison', description: 'Side-by-side analysis' },
  { id: 'CUSTOM', name: 'Custom', description: 'Write your own synthesis instructions' },
]

export function makeDocument(overrides: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: 'doc-1',
    filename: 'energy-outlook.pdf',
    content_type: 'application/pdf',
    file_type: 'pdf',
    size_bytes: 2_400_000,
    checksum: 'abc123',
    status: 'READY',
    error: '',
    chunk_count: 42,
    page_count: 18,
    uploaded_at: '2026-10-01T09:00:00Z',
    ...overrides,
  }
}
