import { useEffect, useState } from 'react'
import { api, type LanguageCapabilities, type OutputFeature } from '../api/client'
import { DEFAULT_LANGUAGE, getLanguage } from './languages'
import { useI18n } from './I18nProvider'

/**
 * Output language: the language Atlas WRITES research in. Distinct from the UI
 * language (what the app's chrome is shown in) and from the language of the
 * sources. The backend decides what the configured models can write; this
 * module only reads that decision.
 */

let cached: Promise<LanguageCapabilities> | null = null

function isCapabilities(value: unknown): value is LanguageCapabilities {
  if (!value || typeof value !== 'object') return false
  const languages = (value as { languages?: unknown }).languages
  return (
    Array.isArray(languages) &&
    languages.every(
      (entry) =>
        !!entry &&
        typeof entry === 'object' &&
        typeof (entry as { code?: unknown }).code === 'string' &&
        typeof (entry as { supported?: unknown }).supported === 'boolean',
    )
  )
}

/**
 * One request per session. A failure, or a payload that is not a capability
 * snapshot, is never cached and never treated as support for anything.
 */
export function loadLanguageCapabilities(): Promise<LanguageCapabilities> {
  if (!cached) {
    cached = api
      .getLanguageCapabilities()
      .then((value) => {
        if (!isCapabilities(value)) throw new Error('Malformed language capabilities.')
        return value
      })
      .catch((error) => {
        cached = null
        throw error
      })
  }
  return cached
}

/** Test hook: forget the cached capability snapshot. */
export function resetLanguageCapabilities(): void {
  cached = null
}

/**
 * The language a new artifact will actually be written in.
 *
 * The stored preference is honoured only when the backend says the routed
 * model supports it. Anything else (unsupported, unknown, or capabilities not
 * loaded) resolves to English, which every model writes. The preference itself
 * is never changed, so it starts working as soon as a capable model exists.
 */
export function resolveOutputLanguage(
  preferred: string,
  capabilities: LanguageCapabilities | null,
  feature: OutputFeature = 'report',
): string {
  if (!capabilities) return DEFAULT_LANGUAGE
  const entry = capabilities.languages.find((language) => language.code === preferred)
  if (!entry) return DEFAULT_LANGUAGE
  // A per-feature verdict, when present, overrides the language verdict.
  const supported = entry.features?.[feature]?.supported ?? entry.supported
  return supported ? preferred : DEFAULT_LANGUAGE
}

/** ``lang`` attribute value for generated content written in ``code``. */
export function artifactLang(code: string | null | undefined): string {
  return getLanguage(code || DEFAULT_LANGUAGE).locale
}

export interface OutputLanguageState {
  /** The user's stored default output language. */
  preferred: string
  /** What new research will be written in right now. */
  effective: string
  /** True when the preference could not be honoured. */
  fellBack: boolean
  /** Model that writes ``effective``, when known. */
  model: string | null
  /** Capabilities could not be loaded (English only until they can). */
  unavailable: boolean
  loading: boolean
}

export function useOutputLanguage(feature: OutputFeature = 'report'): OutputLanguageState {
  const { defaultOutputLanguage } = useI18n()
  const [capabilities, setCapabilities] = useState<LanguageCapabilities | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    loadLanguageCapabilities()
      .then((value) => {
        if (active) setCapabilities(value)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
    return () => {
      active = false
    }
  }, [])

  const effective = resolveOutputLanguage(defaultOutputLanguage, capabilities, feature)
  const model =
    capabilities?.languages.find((language) => language.code === effective)?.model ??
    capabilities?.model ??
    null
  return {
    preferred: defaultOutputLanguage,
    effective,
    fellBack: effective !== defaultOutputLanguage,
    model,
    unavailable: failed,
    loading: !capabilities && !failed,
  }
}
