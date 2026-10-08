import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { LanguageCapabilities } from '../api/client'
import { FollowUpPanel } from '../components/FollowUpPanel'
import { ComparisonPage } from '../pages/ComparisonPage'
import { ResearchPage } from '../pages/ResearchPage'
import { makeComparison, makeFollowUp, makeRun, makeRunSummary, makeSource, TEMPLATE_FIXTURES } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { renderWithLocale } from '../test/renderWithLocale'
import { languageName } from './languages'
import { loadMessages } from './loadMessages'
import { resetLanguageCapabilities, resolveOutputLanguage } from './outputLanguage'
import { makePreference, PREFERENCE_STORAGE_KEY, writePreference } from './preference'

function capabilities(supported: string[]): LanguageCapabilities {
  return {
    default_output_language: 'en',
    model: 'qwen3:4b',
    languages: ['en', 'ml', 'hi', 'es', 'fr', 'de'].map((code) => ({
      code,
      english_name: code,
      native_name: code,
      model: 'qwen3:4b',
      status: supported.includes(code) ? 'supported' : 'unsupported',
      supported: supported.includes(code),
      reason: supported.includes(code) ? '' : 'Not validated.',
    })),
  }
}

/** Research-page backend; `caps` undefined means the capability endpoint fails. */
function researchBackend(caps: LanguageCapabilities | 'malformed' | undefined) {
  return installFetchMock((url, init) => {
    if (url === '/api/capabilities/languages') {
      if (caps === undefined) return { status: 503, body: { detail: 'down' } }
      return { body: caps === 'malformed' ? { languages: 'nope' } : caps }
    }
    if (url === '/api/templates') return { body: { templates: TEMPLATE_FIXTURES } }
    if (url === '/api/documents') return { body: { documents: [] } }
    if (url === '/api/runs' && init?.method === 'POST') return { status: 201, body: makeRun({ id: 'new-run' }) }
    return undefined
  })
}

async function submitResearch(t: (key: never) => string) {
  await userEvent.type(screen.getByLabelText(t('queryForm.questionLabel' as never)), 'solar growth')
  await userEvent.click(screen.getByRole('button', { name: new RegExp(t('queryForm.start' as never)) }))
}

function postedLanguage(mock: ReturnType<typeof installFetchMock>) {
  const post = mock.mock.calls.find(([, init]) => init?.method === 'POST')
  return (requestBody(post?.[1]) as { output_language?: string }).output_language
}

beforeAll(async () => {
  await Promise.all(['ml', 'hi', 'es', 'fr', 'de'].map((language) => loadMessages(language)))
})

beforeEach(() => {
  window.localStorage.clear()
  resetLanguageCapabilities()
  MockEventSource.reset()
  vi.stubGlobal('EventSource', MockEventSource)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('languageName', () => {
  it('names languages in the UI language for use inside sentences', () => {
    expect(languageName('en', 'de')).toBe('Englisch')
    expect(languageName('en', 'fr')).toBe('anglais')
    expect(languageName('en', 'en')).toBe('English')
    expect(languageName('es', 'es')).toBe('español')
  })
})

describe('resolveOutputLanguage', () => {
  it('honours only supported preferences and falls back to English otherwise', () => {
    expect(resolveOutputLanguage('es', capabilities(['en', 'es']))).toBe('es')
    expect(resolveOutputLanguage('ml', capabilities(['en']))).toBe('en')
    expect(resolveOutputLanguage('xx', capabilities(['en']))).toBe('en')
    // No capability data never enables anything but English.
    expect(resolveOutputLanguage('fr', null)).toBe('en')
  })
})

describe('effective research output language', () => {
  it('Malayalam UI with Malayalam preference falls back to English and says so', async () => {
    const mock = researchBackend(capabilities(['en']))
    writePreference(makePreference('ml'))
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'ml' })

    expect(
      await screen.findByText(t('outputLanguage.label', { language: languageName('en', 'ml'), model: 'qwen3:4b' })),
    ).toBeInTheDocument()
    expect(
      screen.getByText(t('outputLanguage.fallback', { preferred: languageName('ml', 'ml'), language: languageName('en', 'ml') })),
    ).toBeInTheDocument()
    await submitResearch(t as never)
    await waitFor(() => expect(postedLanguage(mock)).toBe('en'))
    // The stored preference is never rewritten by the fallback.
    expect(JSON.parse(window.localStorage.getItem(PREFERENCE_STORAGE_KEY) ?? '{}').defaultOutputLanguage).toBe('ml')
  })

  it('Hindi UI with an unsupported Hindi preference also writes English', async () => {
    const mock = researchBackend(capabilities(['en']))
    writePreference(makePreference('hi'))
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'hi' })
    expect(
      await screen.findByText(t('outputLanguage.fallback', { preferred: languageName('hi', 'hi'), language: languageName('en', 'hi') })),
    ).toBeInTheDocument()
    await submitResearch(t as never)
    await waitFor(() => expect(postedLanguage(mock)).toBe('en'))
  })

  it('a supported non-English preference is used directly, with no fallback note', async () => {
    const mock = researchBackend(capabilities(['en', 'es']))
    writePreference(makePreference('es'))
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'es' })
    expect(
      await screen.findByText(t('outputLanguage.label', { language: languageName('es', 'es'), model: 'qwen3:4b' })),
    ).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    await submitResearch(t as never)
    await waitFor(() => expect(postedLanguage(mock)).toBe('es'))
  })

  it('a failed capability request never enables an unsupported language', async () => {
    const mock = researchBackend(undefined)
    writePreference(makePreference('fr'))
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'fr' })
    expect(
      await screen.findByText(t('outputLanguage.unavailable', { language: languageName('en', 'fr') })),
    ).toBeInTheDocument()
    await submitResearch(t as never)
    await waitFor(() => expect(postedLanguage(mock)).toBe('en'))
  })

  it('a malformed capability payload is treated as unavailable', async () => {
    const mock = researchBackend('malformed')
    writePreference(makePreference('de'))
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'de' })
    expect(
      await screen.findByText(t('outputLanguage.unavailable', { language: languageName('en', 'de') })),
    ).toBeInTheDocument()
    await submitResearch(t as never)
    await waitFor(() => expect(postedLanguage(mock)).toBe('en'))
  })

  it('an English user sees no warning even when capabilities are unavailable', async () => {
    researchBackend(undefined)
    writePreference(makePreference('en'))
    await renderWithLocale(<ResearchPage />, { language: 'en' })
    expect(await screen.findByText('Research output: English · current model')).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })
})

describe('artifact lang attributes', () => {
  function reportBackend(run = makeRun({ sources: [makeSource()] })) {
    return installFetchMock((url) => {
      if (url === '/api/capabilities/languages') return { body: capabilities(['en']) }
      if (url === `/api/runs/${run.id}`) return { body: run }
      if (url === `/api/runs/${run.id}/followups`) return { body: { followups: [] } }
      if (url === '/api/templates') return { body: { templates: TEMPLATE_FIXTURES } }
      if (url.startsWith('/api/runs')) return { body: { runs: [makeRunSummary()], total: 1, limit: 50, offset: 0 } }
      return undefined
    })
  }

  it('an English report keeps lang="en" inside a Malayalam UI, and switching UI never changes it', async () => {
    const run = makeRun({ sources: [makeSource()] })
    const mock = reportBackend(run)
    writePreference(makePreference('ml'))
    const { container } = await renderWithLocale(<App />, { language: 'ml', route: `/runs/${run.id}` })

    await screen.findByText(/Solar capacity/)
    expect(document.documentElement.lang).toBe('ml')
    const article = () => container.querySelector('article.report-sections')
    expect(article()).toHaveAttribute('lang', 'en')

    await userEvent.click(screen.getByRole('button', { name: /:/ }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /Deutsch/ }))
    await waitFor(() => expect(document.documentElement.lang).toBe('de'))
    expect(article()).toHaveAttribute('lang', 'en')
    expect(mock.mock.calls.filter(([, init]) => (init?.method ?? 'GET') !== 'GET')).toEqual([])
  })

  it('a stored non-English report carries its own language', async () => {
    const run = makeRun({ sources: [makeSource()], output_language: 'fr', final_report: '## Synthèse\n\nLa croissance [1].' })
    reportBackend(run)
    const { container } = await renderWithLocale(<App />, { language: 'en', route: `/runs/${run.id}` })
    await screen.findByText(/La croissance/)
    expect(container.querySelector('article.report-sections')).toHaveAttribute('lang', 'fr')
    // The Sources card heading is Atlas's own label, in the UI language.
    expect(document.documentElement.lang).toBe('en')
  })

  it('comparisons expose their language', async () => {
    installFetchMock((url) => {
      if (url === '/api/comparisons/cmp-1') return { body: makeComparison({ output_language: 'de' }) }
      return undefined
    })
    const { container } = await renderWithLocale(<ComparisonPage />, {
      language: 'ml',
      route: '/comparisons/cmp-1',
      path: '/comparisons/:id',
    })
    await screen.findByText(/Both topics share a grid focus/)
    expect(container.querySelector('div.report[lang]')).toHaveAttribute('lang', 'de')
  })

  it('follow-up answers expose their language and suggestion chips insert the English question', async () => {
    installFetchMock((url, init) => {
      if (url === '/api/runs/run-1/followups' && (init?.method ?? 'GET') === 'GET') {
        return { body: { followups: [makeFollowUp({ output_language: 'es', answer: 'La evidencia más sólida es [1].' })] } }
      }
      return undefined
    })
    const { container, t } = await renderWithLocale(<FollowUpPanel runId="run-1" />, { language: 'ml' })
    await screen.findByText(/La evidencia más sólida/)
    expect(container.querySelector('.followup-answer')).toHaveAttribute('lang', 'es')

    // Chips are labelled in the UI language but insert an English question; the
    // answer language still follows the parent run, not the question or the UI.
    await userEvent.click(screen.getByRole('button', { name: t('followUp.suggestions.simpler') }))
    expect(screen.getByLabelText(t('followUp.questionLabel'))).toHaveValue('Explain this more simply')
    expect(within(container).queryByText('Explain this more simply', { selector: 'button' })).toBeNull()
  })
})

describe('per-feature capability', () => {
  it('a language supported for reports can still be refused for comparisons', () => {
    const caps = capabilities(['en', 'es'])
    const spanish = caps.languages.find((language) => language.code === 'es')!
    spanish.features = {
      report: { supported: true, reason: '' },
      followup: { supported: true, reason: '' },
      comparison: { supported: false, reason: 'Failed validation.' },
    }
    expect(resolveOutputLanguage('es', caps, 'report')).toBe('es')
    expect(resolveOutputLanguage('es', caps, 'comparison')).toBe('en')
    // Without per-feature data the language verdict applies.
    expect(resolveOutputLanguage('es', capabilities(['en', 'es']), 'comparison')).toBe('es')
  })
})
