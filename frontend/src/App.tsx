import { useEffect, useRef, useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { LanguageOnboarding } from './components/LanguageOnboarding'
import { Sidebar } from './components/Sidebar'
import { AtlasMark, MenuIcon } from './components/icons'
import { useTheme } from './hooks/useTheme'
import { useI18n } from './i18n'
import { ComparisonPage } from './pages/ComparisonPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { WebsiteChatPage } from './pages/WebsiteChatPage'
import { ResearchPage } from './pages/ResearchPage'
import { RunPage } from './pages/RunPage'

export default function App() {
  const { theme, toggleTheme } = useTheme()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { needsOnboarding, t } = useI18n()
  const appRef = useRef<HTMLDivElement>(null)

  // While the language dialog is open, the app behind it is not focusable or announced.
  useEffect(() => {
    if (appRef.current) appRef.current.inert = needsOnboarding
  }, [needsOnboarding])

  return (
    <>
      <div className="app" ref={appRef}>
        <Sidebar
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
        <div className="main-column">
          <div className="mobile-topbar">
            <button
              type="button"
              className="icon-btn"
              onClick={() => setSidebarOpen(true)}
              aria-label={t('sidebar.openSidebar')}
            >
              <MenuIcon />
            </button>
            <Link to="/" className="wordmark compact">
              <AtlasMark size={18} className="wordmark-mark" />
              <span>Atlas</span>
            </Link>
          </div>
          <main className="main-content">
            <Routes>
              <Route path="/" element={<ResearchPage />} />
              <Route path="/runs/:id" element={<RunPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/projects" element={<ProjectsPage />} />
              <Route path="/projects/:id" element={<ProjectPage />} />
              <Route path="/comparisons/:id" element={<ComparisonPage />} />
              <Route path="/websites" element={<WebsiteChatPage />} />
              <Route path="/websites/:id" element={<WebsiteChatPage />} />
              <Route
                path="*"
                element={
                  <div className="page-state">
                    <h1>{t('common.pageNotFound')}</h1>
                    <Link className="btn primary" to="/">
                      {t('common.backToResearch')}
                    </Link>
                  </div>
                }
              />
            </Routes>
          </main>
        </div>
      </div>
      {needsOnboarding && <LanguageOnboarding />}
    </>
  )
}
