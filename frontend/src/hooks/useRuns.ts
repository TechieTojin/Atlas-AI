import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { RunSummary } from '../types'

export function useRuns(limit = 50, projectId?: string): {
  runs: RunSummary[]
  total: number
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
} {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const response = await api.listRuns({ limit, project_id: projectId })
      setRuns(response.runs)
      setTotal(response.total)
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [limit, projectId])

  useEffect(() => {
    void refresh()
    const onChanged = () => void refresh()
    window.addEventListener('atlas:runs-changed', onChanged)
    return () => window.removeEventListener('atlas:runs-changed', onChanged)
  }, [refresh])

  return { runs, total, loading, error, refresh }
}
