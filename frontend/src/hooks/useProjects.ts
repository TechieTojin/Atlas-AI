import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage, type CreateProjectRequest } from '../api/client'
import type { Project, ProjectWithCounts } from '../types'

export function useProjects(): {
  projects: ProjectWithCounts[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  create: (body: CreateProjectRequest) => Promise<Project>
} {
  const [projects, setProjects] = useState<ProjectWithCounts[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const response = await api.listProjects()
      setProjects(response.projects)
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const create = useCallback(
    async (body: CreateProjectRequest) => {
      const project = await api.createProject(body)
      await refresh()
      return project
    },
    [refresh],
  )

  return { projects, loading, error, refresh, create }
}

export function useProject(id: string | undefined): {
  project: ProjectWithCounts | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  setProject: (project: ProjectWithCounts) => void
} {
  const [project, setProject] = useState<ProjectWithCounts | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!id) return
    try {
      setProject(await api.getProject(id))
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    setProject(null)
    setError(null)
    setLoading(true)
    void refresh()
  }, [refresh])

  return { project, loading, error, refresh, setProject }
}
