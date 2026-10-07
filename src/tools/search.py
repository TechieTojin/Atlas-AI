"""Web search abstraction and deterministic evidence deduplication.

The Tavily client is wrapped behind a plain-callable ``SearchFn`` protocol so
the rest of Atlas (and the tests) never depend on live network access.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from src.models.research import Evidence, Source, normalize_url

logger = logging.getLogger(__name__)


class SearchFn(Protocol):
    """Callable that runs one web search and returns raw result dicts."""

    def __call__(self, query: str, max_results: int) -> list[dict[str, Any]]: ...


def create_tavily_search(api_key: str) -> SearchFn:
    """Create a live Tavily-backed search function."""
    from langchain_tavily import TavilySearch

    def search(query: str, max_results: int) -> list[dict[str, Any]]:
        tool = TavilySearch(max_results=max_results, tavily_api_key=api_key)
        response = tool.invoke({"query": query})
        if isinstance(response, dict):
            results = response.get("results", [])
        elif isinstance(response, list):
            results = response
        else:
            logger.warning("Unexpected Tavily response type: %s", type(response))
            return []
        return [r for r in results if isinstance(r, dict)]

    return search


def _domain(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).netloc.lower()
    except ValueError:
        return ""


def result_to_evidence(result: dict[str, Any], query: str) -> Evidence | None:
    """Normalize one raw search result into an Evidence item, or None if unusable."""
    url = str(result.get("url") or "").strip()
    content = str(result.get("content") or result.get("snippet") or "").strip()
    if not url or not content:
        return None
    score = result.get("score")
    from src.tools.quality import with_quality

    return Evidence(
        source=with_quality(
            Source(
                title=str(result.get("title") or "").strip() or url,
                url=url,
                domain=_domain(url),
            )
        ),
        content=content,
        query=query,
        relevance_score=float(score) if isinstance(score, (int, float)) else None,
    )


def run_searches(
    search_fn: SearchFn,
    queries: list[str],
    max_results: int,
) -> list[Evidence]:
    """Run multiple searches, normalizing results and isolating failures.

    A failing or empty search logs a warning and contributes nothing; it
    never raises, so one bad query cannot crash the research graph.
    """
    evidence: list[Evidence] = []
    for query in queries:
        try:
            results = search_fn(query, max_results)
        except Exception:  # network/API failures are expected, not fatal
            logger.warning("Search failed for query %r; skipping.", query, exc_info=True)
            continue
        if not results:
            logger.info("No results for query %r.", query)
            continue
        for result in results:
            item = result_to_evidence(result, query)
            if item is not None:
                evidence.append(item)
    return evidence


def dedupe_evidence(
    new_items: list[Evidence],
    seen_urls: set[str] | None = None,
) -> tuple[list[Evidence], set[str]]:
    """Drop evidence whose normalized URL was already seen.

    Returns the unique new items and the updated seen-URL set. Purely
    deterministic — no LLM involved.
    """
    seen = set(seen_urls or ())
    unique: list[Evidence] = []
    for item in new_items:
        key = normalize_url(item.source.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique, seen


__all__ = [
    "SearchFn",
    "create_tavily_search",
    "result_to_evidence",
    "run_searches",
    "dedupe_evidence",
]
