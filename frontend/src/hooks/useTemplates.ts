import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { TemplateInfo } from '../types'

export const FALLBACK_TEMPLATES: TemplateInfo[] = [
  { id: 'STANDARD', name: 'Standard', description: 'Balanced research report' },
]

/**
 * Fetches the available report templates, falling back to the standard
 * template when the endpoint is unavailable.
 */
export function useTemplates(): { templates: TemplateInfo[]; loading: boolean } {
  const [templates, setTemplates] = useState<TemplateInfo[]>(FALLBACK_TEMPLATES)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api
      .listTemplates()
      .then((response) => {
        if (!cancelled && response.templates.length > 0) setTemplates(response.templates)
      })
      .catch(() => {
        // keep the fallback
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { templates, loading }
}
