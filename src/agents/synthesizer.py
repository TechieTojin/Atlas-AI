"""Synthesizer agent: writes the final cited Markdown report.

Source integrity: the LLM only ever sees numbered sources and cites by
number; the ``## Sources`` section is rendered deterministically in code from
the actual collected Source objects, so URLs can never be fabricated.
Any reference/bibliography section the LLM emits on its own is stripped
deterministically, invalid citation numbers are removed, and a report with
evidence but zero valid citations gets exactly one repair attempt.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from src.cancellation import awake_clock
from src.graph.state import AtlasState
from src.models.research import Evidence, Source
from src.tools.selection import select_synthesis_evidence
from src.prompts.research import (
    CITATION_REPAIR_SYSTEM,
    CITATION_REPAIR_USER,
    SYNTHESIZER_MEMORY_BLOCK,
    SYNTHESIZER_SYSTEM,
    SYNTHESIZER_USER,
)

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")
# A heading (any level, optional bold/numbering) whose title is a reference list.
_REFERENCE_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*\**\s*(?:\d+\.?\s*)?"
    r"(references|bibliography|sources|works cited|citations|source list)\b",
    re.IGNORECASE,
)
_ANY_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")

# Per-source cap on evidence text sent to the synthesizer. Multiple snippets
# from the same source share this budget, which removes the repeated
# title/URL duplication that bloated earlier prompts.
_MAX_CHARS_PER_SOURCE = 1500


def build_numbered_sources(evidence: list[Evidence]) -> list[Source]:
    """Collapse evidence to an ordered list of unique sources (by URL)."""
    sources: list[Source] = []
    seen: set[str] = set()
    for item in evidence:
        key = item.source.normalized_url
        if key not in seen:
            seen.add(key)
            sources.append(item.source)
    return sources


def format_evidence_for_synthesis(
    evidence: list[Evidence],
    sources: list[Source],
    max_chars_per_source: int = _MAX_CHARS_PER_SOURCE,
    clean: bool = False,
) -> str:
    """Render one ``SOURCE [n]`` block per unique source.

    Snippets from the same source are merged under one numbered block so the
    LLM sees an unambiguous number→source mapping without duplicated
    boilerplate. URLs are intentionally omitted: the LLM cites numbers only,
    and Atlas renders real URLs itself.
    """
    index = {s.normalized_url: i for i, s in enumerate(sources, 1)}
    texts: dict[int, list[str]] = {i: [] for i in index.values()}
    for item in evidence:
        n = index[item.source.normalized_url]
        budget = max_chars_per_source - sum(len(t) for t in texts[n])
        if budget > 50:
            if clean:
                # Claim-bearing sentences only, never cut mid-sentence.
                from src.tools.excerpts import clean_excerpt

                text = clean_excerpt(item.content, item.source.title, budget)
                if text and text not in texts[n]:
                    texts[n].append(text)
            else:
                texts[n].append(item.content[:budget])
    blocks = []
    for i, source in enumerate(sources, 1):
        body = "\n".join(texts[i]) or "(no snippet)"
        blocks.append(f"SOURCE [{i}]\nTitle: {source.title}\nEvidence: {body}")
    return "\n\n".join(blocks)


def strip_reasoning_artifacts(text: str) -> str:
    """Deterministically remove model reasoning/thinking artifacts.

    Local Qwen models sometimes emit thinking in the normal content field
    despite ``reasoning=False``: either a full ``<think>...</think>`` block,
    or drafting prose that ends with an orphan ``</think>`` marker before
    the real answer begins. Everything up to and including the LAST
    ``</think>`` is reasoning, never report content, so dropping it is safe;
    text without think markers is returned unchanged.
    """
    # Full <think>...</think> blocks first.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Orphan close tag: the answer follows the last </think>.
    marker = re.compile(r"</think>", re.IGNORECASE)
    last = None
    for match in marker.finditer(text):
        last = match
    if last is not None:
        text = text[last.end():]
    # An unterminated opening tag would make everything after it reasoning.
    open_match = re.search(r"<think>", text, re.IGNORECASE)
    if open_match is not None:
        text = text[: open_match.start()]
    return text.strip()


def strip_generated_reference_sections(markdown: str) -> str:
    """Deterministically remove any LLM-written reference/bibliography/sources
    section: from such a heading up to the next heading (or end of text)."""
    lines = markdown.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        if _REFERENCE_HEADING_RE.match(line):
            skipping = True
            continue
        if skipping and _ANY_HEADING_RE.match(line):
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept).rstrip()


def strip_invalid_citations(markdown: str, valid_max: int) -> str:
    """Remove bracketed citation numbers that do not exist in the source list."""
    return _CITATION_RE.sub(
        lambda m: m.group(0) if 1 <= int(m.group(1)) <= valid_max else "",
        markdown,
    )


def extract_valid_citations(markdown: str, valid_max: int) -> set[int]:
    """Citation numbers present in the text that map to real sources."""
    return {int(n) for n in _CITATION_RE.findall(markdown) if 1 <= int(n) <= valid_max}


def render_source_line(source: Source) -> str:
    """Deterministic rendering for one source (web link or document provenance)."""
    if source.kind == "document":
        page = f", p. {source.page}" if source.page else ""
        return f"[Document: {source.filename}{page}]"
    return f"[{source.title}]({source.url})"


def render_sources_section(sources: list[Source], cited: set[int]) -> str:
    """Render the one and only Sources section from real collected sources."""
    lines = ["## Sources", ""]
    for i, source in enumerate(sources, 1):
        marker = "" if i in cited or not cited else " *(collected, not cited)*"
        lines.append(f"{i}. {render_source_line(source)}{marker}")
    return "\n".join(lines)


class SynthesizerAgent:
    """Produces the final Markdown report with verified citations.

    Synthesis runs on a deterministically selected evidence subset (budgeted
    for local models); source numbering is contiguous over that subset and
    the rendered ``## Sources`` section corresponds to it exactly, so a
    citation like [5] always refers to the listed source 5.
    """

    def __init__(
        self,
        llm: Any,
        max_evidence: int = 12,
        target_words: int = 1000,
        emitter: Any = None,
        structure: str = "",
        repair_llm: Any = None,
        chars_per_source: int = _MAX_CHARS_PER_SOURCE,
        context_chars: int = 0,
        deadline: float | None = None,
        repair_min_seconds: float = 0.0,
        max_words: int = 0,
        json_mode: bool = False,
        clean_evidence: bool = False,
        repair_check: Any = None,
        retry_check: Any = None,
        memory_context: str = "",
    ) -> None:
        from src.events import NullEmitter
        from src.templates import resolve_template

        self._llm = llm
        self._repair_llm = repair_llm if repair_llm is not None else llm
        self._max_evidence = max_evidence
        self._target_words = target_words
        self._emitter = emitter or NullEmitter()
        self._structure = structure or resolve_template("STANDARD")[1]
        self._chars_per_source = chars_per_source
        self._context_chars = context_chars  # 0 = no total cap
        self._deadline = deadline
        self._repair_min_seconds = repair_min_seconds
        # Hard word ceiling (FAST): stated to the model AND enforced by
        # trimming a partial final sentence if the output cap is reached.
        self._max_words = max_words
        # Grammar-constrained output (FAST): stops thinking-only models from
        # deliberating in prose before the report.
        self._json_mode = json_mode
        # FAST: cleaned, claim-bearing excerpts (less prompt time, better
        # grounding) and an adaptive check that repair fits the budget.
        self._clean_evidence = clean_evidence
        self._repair_check = repair_check
        self._retry_check = retry_check
        # Project memory is context only: appended as a clearly separated,
        # non-citable block AFTER the numbered sources, so it can never
        # shift or pollute citation numbering.
        self._memory_context = memory_context

    def _invoke(self, system: str, user: str, llm: Any = None) -> str:
        model = llm or self._llm
        if self._json_mode:
            user += JSON_REPORT_INSTRUCTION
            response = model.invoke(
                [("system", system), ("user", user)], format=REPORT_JSON_SCHEMA
            )
        else:
            response = model.invoke([("system", system), ("user", user)])
        body = response.content if hasattr(response, "content") else str(response)
        body = str(body)
        return extract_report_text(body) if self._json_mode else body

    def _per_source_budget(self, n_sources: int) -> int:
        """Per-source evidence chars, shrunk so the total context stays bounded."""
        budget = self._chars_per_source
        if self._context_chars and n_sources:
            budget = min(budget, self._context_chars // n_sources)
        return max(budget, 200)

    def _retry_affordable(self) -> bool:
        if self._retry_check is not None:
            return bool(self._retry_check())
        if self._deadline is None:
            return True
        return (self._deadline - awake_clock()) >= self._repair_min_seconds

    def _fallback_result(self, selected, sources, reason: str) -> dict:
        body = extractive_fallback_report(selected, sources)
        cited = extract_valid_citations(body, len(sources))
        report = f"{body.rstrip()}\n\n{render_sources_section(sources, cited)}\n"
        return {
            "final_report": report,
            "sources_selected": len(sources),
            "sources_cited": len(cited),
            "citation_repair_ms": 0,
            "synthesis_fallback": True,
            "synthesis_fallback_reason": reason,
        }

    def _repair_affordable(self) -> bool:
        if self._repair_check is not None:
            return bool(self._repair_check())
        if self._deadline is None:
            return True
        return (self._deadline - awake_clock()) >= self._repair_min_seconds

    def _clean(self, body: str, n_sources: int) -> tuple[str, set[int]]:
        """Deterministic post-processing applied to EVERY generation path:
        strip reasoning artifacts, LLM reference sections, and invalid
        citation numbers; return the cleaned body and valid cites."""
        body = strip_reasoning_artifacts(body)
        body = strip_generated_reference_sections(body)
        body = strip_invalid_citations(body, n_sources)
        return body, extract_valid_citations(body, n_sources)

    def __call__(self, state: AtlasState) -> dict[str, Any]:
        logger.info("Synthesizing final report...")
        evidence = state.get("evidence", [])
        question = state["question"]

        if not evidence:
            report = (
                f"# Research Report\n\n**Question:** {question}\n\n"
                "Atlas was unable to collect any evidence for this question "
                "(searches failed or returned no results), so no supported "
                "answer can be given. Please retry, refine the question, or "
                "check search API availability."
            )
            return {"final_report": report}

        selected = select_synthesis_evidence(
            evidence, self._max_evidence, require_claims=self._clean_evidence
        )
        if len(selected) < len(evidence):
            logger.info(
                "Synthesis evidence budget: using %d of %d collected items "
                "(full set retained in state).",
                len(selected),
                len(evidence),
            )
        sources = build_numbered_sources(selected)
        numbered_evidence = format_evidence_for_synthesis(
            selected, sources, max_chars_per_source=self._per_source_budget(len(sources)),
            clean=self._clean_evidence,
        )
        user = SYNTHESIZER_USER.format(question=question, evidence=numbered_evidence)
        if self._memory_context:
            user += SYNTHESIZER_MEMORY_BLOCK.format(memory=self._memory_context)
        if self._max_words:
            user += f"\n\nHard length limit: at most {self._max_words} words."
        system = SYNTHESIZER_SYSTEM.format(
            target_words=self._target_words, structure=self._structure
        )
        from src.llm import is_llm_timeout

        for attempt in (1, 2):
            prompt = user if attempt == 1 else user + EMPTY_DRAFT_RETRY_NOTE.format(
                words=self._target_words
            )
            try:
                body = self._invoke(system, prompt)
            except Exception as exc:
                if not is_llm_timeout(exc):
                    raise
                # Never discard collected research because generation ran out
                # of time: emit a clearly labeled, fully cited summary.
                logger.warning("Synthesis exceeded its time budget; using extractive fallback.")
                return self._fallback_result(selected, sources, "time budget exceeded")
            if self._max_words:
                body = trim_partial_sentence(body)
            body, cited = self._clean(body, len(sources))
            if not is_empty_draft(body):
                break
            # Live failure: qwen3:4b in JSON mode returned {"report": ""}
            # (8 tokens). An empty draft is never accepted as a report.
            if attempt == 1 and self._retry_affordable():
                logger.warning("Synthesis returned an empty draft; retrying once.")
                continue
            logger.warning("Synthesis produced no usable report; using extractive fallback.")
            return self._fallback_result(selected, sources, "model returned an empty report")

        repair_ms = 0
        repair_skipped = False
        if not cited and not self._repair_affordable():
            repair_skipped = True
            logger.warning(
                "Draft has zero inline citations but the run time budget cannot "
                "afford a repair pass; keeping the draft. No citations fabricated."
            )
        elif not cited:
            # Live-run regression: a draft with evidence but no inline
            # citations is not acceptable. Exactly one repair attempt.
            logger.warning(
                "Draft report has zero valid inline citations; "
                "attempting one citation repair pass..."
            )
            from src.events import EventType

            self._emitter.emit(
                EventType.CITATION_REPAIR_STARTED,
                message="Draft had no inline citations; running one repair pass.",
                agent="synthesizer",
            )
            # Compact evidence for repair: the draft already contains the
            # content; the model only needs enough snippet to map claims to
            # source numbers, so per-source text is cut to a fraction.
            repair_evidence = format_evidence_for_synthesis(
                selected, sources, max_chars_per_source=300,
                clean=self._clean_evidence,
            )
            repair_start = time.perf_counter()
            try:
                repaired = self._invoke(
                    CITATION_REPAIR_SYSTEM,
                    CITATION_REPAIR_USER.format(evidence=repair_evidence, draft=body),
                    llm=self._repair_llm,
                )
            except Exception as exc:
                from src.llm import is_llm_timeout

                if not is_llm_timeout(exc):
                    raise
                logger.warning("Citation repair exceeded its time budget.")
                repaired = ""  # treated exactly like a failed repair
            repair_ms = int((time.perf_counter() - repair_start) * 1000)
            repaired, repaired_cited = self._clean(repaired, len(sources))
            if repaired_cited:
                body, cited = repaired, repaired_cited
            else:
                logger.warning(
                    "Citation repair failed: final report contains no inline "
                    "citations. Sources are listed but claims are not "
                    "individually traceable. No citations were fabricated."
                )
            self._emitter.emit(
                EventType.CITATION_REPAIR_COMPLETED,
                message=f"Citation repair finished: {len(cited)} sources cited.",
                agent="synthesizer",
                cited=len(cited),
                succeeded=bool(cited),
            )

        report = f"{body.rstrip()}\n\n{render_sources_section(sources, cited)}\n"
        logger.info("Report complete: %d sources, %d cited.", len(sources), len(cited))
        return {
            "final_report": report,
            "sources_selected": len(sources),
            "sources_cited": len(cited),
            "citation_repair_ms": repair_ms,
            "repair_skipped": repair_skipped,
        }


REPORT_JSON_SCHEMA = {
    "type": "object",
    "properties": {"report": {"type": "string"}},
    "required": ["report"],
}

JSON_REPORT_INSTRUCTION = (
    '\n\nReturn JSON of the form {"report": "<the complete Markdown report>"}.'
)

_JSON_REPORT_PREFIX_RE = re.compile(r'^\{\s*"report"\s*:\s*"')


def extract_report_text(content: str) -> str:
    """Report text from a JSON-mode response, tolerating truncation.

    A complete ``{"report": "..."}`` object is decoded normally. If the output
    cap cut the JSON off mid-string, the partial string value is decoded and
    kept (the caller then trims any unfinished sentence). Non-JSON content is
    returned unchanged, so models that ignore the grammar still work.
    """
    text = content.strip()
    if not text.startswith("{"):
        return content
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("report"), str):
            return data["report"]
    except json.JSONDecodeError:
        pass
    match = _JSON_REPORT_PREFIX_RE.match(text)
    if match is None:
        return content
    partial = text[match.end():]
    # Drop a dangling escape sequence and any closing quote/brace fragment.
    partial = re.sub(r'\\u[0-9a-fA-F]{0,3}$|\\$', "", partial)
    partial = re.sub(r'"\s*\}?\s*$', "", partial)
    try:
        return json.loads(f'"{partial}"')
    except json.JSONDecodeError:
        return partial.replace("\\n", "\n").replace('\\"', '"')


_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

_PROSE_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def is_empty_draft(body: str) -> bool:
    """No prose at all (the live `{"report": ""}` failure, `{}`, bare
    punctuation/citations): a failed generation, never accepted as a report."""
    return _PROSE_WORD_RE.search(body) is None
EMPTY_DRAFT_RETRY_NOTE = (
    "\n\nYour previous answer was empty. Write the complete report now: "
    "about {words} words with inline [number] citations."
)
_COMPLETE_END_RE = re.compile(r"[.!?)\]*`\"']\s*$")


def trim_partial_sentence(body: str) -> str:
    """Drop an unfinished trailing sentence (output cap reached mid-sentence).

    Complete text is returned unchanged. Only the final line is affected,
    and it is cut back to its last sentence end (citations kept intact).
    """
    text = body.rstrip()
    if not text or _COMPLETE_END_RE.search(text):
        return text
    head, _, last = text.rpartition("\n")
    stripped_last = last.lstrip()
    if stripped_last.startswith("#"):
        return head.rstrip()  # dangling heading with no body
    # Last sentence end, extended over any immediately following citations.
    match = None
    for match in re.finditer(r"[.!?](?:\s*\[\d+\])*", last):
        pass
    if match is None:
        return head.rstrip()
    return (head + "\n" if head else "") + last[: match.end()]


def extractive_fallback_report(selected: list[Evidence], sources: list[Source]) -> str:
    """Deterministic, cited evidence summary used only when synthesis can't run.

    Built from claim-bearing sentences only (bibliography entries, navigation
    and keyword lists are excluded), grouped by the research query that found
    them. Every bullet is verbatim evidence followed by its real source
    number, so provenance holds exactly and nothing is invented. No LLM call.
    """
    from src.tools.excerpts import claim_sentences

    index = {s.normalized_url: i for i, s in enumerate(sources, 1)}
    groups: dict[str, list[str]] = {}
    seen_sentences: set[str] = set()
    per_source: dict[int, int] = {}
    for item in selected:
        n = index.get(item.source.normalized_url)
        if n is None:
            continue
        for sentence in claim_sentences(item.content, item.source.title):
            key = sentence.lower()
            if key in seen_sentences or per_source.get(n, 0) >= 2:
                continue
            seen_sentences.add(key)
            per_source[n] = per_source.get(n, 0) + 1
            groups.setdefault(item.query or "Collected evidence", []).append(
                f"- {sentence[:400].rstrip()} [{n}]"
            )

    lines = [
        "## Evidence Summary",
        "",
        "*Atlas could not finish writing a narrative report within this run's "
        "time budget. Below are the key findings from the collected sources, "
        "quoted verbatim and cited. Regenerate the report or re-run in DEEP "
        "mode for a full synthesis.*",
    ]
    for query, bullets in groups.items():
        lines += ["", f"### {query[:1].upper()}{query[1:]}", "", *bullets]
    if not groups:
        lines += ["", "No claim-bearing excerpts could be extracted from the "
                  "collected sources; see the source list below."]
    return "\n".join(lines)
