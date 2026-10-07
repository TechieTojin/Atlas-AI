import { BarChartIcon, FileTextIcon, SearchIcon } from '../icons'
import { FloatingCard } from './FloatingCard'
import { Leaf } from './Leaf'
import { useI18n } from '../../i18n'

function Robot() {
  return (
    <svg className="projects-robot" viewBox="0 0 300 330">
      <defs>
        <linearGradient id="pr-shell" x1="0.2" y1="0" x2="0.8" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.55" stopColor="#e6eeea" />
          <stop offset="1" stopColor="#a9bab2" />
        </linearGradient>
        <radialGradient id="pr-shell-shade" cx="30%" cy="22%" r="85%">
          <stop offset="0.5" stopColor="#000" stopOpacity="0" />
          <stop offset="1" stopColor="#0b2a1c" stopOpacity="0.38" />
        </radialGradient>
        <linearGradient id="pr-face" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1a2d26" />
          <stop offset="0.5" stopColor="#07110d" />
          <stop offset="1" stopColor="#030806" />
        </linearGradient>
        <linearGradient id="pr-gloss" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.28" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="pr-eye" cx="50%" cy="45%" r="55%">
          <stop offset="0" stopColor="#eafff1" />
          <stop offset="0.45" stopColor="#6dff9f" />
          <stop offset="1" stopColor="#18a653" />
        </radialGradient>
        <filter id="pr-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="5" />
        </filter>
        <linearGradient id="pr-rim" x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#7dffab" stopOpacity="0.9" />
          <stop offset="0.5" stopColor="#7dffab" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* ground shadow */}
      <ellipse cx="150" cy="318" rx="92" ry="10" fill="#000" opacity="0.45" filter="url(#pr-glow)" />

      {/* antenna */}
      <rect x="146" y="20" width="8" height="30" rx="4" fill="url(#pr-shell)" />
      <circle cx="150" cy="16" r="16" fill="#55f58a" opacity="0.35" filter="url(#pr-glow)" />
      <circle cx="150" cy="16" r="8" fill="url(#pr-eye)" />

      {/* ears */}
      <rect x="22" y="104" width="30" height="58" rx="15" fill="url(#pr-shell)" />
      <rect x="248" y="104" width="30" height="58" rx="15" fill="url(#pr-shell)" />
      <rect x="30" y="122" width="14" height="22" rx="7" fill="#55f58a" opacity="0.85" />
      <rect x="256" y="122" width="14" height="22" rx="7" fill="#55f58a" opacity="0.85" />

      {/* head */}
      <rect x="44" y="46" width="212" height="170" rx="72" fill="url(#pr-shell)" />
      <rect x="44" y="46" width="212" height="170" rx="72" fill="url(#pr-shell-shade)" />
      <rect x="44" y="46" width="212" height="170" rx="72" fill="none" stroke="url(#pr-rim)" strokeWidth="2.5" />
      <ellipse cx="108" cy="70" rx="44" ry="12" fill="#fff" opacity="0.7" />

      {/* face */}
      <rect x="66" y="72" width="168" height="120" rx="54" fill="url(#pr-face)" />
      <rect x="66" y="72" width="168" height="120" rx="54" fill="none" stroke="#2b4a3c" strokeWidth="2" />
      <path d="M92 86h116a40 40 0 0 1 22 10H74a40 40 0 0 1 18-10z" fill="url(#pr-gloss)" />

      {/* eyes */}
      <ellipse cx="118" cy="128" rx="22" ry="26" fill="#55f58a" opacity="0.55" filter="url(#pr-glow)" />
      <ellipse cx="182" cy="128" rx="22" ry="26" fill="#55f58a" opacity="0.55" filter="url(#pr-glow)" />
      <ellipse cx="118" cy="128" rx="17" ry="21" fill="url(#pr-eye)" />
      <ellipse cx="182" cy="128" rx="17" ry="21" fill="url(#pr-eye)" />
      <ellipse cx="112" cy="119" rx="5" ry="6.5" fill="#fff" opacity="0.95" />
      <ellipse cx="176" cy="119" rx="5" ry="6.5" fill="#fff" opacity="0.95" />
      <path d="M132 166q18 12 36 0" stroke="#6dff9f" strokeWidth="4.5" strokeLinecap="round" fill="none" />

      {/* neck + body */}
      <rect x="122" y="210" width="56" height="18" rx="8" fill="#9fb3a8" />
      <rect x="80" y="222" width="140" height="92" rx="42" fill="url(#pr-shell)" />
      <rect x="80" y="222" width="140" height="92" rx="42" fill="url(#pr-shell-shade)" />
      <rect x="118" y="244" width="64" height="34" rx="14" fill="url(#pr-face)" />
      <circle cx="138" cy="261" r="5" fill="#6dff9f" />
      <circle cx="162" cy="261" r="5" fill="#6dff9f" opacity="0.55" />

      {/* arms */}
      <rect x="36" y="232" width="56" height="24" rx="12" fill="url(#pr-shell)" transform="rotate(-28 64 244)" />
      <rect x="208" y="232" width="56" height="24" rx="12" fill="url(#pr-shell)" transform="rotate(28 236 244)" />
    </svg>
  )
}

function Folder() {
  return (
    <svg className="projects-folder" viewBox="0 0 280 210">
      <defs>
        <linearGradient id="pf-back" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#22a65c" />
          <stop offset="1" stopColor="#0a4a28" />
        </linearGradient>
        <linearGradient id="pf-front" x1="0" y1="0" x2="0.3" y2="1">
          <stop offset="0" stopColor="#8affb2" />
          <stop offset="0.4" stopColor="#45dd7c" />
          <stop offset="1" stopColor="#14904a" />
        </linearGradient>
        <linearGradient id="pf-paper" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#d6e3dc" />
        </linearGradient>
        <linearGradient id="pf-leaf" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#0d6a37" />
          <stop offset="1" stopColor="#d4ffe2" />
        </linearGradient>
      </defs>
      <path d="M18 38a12 12 0 0 1 12-12h66l20 20h126a12 12 0 0 1 12 12v120a12 12 0 0 1-12 12H30a12 12 0 0 1-12-12z" fill="url(#pf-back)" />
      {/* papers */}
      <g transform="rotate(-6 120 90)">
        <rect x="46" y="36" width="160" height="124" rx="8" fill="url(#pf-paper)" opacity="0.85" />
      </g>
      <rect x="62" y="44" width="168" height="126" rx="8" fill="url(#pf-paper)" />
      <rect x="80" y="62" width="96" height="7" rx="3.5" fill="#9fb4a8" />
      <rect x="80" y="78" width="128" height="6" rx="3" fill="#c8d6cf" />
      <rect x="80" y="92" width="112" height="6" rx="3" fill="#c8d6cf" />
      <rect x="80" y="106" width="74" height="6" rx="3" fill="#c8d6cf" />
      {/* front */}
      <path d="M8 88a12 12 0 0 1 12-12h240a12 12 0 0 1 12 12l-16 98a14 14 0 0 1-14 12H38a14 14 0 0 1-14-12z" fill="url(#pf-front)" />
      <path d="M20 78h240a12 12 0 0 1 11 8H9a12 12 0 0 1 11-8z" fill="#d9ffe6" opacity="0.6" />
      <path
        d="M176 160c-16 1-30 10-34 26 8 1 17-1 23-7 4-4 8-9 11-19-7 6-11 12-15 20 9-2 15-10 15-20z"
        fill="url(#pf-leaf)"
      />
    </svg>
  )
}

/** Research robot with a dimensional Atlas folder, floating panels and leaves. */
export function ProjectsHeroArt() {
  const { t } = useI18n()
  return (
    <div className="projects-art" aria-hidden="true">
      <div className="projects-art-glow" />
      <div className="projects-art-grid" />
      <svg className="projects-orbits" viewBox="0 0 600 400">
        <g fill="none" stroke="#7dffab">
          <ellipse cx="300" cy="230" rx="280" ry="110" strokeOpacity="0.14" transform="rotate(-10 300 230)" />
          <ellipse cx="300" cy="220" rx="220" ry="150" strokeOpacity="0.08" transform="rotate(18 300 220)" />
        </g>
        <g fill="#b9ffd1">
          <circle cx="30" cy="250" r="2.2" opacity="0.8" />
          <circle cx="570" cy="190" r="2" opacity="0.7" />
          <circle cx="160" cy="70" r="1.6" opacity="0.7" />
          <circle cx="470" cy="340" r="2.4" opacity="0.8" />
          <circle cx="90" cy="360" r="1.5" opacity="0.6" />
        </g>
      </svg>

      <div className="projects-search-card">
        <SearchIcon size={16} />
        <span>{t('projects.art')}</span>
      </div>

      <Robot />
      <Folder />

      <FloatingCard icon={<BarChartIcon size={15} />} title="" lines={3} tilt={-6} className="projects-card-a" />
      <FloatingCard icon={<FileTextIcon size={15} />} title="" lines={3} tilt={5} className="projects-card-b" />

      <p className="script-note projects-script">
        {t('projects.scriptLine1')}
        <br />
        {t('projects.scriptLine2')}
        <br />
        {t('projects.scriptLine3')}
        <span className="script-sparkle">✦</span>
      </p>
      <svg className="projects-arrow" viewBox="0 0 80 60">
        <path d="M70 6c-18 10-40 26-62 48" stroke="#55f58a" strokeWidth="2.2" fill="none" strokeLinecap="round" />
        <path d="M8 40l0 14 14 0" stroke="#55f58a" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>

      <Leaf size={44} rotate={-30} className="projects-leaf-a" />
      <Leaf size={36} rotate={150} className="projects-leaf-b" />
      <Leaf size={30} rotate={60} className="projects-leaf-c" />
    </div>
  )
}
