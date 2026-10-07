import { useI18n } from '../../i18n'
import { Leaf } from './Leaf'

function DocBadge({ label, className, tone }: { label: string; className: string; tone: 'pdf' | 'txt' | 'md' }) {
  return (
    <span className={`doc-art-badge tone-${tone} ${className}`} aria-hidden="true">
      {label}
    </span>
  )
}

function Sheet({ x, y, rotate, lines }: { x: number; y: number; rotate: number; lines: number[] }) {
  return (
    <g transform={`rotate(${rotate} ${x + 60} ${y + 78})`}>
      <rect x={x + 6} y={y + 10} width="120" height="156" rx="12" fill="#000" opacity="0.35" filter="url(#da-blur)" />
      <path
        d={`M${x + 12} ${y}h78l30 30v114a12 12 0 0 1-12 12H${x + 12}a12 12 0 0 1-12-12V${y + 12}a12 12 0 0 1 12-12z`}
        fill="url(#da-paper)"
        stroke="url(#da-rim)"
        strokeWidth="1.5"
      />
      <path d={`M${x + 90} ${y}v22a8 8 0 0 0 8 8h22z`} fill="#c6d8ce" />
      {lines.map((width, index) => (
        <rect
          key={index}
          x={x + 16}
          y={y + 30 + index * 15}
          width={width}
          height={index === 0 ? 7 : 5.5}
          rx="3"
          fill={index === 0 ? '#8fa89b' : '#c2d1c9'}
        />
      ))}
      <rect x={x} y={y} width="60" height="156" rx="12" fill="url(#da-sheen)" />
    </g>
  )
}

/** Dimensional document stack with format badges above a glowing upload cloud. */
export function DocumentsHeroArt() {
  const { t } = useI18n()
  return (
    <div className="documents-art" aria-hidden="true">
      <div className="documents-art-glow" />
      <svg className="documents-orbit" viewBox="0 0 520 320">
        <g fill="none" stroke="#7dffab">
          <ellipse cx="270" cy="170" rx="210" ry="120" strokeOpacity="0.16" transform="rotate(-14 270 170)" />
          <ellipse cx="270" cy="170" rx="170" ry="150" strokeOpacity="0.08" />
        </g>
        <g fill="#b9ffd1">
          <circle cx="70" cy="90" r="2" opacity="0.8" />
          <circle cx="470" cy="70" r="1.6" opacity="0.7" />
          <circle cx="430" cy="270" r="2.2" opacity="0.8" />
          <circle cx="110" cy="260" r="1.5" opacity="0.6" />
          <circle cx="300" cy="18" r="1.4" opacity="0.7" />
        </g>
      </svg>

      <svg className="documents-pages" viewBox="0 0 260 230">
        <defs>
          <linearGradient id="da-paper" x1="0" y1="0" x2="0.4" y2="1">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="0.6" stopColor="#eef5f0" />
            <stop offset="1" stopColor="#cddcd3" />
          </linearGradient>
          <linearGradient id="da-rim" x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7dffab" stopOpacity="0.9" />
            <stop offset="0.5" stopColor="#7dffab" stopOpacity="0.1" />
          </linearGradient>
          <linearGradient id="da-sheen" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#fff" stopOpacity="0.5" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
          <filter id="da-blur" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="7" />
          </filter>
        </defs>
        <Sheet x={30} y={40} rotate={-14} lines={[60, 86, 86, 54, 80]} />
        <Sheet x={110} y={30} rotate={9} lines={[54, 84, 70, 84]} />
        <Sheet x={70} y={22} rotate={-2} lines={[64, 90, 90, 62, 84, 70]} />
      </svg>

      <DocBadge label="PDF" tone="pdf" className="doc-art-badge-pdf" />
      <DocBadge label="TXT" tone="txt" className="doc-art-badge-txt" />
      <DocBadge label="MD" tone="md" className="doc-art-badge-md" />

      <svg className="documents-cloud" viewBox="0 0 220 170">
        <defs>
          <linearGradient id="dc-fill" x1="0.2" y1="0" x2="0.6" y2="1">
            <stop offset="0" stopColor="#b6ffd0" />
            <stop offset="0.4" stopColor="#5cf28f" />
            <stop offset="1" stopColor="#16924c" />
          </linearGradient>
          <radialGradient id="dc-hi" cx="35%" cy="25%" r="45%">
            <stop offset="0" stopColor="#fff" stopOpacity="0.55" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </radialGradient>
          <filter id="dc-blur" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="6" />
          </filter>
        </defs>
        <ellipse cx="112" cy="156" rx="78" ry="9" fill="#000" opacity="0.5" filter="url(#dc-blur)" />
        <path d="M64 140a38 38 0 0 1-7-75.4A51 51 0 0 1 155 56a40 40 0 0 1 3 84z" fill="url(#dc-fill)" />
        <path d="M64 140a38 38 0 0 1-7-75.4A51 51 0 0 1 155 56a40 40 0 0 1 3 84z" fill="url(#dc-hi)" />
        <path
          d="M64 140a38 38 0 0 1-7-75.4A51 51 0 0 1 155 56a40 40 0 0 1 3 84z"
          fill="none"
          stroke="#d4ffe2"
          strokeOpacity="0.5"
          strokeWidth="1.5"
        />
        <path d="M110 128V80" stroke="#05140b" strokeWidth="10" strokeLinecap="round" />
        <path d="M86 102l24-24 24 24" stroke="#05140b" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </svg>

      <p className="script-note documents-script">
        {t('documents.scriptLine1')}
        <br />
        {t('documents.scriptLine2')}
        <br />
        {t('documents.scriptLine3')}
        <br />
        {t('documents.scriptLine4')}
      </p>

      <Leaf size={42} rotate={-40} className="documents-leaf-a" />
      <Leaf size={32} rotate={160} className="documents-leaf-b" />
      <Leaf size={28} rotate={60} className="documents-leaf-c" />
    </div>
  )
}
