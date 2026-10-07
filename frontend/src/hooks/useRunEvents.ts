import type { RunEvent } from '../types'
import { useEventStream, type UseEventStreamOptions } from './useEventStream'

export type UseRunEventsOptions = UseEventStreamOptions

/**
 * Subscribes to the SSE stream for a run. Reconnects automatically on
 * connection errors and closes the stream once a terminal event arrives.
 */
export function useRunEvents(runId: string | undefined, options: UseRunEventsOptions): RunEvent[] {
  return useEventStream(runId ? `/api/runs/${runId}/events` : undefined, options)
}
