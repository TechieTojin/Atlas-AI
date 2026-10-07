"""Shared V2 test helpers (imported by test modules, not auto-loaded)."""

from __future__ import annotations

import dataclasses
from concurrent.futures import Future

from src.api.container import Container
from src.config import AtlasConfig
from src.models.research import CriticDecision
from tests.conftest import FakeLLM, make_critique, make_plan, make_search_fn

WEB_RESULTS = [
    {"url": "https://a.com/1", "title": "A1", "content": "Alpha evidence.", "score": 0.9},
    {"url": "https://b.com/2", "title": "B2", "content": "Beta evidence.", "score": 0.8},
]


class ImmediateExecutor:
    """Runs submitted work synchronously so tests are deterministic."""

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - surfaced via future
            future.set_exception(exc)
        return future


def fake_embed(texts):
    return [[1.0, float(len(t) % 7), 1.0] for t in texts]


def make_container(
    tmp_path,
    llm: FakeLLM | None = None,
    search_fn=None,
    page_fetcher=None,
    embed_fn=None,
    db_path: str = ":memory:",
    executor=None,
    **config_overrides,
) -> Container:
    config = dataclasses.replace(
        AtlasConfig(tavily_api_key="test-key"),
        data_dir=str(tmp_path),
        **config_overrides,
    )
    llm = llm or FakeLLM(
        plans=[make_plan(n_queries=2)],
        critiques=[make_critique(CriticDecision.SYNTHESIZE, score=9)],
        synthesis="Findings [1] and [2].",
    )
    search_fn = search_fn or make_search_fn(default=WEB_RESULTS)
    return Container(
        config,
        db_path=db_path,
        embed_fn=embed_fn or fake_embed,
        llm_factory=lambda cfg, reasoning: llm,
        search_factory=lambda cfg: search_fn,
        executor=executor or ImmediateExecutor(),
        # Offline by default: no real page fetching in automated tests.
        page_fetcher_factory=lambda cfg: page_fetcher,
    )
