import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { ProjectWithCounts } from '../types'
import { agoLabel, useI18n, type Translate } from '../i18n'
import { ClockIcon, FolderIcon, FolderOpenIcon, LinkIcon, MoreVerticalIcon } from './icons'

export function countsLine(
  t: Translate,
  counts: { runs: number; documents: number; comparisons: number },
): string {
  const parts = [
    t('projectCard.runs', { count: counts.runs }),
    t('projectCard.documents', { count: counts.documents }),
  ]
  if (counts.comparisons > 0) {
    parts.push(t('projectCard.comparisons', { count: counts.comparisons }))
  }
  return parts.join(' · ')
}

const WAVE_SHAPES = [
  [62, 48, 58, 34, 44, 22, 30],
  [58, 64, 40, 50, 28, 36, 18],
  [66, 44, 52, 38, 26, 40, 24],
]

function wavePath(points: number[], lift: number): string {
  const step = 320 / (points.length - 1)
  const ys = points.map((y) => y + lift)
  let d = `M0 ${ys[0]}`
  for (let i = 1; i < ys.length; i++) {
    const x0 = (i - 1) * step
    const x1 = i * step
    d += ` C${x0 + step / 2} ${ys[i - 1]} ${x1 - step / 2} ${ys[i]} ${x1} ${ys[i]}`
  }
  return d
}

/** Decorative only: an abstract terrain line, not project analytics. */
function CardWave({ variant }: { variant: number }) {
  const points = WAVE_SHAPES[variant % WAVE_SHAPES.length]
  const id = `card-wave-${variant % WAVE_SHAPES.length}`
  const line = wavePath(points, 0)
  const back = wavePath(points.map((y, i) => y + (i % 2 ? -10 : 8)), 6)
  const step = 320 / (points.length - 1)
  return (
    <svg className="project-card-wave" viewBox="0 0 320 90" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#55f58a" stopOpacity="0.38" />
          <stop offset="1" stopColor="#55f58a" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${back} V90 H0 Z`} fill="#55f58a" opacity="0.08" />
      <path d={`${line} V90 H0 Z`} fill={`url(#${id})`} />
      <path d={line} stroke="#7dffab" strokeOpacity="0.85" fill="none" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      {points.slice(1, -1).map((y, i) =>
        i % 2 === 1 ? <circle key={i} cx={(i + 1) * step} cy={y} r="2.6" fill="#b9ffd1" /> : null,
      )}
    </svg>
  )
}

/** Dark glass project card showing real project data, with a kebab menu. */
export function ProjectCard({ project, index, layout = 'grid' }: { project: ProjectWithCounts; index: number; layout?: 'grid' | 'list' }) {
  const navigate = useNavigate()
  const { t, format } = useI18n()
  const [menuOpen, setMenuOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onDocClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  const copyLink = async () => {
    const url = `${window.location.origin}/projects/${project.id}`
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable: nothing to pretend.
    }
    setMenuOpen(false)
  }

  return (
    <article className={`project-card ${layout}`}>
      <div className="project-card-top">
        <span className="project-card-folder">
          <FolderIcon size={22} />
        </span>
        <div className="menu-wrap project-card-menu" ref={menuRef}>
          <button
            type="button"
            className="icon-btn"
            aria-label={t('common.moreActionsFor', { name: project.name })}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((value) => !value)}
          >
            <MoreVerticalIcon size={18} />
          </button>
          {menuOpen && (
            <div className="menu" role="menu" aria-label={t('common.actionsFor', { name: project.name })}>
              <button
                type="button"
                role="menuitem"
                className="menu-item"
                onClick={() => navigate(`/projects/${project.id}`)}
              >
                <FolderOpenIcon size={14} />
                {t('projectCard.openProject')}
              </button>
              <button type="button" role="menuitem" className="menu-item" onClick={() => void copyLink()}>
                <LinkIcon size={14} />
                {copied ? t('common.linkCopied') : t('common.copyLink')}
              </button>
            </div>
          )}
        </div>
      </div>
      <Link to={`/projects/${project.id}`} className="project-card-link">
        <span className="project-card-name">{project.name}</span>
        {project.description && (
          <span className="project-card-description">{project.description}</span>
        )}
      </Link>
      <div className="project-card-meta">
        <span className="project-card-counts">
          <FolderIcon size={15} />
          <span>{countsLine(t, project.counts)}</span>
        </span>
        <span className="project-card-updated">
          <ClockIcon size={15} />
          <span>{t('time.updated', { time: agoLabel(t, format, project.updated_at) })}</span>
        </span>
      </div>
      {layout === 'grid' && <CardWave variant={index} />}
    </article>
  )
}
