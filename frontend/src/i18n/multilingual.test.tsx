import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { ProjectKnowledgeGraph } from '../components/ProjectKnowledgeGraph'
import { Sidebar } from '../components/Sidebar'
import { ComparisonPage } from '../pages/ComparisonPage'
import { DocumentsPage } from '../pages/DocumentsPage'
import { ProjectPage } from '../pages/ProjectPage'
import { ProjectsPage } from '../pages/ProjectsPage'
import { ResearchPage } from '../pages/ResearchPage'
import { RunPage } from '../pages/RunPage'
import {
  makeComparison,
  makeDocument,
  makeProject,
  makeProjectOverview,
  makeRun,
  makeRunSummary,
  makeSource,
  TEMPLATE_FIXTURES,
} from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { installFetchMock, requestBody } from '../test/mockFetch'
import { renderWithLocale, translatorFor } from '../test/renderWithLocale'
import type { ProjectGraph } from '../types'
import { createFormatters } from './format'
import { agoLabel } from './labels'
import { en } from './messages/en'
import { loadMessages } from './loadMessages'
import { makePreference, PREFERENCE_STORAGE_KEY, writePreference } from './preference'

const NOW = Date.parse('2026-10-07T12:00:00Z')

function nonGetCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([, init]) => (init?.method ?? 'GET').toUpperCase() !== 'GET')
}

// Dictionaries are lazy chunks; transform them once up front so the first
// test in the file does not pay that cost inside its own time budget.
beforeAll(async () => {
  await Promise.all(['ml', 'hi', 'es', 'fr', 'de'].map((language) => loadMessages(language)))
})

beforeEach(() => {
  window.localStorage.clear()
  MockEventSource.reset()
  vi.stubGlobal('EventSource', MockEventSource)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Research in Malayalam', () => {
  it('renders translated chrome and still starts research exactly as before', async () => {
    const fetchMock = installFetchMock((url, init) => {
      if (url === '/api/templates') return { body: { templates: TEMPLATE_FIXTURES } }
      if (url === '/api/documents') return { body: { documents: [] } }
      if (url === '/api/runs' && init?.method === 'POST') return { status: 201, body: makeRun({ id: 'new-run' }) }
      return undefined
    })
    const { t } = await renderWithLocale(<ResearchPage />, { language: 'ml' })

    expect(document.documentElement.lang).toBe('ml')
    expect(t('queryForm.start')).not.toBe(en.queryForm.start)
    expect(screen.getByText(t('research.tagline'))).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: t('queryForm.modeTitle') })).toBeInTheDocument()
    expect(screen.getByText(t('modes.FAST.label'))).toBeInTheDocument()
    expect(screen.getByText(t('modes.DEEP.description'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('scopes.WEB_AND_DOCUMENTS.label') })).toBeInTheDocument()
    expect(screen.getByText(t('queryForm.reviewPlan'))).toBeInTheDocument()
    expect(screen.getByText(t('queryForm.useMemory'))).toBeInTheDocument()
    // Template names come from the dictionary by id, not the backend's English name.
    const templateSelect = await screen.findByLabelText(t('queryForm.templateLabel'))
    await waitFor(() => expect(within(templateSelect).getAllByRole('option')).toHaveLength(7))
    expect(within(templateSelect).getByRole('option', { name: t('templates.ACADEMIC.name') })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(t('queryForm.questionLabel')), 'solar growth')
    // Malayalam generation is not available: nothing starts until the user
    // explicitly chooses to write this research in English.
    expect(screen.getByRole('button', { name: new RegExp(t('queryForm.start')) })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: t('outputLanguage.continueInEnglish') }))
    await userEvent.click(screen.getByRole('button', { name: new RegExp(t('queryForm.start')) }))

    await waitFor(() => expect(nonGetCalls(fetchMock)).toHaveLength(1))
    // The UI language never reaches the backend. The output language sent is the
    // one the user chose for this research: English.
    expect(requestBody(nonGetCalls(fetchMock)[0][1])).toEqual({
      query: 'solar growth',
      mode: 'FAST',
      source_scope: 'WEB',
      document_ids: [],
      approval_required: false,
      template: 'STANDARD',
      use_memory: true,
      output_language: 'en',
    })
  })
})

describe('Projects in Hindi', () => {
  it('translates the page and pluralises counts while keeping project data as stored', async () => {
    installFetchMock((url) => {
      if (url === '/api/projects') return { body: { projects: [makeProject()] } }
      return undefined
    })
    const { t } = await renderWithLocale(<ProjectsPage />, { language: 'hi' })

    expect(await screen.findByText('Energy transition')).toBeInTheDocument()
    expect(screen.getByText('Research into renewables and grids')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: t('projects.title') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('projects.newProject') })).toBeInTheDocument()
    expect(screen.getByPlaceholderText(t('projects.searchPlaceholder'))).toBeInTheDocument()
    const counts = [
      t('projectCard.runs', { count: 3 }),
      t('projectCard.documents', { count: 2 }),
      t('projectCard.comparisons', { count: 1 }),
    ].join(' · ')
    expect(screen.getByText(counts)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('common.moreActionsFor', { name: 'Energy transition' }) })).toBeInTheDocument()
  })
})

describe('Documents in French', () => {
  it('translates headers, status and the delete confirmation without changing what deletion does', async () => {
    const fetchMock = installFetchMock((url, init) => {
      if (url === '/api/documents' && (!init?.method || init.method === 'GET')) {
        return { body: { documents: [makeDocument()] } }
      }
      return undefined
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { t } = await renderWithLocale(<DocumentsPage />, { language: 'fr' })

    expect(await screen.findByText('energy-outlook.pdf')).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByRole('columnheader', { name: t('documentTable.uploaded') })).toBeInTheDocument()
    expect(within(table).getByText(t('documentTable.ready'))).toBeInTheDocument()
    // Sizes and dates use French number and date formatting.
    expect(within(table).getByText('2,3 MB')).toBeInTheDocument()
    expect(within(table).getByText(createFormatters('fr').date('2026-10-01T09:00:00Z'))).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: t('common.moreActionsFor', { name: 'energy-outlook.pdf' }) }))
    await userEvent.click(screen.getByRole('menuitem', { name: t('common.deleteNamed', { name: 'energy-outlook.pdf' }) }))
    expect(confirm).toHaveBeenCalledWith(t('documents.confirmDelete', { name: 'energy-outlook.pdf' }))
    expect(nonGetCalls(fetchMock)).toEqual([])
  })
})

function mockCompletedRun() {
  const run = makeRun({
    sources: [makeSource()],
    final_report: '## Executive Summary\n\nSolar capacity grew rapidly. [1]\n\n## Outlook\n\nGrowth continues.',
  })
  const fetchMock = installFetchMock((url) => {
    if (url === '/api/runs/run-1') return { body: run }
    if (url === '/api/runs/run-1/followups') return { body: { followups: [] } }
    if (url === '/api/templates') return { body: { templates: TEMPLATE_FIXTURES } }
    if (url.startsWith('/api/runs')) return { body: { runs: [makeRunSummary()], total: 1, limit: 50, offset: 0 } }
    return undefined
  })
  return { run, fetchMock }
}

describe('Report chrome in German', () => {
  it('translates tabs, actions and the right rail but leaves the stored report untouched', async () => {
    mockCompletedRun()
    const { t } = await renderWithLocale(<RunPage />, { language: 'de', route: '/runs/run-1', path: '/runs/:id' })

    expect(await screen.findByRole('tab', { name: t('runTabs.report') })).toHaveAttribute('aria-selected', 'true')
    for (const tab of ['sources', 'evidence', 'metrics', 'graph'] as const) {
      expect(screen.getByRole('tab', { name: new RegExp(t(`runTabs.${tab}`)) })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: t('common.export') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('runActions.regenerateTrigger') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('run.deleteLabel') })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: t('reportSidebar.quickActions') })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: t('reportSidebar.documentInfo') })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: t('followUp.heading') })).toBeInTheDocument()
    // Stored content: question, report headings and body are exactly as generated.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('How fast is global solar capacity growing?')
    expect(screen.getAllByRole('heading', { name: 'Executive Summary' }).length).toBeGreaterThan(0)
    expect(screen.getByText(/Solar capacity grew rapidly\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('report.viewSource', { index: '1' }) })).toHaveTextContent('[1]')
  })
})

describe('Sidebar in Spanish', () => {
  it('translates navigation, history and compact relative times', async () => {
    vi.useFakeTimers({ toFake: ['Date'], now: NOW })
    installFetchMock((url) => {
      if (url.startsWith('/api/runs')) {
        return {
          body: {
            runs: [
              makeRunSummary({ id: 'r1', title: 'Solar growth', created_at: '2026-10-05T12:00:00Z' }),
              makeRunSummary({ id: 'r2', title: 'Battery costs', created_at: '2026-10-07T11:55:00Z' }),
            ],
            total: 2,
            limit: 50,
            offset: 0,
          },
        }
      }
      return undefined
    })
    const { t } = await renderWithLocale(<Sidebar open={false} onClose={vi.fn()} theme="dark" onToggleTheme={vi.fn()} />, {
      language: 'es',
    })
    try {
      expect(await screen.findByText('Solar growth')).toBeInTheDocument()
      expect(screen.getByRole('link', { name: new RegExp(t('nav.documents')) })).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: t('sidebar.history') })).toBeInTheDocument()
      expect(screen.getByText(createFormatters('es').ago('2026-10-05T12:00:00Z', NOW) as string)).toBeInTheDocument()
      expect(screen.getByText(createFormatters('es').ago('2026-10-07T11:55:00Z', NOW) as string)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: t('sidebar.switchToLight') })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: t('language.current', { name: 'Español' }) })).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('Project workspace in Malayalam', () => {
  it('translates tabs and overview labels; findings and names stay as stored', async () => {
    installFetchMock((url) => {
      if (url === '/api/projects/proj-1/overview') return { body: makeProjectOverview() }
      if (url === '/api/projects/proj-1') return { body: makeProject() }
      if (url.startsWith('/api/runs')) return { body: { runs: [], total: 0, limit: 50, offset: 0 } }
      return undefined
    })
    const { t } = await renderWithLocale(<ProjectPage />, {
      language: 'ml',
      route: '/projects/proj-1',
      path: '/projects/:id',
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Energy transition' })).toBeInTheDocument()
    for (const tab of ['overview', 'research', 'documents', 'comparisons', 'graph'] as const) {
      expect(screen.getByRole('tab', { name: t(`workspace.tabs.${tab}`) })).toBeInTheDocument()
    }
    expect(await screen.findByRole('heading', { name: t('overview.currentUnderstanding') })).toBeInTheDocument()
    expect(screen.getByText('Grid storage is the binding constraint on renewable deployment.')).toBeInTheDocument()
    expect(screen.getByText(t('overview.supportRuns', { count: 2 }))).toBeInTheDocument()
    expect(screen.getByText(t('overview.findingsAdded', { count: 5 }))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('common.continueResearch') })).toBeInTheDocument()
  })
})

describe('Comparison UI in Hindi', () => {
  it('translates status and overlap labels; run questions and the report stay original', async () => {
    installFetchMock((url) => {
      if (url === '/api/comparisons/cmp-1') return { body: makeComparison() }
      return undefined
    })
    const { t } = await renderWithLocale(<ComparisonPage />, {
      language: 'hi',
      route: '/comparisons/cmp-1',
      path: '/comparisons/:id',
    })

    expect(await screen.findByText(t('comparison.status.COMPLETED'))).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: t('comparison.overlap') })).toBeInTheDocument()
    expect(screen.getByText(t('comparison.sharedSources'))).toBeInTheDocument()
    expect(screen.getByText(t('comparison.uniqueTo', { run: 'Battery costs' }))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Solar growth' })).toBeInTheDocument()
    expect(screen.getByText(/Both topics share a grid focus\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('comparison.deleteLabel') })).toBeInTheDocument()
  })
})

const GRAPH: ProjectGraph = {
  project: { id: 'proj-1', name: 'Battery Technology Research' },
  stats: { concepts: 1, findings: 2, runs: 1 },
  nodes: [
    { id: 'project-proj-1', label: 'Battery Technology Research', type: 'project', project_id: 'proj-1', support_count: 1, finding_count: 2 },
    { id: 'concept-a', label: 'interface stability', type: 'concept', project_id: 'proj-1', support_count: 1, finding_count: 2 },
  ],
  edges: [{ id: 'e1', source: 'project-proj-1', target: 'concept-a', relation: 'HAS_TOPIC', weight: 2 }],
}

describe('Knowledge graph controls in French', () => {
  it('translates controls, legend and counts; concept labels stay original', async () => {
    installFetchMock((url) => (url === '/api/projects/proj-1/knowledge-graph' ? { body: GRAPH } : undefined))
    const { t } = await renderWithLocale(<ProjectKnowledgeGraph projectId="proj-1" onStartResearch={vi.fn()} />, {
      language: 'fr',
    })

    expect(await screen.findByRole('button', { name: t('projectGraph.fit') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('projectGraph.reset') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('projectGraph.viewAll') })).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: t('projectGraph.searchLabel') })).toBeInTheDocument()
    const legend = screen.getByRole('list', { name: t('projectGraph.legend') })
    expect(within(legend).getByText(t('projectGraph.concept'))).toBeInTheDocument()
    expect(
      screen.getByText(
        [
          t('projectGraph.statsConcepts', { count: 1 }),
          t('projectGraph.findings', { count: 2 }),
          t('projectGraph.statsRuns', { count: 1 }),
        ].join(' · '),
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: `interface stability, ${t('projectGraph.findings', { count: 2 })} · ${t('projectGraph.runs', { count: 1 })}` })).toBeInTheDocument()
  })
})

describe('plurals', () => {
  it('pick the form by each language’s own plural rules', async () => {
    const english = await translatorFor('en')
    expect(english('projectCard.runs', { count: 1 })).toBe('1 run')
    expect(english('projectCard.runs', { count: 0 })).toBe('0 runs')
    expect(english('documents.confirmDeleteMany', { count: 1 })).toBe('Delete 1 document? This cannot be undone.')
    expect(english('followUp.newSources', { count: 1 })).toBe('+1 new source')

    // French treats 0 as singular, English does not.
    const french = await translatorFor('fr')
    expect(french('projectCard.runs', { count: 0 })).toBe(french('projectCard.runs', { count: 1 }).replace('1', '0'))
    expect(french('projectCard.runs', { count: 0 })).not.toBe(french('projectCard.runs', { count: 2 }).replace('2', '0'))

    for (const language of ['ml', 'hi', 'es', 'de']) {
      const t = await translatorFor(language)
      const one = t('projectGraph.findings', { count: 1 })
      const many = t('projectGraph.findings', { count: 5 })
      expect(one).toContain('1')
      expect(many).toContain('5')
      expect(many).not.toBe(en.projectGraph.findings.other.replace('{count}', '5'))
    }
    // Counts are formatted in the language's locale.
    expect((await translatorFor('de'))('projectCard.documents', { count: 1500 })).toContain('1.500')
  })
})

describe('relative dates and locale formatting', () => {
  it('keeps the compact English forms and localises the rest', () => {
    const enFormat = createFormatters('en')
    expect(enFormat.ago(NOW - 5 * 60_000, NOW)).toBe('5m ago')
    expect(enFormat.ago(NOW - 3 * 3_600_000, NOW)).toBe('3h ago')
    expect(enFormat.ago(NOW - 2 * 86_400_000, NOW)).toBe('2d ago')
    expect(enFormat.ago(NOW - 10_000, NOW)).toBeNull()
    expect(enFormat.ago(NOW - 10 * 86_400_000, NOW)).toBe('Sep 27')
    expect(createFormatters('es').ago(NOW - 2 * 86_400_000, NOW)).toBe('hace 2 d')
    // French puts a (narrow) no-break space before the unit.
    expect(createFormatters('fr').ago(NOW - 2 * 86_400_000, NOW)).toMatch(/^il y a 2\sj$/)
    expect(createFormatters('de').ago(NOW - 3 * 3_600_000, NOW)).toBe('vor 3 Std.')
    expect(createFormatters('hi').ago(NOW - 2 * 86_400_000, NOW)).toBe('2 दिन पहले')

    // Durations, sizes and percentages match the previous English output exactly.
    expect(enFormat.duration(120)).toBe('120ms')
    expect(enFormat.duration(2000)).toBe('2.0s')
    expect(enFormat.duration(303_000)).toBe('5m 3s')
    expect(enFormat.bytes(2_400_000)).toBe('2.3 MB')
    expect(enFormat.bytes(512)).toBe('512 B')
    expect(enFormat.percentValue(0.42)).toBe('42%')
    expect(enFormat.percentValue(87)).toBe('87%')
    expect(enFormat.minutes(4)).toBe('4 min')
    expect(createFormatters('de').bytes(1536)).toBe('1,5 KB')
    expect(createFormatters('de').duration(1500)).toBe('1,5 Sek.')
  })

  it('says "just now" in the UI language for the first 45 seconds', async () => {
    const recent = new Date(Date.now() - 5_000).toISOString()
    expect(agoLabel(await translatorFor('en'), createFormatters('en'), recent)).toBe('just now')
    const ml = await translatorFor('ml')
    expect(agoLabel(ml, createFormatters('ml'), recent)).toBe(ml('time.justNow'))
  })
})

describe('accessibility labels', () => {
  it('translates aria-labels and tooltips, and switching updates <html lang>', async () => {
    installFetchMock((url) => {
      if (url.startsWith('/api/runs')) return { body: { runs: [], total: 0, limit: 50, offset: 0 } }
      if (url === '/api/templates') return { body: { templates: TEMPLATE_FIXTURES } }
      if (url === '/api/documents') return { body: { documents: [] } }
      return undefined
    })
    writePreference(makePreference('hi'))
    const { t } = await renderWithLocale(<App />, { language: 'hi' })

    expect(screen.getByRole('navigation', { name: t('nav.primary') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('sidebar.closeSidebar') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('sidebar.openSidebar') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('queryForm.submitLabel') })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t('queryForm.attachFilesLabel') })).toBeInTheDocument()
    expect(screen.getByRole('form', { name: t('queryForm.label') })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('hi')

    await userEvent.click(screen.getByRole('button', { name: t('language.current', { name: 'हिन्दी' }) }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /Deutsch/ }))
    const de = await translatorFor('de')
    expect(await screen.findByRole('button', { name: de('sidebar.closeSidebar') })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('de')
    expect(document.documentElement.dir).toBe('ltr')
  })
})

describe('switching language while a report is open', () => {
  it.each([
    ['മലയാളം', 'ml'],
    ['हिन्दी', 'hi'],
    ['Français', 'fr'],
  ] as const)('to %s changes only the UI chrome; the stored report and question are untouched', async (native, code) => {
    const { run, fetchMock } = mockCompletedRun()
    const snapshot = JSON.stringify(run)
    writePreference(makePreference('en'))
    await renderWithLocale(<App />, { language: 'en', route: '/runs/run-1' })

    expect(await screen.findByRole('tab', { name: 'Report' })).toBeInTheDocument()
    const reportText = () => screen.getByText(/Solar capacity grew rapidly\./).textContent
    const before = reportText()

    await userEvent.click(screen.getByRole('button', { name: 'Language: English' }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: new RegExp(native) }))
    const t = await translatorFor(code)
    expect(await screen.findByRole('tab', { name: t('runTabs.report') })).toBeInTheDocument()
    expect(reportText()).toBe(before)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('How fast is global solar capacity growing?')
    expect(screen.getAllByRole('heading', { name: 'Executive Summary' }).length).toBeGreaterThan(0)
    expect(JSON.parse(window.localStorage.getItem(PREFERENCE_STORAGE_KEY) ?? '{}').uiLanguage).toBe(code)
    // Nothing was written to the backend and the run object was never mutated.
    expect(nonGetCalls(fetchMock)).toEqual([])
    expect(JSON.stringify(run)).toBe(snapshot)
  })
})
