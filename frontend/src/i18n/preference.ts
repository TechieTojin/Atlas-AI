import { DEFAULT_LANGUAGE, isSupportedLanguage } from './languages'

/**
 * Stored language preference. UI language and the default language for new
 * generated content are kept distinct so they can be separated later; in V1
 * choosing a language sets both. Nothing sends defaultOutputLanguage to the
 * backend yet.
 */
export interface LanguagePreference {
  version: 1
  uiLanguage: string
  defaultOutputLanguage: string
}

export const PREFERENCE_STORAGE_KEY = 'atlas.language-preference'
export const PREFERENCE_VERSION = 1

/**
 * - `valid`: a usable stored choice; no onboarding.
 * - `missing`: nothing stored yet (first launch); show onboarding.
 * - `invalid`: something stored but unusable (malformed, unsupported code);
 *   fall back to the default and ask again, which overwrites the bad value.
 * - `unavailable`: storage cannot be read at all; fall back silently, since
 *   asking would repeat on every load with no way to remember the answer.
 */
export type PreferenceStatus = 'valid' | 'missing' | 'invalid' | 'unavailable'

export interface PreferenceReadResult {
  status: PreferenceStatus
  preference: LanguagePreference
}

export function makePreference(language: string): LanguagePreference {
  const code = isSupportedLanguage(language) ? language : DEFAULT_LANGUAGE
  return { version: PREFERENCE_VERSION, uiLanguage: code, defaultOutputLanguage: code }
}

function storage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

/** Accepts any schema version as long as the fields this version needs validate. */
export function parsePreference(raw: string): LanguagePreference | null {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (!isSupportedLanguage(record.uiLanguage)) return null
  const output = isSupportedLanguage(record.defaultOutputLanguage)
    ? record.defaultOutputLanguage
    : record.uiLanguage
  return { version: PREFERENCE_VERSION, uiLanguage: record.uiLanguage, defaultOutputLanguage: output }
}

export function readPreference(): PreferenceReadResult {
  const fallback = makePreference(DEFAULT_LANGUAGE)
  const store = storage()
  if (!store) return { status: 'unavailable', preference: fallback }
  let raw: string | null
  try {
    raw = store.getItem(PREFERENCE_STORAGE_KEY)
  } catch {
    return { status: 'unavailable', preference: fallback }
  }
  if (raw === null) return { status: 'missing', preference: fallback }
  const parsed = parsePreference(raw)
  return parsed ? { status: 'valid', preference: parsed } : { status: 'invalid', preference: fallback }
}

/** Returns false when the preference could not be persisted (it still applies in memory). */
export function writePreference(preference: LanguagePreference): boolean {
  const store = storage()
  if (!store) return false
  try {
    store.setItem(PREFERENCE_STORAGE_KEY, JSON.stringify(preference))
    return true
  } catch {
    return false
  }
}
