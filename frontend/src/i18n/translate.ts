import { DEFAULT_LANGUAGE, getLanguage } from './languages'
import { en, type MessageKey, type MessageTree, type PartialMessages, type PluralForms } from './messages/en'

export type TranslateParams = Record<string, string | number>
export type Translate = (key: MessageKey, params?: TranslateParams) => string

type MessageValue = string | PluralForms | MessageTree | undefined

function lookup(tree: unknown, key: string): MessageValue {
  let node: unknown = tree
  for (const part of key.split('.')) {
    if (!node || typeof node !== 'object') return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return node as MessageValue
}

function isPluralForms(value: MessageValue): value is PluralForms {
  return !!value && typeof value === 'object' && typeof (value as PluralForms).other === 'string'
}

const reported = new Set<string>()

/** Dev-only, once per key: missing translations are visible but never break rendering. */
function reportMissing(language: string, key: string, missingEverywhere: boolean) {
  if (!import.meta.env.DEV) return
  const id = `${language}:${key}`
  if (reported.has(id)) return
  reported.add(id)
  console.warn(
    missingEverywhere
      ? `[i18n] Unknown message key "${key}".`
      : `[i18n] Missing "${language}" translation for "${key}"; using English.`,
  )
}

function interpolate(template: string, params: TranslateParams | undefined, numbers: Intl.NumberFormat) {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name]
    if (value === undefined) return match
    return typeof value === 'number' ? numbers.format(value) : value
  })
}

/**
 * Builds `t(key, params)` for one language. Lookup order: the language's
 * dictionary, then English, then the key itself. Plural messages pick a form
 * with the rules of whichever language supplied the text.
 */
export function createTranslator(language: string, messages: PartialMessages): Translate {
  const locale = getLanguage(language).locale
  const numbers = new Intl.NumberFormat(locale)
  const plurals = new Intl.PluralRules(locale)
  const englishPlurals = new Intl.PluralRules(getLanguage(DEFAULT_LANGUAGE).locale)

  return (key, params) => {
    let value = language === DEFAULT_LANGUAGE ? undefined : lookup(messages, key)
    let rules = plurals
    if (value === undefined || (typeof value === 'object' && !isPluralForms(value))) {
      value = lookup(en, key)
      rules = englishPlurals
      if (value === undefined) {
        reportMissing(language, key, true)
        return key
      }
      if (language !== DEFAULT_LANGUAGE) reportMissing(language, key, false)
    }
    if (isPluralForms(value)) {
      const count = typeof params?.count === 'number' ? params.count : 0
      return interpolate(value[rules.select(count)] ?? value.other, params, numbers)
    }
    if (typeof value === 'string') return interpolate(value, params, numbers)
    reportMissing(language, key, true)
    return key
  }
}
