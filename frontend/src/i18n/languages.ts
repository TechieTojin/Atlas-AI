/**
 * The single source of truth for languages Atlas can display.
 *
 * Adding a language = one entry here + one dictionary file. Nothing else in
 * the app enumerates languages; everything derives from LANGUAGES.
 */

export type TextDirection = 'ltr' | 'rtl'

export interface LanguageDefinition {
  /** Stable code persisted in preferences (and, later, on runs). */
  code: string
  /** Name in the language itself, shown in selectors. */
  nativeName: string
  /** English name, for logs, tooling and accessible hints. */
  englishName: string
  /** BCP 47 locale passed to Intl formatters and the html lang attribute. */
  locale: string
  dir: TextDirection
  /** ISO 15924 script code; lets later phases pick script-specific fonts. */
  script: string
}

export const DEFAULT_LANGUAGE = 'en'

export const LANGUAGES: readonly LanguageDefinition[] = [
  { code: 'en', nativeName: 'English', englishName: 'English', locale: 'en', dir: 'ltr', script: 'Latn' },
  { code: 'ml', nativeName: 'മലയാളം', englishName: 'Malayalam', locale: 'ml', dir: 'ltr', script: 'Mlym' },
  { code: 'hi', nativeName: 'हिन्दी', englishName: 'Hindi', locale: 'hi', dir: 'ltr', script: 'Deva' },
  { code: 'es', nativeName: 'Español', englishName: 'Spanish', locale: 'es', dir: 'ltr', script: 'Latn' },
  { code: 'fr', nativeName: 'Français', englishName: 'French', locale: 'fr', dir: 'ltr', script: 'Latn' },
  { code: 'de', nativeName: 'Deutsch', englishName: 'German', locale: 'de', dir: 'ltr', script: 'Latn' },
]

const BY_CODE = new Map(LANGUAGES.map((language) => [language.code, language]))

export function isSupportedLanguage(code: unknown): code is string {
  return typeof code === 'string' && BY_CODE.has(code)
}

/** Registry entry for `code`, falling back to the default language. */
export function getLanguage(code: string | null | undefined): LanguageDefinition {
  return (code && BY_CODE.get(code)) || (BY_CODE.get(DEFAULT_LANGUAGE) as LanguageDefinition)
}

/** Best supported match for browser locales like "ml-IN" or "fr-CA", if any. */
export function matchLanguage(locales: readonly string[] | undefined): string | null {
  for (const locale of locales ?? []) {
    const base = locale.toLowerCase().split('-')[0]
    if (isSupportedLanguage(base)) return base
  }
  return null
}

/**
 * Locale for dates and numbers. The UI language picks the words; the browser's
 * own regional variant of that language (en-GB, en-IN, es-MX…) keeps the
 * date and number conventions the user is used to. Falls back to the registry.
 */
export function formattingLocale(code: string, browserLocales?: readonly string[]): string {
  const language = getLanguage(code)
  const locales =
    browserLocales ?? (typeof navigator !== 'undefined' ? navigator.languages : undefined) ?? []
  for (const locale of locales) {
    if (locale.toLowerCase().split('-')[0] !== language.code) continue
    try {
      return Intl.DateTimeFormat.supportedLocalesOf([locale]).length > 0 ? locale : language.locale
    } catch {
      return language.locale
    }
  }
  return language.locale
}
