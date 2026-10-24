/**
 * A calm, editorial research motif used behind page heroes: a faint research
 * grid, a few field arcs and a small constellation of connected source nodes —
 * evoking "multi-agent research, grounded in your sources" without mascots,
 * saturated globes or floating labels. Purely decorative.
 */
export function EditorialMotif({ variant = 'a' }: { variant?: 'a' | 'b' | 'c' | 'd' }) {
  // Each surface gets a slightly different node constellation so the heroes are
  // related but not identical. Coordinates live in a 420×520 viewBox.
  const constellations: Record<string, Array<[number, number, number]>> = {
    // [x, y, r] — the first node of each set is the emphasised (filled) node.
    a: [
      [250, 150, 7],
      [150, 110, 4],
      [330, 120, 4],
      [196, 250, 5],
      [320, 250, 4.5],
      [258, 352, 4],
    ],
    b: [
      [262, 170, 7],
      [160, 240, 4.5],
      [350, 210, 4],
      [226, 330, 5],
      [330, 340, 4],
      [150, 120, 3.5],
    ],
    c: [
      [238, 140, 7],
      [330, 220, 4.5],
      [168, 200, 4],
      [288, 318, 5],
      [180, 330, 4],
      [356, 128, 3.5],
    ],
    d: [
      [256, 196, 7],
      [150, 150, 4],
      [346, 160, 4.5],
      [210, 300, 5],
      [330, 312, 4],
      [262, 96, 3.5],
    ],
  }
  const nodes = constellations[variant] ?? constellations.a
  const [hub] = nodes

  return (
    <div className="editorial-motif" aria-hidden="true">
      <div className="editorial-motif-wash" />
      <svg className="editorial-motif-svg" viewBox="0 0 420 520" fill="none" preserveAspectRatio="xMidYMid meet">
        <defs>
          <pattern id={`motif-dots-${variant}`} width="26" height="26" patternUnits="userSpaceOnUse">
            <circle cx="1.4" cy="1.4" r="1.4" fill="var(--accent)" fillOpacity="0.1" />
          </pattern>
          <radialGradient id={`motif-glow-${variant}`} cx="60%" cy="34%" r="60%">
            <stop offset="0" stopColor="var(--accent)" stopOpacity="0.1" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* research grid */}
        <rect x="40" y="20" width="360" height="480" fill={`url(#motif-dots-${variant})`} />
        <circle cx="250" cy="200" r="190" fill={`url(#motif-glow-${variant})`} />

        {/* field arcs — concentric, like a search radius */}
        <g stroke="var(--accent)" fill="none" strokeOpacity="0.16">
          <circle cx={hub[0]} cy={hub[1]} r="86" strokeWidth="1.25" />
          <circle cx={hub[0]} cy={hub[1]} r="140" strokeWidth="1" strokeOpacity="0.1" />
          <circle cx={hub[0]} cy={hub[1]} r="198" strokeWidth="1" strokeOpacity="0.06" />
        </g>

        {/* edges from the hub to each source node */}
        <g stroke="var(--accent)" strokeOpacity="0.28" strokeWidth="1.25">
          {nodes.slice(1).map(([x, y], i) => (
            <line key={i} x1={hub[0]} y1={hub[1]} x2={x} y2={y} />
          ))}
        </g>

        {/* source nodes */}
        <g>
          {nodes.map(([x, y, r], i) =>
            i === 0 ? (
              <g key={i}>
                <circle cx={x} cy={y} r={r + 6} fill="var(--accent)" fillOpacity="0.12" />
                <circle cx={x} cy={y} r={r} fill="var(--accent)" />
              </g>
            ) : (
              <circle
                key={i}
                cx={x}
                cy={y}
                r={r}
                fill="var(--bg-raised)"
                stroke="var(--accent)"
                strokeWidth="1.5"
                strokeOpacity="0.5"
              />
            ),
          )}
        </g>

        {/* a single restrained leaf mark, tucked into the lower-right */}
        <path
          className="editorial-motif-leaf"
          transform="translate(286 392) scale(0.6)"
          d="M352 372c-34 1-58 15-62 44-1 9 2 17 7 22 8-19 21-34 40-46-14 14-25 30-30 48 3 1 7 1 11 1 24-10 37-43 34-69z"
          fill="var(--accent)"
          fillOpacity="0.22"
        />
      </svg>
    </div>
  )
}
