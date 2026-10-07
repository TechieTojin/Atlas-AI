import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import { api, errorMessage } from '../api/client'
import { useEventStream } from '../hooks/useEventStream'
import { useI18n } from '../i18n'
import type { GraphEdge, GraphNode, KnowledgeGraph } from '../types'
import { ExternalIcon, XIcon } from './icons'

export const MAX_RENDERED_NODES = 60

const WIDTH = 900
const HEIGHT = 540

const TYPE_COLORS = [
  'var(--accent)',
  'var(--violet)',
  'var(--blue)',
  'var(--success)',
  'var(--warning)',
  'var(--danger)',
]

interface SimNode extends SimulationNodeDatum {
  node: GraphNode
}

interface LaidOutNode {
  node: GraphNode
  x: number
  y: number
}

interface LaidOutEdge {
  edge: GraphEdge
  source: LaidOutNode
  target: LaidOutNode
}

function computeLayout(nodes: GraphNode[], edges: GraphEdge[]): {
  nodes: LaidOutNode[]
  edges: LaidOutEdge[]
} {
  const simNodes: SimNode[] = nodes.map((node) => ({ node }))
  const byId = new Map(simNodes.map((entry) => [entry.node.id, entry]))
  const links: SimulationLinkDatum<SimNode>[] = edges
    .filter((edge) => byId.has(edge.source_node_id) && byId.has(edge.target_node_id))
    .map((edge) => ({
      source: byId.get(edge.source_node_id) as SimNode,
      target: byId.get(edge.target_node_id) as SimNode,
    }))

  const simulation = forceSimulation(simNodes)
    .force('charge', forceManyBody().strength(-220))
    .force('link', forceLink(links).distance(90).strength(0.6))
    .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
    .force('collide', forceCollide(30))
    .stop()

  for (let i = 0; i < 300; i += 1) simulation.tick()

  const laidOut = simNodes.map((entry) => ({
    node: entry.node,
    x: entry.x ?? WIDTH / 2,
    y: entry.y ?? HEIGHT / 2,
  }))
  const positioned = new Map(laidOut.map((entry) => [entry.node.id, entry]))
  const laidOutEdges: LaidOutEdge[] = []
  for (const edge of edges) {
    const source = positioned.get(edge.source_node_id)
    const target = positioned.get(edge.target_node_id)
    if (source && target) laidOutEdges.push({ edge, source, target })
  }
  return { nodes: laidOut, edges: laidOutEdges }
}

type Selection = { kind: 'node'; id: string } | { kind: 'edge'; id: string } | null

export function GraphExplorer({ graph }: { graph: KnowledgeGraph }) {
  const { t } = useI18n()
  const totalNodes = graph.nodes.length
  const capped = totalNodes > MAX_RENDERED_NODES

  const { nodes, edges } = useMemo(() => {
    let kept = graph.nodes
    if (capped) {
      const degree = new Map<string, number>()
      for (const edge of graph.edges) {
        degree.set(edge.source_node_id, (degree.get(edge.source_node_id) ?? 0) + 1)
        degree.set(edge.target_node_id, (degree.get(edge.target_node_id) ?? 0) + 1)
      }
      kept = [...graph.nodes]
        .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))
        .slice(0, MAX_RENDERED_NODES)
    }
    const keptIds = new Set(kept.map((node) => node.id))
    const keptEdges = graph.edges.filter(
      (edge) => keptIds.has(edge.source_node_id) && keptIds.has(edge.target_node_id),
    )
    return computeLayout(kept, keptEdges)
  }, [graph, capped])

  const types = useMemo(() => {
    const seen: string[] = []
    for (const entry of nodes) {
      if (!seen.includes(entry.node.type)) seen.push(entry.node.type)
    }
    return seen
  }, [nodes])

  const colorFor = useCallback(
    (type: string) => TYPE_COLORS[Math.max(0, types.indexOf(type)) % TYPE_COLORS.length],
    [types],
  )

  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [selection, setSelection] = useState<Selection>(null)
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const dragState = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(
    null,
  )

  const visibleNodes = nodes.filter((entry) => !hiddenTypes.has(entry.node.type))
  const visibleIds = new Set(visibleNodes.map((entry) => entry.node.id))
  const visibleEdges = edges.filter(
    (entry) => visibleIds.has(entry.edge.source_node_id) && visibleIds.has(entry.edge.target_node_id),
  )

  const query = search.trim().toLowerCase()
  const matches = query
    ? visibleNodes.filter(
        (entry) =>
          entry.node.name.toLowerCase().includes(query) ||
          entry.node.norm_name.toLowerCase().includes(query),
      )
    : []

  // Center the first search match.
  useEffect(() => {
    if (!query) return
    const first = matches[0]
    if (!first) return
    setTransform((previous) => ({
      ...previous,
      x: WIDTH / 2 - first.x * previous.k,
      y: HEIGHT / 2 - first.y * previous.k,
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const matchIds = new Set(matches.map((entry) => entry.node.id))

  const toggleType = (type: string) => {
    setHiddenTypes((previous) => {
      const next = new Set(previous)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const onWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    const factor = event.deltaY < 0 ? 1.12 : 0.9
    setTransform((previous) => {
      const k = Math.min(3, Math.max(0.3, previous.k * factor))
      return { ...previous, k }
    })
  }

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.target !== event.currentTarget) return
    dragState.current = {
      startX: event.clientX,
      startY: event.clientY,
      originX: transform.x,
      originY: transform.y,
    }
  }

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragState.current
    if (!drag) return
    setTransform((previous) => ({
      ...previous,
      x: drag.originX + (event.clientX - drag.startX),
      y: drag.originY + (event.clientY - drag.startY),
    }))
  }

  const endDrag = () => {
    dragState.current = null
  }

  const selectedNode =
    selection?.kind === 'node' ? nodes.find((entry) => entry.node.id === selection.id) : undefined
  const selectedEdge =
    selection?.kind === 'edge' ? edges.find((entry) => entry.edge.id === selection.id) : undefined

  const relationshipsOf = (nodeId: string) =>
    edges.filter(
      (entry) => entry.edge.source_node_id === nodeId || entry.edge.target_node_id === nodeId,
    )

  return (
    <div className="graph-explorer">
      <div className="graph-toolbar">
        <input
          type="search"
          className="text-input graph-search"
          placeholder={t('graph.searchPlaceholder')}
          aria-label={t('graph.searchLabel')}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="tier-chips" role="group" aria-label={t('graph.typeFilterLabel')}>
          {types.map((type) => (
            <button
              key={type}
              type="button"
              className={`chip graph-type-chip${hiddenTypes.has(type) ? '' : ' selected'}`}
              aria-pressed={!hiddenTypes.has(type)}
              onClick={() => toggleType(type)}
            >
              <span className="quality-dot" style={{ background: colorFor(type) }} aria-hidden="true" />
              {type}
            </button>
          ))}
        </div>
      </div>

      {capped && (
        <p className="hint-text graph-cap-note">
          {t('graph.capped', { max: MAX_RENDERED_NODES, total: totalNodes })}
        </p>
      )}

      <div className="graph-canvas-row">
        <svg
          className="graph-svg"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="application"
          aria-label={t('graph.label')}
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerLeave={endDrag}
        >
          <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
            {visibleEdges.map((entry) => (
              <g key={entry.edge.id}>
                <line
                  className={`graph-edge${
                    selection?.kind === 'edge' && selection.id === entry.edge.id ? ' selected' : ''
                  }`}
                  x1={entry.source.x}
                  y1={entry.source.y}
                  x2={entry.target.x}
                  y2={entry.target.y}
                />
                <line
                  className="graph-edge-hit"
                  x1={entry.source.x}
                  y1={entry.source.y}
                  x2={entry.target.x}
                  y2={entry.target.y}
                  role="button"
                  tabIndex={0}
                  aria-label={t('graph.relationshipLabel', {
                    source: entry.source.node.name,
                    relation: entry.edge.relation,
                    target: entry.target.node.name,
                  })}
                  onClick={() => setSelection({ kind: 'edge', id: entry.edge.id })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setSelection({ kind: 'edge', id: entry.edge.id })
                    }
                  }}
                />
              </g>
            ))}
            {visibleNodes.map((entry) => {
              const highlighted = matchIds.has(entry.node.id)
              const selected = selection?.kind === 'node' && selection.id === entry.node.id
              return (
                <g
                  key={entry.node.id}
                  className={`graph-node${highlighted ? ' highlighted' : ''}${selected ? ' selected' : ''}`}
                  transform={`translate(${entry.x} ${entry.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={t('graph.entityLabel', { name: entry.node.name })}
                  onClick={() => setSelection({ kind: 'node', id: entry.node.id })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setSelection({ kind: 'node', id: entry.node.id })
                    }
                  }}
                >
                  <circle r={9} fill={colorFor(entry.node.type)} />
                  <text className="graph-node-label" x={12} y={4}>
                    {entry.node.name}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>

        {(selectedNode || selectedEdge) && (
          <aside className="graph-panel" aria-label={t('graph.selectionLabel')}>
            <header className="graph-panel-header">
              <h3 className="graph-panel-title">
                {selectedNode ? selectedNode.node.name : t('graph.relationship')}
              </h3>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setSelection(null)}
                aria-label={t('graph.closeDetails')}
              >
                <XIcon size={14} />
              </button>
            </header>
            {selectedNode && (
              <div className="graph-panel-body">
                <span className="badge" style={{ color: colorFor(selectedNode.node.type) }}>
                  {selectedNode.node.type}
                </span>
                {selectedNode.node.description && <p>{selectedNode.node.description}</p>}
                <h4 className="panel-heading">{t('graph.relationships')}</h4>
                {relationshipsOf(selectedNode.node.id).length === 0 ? (
                  <p className="hint-text">{t('graph.noRelationships')}</p>
                ) : (
                  <ul className="graph-relation-list">
                    {relationshipsOf(selectedNode.node.id).map((entry) => (
                      <li key={entry.edge.id}>
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => setSelection({ kind: 'edge', id: entry.edge.id })}
                        >
                          {entry.source.node.name} <em>{entry.edge.relation}</em>{' '}
                          {entry.target.node.name}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {selectedEdge && (
              <div className="graph-panel-body">
                <p className="graph-relation-summary">
                  {selectedEdge.source.node.name} <em>{selectedEdge.edge.relation}</em>{' '}
                  {selectedEdge.target.node.name}
                </p>
                <h4 className="panel-heading">{t('graph.supportingSources')}</h4>
                {selectedEdge.edge.support.length === 0 ? (
                  <p className="hint-text">{t('graph.noSupportingSources')}</p>
                ) : (
                  <ul className="graph-support-list">
                    {selectedEdge.edge.support.map((support, index) => (
                      <li key={index}>
                        {support.source_url && support.source_url.startsWith('http') ? (
                          <a href={support.source_url} target="_blank" rel="noreferrer" className="source-link">
                            <ExternalIcon size={12} />
                            <span>{support.source_title || support.source_url}</span>
                          </a>
                        ) : (
                          <span>{support.source_title || support.source_url}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  )
}

export interface KnowledgeGraphTabProps {
  fetchGraph: () => Promise<KnowledgeGraph>
  /** When set, the empty state offers generation and streams progress. */
  generate?: () => Promise<unknown>
  eventsUrl?: string
}

export function KnowledgeGraphTab({ fetchGraph, generate, eventsUrl }: KnowledgeGraphTabProps) {
  const { t } = useI18n()
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Keep the fetcher in a ref so inline arrow props cannot retrigger loads.
  const fetchRef = useRef(fetchGraph)
  fetchRef.current = fetchGraph

  const load = useCallback(async () => {
    try {
      setGraph(await fetchRef.current())
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const running = graph?.status === 'RUNNING'

  useEventStream(eventsUrl, {
    enabled: Boolean(eventsUrl) && running,
    onTerminal: () => void load(),
  })

  const handleGenerate = async () => {
    if (!generate) return
    setError(null)
    try {
      await generate()
      setGraph((previous) =>
        previous ? { ...previous, status: 'RUNNING' } : { nodes: [], edges: [], status: 'RUNNING', error: null },
      )
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (loading) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('graph.loading')}</p>
      </div>
    )
  }

  if (error && !graph) {
    return <p className="error-text">{error}</p>
  }

  if (!graph || graph.status === 'NONE') {
    return (
      <div className="page-state">
        <p>{t('graph.none')}</p>
        {generate && (
          <button type="button" className="btn primary" onClick={() => void handleGenerate()}>
            {t('graph.generate')}
          </button>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    )
  }

  if (graph.status === 'RUNNING') {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('graph.extracting')}</p>
      </div>
    )
  }

  if (graph.status === 'FAILED') {
    return (
      <div className="page-state">
        <p className="error-text">{graph.error || t('graph.failed')}</p>
        {generate && (
          <button type="button" className="btn" onClick={() => void handleGenerate()}>
            {t('common.tryAgain')}
          </button>
        )}
      </div>
    )
  }

  if (graph.nodes.length === 0) {
    return <p className="empty-note">{t('graph.noEntities')}</p>
  }

  return <GraphExplorer graph={graph} />
}

export function runKnowledgeGraphTabProps(runId: string): KnowledgeGraphTabProps {
  return {
    fetchGraph: () => api.getKnowledgeGraph(runId),
    generate: () => api.startKnowledgeGraph(runId),
    eventsUrl: `/api/runs/${runId}/knowledge-graph/events`,
  }
}
