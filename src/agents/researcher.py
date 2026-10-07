"""Researcher agent: gathers evidence from memory, web search, and documents.

For each pending query it (1) recalls fresh evidence from research memory,
(2) runs a web search unless memory already satisfied the query or the run
is documents-only, and (3) retrieves relevant chunks from the selected
uploaded documents. Everything is normalized into the unified Evidence model
and deterministically deduplicated. External failures are isolated per
query/source and never crash the graph.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.events import EventType, NullEmitter
from src.graph.state import AtlasState
from src.models.research import Evidence
from src.tools.search import SearchFn, dedupe_evidence, run_searches

logger = logging.getLogger(__name__)


class ResearcherAgent:
    """Runs the pending research queries across the enabled evidence sources.

    All dependencies are injected: ``search_fn`` (web), ``memory`` (a
    MemoryService or None), ``documents`` (a DocumentService or None), and
    an event emitter. Tests never hit the network.
    """

    def __init__(
        self,
        search_fn: SearchFn | None,
        results_per_query: int = 5,
        memory: Any = None,
        documents: Any = None,
        document_ids: list[str] | None = None,
        emitter: Any = None,
        page_fetcher: Any = None,
        page_fetch_per_query: int = 0,
        page_chunks_per_page: int = 2,
        project_id: str = "",
        workers: int = 4,
        cancel_check: Any = None,
    ) -> None:
        self._search_fn = search_fn
        self._results_per_query = results_per_query
        self._memory = memory
        self._documents = documents
        self._document_ids = document_ids or []
        self._emitter = emitter or NullEmitter()
        self._page_fetcher = page_fetcher
        self._page_fetch_per_query = page_fetch_per_query
        self._page_chunks_per_page = page_chunks_per_page
        self._project_id = project_id
        self._workers = max(1, workers)
        # Raises RunCancelledError once the run is cancelled; checked before
        # every search, page fetch, and memory write (never swallowed by the
        # per-query failure isolation, which only wraps the I/O itself).
        self._cancel_check = cancel_check or (lambda: None)
        self._stats_lock = threading.Lock()
        self.page_stats = {"attempted": 0, "fetched": 0, "failed": 0, "fallbacks": 0}

    def _count(self, key: str) -> None:
        with self._stats_lock:
            self.page_stats[key] += 1

    def _enrich_with_pages(self, query: str, web_items: list[Evidence]) -> None:
        """Upgrade top snippet evidence with safely fetched page content.

        In-place content enrichment keeps URL provenance and deduplication
        unchanged; any failure falls back to the original snippet.
        """
        if self._page_fetcher is None or self._page_fetch_per_query <= 0:
            return
        from src.models.runs import utcnow
        from src.tools.webpage import select_relevant_chunks

        targets = web_items[: self._page_fetch_per_query]
        if not targets:
            return

        def fetch(item: Evidence):
            """Fetch + extract one page; returns chunks or the failure."""
            self._cancel_check()
            url = item.source.url
            self._count("attempted")
            self._emitter.emit(
                EventType.PAGE_FETCH_STARTED,
                message=f"Fetching page: {item.source.domain or url}",
                agent="researcher",
                url=url,
            )
            try:
                page = self._page_fetcher.fetch(url)
                chunks = select_relevant_chunks(
                    page.text, query, max_chunks=self._page_chunks_per_page
                )
                if not chunks:
                    raise ValueError("No relevant content extracted.")
                return chunks, None
            except Exception as exc:  # isolated: one page never breaks a run
                return None, exc

        # Pages are independent network I/O: fetch concurrently, then apply
        # results in rank order so evidence content stays deterministic.
        with ThreadPoolExecutor(max_workers=min(self._workers, len(targets))) as pool:
            outcomes = list(pool.map(fetch, targets))
        self._cancel_check()

        for item, (chunks, error) in zip(targets, outcomes):
            url = item.source.url
            if error is not None:
                self._count("failed")
                self._count("fallbacks")
                item.extraction = "fallback_snippet"
                logger.info("Page fetch failed for %s (%s); keeping snippet.",
                            url, type(error).__name__)
                self._emitter.emit(
                    EventType.PAGE_FETCH_FAILED,
                    message=f"Page unavailable; using search snippet "
                            f"({item.source.domain or url}).",
                    agent="researcher",
                    url=url,
                )
                continue
            snippet = item.content
            item.content = "\n\n".join(chunks)
            if snippet and snippet not in item.content:
                item.content = snippet + "\n\n" + item.content
            item.extraction = "full_page"
            item.fetched_at = utcnow().isoformat()
            self._count("fetched")
            self._emitter.emit(
                EventType.PAGE_FETCH_COMPLETED,
                message=f"Extracted page content ({item.source.domain or url}).",
                agent="researcher",
                url=url,
                chunks=len(chunks),
            )

    def _gather_query(self, query: str) -> tuple[list[Evidence], int, int]:
        """Collect evidence for one query. Returns (items, memory_hits, doc_chunks)."""
        items: list[Evidence] = []
        memory_hits = 0
        doc_chunks = 0
        self._cancel_check()

        if self._memory is not None:
            try:
                recalled = self._memory.recall(
                    query, self._results_per_query, project_id=self._project_id
                )
            except Exception:
                logger.warning("Memory recall failed for %r.", query, exc_info=True)
                recalled = []
            memory_hits = len(recalled)
            items.extend(recalled)

        # Web search is skipped when memory already filled this query's quota.
        if self._search_fn is not None and memory_hits < self._results_per_query:
            self._cancel_check()
            web_items = run_searches(self._search_fn, [query], self._results_per_query)
            self._enrich_with_pages(query, web_items)
            items.extend(web_items)

        if self._documents is not None and self._document_ids:
            try:
                chunks = self._documents.retrieve(query, self._document_ids)
            except Exception:
                logger.warning("Document retrieval failed for %r.", query, exc_info=True)
                chunks = []
            doc_chunks = len(chunks)
            items.extend(chunks)

        return items, memory_hits, doc_chunks

    def __call__(self, state: AtlasState) -> dict[str, Any]:
        queries = [q for q in state.get("pending_queries", []) if q.strip()]
        if not queries:
            # Defense in depth: the planner boundary rejects empty plans, so
            # reaching the researcher with zero usable queries is an invalid
            # state — fail loudly instead of silently researching nothing.
            raise RuntimeError(
                "Researcher invoked with no usable research queries; "
                "refusing to run an empty research iteration."
            )
        iteration = state.get("iteration", 0) + 1
        max_iterations = state.get("max_iterations", 1)
        # Per-iteration counters (state reducers accumulate across iterations).
        self.page_stats = {"attempted": 0, "fetched": 0, "failed": 0, "fallbacks": 0}
        logger.info(
            "Research iteration %d/%d: gathering evidence for %d queries...",
            iteration, max_iterations, len(queries),
        )

        collected: list[Evidence] = []
        total_memory_hits = 0
        total_doc_chunks = 0
        per_query_new: dict[str, list[Evidence]] = {}
        def gather(position_query: tuple[int, str]):
            position, query = position_query
            self._emitter.emit(
                EventType.SEARCH_QUERY_STARTED,
                message=f"Searching ({position}/{len(queries)}): {query}",
                agent="researcher",
                iteration=iteration,
                query=query,
                position=position,
                total=len(queries),
            )
            items, memory_hits, doc_chunks = self._gather_query(query)
            self._emitter.emit(
                EventType.SEARCH_QUERY_COMPLETED,
                message=f"Query done: {len(items)} items "
                        f"({memory_hits} from memory, {doc_chunks} from documents)",
                agent="researcher",
                iteration=iteration,
                query=query,
                results=len(items),
                memory_hits=memory_hits,
                document_chunks=doc_chunks,
            )
            return query, items, memory_hits, doc_chunks

        # Queries are independent I/O (search, page fetch, retrieval): run
        # them concurrently, then aggregate in query order so deduplication
        # and evidence ordering remain deterministic.
        with ThreadPoolExecutor(max_workers=min(self._workers, len(queries))) as pool:
            results = list(pool.map(gather, enumerate(queries, 1)))
        for query, items, memory_hits, doc_chunks in results:
            total_memory_hits += memory_hits
            total_doc_chunks += doc_chunks
            per_query_new[query] = items
            collected.extend(items)

        self._cancel_check()
        unique, seen_urls = dedupe_evidence(collected, state.get("seen_urls"))
        unique_urls = {e.source.normalized_url for e in unique}

        # Persist newly collected evidence to research memory for reuse.
        if self._memory is not None:
            for query, items in per_query_new.items():
                new_items = [
                    e for e in items if e.source.normalized_url in unique_urls
                ]
                try:
                    self._memory.remember(query, new_items, project_id=self._project_id)
                except Exception:
                    logger.warning("Memory store failed.", exc_info=True)

        web_new = sum(1 for e in unique if e.origin.value == "web")
        total = len(state.get("evidence", [])) + len(unique)
        logger.info(
            "Collected %d new unique evidence items (%d total; %d memory hits, "
            "%d document chunks).",
            len(unique), total, total_memory_hits, total_doc_chunks,
        )
        self._emitter.emit(
            EventType.EVIDENCE_COLLECTED,
            message=f"Collected {len(unique)} new unique evidence items "
                    f"({total} total).",
            agent="researcher",
            iteration=iteration,
            new_items=len(unique),
            total_items=total,
            memory_hits=total_memory_hits,
            document_chunks=total_doc_chunks,
        )
        return {
            "evidence": unique,  # appended via reducer
            "executed_queries": list(queries),
            "pending_queries": [],
            "seen_urls": seen_urls,
            "iteration": iteration,
            "memory_hits": total_memory_hits,
            "document_chunks_retrieved": total_doc_chunks,
            "web_sources_new": web_new,
            "pages_attempted": self.page_stats["attempted"],
            "pages_fetched": self.page_stats["fetched"],
            "pages_failed": self.page_stats["failed"],
            "snippet_fallbacks": self.page_stats["fallbacks"],
        }
