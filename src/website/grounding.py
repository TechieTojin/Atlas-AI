"""Deterministic grounding check for Website Chat answers: numbers.

A citation proves the model pointed at an excerpt, not that its figures came
from one. A small model can produce a fluent, cited sentence with a number
that is in no excerpt (live acceptance: an example sentence from the prompt,
"91% capacity", was returned for an unanswerable question). Every multi-digit
or decimal number in an answer must therefore appear somewhere in the
evidence the model was given (or in the user's question). The check is
language-independent and tolerant of formatting: subscripts (TiO₂ / TiO2),
other scripts' decimal digits, and thousands/decimal separators
(34.6 / 34,6, 1,000 / 1000).
"""

from __future__ import annotations

import re
import unicodedata

_NUMBER_RE = re.compile(r"\d+(?:[.,   ]\d+)*")
_CITATION_RE = re.compile(r"\[\d+(?:\s*[,;–-]\s*\d+)*\]")
# "1) …", "2. …" list numbering written by the model is structure, not a fact.
_ENUMERATION_RE = re.compile(r"(?:^|(?<=[\s:;(]))\d{1,2}[).](?=\s)", re.MULTILINE)


def _ascii_digits(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(str(unicodedata.digit(c)) if c.isdecimal() and not c.isascii() else c for c in text)


def _forms(token: str) -> tuple[str, list[str]]:
    runs = re.findall(r"\d+", token)
    return "".join(runs), runs


def evidence_numbers(*texts: str) -> set[str]:
    found: set[str] = set()
    for text in texts:
        for token in _NUMBER_RE.findall(_ascii_digits(text)):
            joined, runs = _forms(token)
            found.add(joined)
            found.update(runs)
    return {n.lstrip("0") or "0" for n in found}


def ungrounded_numbers(answer: str, evidence: set[str]) -> list[str]:
    """Numbers in ``answer`` that the evidence does not contain."""
    text = _ENUMERATION_RE.sub(" ", _CITATION_RE.sub(" ", _ascii_digits(answer)))
    missing = []
    for token in _NUMBER_RE.findall(text):
        joined, runs = _forms(token)
        if len(runs) == 1 and len(joined) == 1:
            continue  # single digits: counts and labels, too common to judge
        normal = lambda n: n.lstrip("0") or "0"  # noqa: E731
        if normal(joined) in evidence or all(normal(r) in evidence for r in runs):
            continue
        missing.append(token)
    return missing
