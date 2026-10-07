"""Run-scoped cancellation and hard wall-clock deadlines for blocking calls.

Research runs execute on worker threads and spend most of their time inside
blocking LLM HTTP requests. A cooperative flag checked between pipeline
stages cannot stop such a request, and the HTTP client's ``timeout`` is a
per-read limit (every streamed token resets it), not a total deadline.

:func:`run_abortable` runs a blocking operation on a helper thread and waits
for it with a real deadline. On timeout or run cancellation it invokes the
operation's ``abort`` callback (for Ollama: closing the request's HTTP
connection, which makes the server stop generating) and raises immediately.
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def _make_awake_clock():
    """Seconds of AWAKE time, monotonic, excluding system sleep/standby.

    ``time.monotonic()`` on Windows keeps counting through sleep (including
    Modern Standby): a laptop that slept 7.5 min mid-synthesis woke with its
    300 s deadline long expired and discarded the run's work. Deadlines and
    budgets measure work time, so they use the unbiased interrupt time,
    which excludes sleep. Linux CLOCK_MONOTONIC already excludes suspend.
    """
    import sys

    if sys.platform == "win32":
        try:
            import ctypes

            query = ctypes.windll.kernel32.QueryUnbiasedInterruptTime
            value = ctypes.c_ulonglong()
            if query(ctypes.byref(value)):

                def awake() -> float:
                    query(ctypes.byref(value))
                    return value.value / 10_000_000  # 100 ns units

                return awake
        except (AttributeError, OSError):
            pass
    return time.monotonic


awake_clock = _make_awake_clock()


class RunCancelledError(Exception):
    """The user cancelled the run; propagate without converting to failure."""


class StageTimeoutError(TimeoutError):
    """A pipeline stage exceeded its hard wall-clock deadline."""


class CancelScope:
    """Cancellation state plus the in-flight operations to abort for one run."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._aborters: dict[int, Callable[[], None]] = {}
        self._ids = itertools.count()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise RunCancelledError("Run was cancelled.")

    def cancel(self) -> None:
        """Mark cancelled and abort every registered in-flight operation."""
        self._event.set()
        with self._lock:
            aborters = list(self._aborters.values())
        for abort in aborters:
            _safe(abort)

    def register(self, abort: Callable[[], None]) -> int:
        """Register an aborter; aborts immediately if already cancelled."""
        with self._lock:
            token = next(self._ids)
            self._aborters[token] = abort
        if self._event.is_set():
            _safe(abort)
        return token

    def unregister(self, token: int) -> None:
        with self._lock:
            self._aborters.pop(token, None)


def _safe(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:  # aborting is best-effort; never mask the real outcome
        pass


def run_abortable(
    operation: Callable[[], T],
    abort: Callable[[], None],
    *,
    timeout: float | None = None,
    scope: CancelScope | None = None,
    label: str = "operation",
    join_seconds: float = 2.0,
    deadline_at: float | None = None,
) -> T:
    """Run ``operation`` with a hard deadline and run-cancellation support.

    The effective deadline is the EARLIEST of ``timeout`` seconds from now
    and ``deadline_at`` (an absolute :func:`awake_clock` time, e.g. the run
    budget). If it has already passed, no request is made. Raises
    :class:`RunCancelledError` on cancellation (even if a result arrived at
    the same moment) and :class:`StageTimeoutError` on deadline; in both
    cases ``abort`` is called first so the request stops server-side, and
    the caller regains control after at most ``join_seconds`` of grace.
    """
    if scope is not None:
        scope.check()
    candidates = [d for d in (
        awake_clock() + timeout if timeout and timeout > 0 else None,
        deadline_at,
    ) if d is not None]
    deadline = min(candidates) if candidates else None
    if deadline is not None and deadline <= awake_clock():
        raise StageTimeoutError(f"{label} skipped: the run's time budget is exhausted.")

    done = threading.Event()
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = operation()
        except BaseException as exc:  # re-raised on the calling thread
            box["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=target, name=f"atlas-{label}", daemon=True)
    token = scope.register(abort) if scope is not None else None
    started = awake_clock()
    try:
        worker.start()
        # Wake on completion, cancellation, or deadline — whichever is first.
        while not done.wait(_POLL_SECONDS):
            if scope is not None and scope.cancelled:
                _safe(abort)  # idempotent; also done by scope.cancel()
                worker.join(join_seconds)
                raise RunCancelledError("Run was cancelled.")
            if deadline is not None and awake_clock() >= deadline:
                _safe(abort)
                worker.join(join_seconds)
                limit = deadline - started
                raise StageTimeoutError(
                    f"{label} exceeded its {limit:.0f}s time limit."
                )
        if scope is not None and scope.cancelled:
            raise RunCancelledError("Run was cancelled.")
        if "error" in box:
            raise box["error"]
        return box["result"]
    finally:
        if token is not None:
            scope.unregister(token)


_POLL_SECONDS = 0.2
