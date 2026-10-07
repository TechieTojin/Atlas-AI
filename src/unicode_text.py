"""Script-neutral text primitives for structural checks.

Atlas's report pipeline decides things like "is this draft empty?", "did the
output cap cut a sentence?", "are these two questions the same?" and "is this
finding a duplicate?". Those are structural questions, not linguistic ones,
and they must not depend on the text being English.

Python's ``\\w`` is not enough for that: Indic vowel signs and viramas are
combining marks (categories Mc/Mn), which ``\\w`` does not match, so
``re.findall(r"\\w+", "മലയാളം")`` splits one word into fragments. Words here are
therefore runs of letters, combining marks and decimal digits.

Everything is standard library and cheap. Nothing here is tokenization in a
linguistic sense: whitespace/letter-run word counts are approximate for some
languages, and only ever used as structural thresholds.
"""

from __future__ import annotations

import re
import unicodedata

# --- Character classes -------------------------------------------------------


#: Planes that contain combining marks: the BMP, the Supplementary Multilingual
#: Plane and the variation-selector supplement. Scanning only these keeps the
#: one-time class construction to a few tens of milliseconds.
_MARK_PLANES = (range(0x0000, 0x20000), range(0xE0000, 0xE0200))


def _ranges_for(predicate) -> str:
    """A regex character-class body covering every code point matching ``predicate``."""
    parts: list[str] = []
    start = prev = None
    for cp in (cp for plane in _MARK_PLANES for cp in plane):
        if predicate(chr(cp)):
            if start is None:
                start = prev = cp
            elif cp == prev + 1:
                prev = cp
            else:
                parts.append(_range(start, prev))
                start = prev = cp
    if start is not None:
        parts.append(_range(start, prev))
    return "".join(parts)


def _range(start: int, end: int) -> str:
    return re.escape(chr(start)) if start == end else f"{re.escape(chr(start))}-{re.escape(chr(end))}"


#: Combining marks (Mn, Mc, Me): Indic vowel signs, viramas, anusvara, accents.
_MARKS = _ranges_for(lambda c: unicodedata.category(c).startswith("M"))

#: One "word": letters, decimal digits and combining marks, in any script.
#: ``[^\W_]`` is Python's Unicode letter-or-digit; marks are added explicitly.
WORD_RE = re.compile(rf"(?:[^\W_]|[{_MARKS}])+")

#: Characters that end a sentence in Atlas's initial languages: Latin
#: punctuation plus the Devanagari danda and double danda. Malayalam uses ".".
SENTENCE_TERMINATORS = ".!?।॥"
_TERMINATOR_CLASS = re.escape(SENTENCE_TERMINATORS)
#: Whitespace following a sentence terminator (a split point between sentences).
SENTENCE_BOUNDARY_RE = re.compile(rf"(?<=[{_TERMINATOR_CLASS}])\s+")


def _is_letter(char: str) -> bool:
    return unicodedata.category(char).startswith("L")


def _is_letter_or_mark(char: str) -> bool:
    category = unicodedata.category(char)
    return category.startswith("L") or category.startswith("M")


# --- Meaningful text ---------------------------------------------------------


def words(text: str) -> list[str]:
    """Letter/mark/digit runs in any script, in order."""
    return WORD_RE.findall(text or "")


def is_meaningful_word(word: str) -> bool:
    """At least two letter-or-mark code points, one of them a letter.

    The script-neutral form of the old ``[A-Za-z]{2,}`` test: "is" and "है"
    (consonant + vowel sign) qualify; "a", "7", "12" and a lone consonant do not.
    """
    return sum(1 for c in word if _is_letter_or_mark(c)) >= 2 and any(_is_letter(c) for c in word)


def has_meaningful_text(text: str) -> bool:
    """Whether ``text`` contains any real prose word, in any script.

    Whitespace, punctuation, citation markers such as ``[1]``, bare numbers,
    JSON scaffolding (``{}``, ``{"report": ""}`` keys aside) and control
    characters do not count.
    """
    # Lazy scan: a real report answers on its first word.
    return any(is_meaningful_word(match.group(0)) for match in WORD_RE.finditer(text or ""))


def content_word_count(text: str) -> int:
    """Approximate count of prose words (letter-bearing runs), any script.

    A structural measure only: for scripts written without spaces between
    words it undercounts, and it is never presented as a linguistic word count.
    """
    return sum(1 for word in words(text) if any(_is_letter(c) for c in word))


# --- Comparison keys ---------------------------------------------------------


def comparison_key(text: str) -> str:
    """Deterministic key for equality/dedup, never stored as display text.

    NFKC folds compatibility forms (full-width letters, ligatures, presentation
    forms) so visually identical text compares equal; ``casefold`` is the
    Unicode-correct lower-casing. Punctuation and spacing differences are
    dropped; letters, marks and digits of every script are kept, so two
    different Malayalam sentences never collapse to the same key.
    """
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(words(normalized))


# --- Citations ---------------------------------------------------------------

#: The canonical citation marker: ASCII digits only. This is what Atlas stores.
CANONICAL_CITATION_RE = re.compile(r"\[([0-9]+)\]")
#: A bracketed run of decimal digits in any script (Python's ``\d`` is Unicode).
_ANY_DIGIT_CITATION_RE = re.compile(r"\[(\d+)\]")


def _single_script_ascii(digits: str) -> str | None:
    """ASCII form of a run of decimal digits from ONE digit system, else None.

    Mixed systems such as ``1२`` are rejected: Python would happily read it as
    12, but that is a malformed marker, not a citation Atlas should invent.
    """
    zeros = {ord(c) - unicodedata.decimal(c) for c in digits}
    if len(zeros) != 1:
        return None
    return "".join(str(unicodedata.decimal(c)) for c in digits)


def normalize_citation_markers(text: str) -> str:
    """Rewrite ``[१२]``-style markers to canonical ``[12]``.

    Only decimal digits (Unicode category Nd) are converted, and only when the
    whole marker uses a single digit system. ASCII markers are untouched, so
    existing English reports come out byte-identical. Mixed-system markers are
    left as they are; :func:`strip_noncanonical_citations` removes them.
    """

    def convert(match: re.Match[str]) -> str:
        digits = match.group(1)
        if digits.isascii():
            return match.group(0)
        ascii_digits = _single_script_ascii(digits)
        return match.group(0) if ascii_digits is None else f"[{ascii_digits}]"

    return _ANY_DIGIT_CITATION_RE.sub(convert, text)


def is_canonical_citation(digits: str) -> bool:
    return digits.isascii() and digits.isdigit()


# --- Sentence ends -----------------------------------------------------------


def ends_sentence(text: str) -> bool:
    """Whether the stripped text ends with a sentence terminator."""
    stripped = (text or "").rstrip()
    return bool(stripped) and stripped[-1] in SENTENCE_TERMINATORS


# --- Filenames ---------------------------------------------------------------

#: Characters Windows forbids in file names, plus path separators everywhere.
_WINDOWS_INVALID = set('<>:"/\\|?*')


def _filename_char_ok(char: str, extra: str) -> bool:
    if char in _WINDOWS_INVALID or char in "\x00":
        return False
    if char.isascii():
        return char.isalnum() or char in extra
    category = unicodedata.category(char)
    # Letters, combining marks and digits of any script; never symbols/emoji,
    # controls, format characters or private-use code points.
    return category[0] in "LM" or category == "Nd"


def filename_safe(text: str, *, extra: str = " _-", replacement: str = "") -> str:
    """``text`` restricted to characters that are safe in file names everywhere.

    ASCII keeps exactly the historical rule (alphanumerics plus ``extra``), so
    English names are unchanged. Unicode letters, marks and digits are kept
    instead of being discarded; everything else becomes ``replacement``.
    """
    normalized = unicodedata.normalize("NFC", text or "")
    return "".join(c if _filename_char_ok(c, extra) else replacement for c in normalized)


def truncate_clusters(text: str, limit: int) -> str:
    """``text[:limit]`` without leaving a combining mark detached from its base.

    A cut between a consonant and its vowel sign would leave a broken
    syllable, so the cut moves back to the previous base character.
    """
    if len(text) <= limit:
        return text
    cut = limit
    while cut > 0 and unicodedata.category(text[cut]).startswith("M"):
        cut -= 1
    return text[:cut]
