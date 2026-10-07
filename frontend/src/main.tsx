import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { initialTheme } from './hooks/useTheme'
import { bootstrapI18n, I18nProvider } from './i18n'
import './styles.css'
import './styles/atlas.css'

const root = document.getElementById('root')
if (!root) {
  throw new Error('Root element not found')
}

// Theme and language are applied before the first render so neither flashes.
document.documentElement.dataset.theme = initialTheme()

void bootstrapI18n().then((initial) => {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <I18nProvider initial={initial}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </I18nProvider>
    </React.StrictMode>,
  )
})
