import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyDocumentLanguage } from './document'
import { createFormatters } from './format'
import { bootstrapI18n } from './I18nProvider'
import {
  DEFAULT_LANGUAGE,
  formattingLocale,
  getLanguage,
  isSupportedLanguage,
  LANGUAGES,
  matchLanguage,
} from './languages'
import { loadMessages } from './loadMessages'
import { en } from './messages/en'
import {
  makePreference,
  parsePreference,
  PREFERENCE_STORAGE_KEY,
  readPreference,
  writePreference,
} from './preference'
import { createTranslator } from './translate'

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.lang = 'en'
  document.documentElement.dir = 'ltr'
})

afterEach(() => {
  window.localStorage.clear()
})

describe('language registry', () => {
  it('lists each V1 language once with locale, direction and native name', () => {
    expect(LANGUAGES.map((language) => language.code)).toEqual(['en', 'ml', 'hi', 'es', 'fr', 'de'])
    expect(new Set(LANGUAGES.map((language) => language.code)).size).toBe(LANGUAGES.length)
    expect(getLanguage('ml')).toMatchObject({ nativeName: 'മലയാളം', locale: 'ml', dir: 'ltr', script: 'Mlym' })
    expect(getLanguage('hi').nativeName).toBe('हिन्दी')
    for (const language of LANGUAGES) expect(['ltr', 'rtl']).toContain(language.dir)
  })

  it('falls back to English for unknown codes and matches browser locales', () => {
    expect(DEFAULT_LANGUAGE).toBe('en')
    expect(getLanguage('xx').code).toBe('en')
    expect(getLanguage(null).code).toBe('en')
    expect(isSupportedLanguage('fr')).toBe(true)
    expect(isSupportedLanguage('FR')).toBe(false)
    expect(isSupportedLanguage(42)).toBe(false)
    expect(matchLanguage(['ta-IN', 'ml-IN', 'en'])).toBe('ml')
    expect(matchLanguage(['pt-BR'])).toBeNull()
  })

  it('formats with the regional browser variant of the UI language only', () => {
    expect(formattingLocale('en', ['en-IN', 'ml-IN'])).toBe('en-IN')
    expect(formattingLocale('ml', ['en-IN', 'ml-IN'])).toBe('ml-IN')
    // A regional variant of a different language never leaks into formatting.
    expect(formattingLocale('de', ['en-GB'])).toBe('de')
    expect(formattingLocale('fr', [])).toBe('fr')
    expect(createFormatters('en-GB').date(Date.UTC(2026, 9, 2, 12), { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })).toBe('2 Oct 2026')
    expect(createFormatters('fr-CA').ago(Date.now() - 2 * 86_400_000)).toMatch(/^il y a 2\sj/)
    // Compact list times keep the language's own wording in a regional variant.
    expect(createFormatters('en-IN').ago(Date.now() - 2 * 86_400_000)).toBe('2d ago')
  })
})

describe('language preference storage', () => {
  it('reports a first launch when nothing is stored', () => {
    expect(readPreference()).toEqual({ status: 'missing', preference: makePreference('en') })
  })

  it('reads a valid stored preference', () => {
    writePreference(makePreference('ml'))
    expect(readPreference()).toEqual({
      status: 'valid',
      preference: { version: 1, uiLanguage: 'ml', defaultOutputLanguage: 'ml' },
    })
    expect(JSON.parse(window.localStorage.getItem(PREFERENCE_STORAGE_KEY) ?? '')).toEqual({
      version: 1,
      uiLanguage: 'ml',
      defaultOutputLanguage: 'ml',
    })
  })

  it.each([
    ['malformed JSON', '{not json'],
    ['unsupported language', JSON.stringify({ version: 1, uiLanguage: 'xx', defaultOutputLanguage: 'xx' })],
    ['wrong type', JSON.stringify(['ml'])],
    ['null', 'null'],
  ])('treats %s as invalid and falls back to English', (_label, raw) => {
    window.localStorage.setItem(PREFERENCE_STORAGE_KEY, raw)
    expect(readPreference()).toEqual({ status: 'invalid', preference: makePreference('en') })
  })

  it('accepts a future schema version whose required fields still validate', () => {
    window.localStorage.setItem(
      PREFERENCE_STORAGE_KEY,
      JSON.stringify({ version: 3, uiLanguage: 'hi', defaultOutputLanguage: 'en', extra: true }),
    )
    expect(readPreference().preference).toEqual({ version: 1, uiLanguage: 'hi', defaultOutputLanguage: 'en' })
  })

  it('repairs an unsupported output language from the UI language', () => {
    expect(parsePreference(JSON.stringify({ uiLanguage: 'es', defaultOutputLanguage: 'zz' }))).toEqual({
      version: 1,
      uiLanguage: 'es',
      defaultOutputLanguage: 'es',
    })
  })

  it('keeps V1 UI and output language in sync and rejects unknown codes', () => {
    expect(makePreference('de')).toEqual({ version: 1, uiLanguage: 'de', defaultOutputLanguage: 'de' })
    expect(makePreference('zz')).toEqual(makePreference('en'))
  })

  it('reports unavailable storage without throwing', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(readPreference()).toEqual({ status: 'unavailable', preference: makePreference('en') })
    expect(writePreference(makePreference('fr'))).toBe(false)
  })
})

describe('translator', () => {
  it('uses the English source dictionary by default', () => {
    const t = createTranslator('en', en)
    expect(t('nav.projects')).toBe('Projects')
    expect(t('language.current', { name: 'English' })).toBe('Language: English')
  })

  it('returns translated strings for other languages', async () => {
    expect(createTranslator('ml', await loadMessages('ml'))('nav.research')).toBe('ഗവേഷണം')
    expect(createTranslator('hi', await loadMessages('hi'))('onboarding.continue')).toBe('जारी रखें')
    expect(createTranslator('fr', await loadMessages('fr'))('sidebar.history')).toBe('Historique')
  })

  it('falls back to English for a missing translation and warns once in development', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const t = createTranslator('es', { nav: { research: 'Investigación' } })
    expect(t('nav.research')).toBe('Investigación')
    expect(t('nav.documents')).toBe('Documents')
    expect(t('nav.documents')).toBe('Documents')
    expect(warn).toHaveBeenCalledTimes(1)
    expect(warn.mock.calls[0][0]).toContain('"es" translation for "nav.documents"')
  })

  it('returns the key itself for an unknown key instead of crashing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const t = createTranslator('en', en)
    expect(t('nav.nonexistent' as never)).toBe('nav.nonexistent')
    expect(warn).toHaveBeenCalled()
  })

  it('selects plural forms with the language rules and formats counts in its locale', async () => {
    const english = createTranslator('en', en)
    expect(english('sidebar.compareRuns', { count: 1 })).toBe('Compare 1 run')
    expect(english('sidebar.compareRuns', { count: 3 })).toBe('Compare 3 runs')
    const french = createTranslator('fr', await loadMessages('fr'))
    // French treats 0 and 1 as singular.
    expect(french('sidebar.compareRuns', { count: 0 })).toBe('Comparer 0 exécution')
    const german = createTranslator('de', await loadMessages('de'))
    expect(german('sidebar.compareRuns', { count: 1000 })).toBe('1.000 Läufe vergleichen')
  })

  it('loads dictionaries lazily and returns an empty dictionary for unknown languages', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect((await loadMessages('de')).nav?.projects).toBe('Projekte')
    expect(await loadMessages('xx')).toEqual({})
  })
})

describe('locale formatters', () => {
  const date = new Date(Date.UTC(2026, 9, 7, 12, 30))

  it('formats numbers and percentages in the selected locale', () => {
    expect(createFormatters('en').number(1234567.5)).toBe('1,234,567.5')
    expect(createFormatters('de').number(1234567.5)).toBe('1.234.567,5')
    expect(createFormatters('hi').number(1234567)).toBe('12,34,567')
    expect(createFormatters('en').percent(0.42)).toBe('42%')
    // French puts a (narrow) no-break space before %; ICU versions differ on which.
    expect(createFormatters('fr').percent(0.42)).toMatch(/^42[  ]%$/)
  })

  it('formats dates in the selected locale', () => {
    const options = { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' } as const
    expect(createFormatters('en').date(date, options)).toBe('October 7, 2026')
    expect(createFormatters('de').date(date, options)).toBe('7. Oktober 2026')
    expect(createFormatters('es').date(date, options)).toBe('7 de octubre de 2026')
    expect(createFormatters('en').date('not a date')).toBe('')
  })

  it('formats relative time and plural categories', () => {
    const now = date.getTime()
    const threeDaysAgo = now - 3 * 24 * 60 * 60 * 1000
    expect(createFormatters('en').relativeTime(threeDaysAgo, now)).toBe('3 days ago')
    expect(createFormatters('es').relativeTime(threeDaysAgo, now)).toBe('hace 3 días')
    // numeric: 'auto' prefers idiomatic words where the locale has them.
    expect(createFormatters('en').relativeTime(now - 24 * 60 * 60 * 1000, now)).toBe('yesterday')
    expect(createFormatters('de').relativeTime(now - 3 * 60 * 60 * 1000, now)).toBe('vor 3 Stunden')
    expect(createFormatters('en').relativeTime(now, now)).toBe('now')
    expect(createFormatters('en').plural(1)).toBe('one')
    expect(createFormatters('fr').plural(0)).toBe('one')
    expect(createFormatters('en').plural(0)).toBe('other')
  })
})

describe('document language', () => {
  it('sets lang and dir from the registry and falls back to English', () => {
    applyDocumentLanguage('hi')
    expect(document.documentElement.lang).toBe('hi')
    expect(document.documentElement.dir).toBe('ltr')
    applyDocumentLanguage('unknown')
    expect(document.documentElement.lang).toBe('en')
  })

  it('bootstraps from the stored preference before rendering', async () => {
    writePreference(makePreference('ml'))
    const initial = await bootstrapI18n()
    expect(initial.status).toBe('valid')
    expect(initial.preference.uiLanguage).toBe('ml')
    expect(initial.messages.nav?.research).toBe('ഗവേഷണം')
    expect(document.documentElement.lang).toBe('ml')
  })

  it('bootstraps English and flags onboarding when the preference is corrupted', async () => {
    window.localStorage.setItem(PREFERENCE_STORAGE_KEY, '{oops')
    const initial = await bootstrapI18n()
    expect(initial.status).toBe('invalid')
    expect(initial.preference.uiLanguage).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })
})
