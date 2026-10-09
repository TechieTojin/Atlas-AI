"""Question-appropriate evidence for one Website Chat answer.

Chunks stay 400-800 tokens because that is what retrieves well. The answer
prompt does not need all six retrieved chunks in full: on this CPU every
prompt token costs prompt-evaluation time (measured ~20 tokens/s), and long
prompts invite long answers. So, per question:

* how many passages: a focused question keeps the strongest few (and drops
  passages scoring far below the best); a broad question (summarise, explain,
  list...) keeps up to six;
* how much of each passage: the sentences around the question's terms, in
  page order, with "…" where text was left out. A passage with no lexical
  anchor (e.g. a Hindi question about an English page) is kept whole, so a
  cross-language question never loses its evidence to a lexical guess;
* how long the answer may be: a short budget for focused questions.

Only the MODEL INPUT is shortened. The stored chunk, and the passage the
citation drawer shows, are never modified; every excerpt the model sees is a
verbatim subset of the passage its citation opens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.unicode_text import words
from src.website.chunking import estimate_tokens
from src.website.retrieval import Retrieved, content_terms

#: Words that mark a question needing breadth, in the Website Chat languages.
_BROAD_WORDS = frozenset(
    "summarize summarise summary summarizing overview outline explain describe list compare "
    "main key overall advantages disadvantages challenges problems issues pros cons "
    "resume resumen resumir resúmeme explica describe enumera compara principales ventajas "
    "desventajas problemas "
    "zusammenfassung zusammenfassen fasse erkläre erklären beschreibe beschreiben überblick "
    "wichtigsten vorteile nachteile probleme vergleiche "
    "सारांश संक्षेप मुख्य समझाइए समझाएं वर्णन सूची तुलना फायदे नुकसान समस्याएं चुनौतियां".split()
)
_BROAD_PHRASES = ("what does the page say", "what does this page say", "tell me about", "qué dice", "was sagt")

FOCUSED_K = 4
BROAD_K = 6
MIN_K = 3
#: A focused question drops passages scoring this far below the best one.
SCORE_MARGIN = 0.10
FOCUSED_EXCERPT_TOKENS = 220
BROAD_EXCERPT_TOKENS = 320
FOCUSED_OUTPUT_TOKENS = 350
BROAD_OUTPUT_TOKENS = 700
OMITTED = "…"

_SENTENCE_RE = re.compile(r"(?<=[.!?।])\s+")


@dataclass(frozen=True)
class AnswerPlan:
    broad: bool
    passages: int
    excerpt_tokens: int
    max_tokens: int

    def as_metrics(self) -> dict:
        return {
            "broad": self.broad, "passages": self.passages,
            "excerpt_tokens": self.excerpt_tokens, "max_tokens": self.max_tokens,
        }


def is_broad(question: str) -> bool:
    lowered = question.lower()
    if any(phrase in lowered for phrase in _BROAD_PHRASES):
        return True
    return any(token in _BROAD_WORDS for token in words(lowered))


def plan_for(question: str) -> AnswerPlan:
    if is_broad(question):
        return AnswerPlan(True, BROAD_K, BROAD_EXCERPT_TOKENS, BROAD_OUTPUT_TOKENS)
    return AnswerPlan(False, FOCUSED_K, FOCUSED_EXCERPT_TOKENS, FOCUSED_OUTPUT_TOKENS)


def select_passages(items: list[Retrieved], plan: AnswerPlan) -> list[Retrieved]:
    """The best ``plan.passages`` items; a focused question also drops weak ones."""
    chosen = items[: plan.passages]
    if plan.broad or not chosen:
        return chosen
    floor = chosen[0].score - SCORE_MARGIN
    strong = [item for item in chosen if item.score >= floor]
    return strong if len(strong) >= MIN_K else chosen[:MIN_K]


def _units(text: str) -> list[tuple[int, str]]:
    """(line number, sentence) pieces; headings and table rows stay whole."""
    units: list[tuple[int, str]] = []
    for number, line in enumerate(text.split("\n")):
        if not line.strip():
            continue
        if line.startswith("#") or " | " in line:
            units.append((number, line))
        else:
            units.extend((number, s) for s in _SENTENCE_RE.split(line) if s.strip())
    return units


def focus_excerpt(text: str, terms: set[str], budget: int) -> str:
    """A verbatim, in-order subset of ``text`` around ``terms``, about ``budget`` tokens.

    Returns ``text`` unchanged when it already fits or nothing in it matches
    the question (no lexical anchor: keep the whole passage, never guess).
    """
    if estimate_tokens(text) <= budget or not terms:
        return text
    units = _units(text)
    scores = [len(terms & content_terms(sentence)) for _, sentence in units]
    if not any(scores):
        return text
    keep: set[int] = set()
    used = 0
    if units and units[0][1].startswith("#"):
        keep.add(0)  # the passage's own heading
        used += estimate_tokens(units[0][1])
    ranked = sorted((i for i, s in enumerate(scores) if s), key=lambda i: (-scores[i], i))
    anchors = 0
    for i in ranked:
        cost = estimate_tokens(units[i][1])
        if used + cost > budget and anchors:
            break  # the best-matching sentence is always kept, even if long
        keep.add(i)
        used += cost
        anchors += 1
    # Grow around the anchors with neighbouring sentences while budget remains.
    radius = 1
    while used < budget and radius < len(units):
        grew = False
        for anchor in sorted(keep):
            for i in (anchor - radius, anchor + radius):
                if 0 <= i < len(units) and i not in keep:
                    cost = estimate_tokens(units[i][1])
                    if used + cost <= budget:
                        keep.add(i)
                        used += cost
                        grew = True
        if not grew:
            break
        radius += 1
    out: list[str] = []
    previous: int | None = None
    previous_line: int | None = None
    for i in sorted(keep):
        line, sentence = units[i]
        if previous is not None and i != previous + 1:
            out.append(f"\n{OMITTED}\n")
        elif previous_line is not None and line != previous_line:
            out.append("\n")
        elif out:
            out.append(" ")
        out.append(sentence)
        previous, previous_line = i, line
    if previous is not None and previous != len(units) - 1:
        out.append(f"\n{OMITTED}")
    if min(keep) > 0:
        out.insert(0, f"{OMITTED}\n")
    return "".join(out).strip()


def question_terms(question: str, previous_question: str = "") -> set[str]:
    """Terms that anchor excerpts; a follow-up borrows its previous question's."""
    return content_terms(question) | content_terms(previous_question)
