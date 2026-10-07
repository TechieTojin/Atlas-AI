import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { AtlasMark, MenuIcon } from './components/icons'
import { useTheme } from './hooks/useTheme'
import { ComparisonPage } from './pages/ComparisonPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ResearchPage } from './pages/ResearchPage'
import { RunPage } from './pages/RunPage'

export default function App() {
  const { theme, toggleTheme } = useTheme()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="app">
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
            aria-label="Open sidebar"
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
            <Route
              path="*"
              element={
                <div className="page-state">
                  <h1>Page not found</h1>
                  <Link className="btn primary" to="/">
                    Back to research
                  </Link>
                </div>
              }
            />
          </Routes>
        </main>
      </div>
    </div>
  )
}
