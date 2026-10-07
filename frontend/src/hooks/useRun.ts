import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { RunDetail } from '../types'

export function useRun(id: string | undefined): {
  run: RunDetail | null
  loading: boolean
  error: string | null
  refetch: () => Promise<void>
  setRun: (run: RunDetail) => void
} {
  const [run, setRunState] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refetch = useCallback(async () => {
    if (!id) return
    try {
      const detail = await api.getRun(id)
      setRunState(detail)
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    setRunState(null)
    setError(null)
    setLoading(true)
    void refetch()
  }, [refetch])

  const setRun = useCallback((next: RunDetail) => {
    setRunState(next)
  }, [])

  return { run, loading, error, refetch, setRun }
}
