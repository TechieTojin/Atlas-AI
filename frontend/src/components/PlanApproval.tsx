import { useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { RunDetail } from '../types'

export interface PlanApprovalProps {
  run: RunDetail
  onUpdated: (run: RunDetail) => void
}

function splitLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

export function PlanApproval({ run, onUpdated }: PlanApprovalProps) {
  const plan = run.plan
  const [editing, setEditing] = useState(false)
  const [objective, setObjective] = useState('')
  const [subquestionsText, setSubquestionsText] = useState('')
  const [queriesText, setQueriesText] = useState('')
  const [busy, setBusy] = useState<'approve' | 'save' | 'cancel' | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (!plan) {
    return (
      <section className="card plan-card">
        <h2>Awaiting plan</h2>
        <p className="hint-text">The plan has not been created yet.</p>
      </section>
    )
  }

  const startEditing = () => {
    setObjective(plan.objective)
    setSubquestionsText(plan.subquestions.join('\n'))
    setQueriesText(plan.search_queries.join('\n'))
    setError(null)
    setEditing(true)
  }

  const approve = async () => {
    setBusy('approve')
    setError(null)
    try {
      onUpdated(await api.approvePlan(run.id))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  const cancel = async () => {
    setBusy('cancel')
    setError(null)
    try {
      onUpdated(await api.cancelRun(run.id))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    const subquestions = splitLines(subquestionsText)
    const searchQueries = splitLines(queriesText)
    if (objective.trim().length === 0) {
      setError('Objective cannot be empty.')
      return
    }
    if (subquestions.length === 0) {
      setError('Add at least one subquestion.')
      return
    }
    if (searchQueries.length === 0) {
      setError('Add at least one search query.')
      return
    }
    setBusy('save')
    setError(null)
    try {
      const updated = await api.editPlan(run.id, {
        objective: objective.trim(),
        subquestions,
        search_queries: searchQueries,
      })
      onUpdated(updated)
      setEditing(false)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="card plan-card" aria-label="Research plan awaiting approval">
      <header className="plan-header">
        <h2>Review the research plan</h2>
        <p className="hint-text">Atlas will follow this plan once you approve it.</p>
      </header>

      {editing ? (
        <div className="plan-edit">
          <label className="field-label" htmlFor="plan-objective">
            Objective
          </label>
          <input
            id="plan-objective"
            className="text-input"
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
          />

          <label className="field-label" htmlFor="plan-subquestions">
            Subquestions (one per line)
          </label>
          <textarea
            id="plan-subquestions"
            className="text-input"
            rows={4}
            value={subquestionsText}
            onChange={(event) => setSubquestionsText(event.target.value)}
          />

          <label className="field-label" htmlFor="plan-queries">
            Search queries (one per line)
          </label>
          <textarea
            id="plan-queries"
            className="text-input"
            rows={4}
            value={queriesText}
            onChange={(event) => setQueriesText(event.target.value)}
          />

          <div className="btn-row">
            <button type="button" className="btn primary" onClick={() => void save()} disabled={busy !== null}>
              {busy === 'save' ? 'Saving…' : 'Save plan'}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setEditing(false)
                setError(null)
              }}
              disabled={busy !== null}
            >
              Discard changes
            </button>
          </div>
        </div>
      ) : (
        <div className="plan-body">
          <h3 className="plan-section-title">Objective</h3>
          <p className="plan-objective">{plan.objective}</p>

          <h3 className="plan-section-title">Subquestions</h3>
          <ol className="plan-list">
            {plan.subquestions.map((question, index) => (
              <li key={index}>{question}</li>
            ))}
          </ol>

          <h3 className="plan-section-title">Search queries</h3>
          <ol className="plan-list">
            {plan.search_queries.map((query, index) => (
              <li key={index}>{query}</li>
            ))}
          </ol>

          <div className="btn-row">
            <button type="button" className="btn primary" onClick={() => void approve()} disabled={busy !== null}>
              {busy === 'approve' ? 'Approving…' : 'Approve'}
            </button>
            <button type="button" className="btn" onClick={startEditing} disabled={busy !== null}>
              Edit plan
            </button>
            <button type="button" className="btn danger-ghost" onClick={() => void cancel()} disabled={busy !== null}>
              {busy === 'cancel' ? 'Cancelling…' : 'Cancel run'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
