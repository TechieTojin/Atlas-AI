import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { LanguageCapabilities } from '../api/client'
import { CompareRunsList } from '../components/CompareRunsList'
import { FollowUpPanel } from '../components/FollowUpPanel'
import { ComparisonPage } from '../pages/ComparisonPage'
import { ResearchPage } from '../pages/ResearchPage'
import { makeComparison, makeFollowUp, makeRun, makeRunSummary, makeSource, TEMPLATE_FIXTURES } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { renderWithLocale } from '../test/renderWithLocale'
import { getLanguage, languageName } from './languages'
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
  const startButton = (t: (key: never) => string) =>
    screen.getByRole('button', { name: new RegExp(t('queryForm.start' as never)) })

  it.each(['ml', 'fr'])(
    'unsupported %s: says so before research, creates nothing until English is chosen',
    async (code) => {
      const mock = researchBackend(capabilities(['en', 'es', 'hi', 'de']))
      writePreference(makePreference(code))
      const { t } = await renderWithLocale(<ResearchPage />, { language: code })

      expect(
        await screen.findByText(t('outputLanguage.unsupported', { preferred: languageName(code, code) })),
      ).toBeInTheDocument()
      await userEvent.type(screen.getByLabelText(t('queryForm.questionLabel')), 'solar growth')
      expect(startButton(t as never)).toBeDisabled()
      await userEvent.click(startButton(t as never))
      expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)

      // Only an explicit choice writes this research in English.
      await userEvent.click(screen.getByRole('button', { name: t('outputLanguage.continueInEnglish') }))
      expect(screen.getByText(t('outputLanguage.continuingInEnglish'))).toBeInTheDocument()
      await userEvent.click(startButton(t as never))
      await waitFor(() => expect(postedLanguage(mock)).toBe('en'))
      // The stored preference is never rewritten.
      expect(JSON.parse(window.localStorage.getItem(PREFERENCE_STORAGE_KEY) ?? '{}').defaultOutputLanguage).toBe(code)
      expect(JSON.parse(window.localStorage.getItem(PREFERENCE_STORAGE_KEY) ?? '{}').uiLanguage).toBe(code)
    },
  )

  it('choosing a language in the header switches the UI and the next research language', async () => {
    const mock = researchBackend(capabilities(['en', 'es', 'hi', 'de']))
    writePreference(makePreference('en'))
    await renderWithLocale(<App />, { language: 'en', route: '/' })
    await userEvent.click(await screen.findByRole('button', { name: /Language: English/ }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /Deutsch/ }))
    await waitFor(() => expect(document.documentElement.lang).toBe('de'))
    const stored = JSON.parse(window.localStorage.getItem(PREFERENCE_STORAGE_KEY) ?? '{}')
    expect(stored).toMatchObject({ uiLanguage: 'de', defaultOutputLanguage: 'de' })
    await waitFor(() => expect(document.querySelector('.start-btn')).not.toBeNull())
    await userEvent.type(document.querySelector('.query-input') as HTMLElement, 'Solarwachstum')
    await userEvent.click(document.querySelector('.start-btn') as HTMLElement)
    await waitFor(() => expect(postedLanguage(mock)).toBe('de'))
  })

  it('a supported non-English preference is used directly, with no note', async () => {
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

  it.each(['hi', 'de'])('a LIMITED %s route writes that language and says it is slower', async (code) => {
    const caps = capabilities(['en', 'es', 'hi', 'de'])
    for (const entry of caps.languages) {
      if (entry.code === 'hi' || entry.code === 'de') Object.assign(entry, { status: 'limited', model: 'gemma4:e4b' })
    }
    const mock = researchBackend(caps)
    writePreference(makePreference(code))
    const { t } = await renderWithLocale(<ResearchPage />, { language: code })
    expect(
      await screen.findByText(t('outputLanguage.limited', { language: languageName(code, code) })),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('outputLanguage.continueInEnglish') })).toBeNull()
    await submitResearch(t as never)
    await waitFor(() => expect(postedLanguage(mock)).toBe(code))
  })

  it.each([
    ['a failed capability request', undefined],
    ['a malformed capability payload', 'malformed' as const],
  ])('%s never enables an unsupported language, nor silently writes English', async (_label, caps) => {
    const mock = researchBackend(caps)
    writePreference(makePreference('de'))
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'de' })
    expect(await screen.findByText(t('outputLanguage.unavailable'))).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(t('queryForm.questionLabel')), 'solar growth')
    expect(startButton(t as never)).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: t('outputLanguage.continueInEnglish') }))
    await userEvent.click(startButton(t as never))
    await waitFor(() => expect(postedLanguage(mock)).toBe('en'))
  })

  it('an English user sees no warning even when capabilities are unavailable', async () => {
    const mock = researchBackend(undefined)
    writePreference(makePreference('en'))
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'en' })
    expect(await screen.findByText('Research output: English · current model')).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    await submitResearch(t as never)
    await waitFor(() => expect(postedLanguage(mock)).toBe('en'))
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

  it.each([
    ['hi', 'en', '## निष्कर्ष\n\nनमी MAPbI3 को PbI2 में बदलती है [1]।', /नमी MAPbI3/],
    ['es', 'ml', '## Conclusión\n\nLa humedad degrada MAPbI3 [1].', /La humedad degrada/],
    ['en', 'de', '## Conclusion\n\nMoisture degrades MAPbI3 [1].', /Moisture degrades/],
  ])('a stored %s report in a %s UI keeps its own language', async (artifact, ui, report, body) => {
    const run = makeRun({ sources: [makeSource()], output_language: artifact, final_report: report })
    const mock = reportBackend(run)
    const { container, t } = await renderWithLocale(<App />, { language: ui, route: `/runs/${run.id}` })
    await screen.findByText(body)
    const article = () => container.querySelector('article.report-sections')
    // Static controls follow the UI; the artifact body follows its own language.
    expect(document.documentElement.lang).toBe(getLanguage(ui).locale)
    expect(screen.getAllByText(t('nav.research')).length).toBeGreaterThan(0)
    expect(article()).toHaveAttribute('lang', getLanguage(artifact).locale)
    expect(article()?.textContent).toContain(report.split('\n\n')[1].slice(0, 12))
    // Source evidence keeps the source's own text (the fixture source is English).
    await userEvent.click(screen.getByRole('tab', { name: new RegExp(t('runTabs.sources')) }))
    expect(await screen.findByText(new RegExp(makeSource().title))).toBeInTheDocument()
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

describe('gated comparisons', () => {
  it('a Hindi user is told before comparing that the comparison will be English', async () => {
    const caps = capabilities(['en', 'es', 'hi', 'de'])
    const hindi = caps.languages.find((language) => language.code === 'hi')!
    hindi.features = {
      report: { supported: true, reason: '' },
      followup: { supported: true, reason: '' },
      comparison: { supported: false, reason: 'Not validated.' },
    }
    installFetchMock((url) => (url === '/api/capabilities/languages' ? { body: caps } : undefined))
    writePreference(makePreference('hi'))
    const { t } = await renderWithLocale(
      <CompareRunsList runs={[makeRunSummary({ id: 'a' }), makeRunSummary({ id: 'b' })]} />,
      { language: 'hi' },
    )
    expect(
      await screen.findByText(t('outputLanguage.comparisonInEnglish', { preferred: languageName('hi', 'hi') })),
    ).toBeInTheDocument()
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
