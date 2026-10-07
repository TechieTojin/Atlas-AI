import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { applyDocumentLanguage } from './document'
import { createFormatters, type LocaleFormatters } from './format'
import {
  DEFAULT_LANGUAGE,
  formattingLocale,
  getLanguage,
  isSupportedLanguage,
  matchLanguage,
  type LanguageDefinition,
} from './languages'
import { loadMessages } from './loadMessages'
import { en, type PartialMessages } from './messages/en'
import {
  makePreference,
  readPreference,
  writePreference,
  type LanguagePreference,
  type PreferenceStatus,
} from './preference'
import { setActiveTranslator } from './labels'
import { createTranslator, type Translate } from './translate'

export interface I18nInitialState {
  status: PreferenceStatus
  preference: LanguagePreference
  messages: PartialMessages
}

export interface I18nContextValue {
  /** Registry entry for the UI language. */
  language: LanguageDefinition
  uiLanguage: string
  /** Default language for future generated content. Not sent to the backend yet. */
  defaultOutputLanguage: string
  t: Translate
  format: LocaleFormatters
  /** True until a usable preference exists (first launch or unreadable value). */
  needsOnboarding: boolean
  /** Language to preselect during onboarding. */
  suggestedLanguage: string
  setLanguage: (code: string) => Promise<void>
  completeOnboarding: (code: string) => Promise<void>
}

const ENGLISH: I18nInitialState = {
  status: 'valid',
  preference: makePreference(DEFAULT_LANGUAGE),
  messages: en,
}

/** Reads and applies the stored preference before React renders, so the first paint is already correct. */
export async function bootstrapI18n(): Promise<I18nInitialState> {
  const { status, preference } = readPreference()
  applyDocumentLanguage(preference.uiLanguage)
  const messages = await loadMessages(preference.uiLanguage)
  return { status, preference, messages }
}

function suggestLanguage(initial: I18nInitialState): string {
  if (initial.status !== 'missing') return initial.preference.uiLanguage
  const browser = typeof navigator !== 'undefined' ? navigator.languages : undefined
  return matchLanguage(browser) ?? DEFAULT_LANGUAGE
}

function buildValue(
  preference: LanguagePreference,
  messages: PartialMessages,
  extras: Pick<I18nContextValue, 'needsOnboarding' | 'suggestedLanguage' | 'setLanguage' | 'completeOnboarding'>,
): I18nContextValue {
  const language = getLanguage(preference.uiLanguage)
  return {
    language,
    uiLanguage: preference.uiLanguage,
    defaultOutputLanguage: preference.defaultOutputLanguage,
    t: createTranslator(language.code, messages),
    format: createFormatters(formattingLocale(language.code)),
    ...extras,
  }
}

const noop = async () => {}

// Without a provider (e.g. isolated component tests) everything renders in English.
const I18nContext = createContext<I18nContextValue>(
  buildValue(ENGLISH.preference, ENGLISH.messages, {
    needsOnboarding: false,
    suggestedLanguage: DEFAULT_LANGUAGE,
    setLanguage: noop,
    completeOnboarding: noop,
  }),
)

export function I18nProvider({ initial = ENGLISH, children }: { initial?: I18nInitialState; children: ReactNode }) {
  const [state, setState] = useState({ preference: initial.preference, messages: initial.messages })
  const [needsOnboarding, setNeedsOnboarding] = useState(
    initial.status === 'missing' || initial.status === 'invalid',
  )
  const [suggestedLanguage] = useState(() => suggestLanguage(initial))
  const latestRequest = useRef(0)

  const setLanguage = useCallback(async (code: string) => {
    const next = isSupportedLanguage(code) ? code : DEFAULT_LANGUAGE
    const request = ++latestRequest.current
    const messages = await loadMessages(next)
    if (request !== latestRequest.current) return // a newer choice won
    // V1: one choice sets both the UI language and the default output language.
    const preference = makePreference(next)
    writePreference(preference)
    applyDocumentLanguage(next)
    setState({ preference, messages })
  }, [])

  const completeOnboarding = useCallback(
    async (code: string) => {
      await setLanguage(code)
      setNeedsOnboarding(false)
    },
    [setLanguage],
  )

  const value = useMemo(() => {
    const next = buildValue(state.preference, state.messages, {
      needsOnboarding,
      suggestedLanguage,
      setLanguage,
      completeOnboarding,
    })
    // Errors raised outside React (the API client) are worded in the same language.
    setActiveTranslator(next.t)
    return next
  }, [state, needsOnboarding, suggestedLanguage, setLanguage, completeOnboarding])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext)
}
