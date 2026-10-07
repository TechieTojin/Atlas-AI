import { getLanguage } from './languages'

/** Mirrors the UI language onto <html lang dir> (screen readers, fonts, future RTL). */
export function applyDocumentLanguage(language: string): void {
  const definition = getLanguage(language)
  const root = document.documentElement
  root.lang = definition.locale
  root.dir = definition.dir
}
