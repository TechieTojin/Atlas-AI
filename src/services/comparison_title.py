"""Deterministic, readable titles for comparisons.

Naming a comparison is not worth an LLM call, and on a local 4B model it would
cost more than the comparison itself. These titles are derived from the research
questions by rule, so they are instant, stable, and identical every time the same
runs are compared.

The old title was simply the two questions truncated at 60 characters and joined
with " vs ", which for two phrasings of the same question produced the same
truncated prefix twice.
"""

from __future__ import annotations

import re

from src.unicode_text import WORD_RE as _UNICODE_WORD, comparison_key

MAX_TITLE_CHARS = 120
#: Two questions are "the same question" above this token overlap.
SAME_QUESTION_JACCARD = 0.7

_WORD = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")

#: Question scaffolding and filler. Removing these leaves the subject matter.
_FILLER = frozenset(
    """
    a about above after again against all also am an and another any are as at
    be because been before being below between both but by can cannot could
    currently did do does doing done down during each else enough especially
    even every few for from further had has have having he her here hers him his
    how however i if in into is it its itself just like made main major make many
    may me might more most much must my need no nor not now of off on once one
    only or other our out over own particular per previously primary rather really
    same several she should significant since so some still such than that the
    their them then there these they this those though through thus to too toward
    under until up upon us use used using various very was we were what when where
    whether which while who whom why will with within without would yet you your
    """.split()
)

#: Words that describe the *asking*, not the subject. Dropped even in long runs.
_META = frozenset(
    """
    answer aspect comparison compare consideration context detail difference
    discussion example factor finding identified information insight issue key
    kind point question reason research result review study summary term thing
    topic view way
    """.split()
)

#: Predicate words that attach to a subject without naming one. "Lithium-Ion
#: Batteries Vulnerable" reads better as plain "Lithium-Ion Batteries".
_META |= frozenset(
    """
    able affected based biggest caused driven effective efficient greatest
    largest limited likely possible related smallest susceptible vulnerable
    """.split()
)


def _significant_runs(question: str) -> list[list[str]]:
    """Contiguous stretches of content words, split wherever filler intervenes."""
    runs: list[list[str]] = []
    current: list[str] = []
    for segment in re.split(r"[^A-Za-z0-9\-' ]+", question):
        for match in _WORD.finditer(segment):
            word = match.group(0)
            low = word.lower()
            if low in _FILLER or low in _META or len(low) < 3 or low.isdigit():
                if current:
                    runs.append(current)
                    current = []
                continue
            current.append(word)
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _titlecase(words: list[str]) -> str:
    """Title-case while preserving words that are already capitalised oddly."""
    out = []
    for word in words:
        out.append(word if any(c.isupper() for c in word[1:]) else word.title())
    return " ".join(out)


def topic_phrase(question: str, max_phrases: int = 2) -> str:
    """A short subject phrase for one research question.

    Phrases are ranked by total letter count, a crude but stable proxy for how
    specific a phrase is: "solid-state batteries" outranks "mass production",
    which outranks a bare "barriers". The chosen phrases are then restored to
    their original order so the title still reads like the question.
    """
    runs = _significant_runs(question)
    if not runs:
        # Nothing but filler: fall back to the question itself, trimmed.
        return question.strip()[:MAX_TITLE_CHARS].rstrip(" ,.?-") or "Untitled"
    ranked = sorted(
        enumerate(runs),
        key=lambda pair: (-sum(len(word) for word in pair[1]), pair[0]),
    )
    chosen = sorted(ranked[:max_phrases], key=lambda pair: pair[0])
    return " · ".join(_titlecase(words) for _, words in chosen)


#: Hyphen/apostrophe-joined words in any script ("lithium-ion" stays one token).
_ANY_WORD = re.compile(rf"{_UNICODE_WORD.pattern}(?:[-'](?:{_UNICODE_WORD.pattern}))*")


def _tokens(question: str) -> set[str]:
    """Content tokens of a question, in any script.

    Comparison keys are NFKC + casefold. The old ``[A-Za-z0-9]`` tokenizer
    returned an empty set for any non-Latin question, which made every pair
    of Malayalam or Hindi questions look identical. For ASCII the tokens are
    exactly what they were.
    """
    tokens = set()
    for match in _ANY_WORD.finditer(question):
        token = comparison_key(match.group(0)).replace(" ", "")
        if token and token not in _FILLER:
            tokens.add(token)
    return tokens


def same_question(questions: list[str]) -> bool:
    """True when every question asks substantially the same thing."""
    sets = [_tokens(q) for q in questions if q.strip()]
    if len(sets) < 2:
        return True
    first = sets[0]
    for other in sets[1:]:
        union = first | other
        if not union:
            continue
        if len(first & other) / len(union) < SAME_QUESTION_JACCARD:
            return False
    return True


def comparison_title(questions: list[str]) -> str:
    """Name a comparison from the questions its runs asked.

    Runs of the same question get one subject heading, because repeating the
    question twice tells the reader nothing. Different questions are labelled
    side by side. The full questions stay visible in the UI either way.
    """
    cleaned = [q.strip() for q in questions if q and q.strip()]
    if not cleaned:
        return "Comparison"
    if same_question(cleaned):
        return f"Comparison: {topic_phrase(cleaned[0])}"[:MAX_TITLE_CHARS]
    sides = [topic_phrase(question, max_phrases=1) for question in cleaned]
    return f"Comparison: {' vs '.join(sides)}"[:MAX_TITLE_CHARS]
