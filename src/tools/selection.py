"""Deterministic evidence selection for LLM context budgeting.

With many collected sources, sending everything through a local model makes
critique/synthesis extremely slow. This utility picks the most useful subset
without any LLM call: evidence is grouped by the query that found it, ranked
within each group by search relevance score (ties broken by original search
rank), and then drawn round-robin across queries — so the selection covers
every research dimension instead of exhausting one query's results first.
Within the round-robin, a result from a not-yet-used domain is preferred to
keep source diversity. The full evidence set always remains in Atlas state.
"""

from __future__ import annotations

from src.models.research import Evidence


def _ranked_groups(evidence: list[Evidence]) -> list[list[Evidence]]:
    """Group by originating query (insertion order), best-first within group."""
    groups: dict[str, list[Evidence]] = {}
    for item in evidence:
        groups.setdefault(item.query, []).append(item)
    # Stable sort: higher relevance first; items without a score keep their
    # original search rank behind scored ones. Source quality/authority
    # breaks ties so comparable sources prefer the more authoritative one —
    # it never outranks relevance, and low-quality sources still survive
    # when they carry unique evidence (diversity/round-robin below).
    def sort_key(e):
        relevance = e.relevance_score if e.relevance_score is not None else -1.0
        quality = e.source.quality.score if e.source.quality else 40
        return (-relevance, -quality)

    return [sorted(group, key=sort_key) for group in groups.values()]


def select_synthesis_evidence(
    evidence: list[Evidence], limit: int, require_claims: bool = False
) -> list[Evidence]:
    """Evidence for synthesis; the ONE place numbering is derived from.

    With ``require_claims`` (FAST), items with no citable claim sentence
    (bibliography entries, navigation, keyword lists) are dropped before
    selection, unless that would leave fewer than three items. The service
    uses this same function to build the run's numbered source list, so
    citation numbers always match.
    """
    if require_claims:
        from src.tools.excerpts import has_claims

        useful = [e for e in evidence if has_claims(e.content, e.source.title)]
        if len(useful) >= min(3, len(evidence)):
            evidence = useful
    return select_evidence(evidence, limit)


def select_evidence(evidence: list[Evidence], limit: int) -> list[Evidence]:
    """Pick at most ``limit`` evidence items, deterministically.

    Round-robin across query groups (coverage), best relevance first within
    each group, preferring unseen domains (diversity). Returns the full list
    unchanged when it already fits the budget.
    """
    if limit <= 0 or len(evidence) <= limit:
        return list(evidence)

    groups = _ranked_groups(evidence)
    selected: list[Evidence] = []
    used_domains: set[str] = set()

    while len(selected) < limit and any(groups):
        for group in groups:
            if len(selected) >= limit or not group:
                continue
            # Prefer the best-ranked item from a domain not yet selected.
            pick_index = 0
            for i, candidate in enumerate(group):
                if candidate.source.domain not in used_domains:
                    pick_index = i
                    break
            item = group.pop(pick_index)
            selected.append(item)
            used_domains.add(item.source.domain)
    return selected
