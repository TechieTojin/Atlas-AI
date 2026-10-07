import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { Sidebar } from '../components/Sidebar'
import { installFetchMock } from '../test/mockFetch'
import { bootstrapI18n, I18nProvider, type I18nInitialState } from './I18nProvider'
import { loadMessages } from './loadMessages'
import { makePreference, PREFERENCE_STORAGE_KEY, writePreference } from './preference'

function mockBackend() {
  return installFetchMock((url) => {
    if (url.startsWith('/api/runs')) return { body: { runs: [], total: 0, limit: 50, offset: 0 } }
    if (url.startsWith('/api/templates')) return { body: { templates: [] } }
    if (url.startsWith('/api/documents')) return { body: { documents: [] } }
    if (url.startsWith('/api/projects')) return { body: { projects: [] } }
    return { body: {} }
  })
}

function renderApp(initial: I18nInitialState) {
  return render(
    <I18nProvider initial={initial}>
      <MemoryRouter initialEntries={['/projects']}>
        <App />
      </MemoryRouter>
    </I18nProvider>,
  )
}

function storedPreference() {
  return JSON.parse(window.localStorage.getItem(PREFERENCE_STORAGE_KEY) ?? 'null')
}

function nonGetCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([, init]) => (init?.method ?? 'GET').toUpperCase() !== 'GET')
}

// Dictionaries are lazy chunks; transform them once up front so the first
// test in the file does not pay that cost inside its own time budget.
beforeAll(async () => {
  await Promise.all(['ml', 'hi', 'es'].map((language) => loadMessages(language)))
})

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.lang = 'en'
})

describe('first-launch language selection', () => {
  it('asks once, applies and persists the choice, then stays dismissed after reload', async () => {
    const fetchMock = mockBackend()
    const first = renderApp(await bootstrapI18n())

    const dialog = await screen.findByRole('dialog', { name: 'Welcome to Atlas' })
    expect(within(dialog).getByRole('radio', { name: /English/ })).toBeChecked()
    await userEvent.click(within(dialog).getByRole('radio', { name: /മലയാളം/ }))
    // The dialog previews its own text in the highlighted language.
    expect(await within(dialog).findByText('നിങ്ങളുടെ ഭാഷ തിരഞ്ഞെടുക്കുക', { selector: 'p' })).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /തുടരുക/ }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(storedPreference()).toEqual({ version: 1, uiLanguage: 'ml', defaultOutputLanguage: 'ml' })
    expect(document.documentElement.lang).toBe('ml')
    expect(screen.getByRole('link', { name: /ഗവേഷണം/ })).toBeInTheDocument()
    first.unmount()

    renderApp(await bootstrapI18n())
    expect(screen.getByRole('link', { name: /പ്രോജക്റ്റുകൾ/ })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // Choosing a language never writes anything to the backend.
    expect(nonGetCalls(fetchMock)).toEqual([])
  })

  it('recovers from a corrupted preference by asking again instead of failing', async () => {
    mockBackend()
    window.localStorage.setItem(PREFERENCE_STORAGE_KEY, '{"uiLanguage":"klingon"')
    renderApp(await bootstrapI18n())
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /Continue/ }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(storedPreference()).toEqual({ version: 1, uiLanguage: 'en', defaultOutputLanguage: 'en' })
  })

  it('does not trap the user when storage is unavailable', async () => {
    mockBackend()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    renderApp(await bootstrapI18n())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Research/ })).toBeInTheDocument()
  })
})

describe('language switcher', () => {
  it('switches immediately, persists both language fields and updates <html lang>', async () => {
    const fetchMock = mockBackend()
    writePreference(makePreference('en'))
    renderApp(await bootstrapI18n())

    await userEvent.click(screen.getByRole('button', { name: 'Language: English' }))
    const menu = screen.getByRole('menu', { name: 'Available languages' })
    expect(within(menu).getAllByRole('menuitemradio')).toHaveLength(6)
    expect(within(menu).getByRole('menuitemradio', { name: /English/ })).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(within(menu).getByRole('menuitemradio', { name: /हिन्दी/ }))

    expect(await screen.findByRole('link', { name: /अनुसंधान/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'भाषा: हिन्दी' })).toBeInTheDocument()
    expect(storedPreference()).toEqual({ version: 1, uiLanguage: 'hi', defaultOutputLanguage: 'hi' })
    expect(document.documentElement.lang).toBe('hi')
    expect(document.documentElement.dir).toBe('ltr')

    await userEvent.click(screen.getByRole('button', { name: 'भाषा: हिन्दी' }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /Español/ }))
    expect(await screen.findByRole('link', { name: /Investigación/ })).toBeInTheDocument()
    expect(storedPreference().uiLanguage).toBe('es')

    expect(nonGetCalls(fetchMock)).toEqual([])
  })

  it('supports keyboard navigation and Escape', async () => {
    mockBackend()
    writePreference(makePreference('en'))
    renderApp(await bootstrapI18n())
    const trigger = screen.getByRole('button', { name: 'Language: English' })
    await userEvent.click(trigger)
    expect(screen.getByRole('menuitemradio', { name: /English/ })).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitemradio', { name: /മലയാളം/ })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})

describe('components without a provider', () => {
  it('render English exactly as before', () => {
    mockBackend()
    render(
      <MemoryRouter>
        <Sidebar open={false} onClose={vi.fn()} theme="dark" onToggleTheme={vi.fn()} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toHaveTextContent('Light theme')
    expect(screen.getByRole('button', { name: 'Language: English' })).toBeInTheDocument()
  })
})
