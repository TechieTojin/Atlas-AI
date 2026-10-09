"""Centralized configuration for Atlas.

All runtime settings come from environment variables (optionally loaded
from a local ``.env`` file). Secrets are never stored in code.

Default LLM provider is local Ollama (no API key required); Tavily is the
only required external credential.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MAX_RESEARCH_ITERATIONS = 3
DEFAULT_SEARCH_RESULTS_PER_QUERY = 5
DEFAULT_MAX_QUERIES_PER_ITERATION = 5
# A critic score below this can never be "sufficient"; contradictory
# structured output (SYNTHESIZE + low score) is normalized to MORE_RESEARCH.
DEFAULT_SUFFICIENCY_THRESHOLD = 7
# Evidence items sent through the local LLM context (full set stays in state).
DEFAULT_MAX_EVIDENCE_FOR_CRITIC = 12
DEFAULT_MAX_EVIDENCE_FOR_SYNTHESIS = 12
DEFAULT_REPORT_TARGET_WORDS = 1000
# Qwen3 fills structured fields (e.g. the critic score) unreliably with
# thinking disabled, so reasoning stays on for structured planner/critic
# calls. It is kept off for synthesis, where it only slows generation.
DEFAULT_OLLAMA_STRUCTURED_REASONING = True
# V2: persistence, uploads, RAG, and research memory.
DEFAULT_DATA_DIR = "data"
DEFAULT_MEMORY_TTL_HOURS = 72
DEFAULT_MAX_UPLOAD_MB = 25
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_RAG_CHUNKS_PER_QUERY = 4
DEFAULT_CHUNK_SIZE_CHARS = 1200
DEFAULT_CHUNK_OVERLAP_CHARS = 150
# Hard ceiling per LLM request so a wedged Ollama can't hang a run forever.
DEFAULT_LLM_TIMEOUT_SECONDS = 900
# V3: full-page web research (0 disables page fetching entirely).
DEFAULT_PAGE_FETCH_PER_QUERY = 2
DEFAULT_PAGE_TIMEOUT_SECONDS = 15
DEFAULT_PAGE_MAX_BYTES = 1_500_000
DEFAULT_PAGE_CHUNKS_PER_PAGE = 2
# V3: semantic research memory.
DEFAULT_MEMORY_SEMANTIC_THRESHOLD = 0.83
# Question-to-finding relevance for PROJECT memory (a different scale from
# the query-to-query threshold above). Measured with nomic-embed-text on
# real Atlas runs: a follow-up scored 0.75-0.83 against its own project's
# findings, while off-topic findings in the SAME project (solar vs.
# batteries) peaked at 0.58 and unrelated questions at 0.39.
DEFAULT_PROJECT_MEMORY_THRESHOLD = 0.65
DEFAULT_PROJECT_MEMORY_ITEMS = 4
# V3: knowledge graph bounds.
# A comparison is one narrative pass over a bounded evidence set. Both numbers
# come from measuring this exact workload on qwen3:4b/CPU rather than from a
# guess: a ~2.1k-token prompt prefills at ~18 tok/s (113s), and generation runs
# at ~1.8-2 tok/s, so 900 output tokens take ~500s and produce a ~2.8k-character
# report. End to end that is ~605s measured through the real client, so the
# budget is that plus roughly a quarter for a busier machine. A 600s budget was
# tried first and clipped a comparison that was seconds from finishing.
#
# The output cap is what guarantees termination; the deadline is the backstop
# for a model that stalls or a machine slower than the one measured. Before
# this, the stage had neither, and a single comparison ran past 20 minutes.
DEFAULT_COMPARISON_MAX_TOKENS = 900
DEFAULT_COMPARISON_TIMEOUT_SECONDS = 750
# Website Chat: grounded answers are short; the deadline covers the slower
# multilingual routes (gemma4:e4b writes ~3.4 tokens/s on CPU).
DEFAULT_WEBSITE_CHAT_MAX_TOKENS = 700
#: Whole-answer deadline (all attempts); 360 s is also the hard ceiling.
DEFAULT_WEBSITE_CHAT_TIMEOUT_SECONDS = 360
DEFAULT_WEBSITE_MAX_BYTES = 3_000_000
DEFAULT_WEBSITE_MAX_CHUNKS = 300

DEFAULT_KG_MAX_NODES = 40
DEFAULT_KG_MAX_EDGES = 60
# V3: custom report template instruction size cap.
MAX_CUSTOM_TEMPLATE_CHARS = 2000
# Performance budgets (DEEP defaults; FAST overrides live in src/modes.py).
# On CPU, qwen3:4b generates ~5 tok/s, so output tokens dominate latency.
DEFAULT_LLM_NUM_CTX = 8192
DEFAULT_LLM_KEEP_ALIVE = "30m"
DEFAULT_PLANNER_MAX_TOKENS = 0  # 0 = uncapped (DEEP; thinking needs room)
DEFAULT_CRITIC_MAX_TOKENS = 0
DEFAULT_SYNTHESIS_MAX_TOKENS = 0
# Hard wall-clock deadline per stage request; 0 = none (DEEP keeps its
# unbounded-but-cancellable behaviour). FAST sets real limits in modes.py.
DEFAULT_PLANNER_TIMEOUT_SECONDS = 0
DEFAULT_CRITIC_TIMEOUT_SECONDS = 0
DEFAULT_SYNTHESIS_TIMEOUT_SECONDS = 0
DEFAULT_REPAIR_TIMEOUT_SECONDS = 0
DEFAULT_SYNTHESIS_CHARS_PER_SOURCE = 1500
DEFAULT_SYNTHESIS_CONTEXT_CHARS = 18000
DEFAULT_CRITIC_CHARS_PER_EVIDENCE = 700
DEFAULT_RUN_BUDGET_SECONDS = 0  # 0 = no run-level deadline (DEEP)
DEFAULT_RETRIEVAL_WORKERS = 4

SUPPORTED_PROVIDERS = ("ollama",)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be a boolean (true/false), got {raw!r}.")


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}.") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}.")
    return value


def _language_models_env(raw: str) -> tuple[tuple[str, str], ...]:
    """Parse ``ATLAS_LANGUAGE_MODELS="ml=qwen3:8b,hi=qwen3:8b"``."""
    from src.languages import OUTPUT_LANGUAGES

    pairs: list[tuple[str, str]] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        code, sep, model = (piece.strip() for piece in item.partition("="))
        if not sep or not model:
            raise ConfigError(f"ATLAS_LANGUAGE_MODELS entry {item!r} must look like code=model.")
        if code not in OUTPUT_LANGUAGES:
            raise ConfigError(f"ATLAS_LANGUAGE_MODELS has unknown language {code!r}.")
        pairs.append((code, model))
    return tuple(pairs)


@dataclass(frozen=True)
class AtlasConfig:
    """Immutable runtime configuration."""

    tavily_api_key: str = ""
    llm_provider: str = DEFAULT_LLM_PROVIDER
    model: str = DEFAULT_MODEL
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    max_research_iterations: int = DEFAULT_MAX_RESEARCH_ITERATIONS
    search_results_per_query: int = DEFAULT_SEARCH_RESULTS_PER_QUERY
    max_queries_per_iteration: int = DEFAULT_MAX_QUERIES_PER_ITERATION
    sufficiency_threshold: int = DEFAULT_SUFFICIENCY_THRESHOLD
    max_evidence_for_critic: int = DEFAULT_MAX_EVIDENCE_FOR_CRITIC
    max_evidence_for_synthesis: int = DEFAULT_MAX_EVIDENCE_FOR_SYNTHESIS
    report_target_words: int = DEFAULT_REPORT_TARGET_WORDS
    ollama_structured_reasoning: bool = DEFAULT_OLLAMA_STRUCTURED_REASONING
    data_dir: str = DEFAULT_DATA_DIR
    memory_ttl_hours: int = DEFAULT_MEMORY_TTL_HOURS
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    rag_chunks_per_query: int = DEFAULT_RAG_CHUNKS_PER_QUERY
    chunk_size_chars: int = DEFAULT_CHUNK_SIZE_CHARS
    chunk_overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS
    llm_timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS
    page_fetch_per_query: int = DEFAULT_PAGE_FETCH_PER_QUERY
    page_timeout_seconds: int = DEFAULT_PAGE_TIMEOUT_SECONDS
    page_max_bytes: int = DEFAULT_PAGE_MAX_BYTES
    page_chunks_per_page: int = DEFAULT_PAGE_CHUNKS_PER_PAGE
    memory_semantic_threshold: float = DEFAULT_MEMORY_SEMANTIC_THRESHOLD
    project_memory_threshold: float = DEFAULT_PROJECT_MEMORY_THRESHOLD
    project_memory_items: int = DEFAULT_PROJECT_MEMORY_ITEMS
    comparison_max_tokens: int = DEFAULT_COMPARISON_MAX_TOKENS
    comparison_timeout_seconds: int = DEFAULT_COMPARISON_TIMEOUT_SECONDS
    website_chat_max_tokens: int = DEFAULT_WEBSITE_CHAT_MAX_TOKENS
    website_chat_timeout_seconds: int = DEFAULT_WEBSITE_CHAT_TIMEOUT_SECONDS
    website_max_bytes: int = DEFAULT_WEBSITE_MAX_BYTES
    website_max_chunks: int = DEFAULT_WEBSITE_MAX_CHUNKS
    kg_max_nodes: int = DEFAULT_KG_MAX_NODES
    kg_max_edges: int = DEFAULT_KG_MAX_EDGES
    pdf_font_path: str = ""
    llm_num_ctx: int = DEFAULT_LLM_NUM_CTX
    llm_keep_alive: str = DEFAULT_LLM_KEEP_ALIVE
    planner_max_tokens: int = DEFAULT_PLANNER_MAX_TOKENS
    critic_max_tokens: int = DEFAULT_CRITIC_MAX_TOKENS
    synthesis_max_tokens: int = DEFAULT_SYNTHESIS_MAX_TOKENS
    planner_timeout_seconds: int = DEFAULT_PLANNER_TIMEOUT_SECONDS
    critic_timeout_seconds: int = DEFAULT_CRITIC_TIMEOUT_SECONDS
    synthesis_timeout_seconds: int = DEFAULT_SYNTHESIS_TIMEOUT_SECONDS
    repair_timeout_seconds: int = DEFAULT_REPAIR_TIMEOUT_SECONDS
    synthesis_chars_per_source: int = DEFAULT_SYNTHESIS_CHARS_PER_SOURCE
    synthesis_context_chars: int = DEFAULT_SYNTHESIS_CONTEXT_CHARS
    critic_chars_per_evidence: int = DEFAULT_CRITIC_CHARS_PER_EVIDENCE
    run_budget_seconds: int = DEFAULT_RUN_BUDGET_SECONDS
    retrieval_workers: int = DEFAULT_RETRIEVAL_WORKERS
    planner_max_tasks: int = 0  # 0 = no explicit cap in the planner prompt
    synthesis_json_mode: bool = False  # FAST: grammar-constrained report
    synthesis_clean_evidence: bool = False  # FAST: claim-bearing excerpts only
    budget_allocation: bool = False  # FAST: protect a measured synthesis reserve
    synthesis_max_words: int = 0  # 0 = no hard ceiling (DEEP)
    temperature: float = field(default=0.2)
    #: Output-language -> model routing, e.g. (("ml", "qwen3:8b"),). Languages
    #: not listed use ``model``. Whether a routed pair may actually generate is
    #: decided by ``src.model_capabilities``, never by this setting alone.
    language_models: tuple[tuple[str, str], ...] = ()

    @property
    def database_path(self) -> str:
        return os.path.join(self.data_dir, "atlas.db")

    @property
    def upload_dir(self) -> str:
        return os.path.join(self.data_dir, "uploads")

    def validate(self) -> None:
        """Raise :class:`ConfigError` for missing credentials or bad settings."""
        if self.llm_provider not in SUPPORTED_PROVIDERS:
            raise ConfigError(
                f"Unsupported ATLAS_LLM_PROVIDER {self.llm_provider!r}. "
                f"Supported: {', '.join(SUPPORTED_PROVIDERS)}."
            )
        if not self.tavily_api_key:
            raise ConfigError(
                "Missing required environment variable: TAVILY_API_KEY. "
                "Copy .env.example to .env and add your Tavily key "
                "(free tier: https://app.tavily.com). "
                "The local Ollama LLM requires no API key."
            )


def load_config(dotenv_path: str | None = None) -> AtlasConfig:
    """Build an :class:`AtlasConfig` from the environment.

    Does not validate credentials; call :meth:`AtlasConfig.validate` before a
    live run so tests can construct configs without secrets.
    """
    load_dotenv(dotenv_path=dotenv_path, override=False)
    return AtlasConfig(
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        llm_provider=(
            os.getenv("ATLAS_LLM_PROVIDER", "").strip().lower()
            or DEFAULT_LLM_PROVIDER
        ),
        model=os.getenv("ATLAS_MODEL", "").strip() or DEFAULT_MODEL,
        ollama_base_url=(
            os.getenv("ATLAS_OLLAMA_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_OLLAMA_BASE_URL
        ),
        max_research_iterations=_int_env(
            "ATLAS_MAX_RESEARCH_ITERATIONS", DEFAULT_MAX_RESEARCH_ITERATIONS
        ),
        search_results_per_query=_int_env(
            "ATLAS_SEARCH_RESULTS_PER_QUERY", DEFAULT_SEARCH_RESULTS_PER_QUERY
        ),
        max_queries_per_iteration=_int_env(
            "ATLAS_MAX_QUERIES_PER_ITERATION", DEFAULT_MAX_QUERIES_PER_ITERATION
        ),
        sufficiency_threshold=_int_env(
            "ATLAS_SUFFICIENCY_THRESHOLD", DEFAULT_SUFFICIENCY_THRESHOLD, minimum=0
        ),
        max_evidence_for_critic=_int_env(
            "ATLAS_MAX_EVIDENCE_FOR_CRITIC", DEFAULT_MAX_EVIDENCE_FOR_CRITIC
        ),
        max_evidence_for_synthesis=_int_env(
            "ATLAS_MAX_EVIDENCE_FOR_SYNTHESIS", DEFAULT_MAX_EVIDENCE_FOR_SYNTHESIS
        ),
        report_target_words=_int_env(
            "ATLAS_REPORT_TARGET_WORDS", DEFAULT_REPORT_TARGET_WORDS, minimum=100
        ),
        ollama_structured_reasoning=_bool_env(
            "ATLAS_OLLAMA_STRUCTURED_REASONING", DEFAULT_OLLAMA_STRUCTURED_REASONING
        ),
        data_dir=os.getenv("ATLAS_DATA_DIR", "").strip() or DEFAULT_DATA_DIR,
        memory_ttl_hours=_int_env(
            "ATLAS_MEMORY_TTL_HOURS", DEFAULT_MEMORY_TTL_HOURS, minimum=0
        ),
        max_upload_mb=_int_env("ATLAS_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB),
        embedding_model=os.getenv("ATLAS_EMBEDDING_MODEL", "").strip()
        or DEFAULT_EMBEDDING_MODEL,
        rag_chunks_per_query=_int_env(
            "ATLAS_RAG_CHUNKS_PER_QUERY", DEFAULT_RAG_CHUNKS_PER_QUERY
        ),
        chunk_size_chars=_int_env("ATLAS_CHUNK_SIZE_CHARS", DEFAULT_CHUNK_SIZE_CHARS),
        chunk_overlap_chars=_int_env(
            "ATLAS_CHUNK_OVERLAP_CHARS", DEFAULT_CHUNK_OVERLAP_CHARS, minimum=0
        ),
        llm_timeout_seconds=_int_env(
            "ATLAS_LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS, minimum=30
        ),
        page_fetch_per_query=_int_env(
            "ATLAS_PAGE_FETCH_PER_QUERY", DEFAULT_PAGE_FETCH_PER_QUERY, minimum=0
        ),
        page_timeout_seconds=_int_env(
            "ATLAS_PAGE_TIMEOUT_SECONDS", DEFAULT_PAGE_TIMEOUT_SECONDS, minimum=1
        ),
        page_max_bytes=_int_env("ATLAS_PAGE_MAX_BYTES", DEFAULT_PAGE_MAX_BYTES),
        page_chunks_per_page=_int_env(
            "ATLAS_PAGE_CHUNKS_PER_PAGE", DEFAULT_PAGE_CHUNKS_PER_PAGE
        ),
        memory_semantic_threshold=float(
            os.getenv("ATLAS_MEMORY_SEMANTIC_THRESHOLD", "").strip()
            or DEFAULT_MEMORY_SEMANTIC_THRESHOLD
        ),
        project_memory_threshold=float(
            os.getenv("ATLAS_PROJECT_MEMORY_THRESHOLD", "").strip()
            or DEFAULT_PROJECT_MEMORY_THRESHOLD
        ),
        project_memory_items=_int_env(
            "ATLAS_PROJECT_MEMORY_ITEMS", DEFAULT_PROJECT_MEMORY_ITEMS
        ),
        comparison_max_tokens=_int_env(
            "ATLAS_COMPARISON_MAX_TOKENS", DEFAULT_COMPARISON_MAX_TOKENS
        ),
        comparison_timeout_seconds=_int_env(
            "ATLAS_COMPARISON_TIMEOUT_SECONDS", DEFAULT_COMPARISON_TIMEOUT_SECONDS
        ),
        website_chat_max_tokens=_int_env(
            "ATLAS_WEBSITE_CHAT_MAX_TOKENS", DEFAULT_WEBSITE_CHAT_MAX_TOKENS
        ),
        website_chat_timeout_seconds=_int_env(
            "ATLAS_WEBSITE_CHAT_TIMEOUT_SECONDS", DEFAULT_WEBSITE_CHAT_TIMEOUT_SECONDS
        ),
        website_max_bytes=_int_env("ATLAS_WEBSITE_MAX_BYTES", DEFAULT_WEBSITE_MAX_BYTES),
        website_max_chunks=_int_env("ATLAS_WEBSITE_MAX_CHUNKS", DEFAULT_WEBSITE_MAX_CHUNKS),
        kg_max_nodes=_int_env("ATLAS_KG_MAX_NODES", DEFAULT_KG_MAX_NODES),
        kg_max_edges=_int_env("ATLAS_KG_MAX_EDGES", DEFAULT_KG_MAX_EDGES),
        pdf_font_path=os.getenv("ATLAS_PDF_FONT", "").strip(),
        llm_num_ctx=_int_env("ATLAS_LLM_NUM_CTX", DEFAULT_LLM_NUM_CTX, minimum=2048),
        llm_keep_alive=os.getenv("ATLAS_LLM_KEEP_ALIVE", "").strip()
        or DEFAULT_LLM_KEEP_ALIVE,
        run_budget_seconds=_int_env(
            "ATLAS_DEEP_RUN_BUDGET_SECONDS", DEFAULT_RUN_BUDGET_SECONDS, minimum=0
        ),
        retrieval_workers=_int_env("ATLAS_RETRIEVAL_WORKERS", DEFAULT_RETRIEVAL_WORKERS),
        language_models=_language_models_env(os.getenv("ATLAS_LANGUAGE_MODELS", "")),
    )
