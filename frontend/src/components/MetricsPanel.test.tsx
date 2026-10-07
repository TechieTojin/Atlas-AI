import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { makeMetrics } from '../test/fixtures'
import { MetricsPanel } from './MetricsPanel'

describe('MetricsPanel model usage', () => {
  it('shows LLM call/token totals and a per-stage breakdown', () => {
    render(
      <MetricsPanel
        evaluation={null}
        metrics={makeMetrics({
          llm_calls: 3,
          llm_prompt_tokens: 2100,
          llm_output_tokens: 1250,
          budget_seconds: 540,
          llm_stage_stats: {
            planner: { calls: 1, ms: 61000, input_chars: 900, prompt_tokens: 220, output_tokens: 300, errors: 0 },
            synthesis: { calls: 1, ms: 190000, input_chars: 6200, prompt_tokens: 1500, output_tokens: 700, errors: 0 },
          },
        })}
      />,
    )
    expect(screen.getByText('Model usage')).toBeInTheDocument()
    expect(screen.getByText('LLM calls').previousSibling).toHaveTextContent('3')
    // Counts are locale-formatted (en: thousands separator).
    expect(screen.getByText('Output tokens').previousSibling).toHaveTextContent('1,250')
    const table = screen.getByRole('table', { name: 'Per-stage model usage' })
    const synthesisRow = within(table).getByRole('row', { name: /Synthesis/ })
    expect(synthesisRow).toHaveTextContent('6,200 chars')
    expect(synthesisRow).toHaveTextContent('1,500')
    expect(screen.getByText('Run budget')).toBeInTheDocument()
  })

  it('surfaces budget fallbacks instead of hiding them', () => {
    render(
      <MetricsPanel
        evaluation={null}
        metrics={makeMetrics({
          llm_calls: 2,
          critic_fallback: 'critic exceeded its time budget',
          repair_skipped: true,
        })}
      />,
    )
    expect(screen.getByText('Critic skipped: critic exceeded its time budget.')).toBeInTheDocument()
    expect(screen.getByText(/Citation repair skipped/)).toBeInTheDocument()
  })

  it('shows aborted-call tokens as unavailable, never as a genuine 0', () => {
    render(
      <MetricsPanel
        evaluation={null}
        metrics={makeMetrics({
          llm_calls: 3,
          llm_prompt_tokens: 1240,
          llm_output_tokens: 448,
          llm_tokens_complete: false,
          suspended_ms: 448_000,
          synthesis_fallback: true,
          llm_stage_stats: {
            planner: { calls: 1, ms: 52800, input_chars: 829, prompt_tokens: 184, output_tokens: 218, errors: 0, tokens_available: true, outcomes: ['ok'] },
            synthesis: { calls: 1, ms: 300000, input_chars: 6182, prompt_tokens: 0, output_tokens: 0, errors: 1, tokens_available: false, outcomes: ['timed_out'] },
          },
        })}
      />,
    )
    const table = screen.getByRole('table', { name: 'Per-stage model usage' })
    const synthesisRow = within(table).getByRole('row', { name: /Synthesis/ })
    expect(within(synthesisRow).getAllByText('unavailable')).toHaveLength(2)
    expect(synthesisRow).toHaveTextContent('Timed out')
    const plannerRow = within(table).getByRole('row', { name: /Planner/ })
    expect(plannerRow).toHaveTextContent('184')
    expect(plannerRow).toHaveTextContent('Completed')
    expect(screen.getByText('Prompt tokens (partial)')).toBeInTheDocument()
    expect(screen.getByText(/asleep for/)).toBeInTheDocument()
  })

  it('omits the section for runs recorded before diagnostics existed', () => {
    render(<MetricsPanel evaluation={null} metrics={makeMetrics()} />)
    expect(screen.queryByText('Model usage')).not.toBeInTheDocument()
  })
})

describe('MetricsPanel research memory', () => {
  const renderWithRouter = (metrics: Parameters<typeof makeMetrics>[0]) =>
    render(
      <MemoryRouter>
        <MetricsPanel evaluation={null} metrics={makeMetrics(metrics)} />
      </MemoryRouter>,
    )

  it('lists reused findings with their source run and relevance', () => {
    renderWithRouter({
      memory_enabled: true,
      memory_scope: 'PROJECT',
      memory_candidates: 12,
      project_memory_hits: 2,
      memory_threshold: 0.65,
      memory_items: [
        {
          text: 'Interface instability remains the largest barrier to commercial cells.',
          question: 'What are the biggest technical barriers for solid-state batteries?',
          run_id: 'run-earlier',
          score: 0.83,
        },
        {
          text: 'Manufacturing scalability is limited by dry-room requirements.',
          question: 'What are the biggest technical barriers for solid-state batteries?',
          run_id: 'run-earlier',
          score: 0.77,
        },
      ],
    })
    expect(screen.getByText('Research memory')).toBeInTheDocument()
    expect(screen.getByText('2 of 12 previous findings reused')).toBeInTheDocument()
    expect(screen.getByText(/Interface instability remains/)).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /biggest technical barriers/ })[0]).toHaveAttribute(
      'href',
      '/runs/run-earlier',
    )
    expect(screen.getByText('Relevance 0.83')).toBeInTheDocument()
  })

  it('says memory was disabled rather than showing an empty list', () => {
    renderWithRouter({ memory_enabled: false, memory_scope: 'NONE', memory_items: [] })
    expect(screen.getByText('Disabled for this run')).toBeInTheDocument()
    expect(screen.queryByText('Relevance')).not.toBeInTheDocument()
  })

  it('distinguishes nothing-relevant from a retrieval failure', () => {
    renderWithRouter({
      memory_enabled: true,
      memory_scope: 'PROJECT',
      memory_candidates: 9,
      project_memory_hits: 0,
      memory_items: [],
    })
    expect(screen.getByText('No relevant findings (9 considered)')).toBeInTheDocument()

    renderWithRouter({
      memory_enabled: true,
      memory_scope: 'PROJECT',
      memory_error: 'RuntimeError: embedding service unavailable',
      memory_items: [],
    })
    expect(screen.getByText('Retrieval failed')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('embedding service unavailable')
  })

  it('is hidden for runs recorded before project memory existed', () => {
    renderWithRouter({})
    expect(screen.queryByText('Research memory')).not.toBeInTheDocument()
  })
})
