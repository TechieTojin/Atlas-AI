"""Deterministic cleanup of evidence excerpts before they reach the model.

Search snippets and extracted pages often carry bibliography entries, site
names/navigation, keyword lists, and mis-decoded characters. They cost
prompt time, give the model nothing to cite, and made the last-resort
Evidence Summary unreadable. This keeps complete, claim-bearing sentences
and drops the rest. Pure text processing: no LLM, nothing invented.
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")

# Bibliography / reference-list signals.
_REFERENCE_PATTERNS = [
    re.compile(r"\bet al\.?", re.I),
    re.compile(r"\bdoi\b|doi\.org|\bISBN\b|\bISSN\b", re.I),
    re.compile(r"\b(Available online|Retrieved from|Accessed on|accessed)\b", re.I),
    re.compile(r"\b(pp?\.|vol\.|no\.)\s*\d", re.I),
    re.compile(r"^\s*\[?\d{1,3}[\].]\s+[A-Z][a-z]+,\s*[A-Z]\."),  # "29. Smith, J."
    re.compile(r"(?:[A-Z][a-z]+,\s*(?:[A-Z]\.\s*){1,3}[;,]\s*){2,}"),  # author lists
]
# Navigation / site chrome signals.
_NAV_PATTERNS = re.compile(
    r"\b(skip to|cookie|subscribe|sign in|log in|newsletter|share this|"
    r"all rights reserved|privacy policy|terms of use|read more|click here|"
    r"menu|related articles|back to top)\b",
    re.I,
)
_TITLE_RUN_RE = re.compile(r"(?:\b[A-Z][A-Za-z]+\b[\s&(),-]+){5,}")
_VERB_HINT_RE = re.compile(
    r"\b(is|are|was|were|be|been|has|have|had|can|could|may|might|will|would|"
    r"should|must|requires?|reduces?|increases?|causes?|leads?|shows?|found|"
    r"remains?|poses?|makes?|allows?|limits?|costs?|ranges?|involves?|"
    r"depends?|suggests?|indicates?|provides?|offers?|faces?)\b|\w+(ed|es)\b",
    re.I,
)

# Common UTF-8-read-as-cp1252 sequences and bare replacement characters.
_MOJIBAKE = {
    "â€“": "-", "â€”": "-", "â€™": "'",
    "â€œ": '"', "â€\u009d": '"', "Â ": " ",
}


def normalize_text(text: str) -> str:
    for bad, good in _MOJIBAKE.items():
        text = text.replace(bad, good)
    # A lone replacement char between digits is almost always a dash.
    text = re.sub(r"(?<=\d)�(?=\d)", "-", text)
    text = text.replace("�", "'")
    text = re.sub(r"#+\s*", "", text)  # stray markdown heading markers
    return " ".join(text.split())


def is_reference_fragment(sentence: str) -> bool:
    hits = sum(1 for p in _REFERENCE_PATTERNS if p.search(sentence))
    return hits >= 1 and (hits >= 2 or not _VERB_HINT_RE.search(sentence))


def is_claim_sentence(sentence: str) -> bool:
    """A complete-looking sentence that states something citable."""
    words = _WORD_RE.findall(sentence)
    if len(words) < 7 or len(sentence) > 600:
        return False
    if is_reference_fragment(sentence) or _NAV_PATTERNS.search(sentence):
        return False
    if not _VERB_HINT_RE.search(sentence):
        return False  # keyword lists, headings, titles
    # Mostly Title-Case tokens, or a long Title-Case run, is a heading or a
    # keyword list (e.g. "LCOH Analysis Applying ... Clean Hydrogen Overseas
    # Introduction Cost"), not citable prose.
    capitalized = sum(1 for w in words if w[0].isupper())
    if capitalized / len(words) >= 0.5:
        return False
    return _TITLE_RUN_RE.search(sentence) is None


def _drop_title_echo(text: str, title: str) -> str:
    """Remove leading site-name / title echoes such as
    'Ecosense ecosense Cost to Produce Hydrogen ... The cost to ...'."""
    for _ in range(3):
        before = text
        words = text.split(" ", 2)
        if len(words) >= 2 and words[0].lower() == words[1].lower():
            text = words[2] if len(words) > 2 else ""
        for candidate in (title, title.split(" - ")[0], title.split(" | ")[0]):
            candidate = (candidate or "").strip()
            if len(candidate) >= 8 and text.lower().startswith(candidate.lower()):
                text = text[len(candidate):].lstrip(" :-|")
        if text == before:
            break
    return text


def claim_sentences(text: str, title: str = "") -> list[str]:
    """Unique, claim-bearing sentences from an excerpt, in original order."""
    cleaned = _drop_title_echo(normalize_text(text), title)
    seen: set[str] = set()
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(cleaned):
        sentence = sentence.strip()
        # Leading fragment cut mid-sentence by the search snippet.
        if sentence and sentence[0].islower():
            continue
        key = sentence.lower()
        if key in seen or not is_claim_sentence(sentence):
            continue
        if not sentence.endswith((".", "!", "?")):
            continue  # incomplete trailing fragment
        seen.add(key)
        out.append(sentence)
    return out


def has_claims(text: str, title: str = "") -> bool:
    """Whether an excerpt contains at least one citable claim sentence."""
    return bool(claim_sentences(text, title))


def clean_excerpt(text: str, title: str = "", max_chars: int = 700) -> str:
    """Claim-bearing sentences joined up to ``max_chars``, never cut mid-sentence.

    Falls back to the whitespace-normalized original when nothing qualifies,
    so a source never silently loses all of its evidence text.
    """
    sentences = claim_sentences(text, title)
    if not sentences:
        return normalize_text(text)[:max_chars]
    kept: list[str] = []
    total = 0
    for sentence in sentences:
        if kept and total + len(sentence) + 1 > max_chars:
            break
        kept.append(sentence)
        total += len(sentence) + 1
    return " ".join(kept)[: max(max_chars, len(kept[0]))]
