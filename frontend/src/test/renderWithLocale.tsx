import { render, type RenderResult } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import {
  applyDocumentLanguage,
  createTranslator,
  I18nProvider,
  loadMessages,
  type I18nInitialState,
  type Translate,
} from '../i18n'
import { makePreference } from '../i18n/preference'

/** Provider state for a stored, valid preference in `language`. */
export async function localeState(language: string): Promise<I18nInitialState> {
  return { status: 'valid', preference: makePreference(language), messages: await loadMessages(language) }
}

/** The same translator the app uses, for computing expected text from the dictionaries. */
export async function translatorFor(language: string): Promise<Translate> {
  return createTranslator(language, await loadMessages(language))
}

export interface LocaleRenderOptions {
  language?: string
  /** Initial URL. */
  route?: string
  /** Route pattern the element is mounted at; defaults to rendering it directly. */
  path?: string
}

/**
 * Renders `ui` inside the i18n provider and a router, as the app does after
 * bootstrapping a stored preference. English stays the default; tests opt in
 * to another locale explicitly.
 */
export async function renderWithLocale(
  ui: ReactElement,
  { language = 'en', route = '/', path }: LocaleRenderOptions = {},
): Promise<RenderResult & { t: Translate }> {
  const initial = await localeState(language)
  applyDocumentLanguage(language)
  const result = render(
    <I18nProvider initial={initial}>
      <MemoryRouter initialEntries={[route]}>
        {path ? (
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        ) : (
          ui
        )}
      </MemoryRouter>
    </I18nProvider>,
  )
  return { ...result, t: createTranslator(language, initial.messages) }
}
