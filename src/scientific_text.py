"""Scientific notation in model-generated prose.

Root cause this module guards against (gemma4:e4b, Hindi/French FAST runs):
in JSON mode the model wrote LaTeX such as ``$\\text{MAPbI}_3$`` inside the
``{"report": "..."}`` string with a single backslash. JSON reads ``\\t`` as a
TAB, so ``json.loads`` turned ``\\text`` into ``<TAB>ext`` and the corrupted
formula was persisted. ``\\frac``, ``\\beta``, ``\\nu``, ``\\rho`` collide the
same way (form feed, backspace, newline, carriage return).

Three bounded steps, applied only to Atlas-generated text, never to source
evidence or user input:

* ``repair_json_latex_escapes`` runs on the RAW JSON before decoding, where the
  intent is unambiguous: a backslash that starts a known LaTeX command, or that
  is not a valid JSON escape at all, was meant literally.
* ``plain_notation`` rewrites simple inline math (``$\\text{PbI}_2$``,
  ``$85^{\\circ}\\text{C}$``) to plain text. Anything it cannot rewrite exactly
  is left untouched for validation to catch.
* ``scientific_text_issues`` reports what must never be persisted: control
  characters and leftover LaTeX.
"""

from __future__ import annotations

import re

# LaTeX commands whose first letter forms a valid JSON escape (\b \f \n \r \t).
_COLLIDING_COMMANDS = (
    "textdegree|textrm|textit|textbf|textsubscript|textsuperscript|text|times|theta|tau|to"
    "|frac|beta|bar|bf|nu|neq|nabla|rho|rm|right|rangle"
)
_JSON_ESCAPE_RE = re.compile(
    r'\\(?:(?P<keep>["\\/]|u[0-9a-fA-F]{4})'
    rf"|(?P<latex>(?:{_COLLIDING_COMMANDS})(?![A-Za-z]))"
    r"|(?P<simple>[bfnrt])"
    r"|(?P<invalid>.|$))",
    re.S,
)


def repair_json_latex_escapes(raw: str) -> str:
    """Double the backslashes a model meant literally, inside raw JSON text.

    Valid JSON escapes are kept, except where the escape letter begins a LaTeX
    command (``\\text`` is LaTeX, not TAB + "ext"). Invalid escapes such as
    ``\\circ`` or ``\\mathrm`` would make the whole object undecodable, so they
    are made literal too. The result decodes to exactly what the model wrote.
    """

    def fix(match: re.Match[str]) -> str:
        if match.group("keep") is not None or match.group("simple") is not None:
            return match.group(0)
        return "\\" + match.group(0)

    return _JSON_ESCAPE_RE.sub(fix, raw)


# Only spans with a math signal: "$5 and $10" is prose about money, not math.
_MATH_SPAN_RE = re.compile(r"\$([^$\n]{0,120}[\\_^][^$\n]{0,120})\$")
_SIMPLE_TOKENS = [
    (re.compile(r"\^\s*\{?\s*\\circ\s*\}?\s*(?:\\(?:text|mathrm|rm)\s*\{\s*([CFK])\s*\}|([CFK]))?"),
     lambda m: " °" + (m.group(1) or m.group(2) or "")),
    (re.compile(r"\\(?:text|mathrm|textrm|rm)\s*\{([^{}\\$]*)\}"), lambda m: m.group(1)),
    (re.compile(r"_\{([0-9.]+)\}|_([0-9])"), lambda m: m.group(1) or m.group(2)),
    (re.compile(r"\\times"), lambda m: "×"),
    (re.compile(r"\\pm"), lambda m: "±"),
    (re.compile(r"\\approx"), lambda m: "≈"),
    (re.compile(r"\\cdot"), lambda m: "·"),
    (re.compile(r"\\mu"), lambda m: "µ"),
    (re.compile(r"\\%"), lambda m: "%"),
    (re.compile(r"\\[,;!]|~"), lambda m: " "),
]
_LEFTOVER_MATH_RE = re.compile(r"[\\{}^_$]")


def _plain_span(inner: str) -> str | None:
    text = inner
    for pattern, repl in _SIMPLE_TOKENS:
        text = pattern.sub(repl, text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if not text or _LEFTOVER_MATH_RE.search(text):
        return None  # not provably simple: leave it for validation
    return text


def plain_notation(text: str) -> str:
    """Rewrite simple inline LaTeX math to plain text; leave the rest as is."""

    def fix(match: re.Match[str]) -> str:
        plain = _plain_span(match.group(1))
        return match.group(0) if plain is None else plain

    return _MATH_SPAN_RE.sub(fix, text)


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAB_COMMAND_RE = re.compile(r"\t(?:ext|imes|heta|au|o\b)|\x08eta|\x0crac|\x0d(?:ho|ight)")
_LATEX_RE = re.compile(r"\\[A-Za-z]+")


def scientific_text_issues(text: str) -> list[str]:
    """Problems that make generated scientific prose unfit to persist."""
    issues = []
    if _CONTROL_RE.search(text) or _TAB_COMMAND_RE.search(text):
        issues.append("control characters (corrupted escape sequence) in generated text")
    if _LATEX_RE.search(text) or _MATH_SPAN_RE.search(text):
        issues.append("LaTeX markup in generated text")
    return issues


PLAIN_NOTATION_RETRY_NOTE = (
    "\n\nYour previous answer used LaTeX or broken escape sequences. Write every "
    "formula, unit and number as plain text exactly as the sources write it, "
    "with no $...$ math and no backslash commands."
)
