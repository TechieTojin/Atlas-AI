"""FAST / DEEP research mode profiles.

Both modes run the identical LangGraph architecture; a profile only adjusts
budgets on the run's config. DEEP keeps the user's configured values.

FAST is an explicit performance budget derived from measurements on the
reference machine (qwen3:4b on a 4-core laptop CPU via Ollama): prompt
evaluation runs at ~21 tok/s and generation at ~3.3-5 tok/s, so every output
token costs ~0.2-0.3 s and every 1,000 characters of context ~12 s. Measured
before this profile, Qwen's hidden thinking alone turned a 77 s planner call
into 11.5 min and a 164 s critic call into 19 min. FAST therefore:

- disables thinking for every stage,
- caps output tokens per stage and bounds the evidence context,
- gives each stage a hard timeout with a clean fallback,
- enforces a run-level budget that skips optional work (critic pass,
  citation repair) rather than overrunning.
"""

from __future__ import annotations

import dataclasses

from src.config import AtlasConfig
from src.models.runs import RunMode

# Budgets that FAST may only LOWER relative to the user's config.
_FAST_CAPS = {
    "max_research_iterations": 1,
    "max_queries_per_iteration": 3,
    "search_results_per_query": 3,
    "max_evidence_for_critic": 6,
    "max_evidence_for_synthesis": 6,
    "page_fetch_per_query": 1,  # conservative full-page budget
}

# Values FAST sets outright.
_FAST_FIXED = {
    "report_target_words": 500,
    "ollama_structured_reasoning": False,
    # qwen3:4b (2507) is thinking-only: with think:false it still deliberates
    # in plain prose before free-text answers, and /no_think, an empty-think
    # prefill, and the raw template all failed to stop it. A JSON grammar
    # does: synthesis is requested as {"report": "..."} in FAST.
    "synthesis_json_mode": True,
    "planner_max_tasks": 3,
    # Output-token caps (~0.25 s each at measured generation speed).
    "planner_max_tokens": 450,
    "critic_max_tokens": 320,
    "synthesis_max_tokens": 900,
    # Hard word ceiling stated to the model (it overshot a 500-word target 3x).
    "synthesis_max_words": 600,
    # Per-stage hard timeouts (seconds).
    "planner_timeout_seconds": 150,
    "critic_timeout_seconds": 150,
    # Synthesis is bounded by the run budget instead of a fixed cap: it may
    # use everything left except a finalization margin, and the critic is
    # skipped when it would invade a reserve measured from this run's model
    # speed (src/budget.py). A fixed 300 s cap cut off a slow-but-healthy
    # synthesis with 150 s of budget still unused (run efa29d36).
    "synthesis_timeout_seconds": 0,
    "budget_allocation": True,
    "synthesis_clean_evidence": True,
    "repair_timeout_seconds": 180,
    # Bounded evidence context per LLM stage.
    "critic_chars_per_evidence": 350,
    "synthesis_chars_per_source": 700,
    "synthesis_context_chars": 4200,
    # Whole-run budget: optional stages are skipped rather than overrun.
    "run_budget_seconds": 540,
}


def apply_mode(config: AtlasConfig, mode: RunMode) -> AtlasConfig:
    """Return a config with the mode profile applied (DEEP = unchanged)."""
    if mode is RunMode.FAST:
        overrides = {k: min(v, getattr(config, k)) for k, v in _FAST_CAPS.items()}
        overrides.update(_FAST_FIXED)
        return dataclasses.replace(config, **overrides)
    return config
