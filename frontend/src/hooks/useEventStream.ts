import { useEffect, useRef, useState } from 'react'
import type { RunEvent } from '../types'
import { EVENT_TYPES, TERMINAL_EVENT_TYPES } from '../types'

const RECONNECT_DELAY_MS = 2000

export interface UseEventStreamOptions {
  enabled: boolean
  onEvent?: (event: RunEvent) => void
  onTerminal?: (event: RunEvent) => void
}

/**
 * Subscribes to an Atlas SSE stream. Reconnects automatically on connection
 * errors and closes the stream once a terminal event arrives (run,
 * follow-up, comparison, or knowledge-graph terminal types).
 */
export function useEventStream(
  url: string | undefined,
  options: UseEventStreamOptions,
): RunEvent[] {
  const [events, setEvents] = useState<RunEvent[]>([])
  const onEventRef = useRef(options.onEvent)
  const onTerminalRef = useRef(options.onTerminal)
  onEventRef.current = options.onEvent
  onTerminalRef.current = options.onTerminal
  const { enabled } = options

  useEffect(() => {
    if (!url || !enabled) return

    let source: EventSource | null = null
    let retryTimer: number | undefined
    let stopped = false

    setEvents([])

    const handleMessage = (raw: MessageEvent) => {
      let event: RunEvent
      try {
        event = JSON.parse(String(raw.data)) as RunEvent
      } catch {
        return
      }
      setEvents((previous) => {
        if (previous.some((existing) => existing.seq === event.seq)) return previous
        return [...previous, event].sort((a, b) => a.seq - b.seq)
      })
      onEventRef.current?.(event)
      if (TERMINAL_EVENT_TYPES.includes(event.type)) {
        stopped = true
        source?.close()
        onTerminalRef.current?.(event)
      }
    }

    const connect = () => {
      if (stopped) return
      source = new EventSource(url)
      for (const type of EVENT_TYPES) {
        source.addEventListener(type, handleMessage)
      }
      source.onerror = () => {
        source?.close()
        if (!stopped) {
          retryTimer = window.setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }
    }

    connect()

    return () => {
      stopped = true
      source?.close()
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
    }
  }, [url, enabled])

  return events
}
