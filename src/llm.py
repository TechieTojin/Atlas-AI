"""LLM factory and Ollama preflight checks.

Keeps agents decoupled from any concrete provider: the workflow calls
:func:`create_llm` once and injects the result. ``reasoning=False`` disables
Qwen3's thinking mode so raw reasoning text never reaches reports or logs.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from src.config import AtlasConfig, ConfigError

logger = logging.getLogger(__name__)

_PREFLIGHT_TIMEOUT_SECONDS = 5.0


class OllamaNotAvailableError(ConfigError):
    """Raised when the Ollama server or the configured model is unavailable."""


STAGES = ("planner", "critic", "synthesis", "repair", "website_chat", "default")


def stage_limits(config: AtlasConfig, stage: str) -> tuple[int | None, int | None]:
    """(max output tokens, hard wall-clock deadline seconds) for a stage.

    The deadline is TOTAL request time, enforced by :class:`AbortableLLM`
    (the HTTP client's own timeout is only per-read: a streaming generation
    resets it with every token, so it can never bound a stage). ``None``
    means no cap / no deadline. Values come from the mode-specific config.
    """
    caps = {
        "planner": (config.planner_max_tokens, config.planner_timeout_seconds),
        "critic": (config.critic_max_tokens, config.critic_timeout_seconds),
        "synthesis": (config.synthesis_max_tokens, config.synthesis_timeout_seconds),
        "repair": (config.synthesis_max_tokens, config.repair_timeout_seconds),
        "comparison": (
            config.comparison_max_tokens,
            config.comparison_timeout_seconds,
        ),
        "website_chat": (
            config.website_chat_max_tokens,
            config.website_chat_timeout_seconds,
        ),
    }
    tokens, deadline = caps.get(stage, (None, 0))
    return (tokens or None), (deadline or None)


def create_llm(
    config: AtlasConfig,
    reasoning: bool = False,
    stage: str = "default",
    call_sink: "LLMCallSink | None" = None,
) -> Any:
    """Instantiate the configured chat model (currently Ollama only).

    ``reasoning`` controls Qwen3's thinking mode. Thinking content is
    returned by the Ollama API in a separate field that Atlas never reads,
    logs, or renders — only the final answer/structured output is used.
    DEEP mode enables it for structured planner/critic calls (better field
    reliability); FAST disables it everywhere because on CPU the hidden
    thinking tokens dominated stage latency.

    ``stage`` selects the per-stage output cap and timeout; ``call_sink``
    records Ollama's per-call token/timing statistics for run metrics.
    """
    if config.llm_provider != "ollama":
        raise ConfigError(
            f"Unsupported ATLAS_LLM_PROVIDER {config.llm_provider!r}."
        )
    from langchain_ollama import ChatOllama

    max_tokens, _deadline = stage_limits(config, stage)
    return ChatOllama(
        model=config.model,
        base_url=config.ollama_base_url,
        temperature=config.temperature,
        reasoning=reasoning,
        num_predict=max_tokens,
        # One context size for every stage: changing num_ctx between requests
        # forces Ollama to reload the model. Ollama's 4096 default silently
        # truncated large DEEP prompts.
        num_ctx=config.llm_num_ctx,
        keep_alive=config.llm_keep_alive,
        callbacks=[LLMCallRecorder(stage, call_sink)] if call_sink is not None else None,
        # Per-READ timeout only: a backstop for dead connections. Total stage
        # deadlines and cancellation are enforced by AbortableLLM.
        client_kwargs={"timeout": config.llm_timeout_seconds},
    )


def abort_chat_model(model: Any) -> None:
    """Abort a model's in-flight request by closing its HTTP connection.

    Ollama stops generating (and drops a queued request) when the client
    disconnects, so closing the connection is a request-scoped abort that
    never restarts Ollama or touches other runs. Models may also expose
    their own ``abort()`` (used by test doubles).
    """
    custom = getattr(model, "abort", None)
    if callable(custom):
        custom()
        return
    ollama_client = getattr(model, "_client", None)
    http_client = getattr(ollama_client, "_client", None)
    close = getattr(http_client, "close", None)
    if callable(close):
        close()


class AbortableLLM:
    """A chat-model handle whose every request has a hard deadline and can be
    aborted by run cancellation.

    Each request gets a FRESH underlying model (and HTTP connection) from
    ``build``, so aborting one request never affects another, and a handle
    stays usable after an abort (e.g. for the planner's repair attempt).

    The effective deadline of each request is the earliest of the stage
    limit and the run's remaining budget (``run_deadline`` returns an
    absolute awake-clock time, or None). Each call's outcome (ok, timed out,
    skipped, cancelled, failed) is recorded in ``sink`` so aborted calls are
    visible in metrics instead of silently missing.
    """

    def __init__(
        self,
        build: Any,
        *,
        timeout: float | None,
        scope: Any = None,
        label: str = "llm",
        run_deadline: Any = None,
        sink: "LLMCallSink | None" = None,
        _transform: Any = None,
    ) -> None:
        self._build = build
        self._timeout = timeout
        self._scope = scope
        self._label = label
        self._run_deadline = run_deadline
        self._sink = sink
        self._transform = _transform  # e.g. lambda m: m.with_structured_output(S)

    def invoke(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        from src.cancellation import (
            RunCancelledError,
            StageTimeoutError,
            awake_clock,
            run_abortable,
        )

        deadline_at = self._run_deadline() if self._run_deadline else None
        effective = self._timeout
        if deadline_at is not None:
            remaining = deadline_at - awake_clock()
            effective = remaining if effective is None else min(effective, remaining)
        mark = self._sink.mark() if self._sink is not None else 0
        model = None
        try:
            if effective is not None and effective <= 0:
                raise StageTimeoutError(
                    f"{self._label} skipped: the run's time budget is exhausted."
                )
            model = self._build()
            runnable = self._transform(model) if self._transform else model
            result = run_abortable(
                lambda: runnable.invoke(messages, *args, **kwargs),
                lambda: abort_chat_model(model),
                timeout=self._timeout,
                deadline_at=deadline_at,
                scope=self._scope,
                label=self._label,
            )
        except StageTimeoutError:
            self._annotate(mark, "skipped" if model is None else "timed_out", effective)
            raise
        except RunCancelledError:
            self._annotate(mark, "cancelled", effective)
            raise
        except Exception:
            self._annotate(mark, "failed", effective)
            raise
        self._annotate(mark, "ok", effective)
        return result

    def _annotate(self, mark: int, outcome: str, limit: float | None) -> None:
        if self._sink is not None:
            self._sink.annotate_since(
                mark,
                self._label,
                outcome=outcome,
                limit_s=round(limit, 1) if limit is not None else None,
            )

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "AbortableLLM":
        return AbortableLLM(
            self._build,
            timeout=self._timeout,
            scope=self._scope,
            label=self._label,
            run_deadline=self._run_deadline,
            sink=self._sink,
            _transform=lambda model: model.with_structured_output(schema, **kwargs),
        )


def is_llm_timeout(exc: BaseException) -> bool:
    """True if an exception (or its cause chain) is a request timeout."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError) or "Timeout" in type(current).__name__:
            return True
        current = current.__cause__ or current.__context__
    return False


def is_malformed_output(exc: BaseException) -> bool:
    """True for structured-output parse/validation failures (model quality)."""
    from langchain_core.exceptions import OutputParserException
    from pydantic import ValidationError

    return isinstance(exc, (OutputParserException, ValidationError))


def make_llm(
    factory: Any,
    config: AtlasConfig,
    *,
    reasoning: bool,
    stage: str = "default",
    call_sink: "LLMCallSink | None" = None,
) -> Any:
    """Call an LLM factory, passing ``stage``/``call_sink`` only if supported.

    Keeps injected factories with the original ``(config, reasoning)``
    signature working unchanged.
    """
    import inspect

    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        params = {}
    accepts_any = any(p.kind is p.VAR_KEYWORD for p in params.values())
    kwargs: dict[str, Any] = {"reasoning": reasoning}
    if accepts_any or "stage" in params:
        kwargs["stage"] = stage
    if accepts_any or "call_sink" in params:
        kwargs["call_sink"] = call_sink
    return factory(config, **kwargs)


class LLMCallSink:
    """Thread-safe per-run collector of LLM call statistics."""

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self.calls: list[dict] = []

    def add(self, record: dict) -> None:
        with self._lock:
            self.calls.append(record)

    def mark(self) -> int:
        with self._lock:
            return len(self.calls)

    def annotate_since(self, mark: int, stage: str, **fields: Any) -> None:
        """Attach outcome fields to this stage's call recorded after ``mark``.

        If the request produced no record (skipped before starting, or its
        thread had not finished within the abort grace), one is added so the
        call still appears, with token statistics marked unavailable.
        """
        with self._lock:
            for record in reversed(self.calls[mark:]):
                if record.get("stage") == stage:
                    record.update(fields)
                    return
            self.calls.append(
                {"stage": stage, "duration_ms": 0, "input_chars": 0,
                 "prompt_tokens": None, "output_tokens": None,
                 "tokens_available": False, **fields}
            )

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(c) for c in self.calls]

    def summary(self) -> dict:
        calls = self.snapshot()
        by_stage: dict[str, dict] = {}
        for call in calls:
            stage = by_stage.setdefault(
                call["stage"],
                {"calls": 0, "ms": 0, "input_chars": 0, "prompt_tokens": 0,
                 "output_tokens": 0, "errors": 0, "tokens_available": True,
                 "suspended_ms": 0, "outcomes": []},
            )
            stage["calls"] += 1
            stage["ms"] += call.get("duration_ms", 0)
            stage["input_chars"] += call.get("input_chars", 0)
            stage["suspended_ms"] += call.get("suspended_ms") or 0
            if _tokens_available(call):
                stage["prompt_tokens"] += call.get("prompt_tokens") or 0
                stage["output_tokens"] += call.get("output_tokens") or 0
            else:
                # Ollama reports counts only in its final message; an aborted
                # request has none. Never present that as a genuine zero.
                stage["tokens_available"] = False
            stage["errors"] += 1 if call.get("error") else 0
            if call.get("outcome"):
                stage["outcomes"].append(call["outcome"])
        return {
            "llm_calls": len(calls),
            "llm_prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
            "llm_output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
            "llm_tokens_complete": all(_tokens_available(c) for c in calls),
            "llm_stage_stats": by_stage,
        }


def _tokens_available(call: dict) -> bool:
    if "tokens_available" in call:
        return bool(call["tokens_available"])
    return call.get("prompt_tokens") is not None  # records from older runs


def _ns_to_ms(value: Any) -> int | None:
    return int(value / 1_000_000) if isinstance(value, (int, float)) else None


class LLMCallRecorder(BaseCallbackHandler):
    """LangChain callback recording one stage's calls into an LLMCallSink.

    Captures wall time, input size, request phases (time to first streamed
    token, chunks received), time the machine was suspended during the call,
    and Ollama's own statistics (prompt/output tokens, prompt-eval /
    generation / model-load durations). Only sizes, counts, and timings are
    recorded: never prompt or output text, and never thinking content.
    """

    def __init__(self, stage: str, sink: LLMCallSink) -> None:
        import threading

        super().__init__()
        self.stage = stage
        self._sink = sink
        self._lock = threading.Lock()
        self._calls: dict[Any, dict] = {}

    def _begin(self, run_id, chars: int) -> None:
        import time

        from src.cancellation import awake_clock

        with self._lock:
            self._calls[run_id] = {
                "wall": time.perf_counter(), "awake": awake_clock(),
                "chars": chars, "first_token_ms": None, "chunks": 0,
            }

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs) -> None:
        self._begin(run_id, sum(
            len(m.content) if isinstance(m.content, str) else len(str(m.content))
            for batch in messages
            for m in batch
        ))

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        self._begin(run_id, sum(len(p) for p in prompts))

    def on_llm_new_token(self, token, *, run_id, **kwargs) -> None:
        import time

        with self._lock:
            state = self._calls.get(run_id)
            if state is None:
                return
            state["chunks"] += 1
            if state["first_token_ms"] is None:
                state["first_token_ms"] = int((time.perf_counter() - state["wall"]) * 1000)

    def _finish(self, run_id) -> dict:
        import time

        from src.cancellation import awake_clock

        with self._lock:
            state = self._calls.pop(run_id, None)
        if state is None:
            return {"stage": self.stage, "duration_ms": 0, "input_chars": 0}
        wall_ms = int((time.perf_counter() - state["wall"]) * 1000)
        awake_ms = int((awake_clock() - state["awake"]) * 1000)
        return {
            "stage": self.stage,
            "duration_ms": wall_ms,
            "input_chars": state["chars"],
            "first_token_ms": state["first_token_ms"],
            "streamed_chunks": state["chunks"],
            # Wall time the machine spent asleep during this call.
            "suspended_ms": max(0, wall_ms - awake_ms),
        }

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        record = self._finish(run_id)
        record.update(prompt_tokens=None, output_tokens=None, tokens_available=False)
        try:
            generation = response.generations[0][0]
            message = getattr(generation, "message", None)
            meta = dict(getattr(message, "response_metadata", {}) or {})
            usage = getattr(message, "usage_metadata", None) or {}
            content = getattr(message, "content", "") or getattr(generation, "text", "")
            prompt_tokens = meta.get("prompt_eval_count") or usage.get("input_tokens")
            output_tokens = meta.get("eval_count") or usage.get("output_tokens")
            record.update(
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                tokens_available=prompt_tokens is not None and output_tokens is not None,
                prompt_eval_ms=_ns_to_ms(meta.get("prompt_eval_duration")),
                eval_ms=_ns_to_ms(meta.get("eval_duration")),
                load_ms=_ns_to_ms(meta.get("load_duration")),
                output_chars=len(content) if isinstance(content, str) else 0,
                done_reason=meta.get("done_reason"),
            )
        except (IndexError, AttributeError, TypeError):
            pass
        self._sink.add(record)

    def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        record = self._finish(run_id)
        record.update(
            error=type(error).__name__,
            prompt_tokens=None,
            output_tokens=None,
            tokens_available=False,
            # No streamed token yet means the request was queued in Ollama or
            # still evaluating the prompt (indistinguishable client-side).
            phase="generating" if record.get("streamed_chunks") else "waiting_for_first_token",
        )
        self._sink.add(record)


def _installed_models(tags_payload: dict) -> list[str]:
    models = tags_payload.get("models")
    if not isinstance(models, list):
        return []
    return [
        str(m.get("name") or m.get("model") or "")
        for m in models
        if isinstance(m, dict)
    ]


def check_ollama(
    base_url: str,
    model: str,
    http_get: Any | None = None,
) -> None:
    """Verify the Ollama server is reachable and the model is installed.

    Raises :class:`OllamaNotAvailableError` with actionable guidance on
    failure. ``http_get`` is injectable for tests; the default uses httpx.
    """
    if http_get is None:
        import httpx

        def http_get(url: str) -> Any:  # noqa: F811 - deliberate default
            return httpx.get(url, timeout=_PREFLIGHT_TIMEOUT_SECONDS)

    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        response = http_get(url)
        payload = response.json()
    except Exception as exc:
        raise OllamaNotAvailableError(
            f"Ollama is not reachable at {base_url}. "
            "Start Ollama (run 'ollama serve' or launch the Ollama app) "
            "and try again."
        ) from exc

    names = _installed_models(payload)
    # "qwen3:8b" should match itself exactly; a bare name like "qwen3"
    # matches any installed tag of that model.
    if not any(n == model or n.split(":")[0] == model for n in names):
        raise OllamaNotAvailableError(
            f"Model {model!r} is not installed in Ollama. "
            f"Run: ollama pull {model}"
        )
    logger.debug("Ollama preflight OK: %s serving %s", base_url, model)


def preflight(config: AtlasConfig) -> None:
    """Provider-aware preflight before a live run."""
    if config.llm_provider == "ollama":
        check_ollama(config.ollama_base_url, config.model)
