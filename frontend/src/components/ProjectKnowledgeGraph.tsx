import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { useI18n, type Translate } from '../i18n'
import type { ProjectGraph, ProjectGraphEdge, ProjectGraphNode } from '../types'

/**
 * The drawing area in graph units. The SVG scales to its container through the
 * viewBox, so these never change with screen size and the layout stays stable.
 */
const WIDTH = 1200
const HEIGHT = 700
const CX = WIDTH / 2
const CY = HEIGHT / 2
/** Concepts sit on an ellipse: wider than tall, because screens are. */
const RING_X = 395
const RING_Y = 240
const MIN_ZOOM = 0.3
const MAX_ZOOM = 3
/** Fit never shrinks past this, or labels stop being readable. */
const MIN_FIT_ZOOM = 0.72
const FIT_PADDING = 48
/** Share of the canvas left clear of the floating inspector. */
const PANEL_CLEARANCE = 0.62

const ROOT_WIDTH = 210
const ROOT_HEIGHT = 90
const CONCEPT_MIN_WIDTH = 152
const CONCEPT_MAX_WIDTH = 196
const LINE_HEIGHT = 15
const CARD_PADDING_Y = 13
const META_HEIGHT = 15
const FINDING_RADIUS = 7
/** How far a finding sits from the concept it supports. */
const FINDING_ORBIT = 92

type ViewMode = 'concepts' | 'all'

export interface Placed {
  node: ProjectGraphNode
  x: number
  y: number
  width: number
  height: number
  lines: string[]
}

interface PlacedEdge {
  edge: ProjectGraphEdge
  source: Placed
  target: Placed
}

export interface Layout {
  nodes: Placed[]
  edges: PlacedEdge[]
}

/**
 * Break a label into at most `maxLines` lines of roughly `maxChars`.
 *
 * Concept names like "manufacturing scalability challenges" are the whole point of
 * the node, so they wrap rather than getting cut to "manufacturing scalability c…".
 * Only a label too long even for three lines is ellipsised, and the untruncated text
 * always remains in the node's accessible name and its tooltip.
 */
export function wrapLabel(label: string, maxChars = 20, maxLines = 3): string[] {
  const words = label.split(/\s+/).filter(Boolean)
  if (words.length === 0) return ['']
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word
    if (candidate.length <= maxChars || current === '') {
      current = candidate
    } else {
      lines.push(current)
      current = word
    }
  }
  if (current) lines.push(current)
  if (lines.length <= maxLines) return lines
  const kept = lines.slice(0, maxLines)
  kept[maxLines - 1] = `${kept[maxLines - 1].slice(0, maxChars - 1).trimEnd()}…`
  return kept
}

/** Card width grows a little with evidence, but never enough to shout. */
function conceptWidth(node: ProjectGraphNode): number {
  return Math.min(CONCEPT_MAX_WIDTH, CONCEPT_MIN_WIDTH + node.finding_count * 3)
}

function cardHeight(lines: number, withMeta: boolean): number {
  return CARD_PADDING_Y * 2 + lines * LINE_HEIGHT + (withMeta ? META_HEIGHT : 0)
}

/**
 * Place the graph radially: project at the centre, concepts spread evenly around it,
 * each concept's findings in a small arc just outside it.
 *
 * This replaces a force simulation deliberately. A simulation left most of the canvas
 * empty, piled labels on top of one another, and settled slightly differently as the
 * node set changed. A radial layout is exact, uses the full canvas, keeps label room
 * by construction, and puts a concept in the same place every time it is opened.
 */
export function layoutGraph(nodes: ProjectGraphNode[], edges: ProjectGraphEdge[]): Layout {
  const placed = new Map<string, Placed>()

  const root = nodes.find((node) => node.type === 'project')
  if (root) {
    placed.set(root.id, {
      node: root,
      x: CX,
      y: CY,
      width: ROOT_WIDTH,
      height: ROOT_HEIGHT,
      lines: wrapLabel(root.label, 22, 2),
    })
  }

  const concepts = nodes.filter((node) => node.type === 'concept')
  concepts.forEach((node, index) => {
    // Start at the top and go clockwise, so the ordering the backend ranked by
    // support is also the order the eye follows.
    const angle = (index / Math.max(1, concepts.length)) * Math.PI * 2 - Math.PI / 2
    const width = conceptWidth(node)
    const lines = wrapLabel(node.label, Math.floor(width / 7.4))
    placed.set(node.id, {
      node,
      x: CX + Math.cos(angle) * RING_X,
      y: CY + Math.sin(angle) * RING_Y,
      width,
      height: cardHeight(lines.length, true),
      lines,
    })
  })

  // Findings orbit the concept that supports them, on the side facing away from
  // the centre so they never land on top of the hierarchy edges.
  const byConcept = new Map<string, string[]>()
  for (const edge of edges) {
    if (edge.relation !== 'SUPPORTED_BY') continue
    if (!placed.has(edge.source)) continue
    const bucket = byConcept.get(edge.source) ?? []
    bucket.push(edge.target)
    byConcept.set(edge.source, bucket)
  }

  const findings = new Map(
    nodes.filter((node) => node.type === 'finding').map((node) => [node.id, node]),
  )

  for (const [conceptId, ids] of byConcept) {
    const anchor = placed.get(conceptId)
    if (!anchor) continue
    const visible = ids.filter((id) => findings.has(id))
    if (visible.length === 0) continue
    const outward = Math.atan2(anchor.y - CY, anchor.x - CX)
    const spread = Math.min(Math.PI * 0.9, 0.3 * visible.length)
    visible.forEach((id, index) => {
      const offset =
        visible.length === 1 ? 0 : -spread / 2 + (spread * index) / (visible.length - 1)
      const angle = outward + offset
      // Stagger alternate findings outward so dense fans do not overlap.
      const distance = FINDING_ORBIT + (index % 2) * 26
      placed.set(id, {
        node: findings.get(id) as ProjectGraphNode,
        x: anchor.x + Math.cos(angle) * distance,
        y: anchor.y + Math.sin(angle) * distance * 0.78,
        width: FINDING_RADIUS * 2,
        height: FINDING_RADIUS * 2,
        lines: [],
      })
    })
  }

  const placedEdges: PlacedEdge[] = []
  for (const edge of edges) {
    const source = placed.get(edge.source)
    const target = placed.get(edge.target)
    if (source && target) placedEdges.push({ edge, source, target })
  }

  return { nodes: [...placed.values()], edges: placedEdges }
}

/**
 * The transform that frames `placed` with comfortable padding.
 *
 * `widthFraction` restricts the framing to the left part of the canvas. The inspector
 * floats over the right-hand side, so framing a selection into the clear area keeps
 * the graph at full scale instead of squeezing it into a half-width canvas, where the
 * labels would render at roughly half their intended size.
 */
export function fitTransform(
  placed: Placed[],
  widthFraction = 1,
): { x: number; y: number; k: number } {
  if (placed.length === 0) return { x: 0, y: 0, k: 1 }
  const available = WIDTH * widthFraction
  const minX = Math.min(...placed.map((entry) => entry.x - entry.width / 2)) - FIT_PADDING
  const maxX = Math.max(...placed.map((entry) => entry.x + entry.width / 2)) + FIT_PADDING
  // Labels under finding dots and the meta line need a little extra vertical room.
  const minY = Math.min(...placed.map((entry) => entry.y - entry.height / 2)) - FIT_PADDING
  const maxY = Math.max(...placed.map((entry) => entry.y + entry.height / 2)) + FIT_PADDING
  const k = Math.min(
    MAX_ZOOM,
    Math.max(MIN_FIT_ZOOM, Math.min(available / (maxX - minX), HEIGHT / (maxY - minY))),
  )
  return {
    k,
    x: available / 2 - ((minX + maxX) / 2) * k,
    y: CY - ((minY + maxY) / 2) * k,
  }
}

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1).trimEnd()}…`
}

function countsLabel(t: Translate, node: ProjectGraphNode): string {
  const findings = t('projectGraph.findings', { count: node.finding_count })
  const runs = t('projectGraph.runs', { count: node.support_count })
  return `${findings} · ${runs}`
}

/** The detail panel. Provenance lives here rather than as nodes on the canvas. */
function Inspector({
  node,
  graph,
  onSelect,
  onClose,
}: {
  node: ProjectGraphNode
  graph: ProjectGraph
  onSelect: (id: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const byId = useMemo(() => new Map(graph.nodes.map((entry) => [entry.id, entry])), [graph.nodes])

  if (node.type === 'finding') {
    return (
      <aside className="graph-panel" aria-label={t('projectGraph.findingDetails')}>
        <div className="graph-panel-head">
          <span className="graph-kind">{t('projectGraph.finding')}</span>
          <button type="button" className="btn ghost" onClick={onClose}>
            {t('common.close')}
          </button>
        </div>
        <p className="finding-text">{node.text}</p>
        {node.section && (
          <p className="graph-panel-meta">{t('projectGraph.section', { section: node.section })}</p>
        )}
        <p className="graph-panel-meta">
          {t('projectGraph.fromResearch')}{' '}
          <Link to={`/runs/${node.source_run_id}`} className="finding-source-link">
            {node.source_question || t('common.viewRun')}
          </Link>
        </p>
        {node.sources && node.sources.length > 0 && (
          <>
            <h4 className="graph-panel-subhead">{t('projectGraph.sources')}</h4>
            <ul className="graph-source-list">
              {node.sources.map((source) => (
                <li key={source.url}>
                  <a href={source.url} target="_blank" rel="noreferrer noopener">
                    {source.title || source.url}
                  </a>
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>
    )
  }

  const supporting = graph.edges
    .filter((edge) => edge.relation === 'SUPPORTED_BY' && edge.source === node.id)
    .map((edge) => byId.get(edge.target))
    .filter((entry): entry is ProjectGraphNode => Boolean(entry))

  const related = graph.edges
    .filter(
      (edge) =>
        edge.relation === 'RELATED_TO' && (edge.source === node.id || edge.target === node.id),
    )
    .map((edge) => ({
      node: byId.get(edge.source === node.id ? edge.target : edge.source),
      weight: edge.weight,
    }))
    .filter((entry): entry is { node: ProjectGraphNode; weight: number } => Boolean(entry.node))
    .sort((a, b) => b.weight - a.weight)

  return (
    <aside className="graph-panel" aria-label={t('projectGraph.conceptDetails')}>
      <div className="graph-panel-head">
        <span className="graph-kind">
          {node.type === 'project' ? t('projectGraph.project') : t('projectGraph.concept')}
        </span>
        <button type="button" className="btn ghost" onClick={onClose}>
          {t('common.close')}
        </button>
      </div>
      <h3 className="graph-panel-title">{node.label}</h3>
      {node.type === 'concept' && (
        <p className="graph-panel-meta">
          {t('projectGraph.supportedBy', {
            findings: t('projectGraph.findings', { count: node.finding_count }),
            count: node.support_count,
          })}
        </p>
      )}

      {related.length > 0 && (
        <>
          <h4 className="graph-panel-subhead">{t('projectGraph.relatedConcepts')}</h4>
          <ul className="graph-related">
            {related.map((entry) => (
              <li key={entry.node.id}>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => onSelect(entry.node.id)}
                >
                  {entry.node.label}
                </button>
                <span className="history-meta">
                  {t('projectGraph.sharedFindings', { count: entry.weight })}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {supporting.length > 0 && (
        <>
          <h4 className="graph-panel-subhead">{t('projectGraph.supportingFindings')}</h4>
          <ul className="graph-finding-list">
            {supporting.map((finding) => (
              <li key={finding.id}>
                <p className="finding-text">{truncate(finding.text ?? finding.label, 200)}</p>
                <p className="graph-panel-meta">
                  <Link to={`/runs/${finding.source_run_id}`} className="finding-source-link">
                    {finding.source_question || t('common.viewRun')}
                  </Link>
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </aside>
  )
}

export function ProjectGraphExplorer({ graph }: { graph: ProjectGraph }) {
  const { t } = useI18n()
  const [view, setView] = useState<ViewMode>('concepts')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const drag = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(
    null,
  )

  // In the concepts view a selected concept reveals its own findings, so one idea
  // can be opened up without flooding the canvas with every other concept's evidence.
  const visible = useMemo(() => {
    if (view === 'all') return graph.nodes
    const expanded = new Set(
      graph.edges
        .filter((edge) => edge.relation === 'SUPPORTED_BY' && edge.source === selectedId)
        .map((edge) => edge.target),
    )
    return graph.nodes.filter((node) => node.type !== 'finding' || expanded.has(node.id))
  }, [graph, view, selectedId])

  const visibleIds = useMemo(() => new Set(visible.map((node) => node.id)), [visible])
  const shownEdges = useMemo(
    () => graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)),
    [graph.edges, visibleIds],
  )

  const layout = useMemo(() => layoutGraph(visible, shownEdges), [visible, shownEdges])

  /** Everything one hop from the selection, used to dim the rest of the graph. */
  const neighbourhood = useMemo(() => {
    if (!selectedId) return null
    const ids = new Set<string>([selectedId])
    const edgeIds = new Set<string>()
    for (const edge of shownEdges) {
      if (edge.source === selectedId || edge.target === selectedId) {
        ids.add(edge.source)
        ids.add(edge.target)
        edgeIds.add(edge.id)
      }
    }
    return { ids, edgeIds }
  }, [selectedId, shownEdges])

  const layoutRef = useRef(layout)
  layoutRef.current = layout

  const fit = useCallback(
    () => setTransform(fitTransform(layoutRef.current.nodes, selectedId ? PANEL_CLEARANCE : 1)),
    [selectedId],
  )

  // Frame the whole graph when the drawn set changes for a reason other than
  // selection: a new project, or switching between the concept and finding views.
  useEffect(() => {
    setTransform(fitTransform(layoutRef.current.nodes))
  }, [view, graph])

  // Selecting only pans. Re-fitting here would shrink the graph twice over -- once
  // for the inspector's clearance and again for the findings a concept reveals --
  // and the labels are the thing most worth protecting.
  useEffect(() => {
    if (!selectedId) return
    const target = layoutRef.current.nodes.find((entry) => entry.node.id === selectedId)
    if (!target) return
    setTransform((previous) => ({
      ...previous,
      x: (WIDTH * PANEL_CLEARANCE) / 2 - target.x * previous.k,
      y: CY - target.y * previous.k,
    }))
  }, [selectedId])

  const reset = () => {
    setView('concepts')
    setSelectedId(null)
    setQuery('')
  }

  const normalized = query.trim().toLowerCase()
  const matches = useMemo(
    () =>
      normalized.length === 0
        ? []
        : layout.nodes.filter(
            (entry) =>
              entry.node.type !== 'finding' &&
              entry.node.label.toLowerCase().includes(normalized),
          ),
    [layout.nodes, normalized],
  )
  const matchIds = useMemo(() => new Set(matches.map((entry) => entry.node.id)), [matches])

  // Centre the first match. Search is local to the loaded graph; it never calls out.
  useEffect(() => {
    const first = matches[0]
    if (!first) return
    setTransform((previous) => ({
      ...previous,
      x: CX - first.x * previous.k,
      y: CY - first.y * previous.k,
    }))
  }, [matches])

  const onWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    const factor = event.deltaY < 0 ? 1.12 : 0.9
    setTransform((previous) => ({
      ...previous,
      k: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, previous.k * factor)),
    }))
  }

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.target !== event.currentTarget) return
    drag.current = {
      startX: event.clientX,
      startY: event.clientY,
      originX: transform.x,
      originY: transform.y,
    }
  }

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const state = drag.current
    if (!state) return
    setTransform((previous) => ({
      ...previous,
      x: state.originX + (event.clientX - state.startX),
      y: state.originY + (event.clientY - state.startY),
    }))
  }

  const selected = selectedId ? graph.nodes.find((node) => node.id === selectedId) ?? null : null
  const hovered = hoveredId ? layout.nodes.find((entry) => entry.node.id === hoveredId) ?? null : null

  const dimmedNode = (id: string): boolean => {
    if (normalized.length > 0) return !matchIds.has(id)
    if (neighbourhood) return !neighbourhood.ids.has(id)
    return false
  }

  return (
    <div className={`project-graph${selected ? ' with-panel' : ''}`}>
      <div className="graph-toolbar">
        <p className="graph-stats">
          {[
            t('projectGraph.statsConcepts', { count: graph.stats.concepts }),
            t('projectGraph.findings', { count: graph.stats.findings }),
            t('projectGraph.statsRuns', { count: graph.stats.runs }),
          ].join(' · ')}
        </p>
        <div className="graph-controls">
          <label className="graph-search">
            <span className="visually-hidden">{t('projectGraph.searchLabel')}</span>
            <input
              type="search"
              placeholder={t('projectGraph.searchPlaceholder')}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label={t('projectGraph.searchLabel')}
            />
          </label>
          <div className="segmented" role="group" aria-label={t('projectGraph.detailLabel')}>
            <button
              type="button"
              className={view === 'concepts' ? 'active' : ''}
              aria-pressed={view === 'concepts'}
              onClick={() => setView('concepts')}
            >
              {t('projectGraph.viewConcepts')}
            </button>
            <button
              type="button"
              className={view === 'all' ? 'active' : ''}
              aria-pressed={view === 'all'}
              onClick={() => setView('all')}
            >
              {t('projectGraph.viewAll')}
            </button>
          </div>
          <button type="button" className="btn" onClick={fit}>
            {t('projectGraph.fit')}
          </button>
          <button type="button" className="btn" onClick={reset}>
            {t('projectGraph.reset')}
          </button>
        </div>
      </div>

      <div className="graph-subbar">
        <ul className="graph-legend" aria-label={t('projectGraph.legend')}>
          <li>
            <span className="legend-swatch kind-project" aria-hidden="true" />
            {t('projectGraph.project')}
          </li>
          <li>
            <span className="legend-swatch kind-concept" aria-hidden="true" />
            {t('projectGraph.concept')}
          </li>
          <li>
            <span className="legend-swatch kind-finding" aria-hidden="true" />
            {t('projectGraph.finding')}
          </li>
          <li className="legend-note">{t('projectGraph.legendNote')}</li>
        </ul>
        {normalized.length > 0 && (
          <p className="graph-search-result" role="status">
            {matches.length === 0
              ? t('projectGraph.noMatches', { query: query.trim() })
              : t('projectGraph.matches', { count: matches.length, query: query.trim() })}
          </p>
        )}
      </div>

      <div className="graph-body">
        <div className="graph-canvas-wrap">
          <svg
            className="graph-canvas"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label={t('projectGraph.canvasLabel', { name: graph.project.name })}
            onWheel={onWheel}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={() => {
              drag.current = null
            }}
            onPointerLeave={() => {
              drag.current = null
            }}
          >
            <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
              {layout.edges.map(({ edge, source, target }) => {
                const emphasised = neighbourhood?.edgeIds.has(edge.id) ?? false
                const faded = Boolean(neighbourhood) && !emphasised
                const className = [
                  'graph-edge',
                  `relation-${edge.relation.toLowerCase()}`,
                  emphasised ? 'emphasised' : '',
                  faded ? 'faded' : '',
                ]
                  .filter(Boolean)
                  .join(' ')

                if (edge.relation === 'RELATED_TO') {
                  // Secondary links bow perpendicular to their own chord, always away
                  // from the centre. Bowing radially left links between opposite
                  // concepts running straight through the middle of the hierarchy,
                  // which is exactly where the graph was hardest to read.
                  const midX = (source.x + target.x) / 2
                  const midY = (source.y + target.y) / 2
                  const dx = target.x - source.x
                  const dy = target.y - source.y
                  const length = Math.hypot(dx, dy) || 1
                  let normalX = -dy / length
                  let normalY = dx / length
                  if (normalX * (midX - CX) + normalY * (midY - CY) < 0) {
                    normalX = -normalX
                    normalY = -normalY
                  }
                  const bow = length * 0.26
                  const controlX = midX + normalX * bow
                  const controlY = midY + normalY * bow
                  return (
                    <path
                      key={edge.id}
                      className={className}
                      d={`M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`}
                      fill="none"
                      strokeWidth={Math.min(3, 1 + edge.weight / 4)}
                    />
                  )
                }
                return (
                  <line
                    key={edge.id}
                    className={className}
                    x1={source.x}
                    y1={source.y}
                    x2={target.x}
                    y2={target.y}
                  />
                )
              })}

              {layout.nodes.map((entry) => {
                const { node, x, y, width, height, lines } = entry
                const isSelected = node.id === selectedId
                const dimmed = dimmedNode(node.id)
                const className = [
                  'graph-node',
                  `kind-${node.type}`,
                  isSelected ? 'selected' : '',
                  dimmed ? 'dimmed' : '',
                  matchIds.has(node.id) ? 'match' : '',
                ]
                  .filter(Boolean)
                  .join(' ')

                const accessibleName =
                  node.type === 'finding'
                    ? t('projectGraph.findingLabel', { text: truncate(node.text ?? node.label, 80) })
                    : node.type === 'project'
                      ? t('projectGraph.projectLabel', { name: node.label })
                      : `${node.label}, ${countsLabel(t, node)}`

                const common = {
                  className,
                  transform: `translate(${x} ${y})`,
                  role: 'button' as const,
                  tabIndex: 0,
                  'aria-label': accessibleName,
                  'aria-pressed': isSelected,
                  onClick: () => setSelectedId(isSelected ? null : node.id),
                  onMouseEnter: () => setHoveredId(node.id),
                  onMouseLeave: () => setHoveredId((current) => (current === node.id ? null : current)),
                  onFocus: () => setHoveredId(node.id),
                  onBlur: () => setHoveredId((current) => (current === node.id ? null : current)),
                  onKeyDown: (event: React.KeyboardEvent<SVGGElement>) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setSelectedId(isSelected ? null : node.id)
                    }
                  },
                }

                if (node.type === 'finding') {
                  return (
                    <g key={node.id} {...common}>
                      <circle r={FINDING_RADIUS} />
                    </g>
                  )
                }

                const isRoot = node.type === 'project'
                // The root reserves a line above its title for the PROJECT eyebrow.
                const textTop = -height / 2 + (isRoot ? 40 : CARD_PADDING_Y + 11)
                return (
                  <g key={node.id} {...common}>
                    <rect
                      x={-width / 2}
                      y={-height / 2}
                      width={width}
                      height={height}
                      rx={isRoot ? 12 : 9}
                    />
                    {isRoot && (
                      <text className="graph-eyebrow" y={-height / 2 + 19} textAnchor="middle">
                        {t('projectGraph.projectEyebrow')}
                      </text>
                    )}
                    {lines.map((line, index) => (
                      <text
                        key={line + index}
                        className="graph-label"
                        y={textTop + index * LINE_HEIGHT}
                        textAnchor="middle"
                      >
                        {line}
                      </text>
                    ))}
                    {!isRoot && (
                      <text
                        className="graph-meta"
                        y={textTop + lines.length * LINE_HEIGHT + 2}
                        textAnchor="middle"
                      >
                        {countsLabel(t, node)}
                      </text>
                    )}
                  </g>
                )
              })}
            </g>
          </svg>

          {hovered && hovered.node.type !== 'finding' && (
            <div
              className="graph-tooltip"
              role="tooltip"
              style={{
                left: `${((hovered.x * transform.k + transform.x) / WIDTH) * 100}%`,
                top: `${((hovered.y * transform.k + transform.y - hovered.height / 2) / HEIGHT) * 100}%`,
              }}
            >
              <strong>{hovered.node.label}</strong>
              {hovered.node.type === 'concept' && (
                <>
                  <span>{t('projectGraph.tooltipFindings', { count: hovered.node.finding_count })}</span>
                  <span>{t('projectGraph.tooltipRuns', { count: hovered.node.support_count })}</span>
                  <span className="graph-tooltip-hint">{t('projectGraph.clickToInspect')}</span>
                </>
              )}
            </div>
          )}
        </div>

        {selected && (
          <Inspector
            node={selected}
            graph={graph}
            onSelect={setSelectedId}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  )
}

export function ProjectKnowledgeGraph({
  projectId,
  onStartResearch,
}: {
  projectId: string
  onStartResearch: () => void
}) {
  const { t } = useI18n()
  const [graph, setGraph] = useState<ProjectGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setGraph(await api.getProjectKnowledgeGraph(projectId))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return (
      <div className="page-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <p>{t('projectGraph.loading')}</p>
      </div>
    )
  }

  if (error || !graph) {
    return (
      <div className="page-state">
        <p className="error-text" role="alert">
          {error ?? t('projectGraph.loadFailed')}
        </p>
        <button type="button" className="btn" onClick={() => void load()}>
          {t('common.tryAgain')}
        </button>
      </div>
    )
  }

  // The graph is derived, never "generated", so the only honest empty states are
  // about missing research rather than a missing generation step.
  if (graph.stats.findings === 0) {
    return (
      <section className="card empty-project">
        <h3>{t('projectGraph.emptyTitle')}</h3>
        <p className="hint-text">{t('projectGraph.emptyText')}</p>
        <button type="button" className="btn primary" onClick={onStartResearch}>
          {t('common.startResearch')}
        </button>
      </section>
    )
  }

  if (graph.stats.concepts === 0) {
    return (
      <section className="card empty-project">
        <h3>{t('projectGraph.noConceptsTitle')}</h3>
        <p className="hint-text">{t('projectGraph.noConceptsText', { count: graph.stats.findings })}</p>
        <button type="button" className="btn primary" onClick={onStartResearch}>
          {t('common.continueResearch')}
        </button>
      </section>
    )
  }

  return <ProjectGraphExplorer graph={graph} />
}
