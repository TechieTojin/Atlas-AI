type Listener = (event: MessageEvent) => void

/**
 * Minimal EventSource stand-in for tests. Emit named SSE events with
 * `instance.emit(type, data)`; trigger connection errors with `instance.fail()`.
 */
export class MockEventSource {
  static instances: MockEventSource[] = []

  static reset(): void {
    MockEventSource.instances = []
  }

  static latest(): MockEventSource {
    const instance = MockEventSource.instances[MockEventSource.instances.length - 1]
    if (!instance) throw new Error('No MockEventSource instance was created')
    return instance
  }

  readonly url: string
  readyState = 1
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onmessage: Listener | null = null

  private listeners = new Map<string, Set<Listener>>()

  constructor(url: string | URL) {
    this.url = String(url)
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: Listener): void {
    const existing = this.listeners.get(type) ?? new Set<Listener>()
    existing.add(listener)
    this.listeners.set(type, existing)
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener)
  }

  close(): void {
    this.readyState = 2
  }

  emit(type: string, data: unknown): void {
    const event = new MessageEvent(type, { data: JSON.stringify(data) })
    this.listeners.get(type)?.forEach((listener) => listener(event))
  }

  fail(): void {
    this.onerror?.(new Event('error'))
  }
}
