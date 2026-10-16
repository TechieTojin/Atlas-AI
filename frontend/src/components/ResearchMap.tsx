import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { createPortal } from 'react-dom'
import { api, errorMessage } from '../api/client'
import { useI18n } from '../i18n'
import type {
  ResearchMap as ResearchMapData,
  ResearchMapEdge,
  ResearchMapGroup,
  ResearchMapNode,
  ResearchMapNodeType,
  ResearchMapStatus,
} from '../types'
import { safeHttpUrl } from '../utils/safeUrl'
import { ResearchTimeline } from './ResearchTimeline'
import {
  ExternalIcon,
  GitBranchIcon,
  FileTextIcon,
  LayersIcon,
  ListTreeIcon,
  QuoteIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparklesIcon,
  TargetIcon,
  XIcon,
  AlertIcon,
  BulbIcon,
} from './icons'

/**
 * Research Map: how Atlas produced one run, as a deterministic left-to-right
 * execution map. Everything shown comes from the backend map, which is built
 * from stored data only; nothing here infers stages, timings or relations.
 *
 * Nodes are real buttons (keyboard and screen-reader reachable) placed on a
 * pan/zoom stage; edges are drawn underneath in SVG. Sources and evidence are
 * collapsed into groups by default so evidence-heavy runs stay readable.
 */

const NODE_W = 208
const NODE_H = 76
const COL_GAP = 92
const ROW_GAP = 22
const PAD = 40
const MIN_SCALE = 0.25
const MAX_SCALE = 2
/** The first view never shrinks text below a readable size; Fit view shows everything. */
export const READABLE_SCALE = 0.85

type Item =
  | { kind: 'node'; id: string; node: ResearchMapNode }
  | { kind: 'group'; id: string; group: ResearchMapGroup; members: ResearchMapNode[] }

interface Placed {
  item: Item
  x: number
  y: number
}

/** Node types a new research run may branch from (mirrors the backend). */
const BRANCHABLE = new Set<ResearchMapNodeType>(['question', 'plan', 'query', 'source', 'evidence', 'critic'])

const ICONS: Record<ResearchMapNodeType, typeof SearchIcon> = {
  question: TargetIcon,
  plan: ListTreeIcon,
  query: SearchIcon,
  project_memory: BulbIcon,
  source: LayersIcon,
  evidence: QuoteIcon,
  critic: ShieldCheckIcon,
  synthesis: SparklesIcon,
  report: FileTextIcon,
  terminal: AlertIcon,
  branch: GitBranchIcon,
}

/** Visible items: collapsed groups replace their members; edges are re-pointed. */
export function visibleGraph(map: ResearchMapData, expanded: Set<string>) {
  const groupOf = new Map<string, ResearchMapGroup>()
  for (const group of map.groups) {
    if (!expanded.has(group.id) && group.members.length > 1) {
      for (const member of group.members) groupOf.set(member, group)
    }
  }
  const items: Item[] = []
  const seenGroups = new Set<string>()
  const byId = new Map(map.nodes.map((node) => [node.id, node]))
  for (const node of map.nodes) {
    const group = groupOf.get(node.id)
    if (!group) {
      items.push({ kind: 'node', id: node.id, node })
    } else if (!seenGroups.has(group.id)) {
      seenGroups.add(group.id)
      const members = group.members.map((id) => byId.get(id)).filter((n): n is ResearchMapNode => !!n)
      items.push({ kind: 'group', id: group.id, group, members })
    }
  }
  const endpoint = (id: string) => groupOf.get(id)?.id ?? id
  const edges = new Map<string, ResearchMapEdge & { count: number }>()
  for (const edge of map.edges) {
    const source = endpoint(edge.source)
    const target = endpoint(edge.target)
    if (source === target) continue
    const key = `${source}->${target}:${edge.type}`
    const existing = edges.get(key)
    if (existing) existing.count += 1
    else edges.set(key, { ...edge, id: key, source, target, count: 1 })
  }
  return { items, edges: [...edges.values()] }
}

/** Deterministic layered layout: column from the stored rank, row from stored order. */
export function layout(items: Item[]): { placed: Placed[]; width: number; height: number } {
  const rankOf = (item: Item) => (item.kind === 'node' ? item.node.rank : item.group.rank)
  const ranks = [...new Set(items.map(rankOf))].sort((a, b) => a - b)
  const columns = new Map<number, Item[]>(ranks.map((rank) => [rank, []]))
  for (const item of items) columns.get(rankOf(item))?.push(item)
  const tallest = Math.max(1, ...[...columns.values()].map((column) => column.length))
  const height = tallest * NODE_H + (tallest - 1) * ROW_GAP + PAD * 2
  const placed: Placed[] = []
  ranks.forEach((rank, col) => {
    const column = columns.get(rank) ?? []
    const columnHeight = column.length * NODE_H + (column.length - 1) * ROW_GAP
    const top = (height - columnHeight) / 2
    column.forEach((item, row) => {
      placed.push({ item, x: PAD + col * (NODE_W + COL_GAP), y: top + row * (NODE_H + ROW_GAP) })
    })
  })
  const width = PAD * 2 + ranks.length * NODE_W + Math.max(0, ranks.length - 1) * COL_GAP
  return { placed, width, height }
}

function formatDuration(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined) return null
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  return seconds < 60 ? `${seconds.toFixed(1)} s` : `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`
}

export function ResearchMap({ runId, onOpenReport }: { runId: string; onOpenReport?: () => void }) {
  const { t } = useI18n()
  const [map, setMap] = useState<ResearchMapData | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getResearchMap(runId)
      .then(setMap)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [runId])

  useEffect(() => {
    load()
  }, [load])

  if (loading && !map) {
    return (
      <div className="page-state research-map-state" role="status">
        <span className="spinner" aria-hidden="true" /> {t('researchMap.loading')}
      </div>
    )
  }
  if (error || !map) {
    return (
      <div className="page-state research-map-state" role="alert">
        <p className="error-text">{t('researchMap.error')}</p>
        <p className="hint-text">{errorMessage(error)}</p>
        <button type="button" className="btn light compact" onClick={load}>
          {t('researchMap.retry')}
        </button>
      </div>
    )
  }
  return <MapOrTimeline map={map} onOpenReport={onOpenReport} />
}

/** The Research Map and the Timeline are two views of the same stored run. */
function MapOrTimeline({ map, onOpenReport }: { map: ResearchMapData; onOpenReport?: () => void }) {
  const { t } = useI18n()
  const [view, setView] = useState<'map' | 'timeline'>('map')
  return (
    <div className="research-views">
      <div className="research-view-toggle" role="tablist" aria-label={t('researchMap.viewLabel')}>
        <button
          type="button"
          role="tab"
          aria-selected={view === 'map'}
          className={`research-view-tab${view === 'map' ? ' active' : ''}`}
          onClick={() => setView('map')}
        >
          {t('researchMap.viewMap')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === 'timeline'}
          className={`research-view-tab${view === 'timeline' ? ' active' : ''}`}
          onClick={() => setView('timeline')}
        >
          {t('researchMap.viewTimeline')}
        </button>
      </div>
      {view === 'map' ? (
        <MapView map={map} onOpenReport={onOpenReport} />
      ) : (
        <ResearchTimeline runId={map.run_id} />
      )}
    </div>
  )
}

function MapView({ map, onOpenReport }: { map: ResearchMapData; onOpenReport?: () => void }) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const viewport = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null)

  const { items, edges } = useMemo(() => visibleGraph(map, expanded), [map, expanded])
  const { placed, width, height } = useMemo(() => layout(items), [items])
  const position = useMemo(() => new Map(placed.map((p) => [p.item.id, p])), [placed])
  const groupable = map.groups.filter((group) => group.members.length > 1)

  const fitScale = useCallback(() => {
    const box = viewport.current?.getBoundingClientRect()
    if (!box || box.width === 0) return null
    return { box, k: Math.min(1, Math.max(MIN_SCALE, Math.min(box.width / width, box.height / height) * 0.96)) }
  }, [width, height])

  /** Whole map in view, however small (the user asked for it). */
  const fit = useCallback(() => {
    const f = fitScale()
    if (!f) return
    setView({ k: f.k, x: (f.box.width - width * f.k) / 2, y: (f.box.height - height * f.k) / 2 })
  }, [fitScale, width, height])

  /** First view: the whole map if it is readable, otherwise a readable view
   *  starting at the question, with the rest one pan away. */
  const initialView = useCallback(() => {
    const f = fitScale()
    if (!f) return
    if (f.k >= READABLE_SCALE) {
      fit()
      return
    }
    const k = READABLE_SCALE
    const question = placed.find((p) => p.item.id === 'question') ?? placed[0]
    const qy = question ? question.y + NODE_H / 2 : height / 2
    const y = height * k <= f.box.height ? (f.box.height - height * k) / 2 : f.box.height / 2 - qy * k
    setView({ k, x: 16 - (question ? question.x - PAD : 0) * k, y })
  }, [fitScale, fit, placed, height])

  useLayoutEffect(() => {
    initialView()
  }, [initialView])

  useEffect(() => {
    const element = viewport.current
    if (!element || typeof ResizeObserver === 'undefined') return
    let lastWidth = element.getBoundingClientRect().width
    const observer = new ResizeObserver(() => {
      const next = element.getBoundingClientRect().width
      if (Math.abs(next - lastWidth) > 1) initialView()
      lastWidth = next
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [initialView])

  // Ctrl/Cmd + wheel zooms the map; a plain wheel keeps scrolling the page.
  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      const box = element.getBoundingClientRect()
      zoomRef.current(event.deltaY < 0 ? 1.1 : 1 / 1.1, event.clientX - box.left, event.clientY - box.top)
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [])

  const zoom = (factor: number, cx?: number, cy?: number) => {
    const box = viewport.current?.getBoundingClientRect()
    const px = cx ?? (box ? box.width / 2 : 0)
    const py = cy ?? (box ? box.height / 2 : 0)
    setView((v) => {
      const k = Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.k * factor))
      const ratio = k / v.k
      return { k, x: px - (px - v.x) * ratio, y: py - (py - v.y) * ratio }
    })
  }

  const zoomRef = useRef(zoom)
  zoomRef.current = zoom

  // Neighbourhood of the selection (for restrained highlighting).
  const neighbours = useMemo(() => {
    if (!selected) return null
    const ids = new Set([selected])
    for (const edge of edges) {
      if (edge.source === selected) ids.add(edge.target)
      if (edge.target === selected) ids.add(edge.source)
    }
    return ids
  }, [selected, edges])

  const byId = useMemo(() => new Map(map.nodes.map((n) => [n.id, n])), [map.nodes])
  // A member chosen from a collapsed group is inspected even though it is not drawn.
  const selectedItem: Item | null =
    items.find((item) => item.id === selected) ??
    (selected && byId.has(selected) ? { kind: 'node', id: selected, node: byId.get(selected)! } : null)

  const toggleGroup = (groupId: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })

  const statusLabel = (status: ResearchMapStatus) => t(`researchMap.status.${status}`)

  return (
    <div className="research-map">
      <div className="research-map-toolbar">
        <div className="research-map-title">
          <h2 className="panel-heading">{t('researchMap.title')}</h2>
          <p className="research-map-subtitle">
            <span className="badge tone-muted">{map.mode}</span>
            <span className={`research-map-status status-${map.run_status.toLowerCase()}`}>
              {t(`researchMap.runStatus.${map.run_status}`)}
            </span>
            <span className="research-map-counts">
              {t('researchMap.counts', {
                queries: String(map.summary.query_count),
                sources: String(map.summary.source_count),
                evidence: String(map.summary.evidence_count),
              })}
            </span>
          </p>
        </div>
        <div className="research-map-controls">
          <button type="button" className="btn compact" onClick={() => zoom(1 / 1.2)} aria-label={t('researchMap.zoomOut')}>
            −
          </button>
          <button type="button" className="btn compact" onClick={() => zoom(1.2)} aria-label={t('researchMap.zoomIn')}>
            +
          </button>
          <button type="button" className="btn compact" onClick={fit}>
            {t('researchMap.fit')}
          </button>
          {groupable.length > 0 && (
            <>
              <button type="button" className="btn compact" onClick={() => setExpanded(new Set(groupable.map((g) => g.id)))}>
                {t('researchMap.expandAll')}
              </button>
              <button type="button" className="btn compact" onClick={() => setExpanded(new Set())}>
                {t('researchMap.collapseAll')}
              </button>
            </>
          )}
        </div>
      </div>

      {map.limitations.length > 0 && <p className="research-map-note">{t('researchMap.historical')}</p>}

      <div
        ref={viewport}
        className="research-map-viewport"
        // As tall as the map needs at a readable scale, within the CSS bounds.
        style={{ height: `${Math.round(height * READABLE_SCALE + 48)}px` }}
        onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest('.research-map-node')) return
          drag.current = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y, moved: false }
          event.currentTarget.setPointerCapture?.(event.pointerId)
        }}
        onPointerMove={(event) => {
          const d = drag.current
          if (!d) return
          d.moved = true
          setView((v) => ({ ...v, x: d.vx + event.clientX - d.x, y: d.vy + event.clientY - d.y }))
        }}
        onPointerUp={() => {
          drag.current = null
        }}
        onPointerCancel={() => {
          drag.current = null
        }}
      >
        <div
          className="research-map-stage"
          style={{ width, height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}
        >
          <svg className="research-map-edges" width={width} height={height} aria-hidden="true">
            <defs>
              <marker id="rm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" className="research-map-arrow" />
              </marker>
            </defs>
            {edges.map((edge) => {
              const a = position.get(edge.source)
              const b = position.get(edge.target)
              if (!a || !b) return null
              const x1 = a.x + NODE_W
              const y1 = a.y + NODE_H / 2
              const x2 = b.x
              const y2 = b.y + NODE_H / 2
              const back = x2 <= x1
              const mid = back ? 0 : (x2 - x1) / 2
              const d = back
                ? `M${x1},${y1} C${x1 + 60},${y1 + 120} ${x2 - 60},${y2 + 120} ${x2},${y2}`
                : `M${x1},${y1} C${x1 + mid},${y1} ${x2 - mid},${y2} ${x2},${y2}`
              const active = neighbours ? neighbours.has(edge.source) && neighbours.has(edge.target) : false
              return (
                <path
                  key={edge.id}
                  d={d}
                  className={`research-map-edge edge-${edge.type.toLowerCase()}${active ? ' active' : ''}${neighbours && !active ? ' dim' : ''}`}
                  markerEnd="url(#rm-arrow)"
                />
              )
            })}
          </svg>
          {placed.map(({ item, x, y }) => (
            <MapNodeButton
              key={item.id}
              item={item}
              x={x}
              y={y}
              selected={selected === item.id}
              dimmed={neighbours !== null && !neighbours.has(item.id)}
              statusLabel={statusLabel}
              onSelect={() => setSelected(item.id)}
            />
          ))}
        </div>
      </div>

      <p className="research-map-hint">{t('researchMap.hint')}</p>

      {/* Text equivalent of the map for assistive technology. */}
      <ol className="visually-hidden" aria-label={t('researchMap.listLabel')}>
        {map.nodes.map((node) => (
          <li key={node.id}>
            {t(`researchMap.type.${node.type}`)}: {nodeTitle(node, t)} ({statusLabel(node.status)})
          </li>
        ))}
      </ol>

      {selectedItem && (
        <Inspector
          item={selectedItem}
          runId={map.run_id}
          byId={byId}
          expanded={selectedItem.kind === 'group' && expanded.has(selectedItem.group.id)}
          onToggleGroup={toggleGroup}
          onSelectNode={(id) => setSelected(id)}
          onClose={() => setSelected(null)}
          onOpenReport={onOpenReport}
          statusLabel={statusLabel}
        />
      )}
    </div>
  )
}

type Translate = ReturnType<typeof useI18n>['t']

function nodeTitle(node: ResearchMapNode, t: Translate): string {
  const d = node.data
  switch (node.type) {
    case 'question':
    case 'query':
      return node.label
    case 'plan': {
      const subs = (d.subquestions as unknown[] | undefined)?.length ?? 0
      const queries = (d.search_queries as unknown[] | undefined)?.length ?? 0
      return t('researchMap.planSummary', { subquestions: String(subs), queries: String(queries) })
    }
    case 'source':
      return `[${d.citation}] ${node.label}`
    case 'evidence':
      return node.label
    case 'critic':
      return d.score !== null && d.score !== undefined
        ? t('researchMap.criticScore', { score: String(d.score), decision: String(d.decision ?? '') })
        : t('researchMap.type.critic')
    case 'project_memory':
      return t('researchMap.memoryHits', { count: String(d.hits ?? 0) })
    case 'report':
      return node.label
    case 'branch':
      return node.label
    default:
      return t(`researchMap.type.${node.type}`)
  }
}

function MapNodeButton({
  item,
  x,
  y,
  selected,
  dimmed,
  statusLabel,
  onSelect,
}: {
  item: Item
  x: number
  y: number
  selected: boolean
  dimmed: boolean
  statusLabel: (status: ResearchMapStatus) => string
  onSelect: () => void
}) {
  const { t } = useI18n()
  const type = item.kind === 'node' ? item.node.type : item.group.type
  const Icon = ICONS[type]
  const status: ResearchMapStatus = item.kind === 'node' ? item.node.status : 'completed'
  const iteration = item.kind === 'node' ? item.node.iteration : item.group.iteration
  const title =
    item.kind === 'node'
      ? nodeTitle(item.node, t)
      : t(type === 'source' ? 'researchMap.sourcesGroup' : 'researchMap.evidenceGroup', {
          count: String(item.members.length),
        })
  const kind = t(`researchMap.type.${type}`)
  const showStatus = status !== 'completed'
  return (
    <button
      type="button"
      className={`research-map-node type-${type} status-${status}${item.kind === 'group' ? ' is-group' : ''}${selected ? ' selected' : ''}${dimmed ? ' dim' : ''}`}
      style={{ left: x, top: y, width: NODE_W, height: NODE_H }}
      onClick={onSelect}
      aria-label={`${kind}: ${title}. ${statusLabel(status)}`}
      aria-pressed={selected}
    >
      <span className="research-map-node-head">
        <Icon size={14} className="research-map-node-icon" />
        <span className="research-map-node-kind">
          {kind}
          {iteration ? ` · ${t('researchMap.iteration', { n: String(iteration) })}` : ''}
        </span>
        {showStatus && <span className={`research-map-badge status-${status}`}>{statusLabel(status)}</span>}
      </span>
      <span className="research-map-node-label">{title}</span>
    </button>
  )
}

function Inspector({
  item,
  runId,
  byId,
  expanded,
  onToggleGroup,
  onSelectNode,
  onClose,
  onOpenReport,
  statusLabel,
}: {
  item: Item
  runId: string
  byId: Map<string, ResearchMapNode>
  expanded: boolean
  onToggleGroup: (id: string) => void
  onSelectNode: (id: string) => void
  onClose: () => void
  onOpenReport?: () => void
  statusLabel: (status: ResearchMapStatus) => string
}) {
  const { t } = useI18n()
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [item.id])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const type = item.kind === 'node' ? item.node.type : item.group.type
  const heading =
    item.kind === 'node'
      ? t(`researchMap.type.${type}`)
      : t(type === 'source' ? 'researchMap.sourcesGroup' : 'researchMap.evidenceGroup', {
          count: String(item.members.length),
        })

  return createPortal(
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside ref={ref} className="drawer research-map-drawer" role="dialog" aria-modal="true" aria-label={heading} tabIndex={-1}>
        <header className="drawer-header">
          <h2 className="drawer-title">{heading}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t('researchMap.close')}>
            <XIcon size={15} />
          </button>
        </header>
        <div className="drawer-body">
          {item.kind === 'group' ? (
            <>
              <button type="button" className="btn light compact" onClick={() => onToggleGroup(item.group.id)}>
                {expanded ? t('researchMap.collapse') : t('researchMap.expand')}
              </button>
              <ul className="research-map-members">
                {item.members.map((member) => (
                  <li key={member.id}>
                    <button type="button" className="link-btn" onClick={() => onSelectNode(member.id)}>
                      {member.type === 'source' ? `[${member.data.citation}] ` : ''}
                      {member.label}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <NodeDetails node={item.node} runId={runId} byId={byId} onSelectNode={onSelectNode} onOpenReport={onOpenReport} statusLabel={statusLabel} />
          )}
        </div>
      </aside>
    </>,
    document.body,
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  if (children === null || children === undefined || children === '') return null
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function List({ items }: { items: unknown }) {
  const list = Array.isArray(items) ? items.map(String) : []
  if (list.length === 0) return null
  return (
    <ul className="research-map-list">
      {list.map((value, i) => (
        <li key={i}>{value}</li>
      ))}
    </ul>
  )
}

function NodeDetails({
  node,
  runId,
  byId,
  onSelectNode,
  onOpenReport,
  statusLabel,
}: {
  node: ResearchMapNode
  runId: string
  byId: Map<string, ResearchMapNode>
  onSelectNode: (id: string) => void
  onOpenReport?: () => void
  statusLabel: (status: ResearchMapStatus) => string
}) {
  const { t, format } = useI18n()
  const navigate = useNavigate()
  const d = node.data as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
  const time = (value: string | null) => (value ? format.dateTime(new Date(value)) : null)
  const common = (
    <>
      <Field label={t('researchMap.field.status')}>{statusLabel(node.status)}</Field>
      {node.iteration ? <Field label={t('researchMap.field.iteration')}>{node.iteration}</Field> : null}
      <Field label={t('researchMap.field.started')}>{time(node.started_at)}</Field>
      <Field label={t('researchMap.field.completed')}>{time(node.completed_at)}</Field>
      <Field label={t('researchMap.field.duration')}>{formatDuration(node.duration_ms)}</Field>
    </>
  )
  const url = typeof d.url === 'string' ? safeHttpUrl(d.url) : null
  const sourceId = typeof d.citation === 'number' ? `source:${d.citation}` : null

  return (
    <>
      {node.type === 'question' && <p className="research-map-quote">{d.question}</p>}
      {node.type === 'query' && <p className="research-map-quote">{d.query}</p>}
      {node.type === 'evidence' && <blockquote className="website-passage research-map-excerpt">{d.content}</blockquote>}
      {node.type === 'source' && <p className="research-map-quote">{d.title || d.filename || d.url}</p>}
      {node.type === 'terminal' && d.error && <p className="error-text">{d.error}</p>}
      <dl className="website-drawer-meta">
        {common}
        {node.type === 'question' && (
          <>
            <Field label={t('researchMap.field.mode')}>{d.mode}</Field>
            <Field label={t('researchMap.field.scope')}>{d.source_scope}</Field>
            <Field label={t('researchMap.field.template')}>{d.template}</Field>
            <Field label={t('researchMap.field.language')}>{d.output_language}</Field>
            <Field label={t('researchMap.field.memory')}>{d.use_memory ? t('researchMap.yes') : t('researchMap.no')}</Field>
          </>
        )}
        {node.type === 'plan' && (
          <>
            <Field label={t('researchMap.field.objective')}>{d.objective}</Field>
            <Field label={t('researchMap.field.subquestions')}>
              <List items={d.subquestions} />
            </Field>
            <Field label={t('researchMap.field.queries')}>
              <List items={d.search_queries} />
            </Field>
            {d.approval_required ? (
              <Field label={t('researchMap.field.approval')}>
                {d.approved ? t('researchMap.approved') : t('researchMap.notApproved')}
                {d.edited ? ` · ${t('researchMap.edited')}` : ''}
              </Field>
            ) : null}
            {d.original_queries ? (
              <Field label={t('researchMap.field.originalQueries')}>
                <List items={d.original_queries} />
              </Field>
            ) : null}
          </>
        )}
        {node.type === 'query' && (
          <>
            <Field label={t('researchMap.field.retrieval')}>{t(`researchMap.retrieval.${d.retrieval as 'web' | 'documents' | 'web_and_documents'}`)}</Field>
            <Field label={t('researchMap.field.webResults')}>{d.web_results ?? null}</Field>
            <Field label={t('researchMap.field.documentChunks')}>{d.document_chunks ?? null}</Field>
            <Field label={t('researchMap.field.memoryHits')}>{d.memory_hits ?? null}</Field>
          </>
        )}
        {node.type === 'project_memory' && (
          <Field label={t('researchMap.field.findings')}>
            <List items={(d.items as { text: string }[]).map((i) => i.text)} />
          </Field>
        )}
        {node.type === 'source' && (
          <>
            <Field label={t('researchMap.field.citation')}>[{d.citation}]</Field>
            <Field label={t('researchMap.field.publisher')}>{d.domain || d.filename}</Field>
            <Field label={t('researchMap.field.page')}>{d.page ?? null}</Field>
            <Field label={t('researchMap.field.authority')}>
              {d.quality ? `${d.quality.category} · ${d.quality.tier} · ${d.quality.score}/100` : null}
            </Field>
            {Array.isArray(d.claims) && d.claims.length > 0 && (
              <Field label={t('researchMap.field.claims')}>
                <List items={d.claims.map((c: { text: string }) => c.text)} />
              </Field>
            )}
          </>
        )}
        {node.type === 'evidence' && (
          <>
            <Field label={t('researchMap.field.citation')}>{d.citation ? `[${d.citation}]` : t('researchMap.notCited')}</Field>
            <Field label={t('researchMap.field.source')}>{d.source_title || d.filename}</Field>
            <Field label={t('researchMap.field.page')}>{d.page ?? null}</Field>
            <Field label={t('researchMap.field.query')}>{d.query}</Field>
            <Field label={t('researchMap.field.origin')}>{t(`researchMap.origin.${d.origin as 'web' | 'document' | 'memory'}`)}</Field>
            <Field label={t('researchMap.field.extraction')}>{d.extraction}</Field>
            <Field label={t('researchMap.field.relevance')}>
              {typeof d.relevance === 'number' ? d.relevance.toFixed(2) : null}
            </Field>
            <Field label={t('researchMap.field.authority')}>{d.quality_tier ?? null}</Field>
          </>
        )}
        {node.type === 'critic' && (
          <>
            <Field label={t('researchMap.field.score')}>{d.score ?? null}</Field>
            <Field label={t('researchMap.field.decision')}>{d.decision ?? null}</Field>
            <Field label={t('researchMap.field.reason')}>{d.fallback_reason ?? null}</Field>
            <Field label={t('researchMap.field.coverage')}>{d.coverage ?? null}</Field>
            <Field label={t('researchMap.field.gaps')}>
              <List items={d.missing_information} />
            </Field>
            <Field label={t('researchMap.field.followUps')}>
              <List items={d.follow_up_queries} />
            </Field>
          </>
        )}
        {node.type === 'synthesis' && (
          <>
            <Field label={t('researchMap.field.template')}>{d.template}</Field>
            <Field label={t('researchMap.field.language')}>{d.output_language}</Field>
            <Field label={t('researchMap.field.sources')}>{d.sources}</Field>
            <Field label={t('researchMap.field.evidence')}>{d.evidence}</Field>
            <Field label={t('researchMap.field.cited')}>{d.sources_cited ?? null}</Field>
            {d.fallback ? <Field label={t('researchMap.field.fallback')}>{d.fallback_reason || t('researchMap.yes')}</Field> : null}
          </>
        )}
        {node.type === 'report' && (
          <>
            <Field label={t('researchMap.field.citations')}>{d.citations}</Field>
            <Field label={t('researchMap.field.words')}>{d.word_count}</Field>
          </>
        )}
        {node.type === 'branch' && (
          <>
            <Field label={t('researchMap.field.instruction')}>{d.instruction}</Field>
            <Field label={t('researchMap.field.mode')}>{d.mode}</Field>
          </>
        )}
      </dl>
      {node.type === 'source' && url && (
        <a className="btn drawer-open-link" href={url} target="_blank" rel="noopener noreferrer">
          <ExternalIcon size={13} />
          <span>{t('researchMap.openSource')}</span>
        </a>
      )}
      {node.type === 'evidence' && sourceId && byId.has(sourceId) && (
        <button type="button" className="btn light compact" onClick={() => onSelectNode(sourceId)}>
          {t('researchMap.showSource')}
        </button>
      )}
      {node.type === 'report' && onOpenReport && (
        <button type="button" className="btn primary compact" onClick={onOpenReport}>
          {t('researchMap.openReport')}
        </button>
      )}
      {node.type === 'branch' && typeof d.run_id === 'string' && (
        <button type="button" className="btn primary compact" onClick={() => navigate(`/runs/${d.run_id}`)}>
          {t('researchMap.openResearch')}
        </button>
      )}
      {BRANCHABLE.has(node.type) && <BranchComposer runId={runId} node={node} />}
    </>
  )
}

/**
 * "Research from here": starts a NEW run whose planner receives this node's
 * stored content as background. The parent run is never modified.
 */
function BranchComposer({ runId, node }: { runId: string; node: ResearchMapNode }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [mode, setMode] = useState<'FAST' | 'DEEP'>('FAST')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) {
    return (
      <button type="button" className="btn light compact" onClick={() => setOpen(true)}>
        <GitBranchIcon size={13} />
        <span>{t('researchMap.branchAction')}</span>
      </button>
    )
  }
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const text = instruction.trim()
    if (!text || busy) return
    setBusy(true)
    setError(null)
    try {
      const child = await api.createBranch(runId, { node_id: node.id, instruction: text, mode })
      navigate(`/runs/${child.id}`)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }
  return (
    <form className="research-branch-composer" onSubmit={submit}>
      <h3 className="panel-heading">{t('researchMap.branchTitle')}</h3>
      <p className="hint-text">{t('researchMap.branchHint')}</p>
      <label className="visually-hidden" htmlFor={`branch-${node.id}`}>
        {t('researchMap.branchInstructionLabel')}
      </label>
      <textarea
        id={`branch-${node.id}`}
        className="research-branch-input"
        rows={3}
        maxLength={2000}
        placeholder={t('researchMap.branchPlaceholder')}
        value={instruction}
        onChange={(event) => setInstruction(event.target.value)}
        disabled={busy}
      />
      <div className="research-branch-row">
        <label className="research-branch-mode">
          <span>{t('researchMap.field.mode')}</span>
          <select value={mode} onChange={(event) => setMode(event.target.value as 'FAST' | 'DEEP')} disabled={busy}>
            <option value="FAST">FAST</option>
            <option value="DEEP">DEEP</option>
          </select>
        </label>
        <button type="submit" className="btn primary compact" disabled={!instruction.trim() || busy}>
          {busy ? t('researchMap.branchStarting') : t('researchMap.branchStart')}
        </button>
        <button type="button" className="btn light compact" onClick={() => setOpen(false)} disabled={busy}>
          {t('researchMap.close')}
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
