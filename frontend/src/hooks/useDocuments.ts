import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { DocumentRecord } from '../types'

const POLL_INTERVAL_MS = 2500

export function useDocuments(projectId?: string): {
  documents: DocumentRecord[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  upload: (file: File) => Promise<DocumentRecord>
  remove: (id: string) => Promise<void>
} {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const response = await api.listDocuments(projectId)
      setDocuments(response.documents)
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const hasProcessing = documents.some((doc) => doc.status === 'PROCESSING')

  useEffect(() => {
    if (!hasProcessing) return
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [hasProcessing, refresh])

  const upload = useCallback(
    async (file: File) => {
      const record = await api.uploadDocument(file, projectId)
      await refresh()
      return record
    },
    [refresh, projectId],
  )

  const remove = useCallback(async (id: string) => {
    await api.deleteDocument(id)
    setDocuments((previous) => previous.filter((doc) => doc.id !== id))
  }, [])

  return { documents, loading, error, refresh, upload, remove }
}
