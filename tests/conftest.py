"""Shared test fakes: no real OpenAI or Tavily calls anywhere in the suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.config import AtlasConfig
from src.models.research import (
    Critique,
    CriticDecision,
    Evidence,
    ResearchPlan,
    ResearchTask,
    Source,
)


@dataclass
class FakeStructured:
    """Stands in for llm.with_structured_output(Model): pops queued outputs."""

    outputs: list[Any]
    calls: list[Any] = field(default_factory=list)

    def invoke(self, messages: Any) -> Any:
        self.calls.append(messages)
        if len(self.outputs) > 1:
            return self.outputs.pop(0)
        return self.outputs[0]


@dataclass
class FakeMessage:
    content: str


class FakeLLM:
    """Fake chat model: routes structured output by schema type, plain
    invoke returns a canned message."""

    def __init__(
        self,
        plans: list[ResearchPlan] | None = None,
        critiques: list[Critique] | None = None,
        synthesis: str | list[str] = "Report body citing [1].",
    ) -> None:
        self._structured: dict[type, FakeStructured] = {}
        if plans:
            self._structured[ResearchPlan] = FakeStructured(list(plans))
        if critiques:
            self._structured[Critique] = FakeStructured(list(critiques))
        # A list queues successive responses (last one repeats), so tests can
        # exercise the draft -> citation-repair sequence.
        self._syntheses = [synthesis] if isinstance(synthesis, str) else list(synthesis)
        self.invoke_calls: list[Any] = []
        self.invoke_kwargs: list[dict] = []

    def queue_structured(self, schema: type, outputs: list[Any]) -> None:
        self._structured[schema] = FakeStructured(list(outputs))

    def with_structured_output(self, schema: type) -> FakeStructured:
        # An unqueued schema still returns a stub; invoking it fails loudly.
        return self._structured.setdefault(schema, FakeStructured([]))

    def invoke(self, messages: Any, **kwargs: Any) -> FakeMessage:
        self.invoke_calls.append(messages)
        self.invoke_kwargs.append(kwargs)
        if len(self._syntheses) > 1:
            return FakeMessage(self._syntheses.pop(0))
        return FakeMessage(self._syntheses[0])


def make_plan(n_queries: int = 2) -> ResearchPlan:
    return ResearchPlan(
        objective="Understand barriers to AV adoption.",
        tasks=[
            ResearchTask(
                subquestion="What are the technical barriers?",
                evidence_needed="Engineering analyses of AV limitations.",
            )
        ],
        search_queries=[f"av barriers query {i}" for i in range(n_queries)],
    )


def make_critique(
    decision: CriticDecision,
    follow_ups: list[str] | None = None,
    score: int = 5,
) -> Critique:
    return Critique(
        overall_score=score,
        coverage_assessment="Partial coverage.",
        missing_information=["regulatory detail"] if decision is CriticDecision.MORE_RESEARCH else [],
        decision=decision,
        follow_up_queries=follow_ups or [],
        reasoning="test",
    )


def make_evidence(url: str, title: str = "T", content: str = "Some content.", query: str = "q") -> Evidence:
    return Evidence(
        source=Source(title=title, url=url, domain="example.com"),
        content=content,
        query=query,
    )


def make_search_fn(results_by_query: dict[str, list[dict[str, Any]]] | None = None,
                   default: list[dict[str, Any]] | None = None):
    """Fake SearchFn returning canned raw Tavily-style dicts."""
    calls: list[str] = []

    def search(query: str, max_results: int) -> list[dict[str, Any]]:
        calls.append(query)
        if results_by_query and query in results_by_query:
            return results_by_query[query][:max_results]
        return (default or [])[:max_results]

    search.calls = calls  # type: ignore[attr-defined]
    return search


@pytest.fixture
def config() -> AtlasConfig:
    return AtlasConfig(
        tavily_api_key="test-key",
        max_research_iterations=3,
        search_results_per_query=5,
    )
