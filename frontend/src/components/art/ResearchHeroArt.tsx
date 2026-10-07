import { BarChartIcon, FileTextIcon, GlobeIcon } from '../icons'
import { FloatingCard } from './FloatingCard'
import { Leaf } from './Leaf'

/** Illuminated globe with network arcs, floating research cards and leaves. */
export function ResearchHeroArt() {
  return (
    <div className="research-art" aria-hidden="true">
      <div className="research-art-glow" />
      <svg className="research-globe" viewBox="0 0 520 520">
        <defs>
          <radialGradient id="globe-body" cx="38%" cy="32%" r="75%">
            <stop offset="0" stopColor="#1d6b42" />
            <stop offset="0.45" stopColor="#0d3a26" />
            <stop offset="1" stopColor="#04110c" />
          </radialGradient>
          <radialGradient id="globe-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0.62" stopColor="#47ff85" stopOpacity="0" />
            <stop offset="0.8" stopColor="#47ff85" stopOpacity="0.22" />
            <stop offset="1" stopColor="#47ff85" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="globe-rim" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#9dffc0" stopOpacity="0.9" />
            <stop offset="0.5" stopColor="#3fe07a" stopOpacity="0.35" />
            <stop offset="1" stopColor="#0c4a2b" stopOpacity="0.2" />
          </linearGradient>
          <radialGradient id="globe-shade" cx="78%" cy="80%" r="80%">
            <stop offset="0.35" stopColor="#000" stopOpacity="0" />
            <stop offset="1" stopColor="#000" stopOpacity="0.7" />
          </radialGradient>
          <radialGradient id="globe-spec" cx="34%" cy="28%" r="40%">
            <stop offset="0" stopColor="#c9ffdc" stopOpacity="0.32" />
            <stop offset="1" stopColor="#c9ffdc" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="globe-atmo" cx="50%" cy="50%" r="50%">
            <stop offset="0.86" stopColor="#5dff97" stopOpacity="0" />
            <stop offset="0.93" stopColor="#5dff97" stopOpacity="0.38" />
            <stop offset="1" stopColor="#5dff97" stopOpacity="0" />
          </radialGradient>
          <clipPath id="globe-clip">
            <circle cx="260" cy="260" r="186" />
          </clipPath>
        </defs>
        <circle cx="260" cy="260" r="258" fill="url(#globe-halo)" />
        <g stroke="#7dffab" fill="none" strokeWidth="1">
          <ellipse cx="260" cy="270" rx="250" ry="84" strokeOpacity="0.16" transform="rotate(-16 260 270)" />
          <ellipse cx="260" cy="250" rx="236" ry="120" strokeOpacity="0.1" transform="rotate(24 260 250)" />
        </g>
        <circle cx="260" cy="260" r="202" fill="url(#globe-atmo)" />
        <circle cx="260" cy="260" r="186" fill="url(#globe-body)" />
        <g clipPath="url(#globe-clip)" opacity="0.9">
          {/* stylised continents */}
          <path
            d="M150 150c22-18 50-24 76-16 14 5 17 22 32 24 20 3 30 24 24 42-7 20-32 22-44 40-9 14-5 34-20 42-18 10-40-2-50-20-10-20-4-40-14-58-6-12-16-22-4-54z"
            fill="#2f9a5d"
            opacity="0.55"
          />
          <path
            d="M300 118c26-4 56 6 74 26 12 14 10 36 2 52-10 20-36 24-50 40-12 14-8 36-24 44-14 6-32-4-36-20-6-26 10-48 8-74-2-22 2-56 26-68z"
            fill="#2f9a5d"
            opacity="0.45"
          />
          <path
            d="M200 330c26-8 56 2 72 22 10 12 8 32-4 44-16 16-44 10-62 22-12 8-28 10-38-2-12-14-2-36 10-50 8-10 10-30 22-36z"
            fill="#2f9a5d"
            opacity="0.5"
          />
          {/* latitude / longitude */}
          <g stroke="#7affa8" strokeOpacity="0.16" fill="none" strokeWidth="1">
            <ellipse cx="260" cy="260" rx="186" ry="60" />
            <ellipse cx="260" cy="260" rx="186" ry="120" />
            <ellipse cx="260" cy="260" rx="60" ry="186" />
            <ellipse cx="260" cy="260" rx="120" ry="186" />
            <ellipse cx="260" cy="260" rx="186" ry="160" />
            <ellipse cx="260" cy="260" rx="160" ry="186" />
            <line x1="74" y1="260" x2="446" y2="260" />
            <line x1="260" y1="74" x2="260" y2="446" />
          </g>
          {/* city lights */}
          <g fill="#c8ffdc">
            {[
              [190, 180],
              [230, 210],
              [300, 170],
              [340, 220],
              [210, 300],
              [270, 350],
              [330, 320],
              [160, 250],
              [360, 270],
              [250, 140],
            ].map(([x, y], index) => (
              <circle key={index} cx={x} cy={y} r={index % 3 === 0 ? 2.4 : 1.6} opacity={0.85} />
            ))}
          </g>
          {/* network arcs */}
          <g stroke="#7dffab" strokeOpacity="0.45" fill="none" strokeWidth="1.1">
            <path d="M190 180Q260 120 340 220" />
            <path d="M230 210Q300 260 330 320" />
            <path d="M160 250Q220 330 270 350" />
            <path d="M300 170Q380 200 360 270" />
          </g>
        </g>
        <circle cx="260" cy="260" r="186" fill="url(#globe-shade)" />
        <circle cx="260" cy="260" r="186" fill="url(#globe-spec)" />
        <circle cx="260" cy="260" r="186" fill="none" stroke="url(#globe-rim)" strokeWidth="2.5" />
        <circle cx="260" cy="260" r="200" fill="none" stroke="#47ff85" strokeOpacity="0.1" strokeWidth="1" />
        {/* light points around the globe */}
        <g fill="#b9ffd1">
          <circle cx="72" cy="140" r="2.2" opacity="0.9" />
          <circle cx="460" cy="120" r="1.8" opacity="0.8" />
          <circle cx="480" cy="330" r="2.6" opacity="0.9" />
          <circle cx="40" cy="330" r="1.6" opacity="0.7" />
          <circle cx="400" cy="470" r="2" opacity="0.8" />
          <circle cx="24" cy="236" r="1.4" opacity="0.6" />
          <circle cx="500" cy="210" r="1.5" opacity="0.7" />
          <circle cx="132" cy="58" r="1.6" opacity="0.7" />
          <circle cx="340" cy="30" r="1.3" opacity="0.6" />
        </g>
        <g stroke="#7dffab" strokeOpacity="0.35" strokeWidth="1" fill="none">
          <path d="M72 140 L120 190" />
          <path d="M460 120 L420 150" />
          <path d="M480 330 L440 320" />
        </g>
      </svg>

      <FloatingCard
        icon={<GlobeIcon size={16} />}
        title="Trusted Sources"
        tilt={-8}
        className="research-card-a"
      />
      <FloatingCard
        icon={<BarChartIcon size={16} />}
        title="Detailed Analysis"
        tilt={6}
        className="research-card-b"
      />
      <FloatingCard
        icon={<FileTextIcon size={16} />}
        title="Structured Report"
        tilt={-5}
        className="research-card-c"
      />

      <Leaf size={64} rotate={-20} className="research-leaf-a" />
      <Leaf size={48} rotate={120} className="research-leaf-b" />
      <Leaf size={40} rotate={200} className="research-leaf-c" />
    </div>
  )
}
