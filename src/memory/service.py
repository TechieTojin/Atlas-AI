"""Research evidence memory: reuse fresh evidence from previous runs.

This is evidence memory, not chat memory: rows map a research query to the
evidence it produced, with origin, fetch timestamps, project scope, and (V3)
a query embedding for semantic reuse. Exact normalized-query matching is the
fast path; semantic lookup fills the remaining budget with evidence from
similar queries above a configurable cosine threshold. Web evidence expires
after a configurable TTL; document evidence stays valid until its document is
deleted. Reused evidence keeps its ORIGINAL source object, so citation
provenance is unaffected — only ``origin`` marks it as a memory hit.
"""

from __future__ import annotations

import logging
from typing import Callable

from src.models.research import Evidence, EvidenceOrigin, normalize_url
from src.persistence.memory import MemoryRepository

logger = logging.getLogger(__name__)

EmbedQueryFn = Callable[[str], list[float]]


class MemoryService:
    def __init__(
        self,
        repo: MemoryRepository,
        ttl_hours: int,
        embed_query: EmbedQueryFn | None = None,
        semantic_threshold: float = 0.83,
    ) -> None:
        self._repo = repo
        self._ttl_hours = ttl_hours
        self._embed_query = embed_query
        self._semantic_threshold = semantic_threshold
        self._embedding_cache: dict[str, list[float]] = {}

    @property
    def enabled(self) -> bool:
        return self._ttl_hours > 0

    def _embedding_for(self, query: str) -> list[float] | None:
        """Embed a query once per service lifetime (embeddings are cached)."""
        if self._embed_query is None:
            return None
        key = " ".join(query.lower().split())
        if key not in self._embedding_cache:
            try:
                self._embedding_cache[key] = self._embed_query(query)
            except Exception:
                logger.warning("Query embedding failed; semantic memory skipped.",
                               exc_info=True)
                self._embedding_cache[key] = []
        return self._embedding_cache[key] or None

    def recall(self, query: str, limit: int, project_id: str = "") -> list[Evidence]:
        """Fresh prior evidence for this query, marked as memory hits.

        Exact match first; if budget remains and embeddings are available,
        semantically similar queries' evidence fills the rest. Results are
        deduplicated by normalized URL, deterministically ordered.
        """
        if not self.enabled:
            return []
        hits = self._repo.lookup(
            query, self._ttl_hours, limit, project_id=project_id
        )
        if len(hits) < limit:
            embedding = self._embedding_for(query)
            if embedding:
                semantic = self._repo.lookup_semantic(
                    embedding,
                    self._ttl_hours,
                    self._semantic_threshold,
                    limit=limit - len(hits),
                    project_id=project_id,
                    exclude_query=query,
                )
                hits.extend(item for item, _sim in semantic)
        seen: set[str] = set()
        unique: list[Evidence] = []
        for item in hits:
            key = normalize_url(item.source.url)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return [
            item.model_copy(update={"origin": EvidenceOrigin.MEMORY, "query": query})
            for item in unique[:limit]
        ]

    def remember(
        self, query: str, evidence: list[Evidence], project_id: str = ""
    ) -> int:
        """Store newly collected (non-memory) evidence for future reuse."""
        if not self.enabled:
            return 0
        fresh = [e for e in evidence if e.origin is not EvidenceOrigin.MEMORY]
        if not fresh:
            return 0
        return self._repo.store(
            query,
            fresh,
            project_id=project_id,
            embedding=self._embedding_for(query),
        )
