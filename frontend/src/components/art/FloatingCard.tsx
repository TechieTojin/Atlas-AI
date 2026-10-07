import type { ReactNode } from 'react'

/** Small tilted glass card with an icon, title and placeholder text lines. */
export function FloatingCard({
  icon,
  title,
  lines = 2,
  tilt = 0,
  className,
  style,
}: {
  icon: ReactNode
  title: string
  lines?: number
  tilt?: number
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div
      className={`floating-card${className ? ` ${className}` : ''}`}
      style={{ transform: `rotate(${tilt}deg)`, ...style }}
      aria-hidden="true"
    >
      <span className="floating-card-icon">{icon}</span>
      <span className="floating-card-body">
        <span className="floating-card-title">{title}</span>
        {Array.from({ length: lines }).map((_, index) => (
          <span key={index} className="floating-card-line" style={{ width: `${88 - index * 22}%` }} />
        ))}
      </span>
    </div>
  )
}
