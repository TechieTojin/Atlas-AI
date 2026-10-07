import type { FollowUpKind, QualityTier, RunMode, RunStatus } from '../types'
import type { LocaleFormatters } from './format'
import { DEFAULT_LANGUAGE } from './languages'
import type { MessageKey } from './messages/en'
import { createTranslator, type Translate } from './translate'
import { en } from './messages/en'

/**
 * Display labels for machine values the backend returns. The stored/API value
 * never changes; only what the user reads does. Unknown values fall back to
 * the raw value (or the backend's own text) rather than guessing.
 */

const TEMPLATE_IDS = [
  'STANDARD',
  'ACADEMIC',
  'TECHNICAL',
  'EXECUTIVE',
  'LITERATURE_REVIEW',
  'COMPARISON',
  'CUSTOM',
] as const
type KnownTemplate = (typeof TEMPLATE_IDS)[number]

function isKnownTemplate(id: string): id is KnownTemplate {
  return (TEMPLATE_IDS as readonly string[]).includes(id)
}

/** "LITERATURE_REVIEW" → "Literature Review"; how unknown ids have always been shown. */
function titleCase(id: string): string {
  return id
    .toLowerCase()
    .split('_')
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(' ')
}

/** Template display name; blank templates read as Standard. `fallback` is the backend's own name. */
export function templateName(t: Translate, template: string | undefined | null, fallback?: string): string {
  const id = template || 'STANDARD'
  return isKnownTemplate(id) ? t(`templates.${id}.name`) : (fallback ?? titleCase(id))
}

/**
 * A template from the backend catalog. In English the backend's own name and
 * description are shown verbatim, exactly as before; other languages use the
 * dictionary entry for a known id.
 */
export function templateEntryName(t: Translate, language: string, template: { id: string; name: string }): string {
  return language === DEFAULT_LANGUAGE ? template.name : templateName(t, template.id, template.name)
}

export function templateDescription(
  t: Translate,
  language: string,
  template: { id: string; description: string },
  customMax: number,
): string {
  return language !== DEFAULT_LANGUAGE && isKnownTemplate(template.id)
    ? t(`templates.${template.id}.description`, { max: String(customMax) })
    : template.description
}

export function statusLabel(t: Translate, status: RunStatus): string {
  return t(`status.${status}`)
}

export function modeBadge(t: Translate, mode: RunMode): string {
  return mode === 'FAST' || mode === 'DEEP' ? t(`modes.${mode}.badge`) : mode
}

export function tierLabel(t: Translate, tier: QualityTier | string): string {
  return tier === 'high' || tier === 'medium' || tier === 'low' || tier === 'unknown'
    ? t(`quality.tier.${tier}`)
    : tier
}

const CATEGORY_KEYS: Record<string, MessageKey> = {
  'peer-reviewed / academic': 'quality.category.academic',
  'standards organization': 'quality.category.standards',
  'research institution': 'quality.category.researchInstitution',
  government: 'quality.category.government',
  university: 'quality.category.university',
  'reputable technical publication': 'quality.category.technicalPublication',
  'mainstream publication': 'quality.category.mainstream',
  'secondary informational source': 'quality.category.secondary',
  'community / user-generated': 'quality.category.community',
  'official organization': 'quality.category.official',
  unknown: 'quality.category.unknown',
}

/** Source-quality category codes from the backend's classifier. */
export function qualityCategoryLabel(t: Translate, category: string): string {
  const key = CATEGORY_KEYS[category]
  return key ? t(key) : category
}

export function followUpKindLabel(t: Translate, kind: FollowUpKind): string {
  return kind === 'RESEARCH' ? t('followUp.kind.RESEARCH') : t('followUp.kind.ANALYTICAL')
}

/** "5m ago" in lists; "just now" for the first 45 seconds. */
export function agoLabel(t: Translate, format: LocaleFormatters, value: string): string {
  return format.ago(value) ?? t('time.justNow')
}

// Code outside React (the API client) reads the active translator from here.
let active: Translate = createTranslator('en', en)

export function setActiveTranslator(t: Translate): void {
  active = t
}

export function activeTranslator(): Translate {
  return active
}
