import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeEvent, resetEventSeq } from '../test/fixtures'
import { MockEventSource } from '../test/mockEventSource'
import { useRunEvents } from './useRunEvents'

describe('useRunEvents', () => {
  beforeEach(() => {
    MockEventSource.reset()
    resetEventSeq()
    vi.stubGlobal('EventSource', MockEventSource)
  })

  it('collects streamed events in sequence order and dedupes by seq', () => {
    const { result } = renderHook(() => useRunEvents('run-1', { enabled: true }))
    const source = MockEventSource.latest()
    expect(source.url).toBe('/api/runs/run-1/events')

    const first = makeEvent('PLANNING_STARTED')
    const second = makeEvent('PLAN_CREATED')
    act(() => {
      source.emit('PLAN_CREATED', second)
      source.emit('PLANNING_STARTED', first)
      source.emit('PLANNING_STARTED', first) // duplicate
    })

    expect(result.current.map((event) => event.type)).toEqual([
      'PLANNING_STARTED',
      'PLAN_CREATED',
    ])
  })

  it('closes the stream and fires onTerminal when a terminal event arrives', () => {
    const onTerminal = vi.fn()
    renderHook(() => useRunEvents('run-1', { enabled: true, onTerminal }))
    const source = MockEventSource.latest()

    act(() => {
      source.emit('RUN_COMPLETED', makeEvent('RUN_COMPLETED'))
    })

    expect(onTerminal).toHaveBeenCalledTimes(1)
    expect(source.readyState).toBe(2)
  })

  it('reconnects after a connection error', () => {
    vi.useFakeTimers()
    try {
      renderHook(() => useRunEvents('run-1', { enabled: true }))
      expect(MockEventSource.instances.length).toBe(1)

      act(() => {
        MockEventSource.latest().fail()
        vi.advanceTimersByTime(2500)
      })

      expect(MockEventSource.instances.length).toBe(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not open a stream when disabled', () => {
    renderHook(() => useRunEvents('run-1', { enabled: false }))
    expect(MockEventSource.instances.length).toBe(0)
  })
})
