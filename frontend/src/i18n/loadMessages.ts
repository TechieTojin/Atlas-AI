import { DEFAULT_LANGUAGE, isSupportedLanguage } from './languages'
import { en, type PartialMessages } from './messages/en'

// Non-English dictionaries become separate lazily loaded chunks; the file
// name is the language code, so no second list of languages exists.
const dictionaries = import.meta.glob<{ default: PartialMessages }>([
  './messages/*.ts',
  '!./messages/en.ts',
])

const cache = new Map<string, PartialMessages>([[DEFAULT_LANGUAGE, en]])

/** Never rejects: an unknown language or failed chunk yields {}, so every key falls back to English. */
export async function loadMessages(language: string): Promise<PartialMessages> {
  const cached = cache.get(language)
  if (cached) return cached
  const loader = isSupportedLanguage(language) ? dictionaries[`./messages/${language}.ts`] : undefined
  if (!loader) {
    if (import.meta.env.DEV) console.warn(`[i18n] No dictionary for "${language}"; using English.`)
    return {}
  }
  try {
    const messages = (await loader()).default
    cache.set(language, messages)
    return messages
  } catch {
    return {}
  }
}

/** Synchronous access for languages already loaded (used to avoid a render gap). */
export function cachedMessages(language: string): PartialMessages | undefined {
  return cache.get(language)
}
