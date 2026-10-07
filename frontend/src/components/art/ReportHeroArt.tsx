import { BarChartIcon, ShieldCheckIcon } from '../icons'

/**
 * Abstract research visualisation for the report hero.
 *
 * Atlas does not generate topic artwork, so this is a neutral technical
 * composition (grid, orbit rings, node network) with a shield badge and a
 * small analytics card. `label` is real run data (the template name).
 */
export function ReportHeroArt({ label }: { label: string }) {
  return (
    <div className="report-art" aria-hidden="true">
      <svg className="report-art-svg" viewBox="0 0 520 260" preserveAspectRatio="xMidYMid slice">
        <defs>
          <pattern id="report-grid" width="26" height="26" patternUnits="userSpaceOnUse">
            <path d="M26 0H0v26" fill="none" stroke="#55f58a" strokeOpacity="0.08" />
          </pattern>
          <radialGradient id="report-core" cx="45%" cy="40%" r="55%">
            <stop offset="0" stopColor="#f2fff6" />
            <stop offset="0.3" stopColor="#8affb4" />
            <stop offset="0.7" stopColor="#1ea35a" stopOpacity="0.55" />
            <stop offset="1" stopColor="#0c4a2b" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="report-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#55f58a" stopOpacity="0.35" />
            <stop offset="1" stopColor="#55f58a" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width="520" height="260" fill="url(#report-grid)" />
        <ellipse cx="300" cy="140" rx="200" ry="110" fill="url(#report-glow)" />
        {/* orbit rings */}
        <g fill="none" stroke="#55f58a" strokeOpacity="0.25">
          <ellipse cx="300" cy="140" rx="170" ry="54" />
          <ellipse cx="300" cy="140" rx="120" ry="38" strokeOpacity="0.18" />
          <ellipse cx="300" cy="140" rx="210" ry="70" strokeOpacity="0.12" strokeDasharray="3 6" />
        </g>
        {/* focal orb with a connected node network */}
        <g stroke="#7dffab" strokeOpacity="0.4" fill="none" strokeWidth="1.2">
          <path d="M300 140L210 92M300 140L236 196M300 140L380 98M300 140L392 186M210 92L236 196M380 98L392 186M210 92L150 60M392 186L452 214" />
        </g>
        <circle cx="300" cy="140" r="58" fill="url(#report-core)" />
        <circle cx="300" cy="140" r="22" fill="none" stroke="#d4ffe2" strokeOpacity="0.6" />
        <g fill="#0b1f15" stroke="#8affb4" strokeWidth="1.5">
          <circle cx="210" cy="92" r="7" />
          <circle cx="236" cy="196" r="6" />
          <circle cx="380" cy="98" r="6" />
          <circle cx="392" cy="186" r="7" />
        </g>
        <g fill="#8affb4">
          <circle cx="210" cy="92" r="2.5" />
          <circle cx="392" cy="186" r="2.5" />
        </g>
        {/* nodes */}
        <g fill="#b9ffd1">
          <circle cx="90" cy="70" r="2.5" />
          <circle cx="140" cy="200" r="2" />
          <circle cx="440" cy="50" r="2.5" />
          <circle cx="470" cy="210" r="2" />
          <circle cx="60" cy="150" r="1.6" />
        </g>
        <g stroke="#55f58a" strokeOpacity="0.3" fill="none">
          <path d="M90 70L160 110" />
          <path d="M140 200L200 160" />
          <path d="M440 50L390 90" />
          <path d="M470 210L410 180" />
        </g>
      </svg>

      <span className="report-art-shield">
        <ShieldCheckIcon size={30} />
      </span>

      <div className="report-art-card">
        <span className="report-art-card-icon">
          <BarChartIcon size={16} />
        </span>
        <span className="report-art-card-text">
          <span className="report-art-card-title">{label}</span>
          <span className="report-art-card-sub">Report</span>
        </span>
      </div>
    </div>
  )
}
