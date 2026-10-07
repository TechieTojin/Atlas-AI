import type { ComponentType, ReactNode } from 'react'

interface IconComponentProps {
  size?: number
  className?: string
}

export type IconComponent = ComponentType<IconComponentProps>

/** Small green pill with an icon and uppercase or title-case label. */
export function EyebrowPill({
  icon: Icon,
  children,
  uppercase = false,
}: {
  icon?: IconComponent
  children: ReactNode
  uppercase?: boolean
}) {
  return (
    <span className={`eyebrow-pill${uppercase ? ' uppercase' : ''}`}>
      {Icon && <Icon size={14} className="eyebrow-icon" />}
      <span>{children}</span>
    </span>
  )
}

/** Circular green icon followed by a label (and optional sub-line). */
export function FeaturePill({
  icon: Icon,
  label,
  detail,
  variant = 'round',
}: {
  icon: IconComponent
  label: string
  detail?: string
  variant?: 'round' | 'square' | 'chip'
}) {
  if (variant === 'chip') {
    return (
      <span className="feature-chip">
        <Icon size={15} className="feature-chip-icon" />
        <span>{label}</span>
      </span>
    )
  }
  return (
    <span className={`feature-pill ${variant}`}>
      <span className="feature-pill-icon">
        <Icon size={variant === 'square' ? 16 : 18} />
      </span>
      <span className="feature-pill-text">
        <span className="feature-pill-label">{label}</span>
        {detail && <span className="feature-pill-detail">{detail}</span>}
      </span>
    </span>
  )
}

export interface PageHeroProps {
  eyebrow: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  features?: ReactNode
  art?: ReactNode
  actions?: ReactNode
  /** Extra class for page-specific sizing. */
  className?: string
}

/** Editorial page header: pill, large serif title, subtitle, feature row, decorative art on the right. */
export function PageHero({ eyebrow, title, subtitle, features, art, actions, className }: PageHeroProps) {
  return (
    <header className={`page-hero${className ? ` ${className}` : ''}`}>
      <div className="page-hero-copy">
        <div className="page-hero-eyebrow">{eyebrow}</div>
        <h1 className="display-title">{title}</h1>
        {subtitle && <p className="page-hero-subtitle">{subtitle}</p>}
        {features && <div className="page-hero-features">{features}</div>}
      </div>
      {actions && <div className="page-hero-actions">{actions}</div>}
      {art && (
        <div className="page-hero-art" aria-hidden="true">
          {art}
        </div>
      )}
    </header>
  )
}
