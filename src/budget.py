"""FAST run-budget allocation: report completion > optional critique > repair.

Synthesis gets a protected time reserve estimated from THIS run's measured
model speed (Ollama's own prompt-eval and generation rates from earlier
calls), so the reserve adapts when the laptop is slower (e.g. on battery).
The critic runs only if it can finish without invading that reserve, and it
is bounded so it cannot. Synthesis may use everything left in the run budget
except a small finalization margin; citation repair is never allowed to start
unless its own estimate fits.

Calibration (real qwen3:4b runs on the reference laptop, see run metrics):
- planner generation 4.5-5.0 tok/s; synthesis/critic with ~1-1.4k-token
  prompts generated at 0.64-0.80x of that, prompt eval at ~0.75-1.0x.
- ~4.5 characters per prompt token; 500-word reports ~500-700 output tokens.
"""

from __future__ import annotations

from typing import Callable

from src.cancellation import awake_clock
from src.config import AtlasConfig

# Fallback rates (tok/s) if no call in this run has reported statistics yet:
# medians of the planner calls of real FAST runs.
DEFAULT_PREFILL_TPS = 25.0
DEFAULT_GENERATE_TPS = 4.5
# Long prompts are slower than the short planner prompt that rates come from.
LONG_CONTEXT_PREFILL_FACTOR = 0.75
LONG_CONTEXT_GENERATE_FACTOR = 0.62
CHARS_PER_TOKEN = 4.5
SYNTHESIS_PROMPT_OVERHEAD_CHARS = 2400  # system prompt, template, question
CRITIC_PROMPT_OVERHEAD_CHARS = 2000
CRITIC_OUTPUT_TOKENS = 240
TOKENS_PER_REPORT_WORD = 1.35
FINALIZATION_MARGIN_SECONDS = 15.0


class RunBudget:
    """Budget decisions for one run (only meaningful with a run deadline)."""

    def __init__(
        self,
        config: AtlasConfig,
        calls: Callable[[], list[dict]],
        deadline: Callable[[], float | None],
    ) -> None:
        self._config = config
        self._calls = calls
        self._deadline = deadline
        self.decisions: dict = {}

    # -- measured speed -----------------------------------------------------

    def rates(self) -> tuple[float, float]:
        """(prompt-eval tok/s, generation tok/s) measured in this run."""
        prompt_tokens = prompt_s = output_tokens = gen_s = 0.0
        for call in self._calls():
            if not call.get("tokens_available", call.get("prompt_tokens") is not None):
                continue
            # Ollama's own durations include time the machine was asleep;
            # a call that spanned a suspension would report an absurdly slow
            # model (live: an 11 h overnight sleep produced a 20,151 s critic
            # estimate). Such calls are excluded from the measurement.
            if (call.get("suspended_ms") or 0) > 0.05 * max(call.get("duration_ms") or 1, 1):
                continue
            if call.get("prompt_eval_ms") and call.get("prompt_tokens"):
                prompt_tokens += call["prompt_tokens"]
                prompt_s += call["prompt_eval_ms"] / 1000
            if call.get("eval_ms") and call.get("output_tokens"):
                output_tokens += call["output_tokens"]
                gen_s += call["eval_ms"] / 1000
        prefill = prompt_tokens / prompt_s if prompt_s > 1 else DEFAULT_PREFILL_TPS
        generate = output_tokens / gen_s if gen_s > 1 else DEFAULT_GENERATE_TPS
        return prefill, generate

    def estimate_seconds(self, prompt_chars: float, output_tokens: float) -> float:
        prefill, generate = self.rates()
        prompt_tokens = prompt_chars / CHARS_PER_TOKEN
        return (prompt_tokens / (prefill * LONG_CONTEXT_PREFILL_FACTOR)
                + output_tokens / (generate * LONG_CONTEXT_GENERATE_FACTOR))

    # -- estimates ---------------------------------------------------------

    def synthesis_estimate(self) -> float:
        cfg = self._config
        return self.estimate_seconds(
            SYNTHESIS_PROMPT_OVERHEAD_CHARS + cfg.synthesis_context_chars,
            cfg.report_target_words * TOKENS_PER_REPORT_WORD,
        )

    def critic_estimate(self) -> float:
        cfg = self._config
        return self.estimate_seconds(
            CRITIC_PROMPT_OVERHEAD_CHARS
            + cfg.max_evidence_for_critic * cfg.critic_chars_per_evidence,
            CRITIC_OUTPUT_TOKENS,
        )

    def repair_estimate(self) -> float:
        cfg = self._config
        draft_tokens = cfg.report_target_words * TOKENS_PER_REPORT_WORD
        return self.estimate_seconds(
            CRITIC_PROMPT_OVERHEAD_CHARS + 300 * cfg.max_evidence_for_synthesis
            + draft_tokens * CHARS_PER_TOKEN,
            draft_tokens,
        )

    def synthesis_reserve(self) -> float:
        return self.synthesis_estimate() + FINALIZATION_MARGIN_SECONDS

    def remaining(self) -> float | None:
        deadline = self._deadline()
        return None if deadline is None else deadline - awake_clock()

    # -- decisions ---------------------------------------------------------

    def critic_skip_reason(self) -> str:
        """Non-empty if the critic must be skipped to protect synthesis."""
        remaining = self.remaining()
        if remaining is None:
            return ""
        reserve = self.synthesis_reserve()
        needed = self.critic_estimate()
        self.decisions.update(
            critic_check_remaining_s=round(remaining),
            critic_estimate_s=round(needed),
            synthesis_reserve_s=round(reserve),
        )
        if remaining - needed < reserve:
            self.decisions["critic"] = "skipped"
            return (
                f"skipped to protect the synthesis time reserve ({remaining:.0f}s "
                f"left; critic needs ~{needed:.0f}s, report needs ~{reserve:.0f}s)"
            )
        self.decisions["critic"] = "ran"
        return ""

    def critic_deadline(self) -> float | None:
        """The critic may never run into the synthesis reserve."""
        deadline = self._deadline()
        return None if deadline is None else deadline - self.synthesis_reserve()

    def synthesis_deadline(self) -> float | None:
        """Synthesis may use the whole remaining budget minus finalization."""
        deadline = self._deadline()
        if deadline is None:
            return None
        if "synthesis_budget_s" not in self.decisions:
            self.decisions["synthesis_budget_s"] = round(
                deadline - FINALIZATION_MARGIN_SECONDS - awake_clock()
            )
        return deadline - FINALIZATION_MARGIN_SECONDS

    def repair_check(self) -> bool:
        remaining = self.remaining()
        if remaining is None:
            return True
        fits = remaining - FINALIZATION_MARGIN_SECONDS >= self.repair_estimate()
        self.decisions["repair"] = "allowed" if fits else "skipped"
        return fits

    def synthesis_retry_check(self) -> bool:
        """A second synthesis attempt (after an empty draft) only if it fits."""
        remaining = self.remaining()
        if remaining is None:
            return True
        fits = remaining - FINALIZATION_MARGIN_SECONDS >= self.synthesis_estimate()
        self.decisions["synthesis_retry"] = "allowed" if fits else "skipped"
        return fits

    def repair_deadline(self) -> float | None:
        deadline = self._deadline()
        return None if deadline is None else deadline - FINALIZATION_MARGIN_SECONDS
