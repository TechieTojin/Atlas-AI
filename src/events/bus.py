"""Thread-safe in-process event bus for research runs.

Runs execute on worker threads while the CLI, API/SSE streams, and tests
consume events. Each run keeps an in-memory history (for late subscribers)
and fans events out to per-subscriber queues. Durable history is persisted
separately by the research service.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable

from src.events.models import EventType, RunEvent

# Sentinel a subscriber queue receives when the run's stream closes.
STREAM_END = None


class RunEventBus:
    """Publish/subscribe hub keyed by run id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: dict[str, list[RunEvent]] = {}
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._seq: dict[str, int] = {}
        self._listeners: list[Callable[[RunEvent], None]] = []

    def add_listener(self, listener: Callable[[RunEvent], None]) -> None:
        """Register a global synchronous listener (e.g. persistence)."""
        self._listeners.append(listener)

    def publish(self, event: RunEvent) -> RunEvent:
        with self._lock:
            seq = self._seq.get(event.run_id, 0) + 1
            self._seq[event.run_id] = seq
            event = event.model_copy(update={"seq": seq})
            self._history.setdefault(event.run_id, []).append(event)
            subscribers = list(self._subscribers.get(event.run_id, ()))
        for listener in self._listeners:
            listener(event)
        for q in subscribers:
            q.put(event)
        if event.type.is_terminal:
            self._close(event.run_id)
        return event

    def _close(self, run_id: str) -> None:
        with self._lock:
            subscribers = self._subscribers.pop(run_id, [])
        for q in subscribers:
            q.put(STREAM_END)

    def history(self, run_id: str) -> list[RunEvent]:
        with self._lock:
            return list(self._history.get(run_id, ()))

    def subscribe(self, run_id: str) -> tuple[list[RunEvent], queue.Queue | None]:
        """Return (history so far, live queue or None if already terminal)."""
        with self._lock:
            history = list(self._history.get(run_id, ()))
            if history and history[-1].type.is_terminal:
                return history, None
            q: queue.Queue = queue.Queue()
            self._subscribers.setdefault(run_id, []).append(q)
            return history, q

    def unsubscribe(self, run_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(run_id)
            if subs and q in subs:
                subs.remove(q)


class RunEmitter:
    """Convenience emitter bound to one run, injected into the workflow."""

    def __init__(self, bus: RunEventBus, run_id: str) -> None:
        self._bus = bus
        self.run_id = run_id

    def emit(
        self,
        type_: EventType,
        message: str = "",
        agent: str = "",
        iteration: int = 0,
        **payload,
    ) -> RunEvent:
        return self._bus.publish(
            RunEvent(
                type=type_,
                run_id=self.run_id,
                agent=agent,
                message=message,
                iteration=iteration,
                payload=payload,
            )
        )


class NullEmitter:
    """No-op emitter so the workflow runs without event infrastructure."""

    run_id = ""

    def emit(self, *args, **kwargs):  # noqa: D102
        return None
