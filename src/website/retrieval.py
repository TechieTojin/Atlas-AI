"""Website-scoped retrieval: semantic similarity with a light lexical boost.

score = cosine(question, chunk) + LEXICAL_WEIGHT * (share of the question's
content words that occur in the chunk). The lexical term is deterministic
(Unicode word runs, no stemming or translation) and only re-ranks chunks of
THIS website's live index; it is a tie-breaker for exact numbers, names and
technical terms that embeddings blur.

Follow-ups: a short question ("What about its efficiency?") is also embedded
together with the previous user question, and each chunk keeps its best
score, so pronouns resolve to the right passage. Evidence still comes only
from fresh retrieval over the indexed page.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from src.models.websites import WebsiteChunk, WebsiteSource
from src.unicode_text import words

logger = logging.getLogger(__name__)

TOP_K = 6
LEXICAL_WEIGHT = 0.15
#: Extra score when a chunk contains a figure the user quoted ("3.8%", "2009").
#: Quoted figures are very specific; spread over all question terms they were
#: too weak to beat 0.01 cosine differences (live: the passage stating 3.8% was
#: ranked 6th for "Which year ... reach 3.8% efficiency?").
FIGURE_WEIGHT = 0.06
#: nomic-embed-text was trained with these task prefixes.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

_STOPWORDS = frozenset(
    "the and for are was were what which who whom whose when where why how does did "
    "this that these those with from about into over under than then there their they "
    "them its it's has have had can could would should will shall may might must not "
    "page article website site say says said tell according describe explain please "
    "any some all more most such only also".split()
)
#: Words that point back at an earlier turn, in the languages Website Chat
#: answers in (English, Spanish, German, Hindi). Words that are also common
#: non-referring words are left out on purpose (Spanish "es" = "is", German
#: "die"/"das" = articles), so ordinary questions are not treated as follow-ups.
_CONTEXT_WORDS = frozenset(
    "it its they them their this that these those he she his her one ones there "
    "él ella ello ellos ellas su sus eso esto esa ese esos esas "
    "er ihm ihn ihr ihre ihrer sein seine seiner seinen dessen deren dies diese dieser dieses dort "
    "यह वह ये वे इसके इसका इसकी इसे इसमें उसके उसका उसकी उसे उसमें इनके इनका इनकी उनके उनका उनकी".split()
)
#: "this page" / "diese Seite" / "इस पेज" name the indexed page itself, not an earlier turn.
_SELF_REFERENCES = frozenset(
    "page article website site webpage document text "
    "página artículo sitio web documento texto "
    "seite artikel webseite website dokument text "
    "पेज पृष्ठ लेख वेबसाइट".split()
)


#: Decimal figures ("3.8", "34,6") are single terms: word splitting would cut
#: them into "3" and "8" and drop both, so a figure the user quotes gave no
#: lexical signal (live: "Which year ... reach 3.8% efficiency?" missed the
#: passage stating it).
_DECIMAL_RE = re.compile(r"\d+[.,]\d+")


_YEAR_RE = re.compile(r"\b(?:1[89]|20)\d\d\b")


def figures(text: str) -> set[str]:
    """Decimal figures and years in ``text`` (normalised like content terms)."""
    lowered = text.lower()
    return {m.replace(",", ".") for m in _DECIMAL_RE.findall(lowered)} | set(_YEAR_RE.findall(lowered))


def content_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = {w for w in words(lowered) if len(w) >= 3 and w not in _STOPWORDS}
    terms.update(m.replace(",", ".") for m in _DECIMAL_RE.findall(lowered))
    return terms


def wants_context(question: str) -> bool:
    tokens = words(question.lower())
    if len(tokens) <= 6:
        return True
    return any(
        t in _CONTEXT_WORDS and not (i + 1 < len(tokens) and tokens[i + 1] in _SELF_REFERENCES)
        for i, t in enumerate(tokens)
    )


def document_text(site: WebsiteSource, section: str, text: str, prefixed: bool) -> str:
    body = f"{site.page_title}\n{section}\n\n{text}" if section else f"{site.page_title}\n\n{text}"
    return (DOCUMENT_PREFIX if prefixed else "") + body


@dataclass
class Retrieved:
    chunk: WebsiteChunk
    score: float
    cosine: float
    lexical: float


@dataclass
class RetrievalResult:
    items: list[Retrieved]
    queries: list[str]
    elapsed_ms: int


def retrieve(
    repo,
    site: WebsiteSource,
    question: str,
    embed_fn,
    *,
    previous_question: str = "",
    top_k: int = TOP_K,
    prefixed: bool = True,
    lexical_weight: float = LEXICAL_WEIGHT,
) -> RetrievalResult:
    start = time.perf_counter()
    queries = [question]
    if previous_question and wants_context(question):
        queries.append(f"{previous_question} {question}")
    prefix = QUERY_PREFIX if prefixed else ""
    vectors = embed_fn([prefix + q for q in queries])
    scored = repo.search(site.id, site.index_version, vectors)
    terms = content_terms(" ".join(queries))
    quoted = figures(question)
    items: list[Retrieved] = []
    for chunk, cosine in scored:
        lexical = 0.0
        body = f"{chunk.section_title} {chunk.text}"
        if terms:
            lexical = len(terms & content_terms(body)) / len(terms)
        figure = len(quoted & figures(body)) / len(quoted) if quoted else 0.0
        score = cosine + lexical_weight * lexical + FIGURE_WEIGHT * figure
        items.append(Retrieved(chunk, score, cosine, lexical))
    items.sort(key=lambda item: (-item.score, item.chunk.chunk_index))
    result = RetrievalResult(items[:top_k], queries, int((time.perf_counter() - start) * 1000))
    logger.info(
        "Website retrieval %s: %d ms, top %s",
        site.id,
        result.elapsed_ms,
        [(i.chunk.chunk_index, round(i.score, 3)) for i in result.items],
    )
    return result
