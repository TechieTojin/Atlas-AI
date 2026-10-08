"""Structured comparison synthesis: the model reasons, Atlas writes.

The previous design asked qwen3:4b for a finished Markdown report. Even with
``think: false`` the model spent most of its 900-token budget narrating its own
process ("We are comparing two research runs...", "Let me map the sources to
runs...") and was cut off by the output cap before finishing the comparison.

``think: false`` only suppresses Ollama's separate ``thinking`` field; it does not
stop qwen3 deliberating inline in ``content``. What does stop it is a JSON schema
in the request's ``format`` field: Ollama then decodes under a grammar, so tokens
outside the schema are not merely discouraged, they are impossible. That is the
mechanism this module relies on, which is why narration is prevented
architecturally rather than stripped from the text afterwards.

Everything the application already knows -- source numbering, which run used
which source, overlap statistics, the source list, the title -- is computed here
and never asked of the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from src.models.research import Source
from src.models.runs import ResearchRun
from src.models.workspace import ComparisonSource

#: Caps on what the model may return, so one bad response cannot blow the budget.
MAX_ITEMS_PER_SECTION = 6
MAX_CITATIONS_PER_ITEM = 6


class ComparisonError(Exception):
    """Raised when model output cannot be validated into a comparison."""


# -- the structured payload the model returns ---------------------------------
#
# Field order matters: Ollama's grammar-constrained decoding emits properties in
# schema order, so the overview is written first and the conclusion last, which
# is also the order a reader needs them in.
#
# Every point carries an id so the conclusion can reference the body instead of
# introducing fresh claims. V2 let the model write any conclusion it liked, and
# it asserted "interfacial engineering stability is consistently identified as
# the primary obstacle across both runs" when the Agreements section established
# nothing of the sort.


class ComparisonPoint(BaseModel):
    """An agreement: one finding that two or more runs both support."""

    id: str = Field(description="Point id")
    text: str = Field(description="Finding")
    runs: list[int] = Field(default_factory=list, description="Run numbers")
    citations: list[int] = Field(default_factory=list, description="Source numbers")


class ContradictionPosition(BaseModel):
    """One side of a disagreement."""

    runs: list[int] = Field(default_factory=list, description="Run numbers")
    text: str = Field(description="Position")
    citations: list[int] = Field(default_factory=list, description="Source numbers")


class Contradiction(BaseModel):
    """A genuine disagreement, with both sides and the evidence for each."""

    id: str = Field(description="Point id")
    topic: str = Field(description="Disagreement topic")
    positions: list[ContradictionPosition] = Field(
        default_factory=list, description="Opposing positions"
    )


class UniqueEvidencePoint(BaseModel):
    """Something exactly one run found, from a source only that run collected."""

    id: str = Field(description="Point id")
    run: int = Field(description="Run number")
    text: str = Field(description="Finding")
    citations: list[int] = Field(default_factory=list, description="Source numbers")


class Conclusion(BaseModel):
    """The closing summary, tied to points established above."""

    text: str = Field(description="Conclusion")
    based_on: list[str] = Field(default_factory=list, description="Point ids")


class ComparisonSynthesis(BaseModel):
    """The whole comparison, as data rather than prose."""

    overview: str = Field(description="Overview")
    agreements: list[ComparisonPoint] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    unique_evidence: list[UniqueEvidencePoint] = Field(default_factory=list)
    conclusion: Conclusion


# -- the canonical source registry --------------------------------------------


@dataclass
class RegisteredSource:
    """One source, numbered once, owned by a known set of runs."""

    number: int
    source: Source
    #: Run numbers (1-based, in comparison order) that used this source.
    run_numbers: list[int] = field(default_factory=list)

    @property
    def is_shared(self) -> bool:
        return len(self.run_numbers) > 1


@dataclass
class SourceRegistry:
    """The single source of truth for numbering, ownership and overlap.

    Every consumer -- the prompt, citation validation, the Source Differences
    section, the rendered Sources list and the stats the UI shows -- reads from
    this one object, so they cannot disagree with each other.
    """

    entries: list[RegisteredSource]
    run_labels: dict[int, str]

    @property
    def count(self) -> int:
        return len(self.entries)

    def get(self, number: int) -> RegisteredSource | None:
        if 1 <= number <= len(self.entries):
            return self.entries[number - 1]
        return None

    def runs_for(self, number: int) -> list[int]:
        entry = self.get(number)
        return list(entry.run_numbers) if entry else []

    def shared(self) -> list[RegisteredSource]:
        return [entry for entry in self.entries if entry.is_shared]

    def unique_to(self, run_number: int) -> list[RegisteredSource]:
        return [entry for entry in self.entries if entry.run_numbers == [run_number]]

    def comparison_sources(self, runs: list[ResearchRun]) -> list[ComparisonSource]:
        """The persisted representation, in registry order."""
        by_number = {index + 1: run.id for index, run in enumerate(runs)}
        return [
            ComparisonSource(
                source=entry.source,
                run_ids=[by_number[n] for n in entry.run_numbers if n in by_number],
            )
            for entry in self.entries
        ]

    def overlap_stats(self, runs: list[ResearchRun]) -> dict:
        """Overlap figures, derived from the same registry the prompt used."""
        return {
            "total_sources": self.count,
            "shared_sources": len(self.shared()),
            "unique_per_run": {
                run.id: len(self.unique_to(index + 1))
                for index, run in enumerate(runs)
            },
        }


def build_registry(runs: list[ResearchRun]) -> SourceRegistry:
    """Number every distinct source once and record which runs used it.

    Identity is the source's ``normalized_url``, the same key Atlas uses
    everywhere else, so "the same page reached by two runs" is one numbered
    source owned by both rather than two entries that look unique.
    """
    entries: dict[str, RegisteredSource] = {}
    order: list[str] = []
    for index, run in enumerate(runs, 1):
        for source in run.selected_sources:
            key = source.normalized_url
            entry = entries.get(key)
            if entry is None:
                entry = entries[key] = RegisteredSource(number=0, source=source)
                order.append(key)
            if index not in entry.run_numbers:
                entry.run_numbers.append(index)
    ordered = [entries[key] for key in order]
    for number, entry in enumerate(ordered, 1):
        entry.number = number
    return SourceRegistry(
        entries=ordered,
        run_labels={index: f"Run {index}" for index in range(1, len(runs) + 1)},
    )


# -- validation ---------------------------------------------------------------
#
# V2 checked that citations existed and that attribution was not contradicted by
# the registry. That let through an "agreement" supported by one run alone, and a
# conclusion asserting something the body never showed. These rules give each
# section the meaning its heading promises.

#: Phrases that describe the comparison's setup rather than its findings. An
#: overview made of these tells the reader nothing they did not already know.
_METADATA_HINTS = (
    "same question",
    "identical question",
    "same template",
    "identical template",
    "same completion date",
    "identical completion date",
    "same date",
    "identical date",
    "same mode",
    "identical mode",
    "both runs were completed",
    "same scope and timing",
)


def _schema_phrases() -> frozenset[str]:
    """Every description string in the schema, normalised.

    Derived from the models themselves so the guard cannot drift from them.
    """
    phrases: set[str] = set()
    for model in (
        ComparisonSynthesis, ComparisonPoint, Contradiction,
        ContradictionPosition, UniqueEvidencePoint, Conclusion,
    ):
        for info in model.model_fields.values():
            if info.description:
                phrases.add(_squash(info.description))
    return frozenset(phrases)


def _squash(text: str) -> str:
    return " ".join((text or "").lower().split())


#: Wording that only ever appears in instructions, never in a finding.
_INSTRUCTION_MARKERS = (
    "2-3 sentences",
    "one specific sentence",
    "no headings",
    "citation markers",
    "never mention",
    "based_on",
    "empty list",
    "source numbers",
    "run numbers",
    "about the subject matter",
)


def _looks_like_instructions(text: str) -> bool:
    """True when the model echoed its own schema or prompt instead of writing.

    With a richer schema, qwen3:4b sometimes fills a field with that field's
    description. Structurally such output is perfect, so only the content can
    give it away.
    """
    squashed = _squash(text)
    if not squashed:
        return False
    if squashed in _schema_phrases():
        return True
    return any(marker in squashed for marker in _INSTRUCTION_MARKERS)


def _clean_text(text: str) -> str:
    """Strip any citation markers the model inlined; Atlas renders those."""
    return re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", text or "").strip()


def _normalise_id(value: str, fallback: str) -> str:
    cleaned = (value or "").strip().upper()
    return cleaned or fallback


def validate_synthesis(
    synthesis: ComparisonSynthesis, registry: SourceRegistry
) -> ComparisonSynthesis:
    """Check the model's claims against what Atlas actually knows.

    Failures raise rather than being quietly repaired in place: a comparison
    whose sections do not mean what their headings say is wrong in a way the
    reader cannot see. The caller turns a failure into one bounded repair.
    """
    run_numbers = set(registry.run_labels)
    total_runs = len(run_numbers)

    def reject_echo(text: str, where: str) -> None:
        if _looks_like_instructions(text):
            raise ComparisonError(
                f"{where} repeats the instructions instead of saying something "
                "about the research. Write the actual finding."
            )

    overview = _clean_text(synthesis.overview)
    if not overview:
        raise ComparisonError("The comparison has no overview.")
    reject_echo(overview, "The overview")
    lowered = overview.lower()
    hits = [hint for hint in _METADATA_HINTS if hint in lowered]
    if hits:
        raise ComparisonError(
            "The overview describes how the runs were set up "
            f"({', '.join(hits)}) instead of how their findings relate. "
            "Describe where the runs converge, diverge or complement each other."
        )

    def check_citations(citations: list[int], where: str) -> list[int]:
        seen: list[int] = []
        for number in citations:
            if registry.get(number) is None:
                raise ComparisonError(
                    f"{where} cites source [{number}], which does not exist "
                    f"(sources are 1-{registry.count})."
                )
            if number not in seen:
                seen.append(number)
        if not seen:
            raise ComparisonError(f"{where} cites no sources.")
        return seen[:MAX_CITATIONS_PER_ITEM]

    def check_runs(runs: list[int], where: str) -> list[int]:
        seen: list[int] = []
        for number in runs:
            if number not in run_numbers:
                raise ComparisonError(
                    f"{where} refers to run {number}, which is not part of this "
                    f"comparison (runs are 1-{total_runs})."
                )
            if number not in seen:
                seen.append(number)
        return sorted(seen)

    def owners(citations: list[int]) -> list[int]:
        found: list[int] = []
        for number in citations:
            for run_number in registry.runs_for(number):
                if run_number not in found:
                    found.append(run_number)
        return sorted(found)

    # -- agreements: at least two runs, each backed by its own evidence --------
    agreements: list[ComparisonPoint] = []
    for index, point in enumerate(synthesis.agreements[:MAX_ITEMS_PER_SECTION], 1):
        where = f"Agreement {index}"
        text = _clean_text(point.text)
        if not text:
            continue
        reject_echo(text, where)
        citations = check_citations(point.citations, where)
        # An omitted run list is read off the evidence rather than guessed.
        runs = check_runs(point.runs, where) or owners(citations)
        if len(runs) < 2:
            raise ComparisonError(
                f"{where} is supported by only run {runs[0] if runs else '?'}. An "
                "agreement needs at least two runs; a single-run finding belongs "
                "in unique_evidence."
            )
        for run_number in runs:
            if not any(run_number in registry.runs_for(c) for c in citations):
                raise ComparisonError(
                    f"{where} claims run {run_number} agrees, but none of its cited "
                    f"sources were collected by run {run_number}. Cite a source from "
                    "every run you list."
                )
        agreements.append(
            ComparisonPoint(
                id=_normalise_id(point.id, f"A{index}"),
                text=text,
                runs=runs,
                citations=citations,
            )
        )

    # -- contradictions: two grounded sides held by different runs ------------
    contradictions: list[Contradiction] = []
    for index, item in enumerate(synthesis.contradictions[:MAX_ITEMS_PER_SECTION], 1):
        where = f"Contradiction {index}"
        positions: list[ContradictionPosition] = []
        for position_index, position in enumerate(item.positions, 1):
            label = f"{where} position {position_index}"
            text = _clean_text(position.text)
            if not text:
                continue
            reject_echo(text, label)
            citations = check_citations(position.citations, label)
            runs = check_runs(position.runs, label) or owners(citations)
            if not runs:
                raise ComparisonError(f"{label} is not attributed to any run.")
            for run_number in runs:
                if not any(run_number in registry.runs_for(c) for c in citations):
                    raise ComparisonError(
                        f"{label} is attributed to run {run_number}, but none of its "
                        f"cited sources were collected by that run."
                    )
            positions.append(
                ContradictionPosition(runs=runs, text=text, citations=citations)
            )
        if len(positions) < 2:
            raise ComparisonError(
                f"{where} has {len(positions)} grounded position(s). A contradiction "
                "needs at least two opposing positions, each with its own evidence. "
                "If the runs merely emphasise different things, that is not a "
                "contradiction: leave the list empty."
            )
        involved = {run for position in positions for run in position.runs}
        if len(involved) < 2:
            raise ComparisonError(
                f"{where} puts every position with the same run. A contradiction must "
                "be between different runs."
            )
        contradictions.append(
            Contradiction(
                id=_normalise_id(item.id, f"C{index}"),
                topic=_clean_text(item.topic) or "Disagreement",
                positions=positions,
            )
        )

    # -- unique evidence: one run, from sources only that run collected --------
    unique: list[UniqueEvidencePoint] = []
    for index, point in enumerate(synthesis.unique_evidence[:MAX_ITEMS_PER_SECTION], 1):
        where = f"Unique evidence {index}"
        text = _clean_text(point.text)
        if not text:
            continue
        reject_echo(text, where)
        check_runs([point.run], where)
        citations = check_citations(point.citations, where)
        for number in citations:
            holders = registry.runs_for(number)
            if point.run not in holders:
                raise ComparisonError(
                    f"{where} attributes source [{number}] to run {point.run}, but "
                    f"run {point.run} did not collect it."
                )
            if holders != [point.run]:
                other = [h for h in holders if h != point.run]
                raise ComparisonError(
                    f"{where} claims run {point.run} uniquely found source "
                    f"[{number}], but run(s) {other} collected it too, so it is "
                    "not unique."
                )
        unique.append(
            UniqueEvidencePoint(
                id=_normalise_id(point.id, f"U{index}"),
                run=point.run,
                text=text,
                citations=citations,
            )
        )

    # -- conclusion: may only summarise what survived above --------------------
    conclusion_text = _clean_text(synthesis.conclusion.text)
    if not conclusion_text:
        raise ComparisonError("The comparison has no conclusion.")
    reject_echo(conclusion_text, "The conclusion")
    known = {point.id for point in agreements}
    known |= {item.id for item in contradictions}
    known |= {point.id for point in unique}
    # An id that names no validated point is dropped rather than fatal. It
    # contributes no citation and removes no claim, so keeping the whole
    # comparison hostage to a stale reference would cost the reader far more
    # than it protects them. What must hold is that the conclusion still rests
    # on at least one point that survived validation.
    based_on: list[str] = []
    for raw in synthesis.conclusion.based_on:
        point_id = _normalise_id(raw, "")
        if point_id in known and point_id not in based_on:
            based_on.append(point_id)
    if known and not based_on:
        raise ComparisonError(
            "The conclusion does not reference any of the comparison points above. "
            f"It cited {synthesis.conclusion.based_on or 'nothing'}; list the ids it "
            f"actually summarises, from: {', '.join(sorted(known))}."
        )

    return ComparisonSynthesis(
        overview=overview,
        agreements=agreements,
        contradictions=contradictions,
        unique_evidence=unique,
        conclusion=Conclusion(text=conclusion_text, based_on=based_on),
    )


# -- deterministic rendering --------------------------------------------------


def _citation_marker(citations: list[int]) -> str:
    return "".join(f"[{number}]" for number in citations)


def _run_names(runs: list[int], registry: SourceRegistry, language: str = "en") -> str:
    from src.artifact_text import artifact_text

    names = [_run_label(number, registry, language) for number in sorted(runs)]
    joiner = artifact_text(language, "comparison.and")
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return joiner.join(names)
    return ", ".join(names[:-1]) + joiner + names[-1]


def _run_label(number: int, registry: SourceRegistry, language: str = "en") -> str:
    """'Run 2' in the comparison's language (English keeps the registry's label)."""
    from src.artifact_text import artifact_text

    if language == "en":
        return registry.run_labels.get(number, f"Run {number}")
    return artifact_text(language, "comparison.run", number=number)


def conclusion_citations(synthesis: ComparisonSynthesis) -> list[int]:
    """Sources behind the conclusion, taken from the points it references.

    Derived rather than accepted from the model, so the conclusion can never
    rest on a source the validated body did not already use.
    """
    by_id: dict[str, list[int]] = {}
    for point in synthesis.agreements:
        by_id[point.id] = point.citations
    for item in synthesis.contradictions:
        by_id[item.id] = [c for position in item.positions for c in position.citations]
    for point in synthesis.unique_evidence:
        by_id[point.id] = point.citations
    cited: list[int] = []
    for point_id in synthesis.conclusion.based_on:
        for number in by_id.get(point_id, []):
            if number not in cited:
                cited.append(number)
    return sorted(cited)


def cited_numbers(synthesis: ComparisonSynthesis) -> set[int]:
    """Every source number the finished comparison actually relies on.

    Includes the conclusion's references, so a source that carries the
    conclusion is never listed as "collected, not cited".
    """
    cited: set[int] = set()
    for point in synthesis.agreements:
        cited.update(point.citations)
    for item in synthesis.contradictions:
        for position in item.positions:
            cited.update(position.citations)
    for point in synthesis.unique_evidence:
        cited.update(point.citations)
    cited.update(conclusion_citations(synthesis))
    return cited


def render_comparison(
    synthesis: ComparisonSynthesis,
    registry: SourceRegistry,
    runs: list[ResearchRun],
    title: str,
    render_sources: object,
    language: str = "en",
) -> str:
    """Render the final Markdown. Atlas writes every heading and every number.

    Headings and fixed sentences are in the comparison's output language; the
    trailing ``## Sources`` block stays the canonical English protocol marker.
    """
    from src.artifact_text import artifact_text

    def text(key: str, **params: object) -> str:
        return artifact_text(language, key, **params)

    lines: list[str] = [
        f"# {title}", "", f"## {text('comparison.overview')}", "", synthesis.overview, ""
    ]

    lines += [f"## {text('comparison.agreements')}", ""]
    if synthesis.agreements:
        for point in synthesis.agreements:
            names = _run_names(point.runs, registry, language)
            lines.append(
                f"- {names}: {point.text} {_citation_marker(point.citations)}".rstrip()
            )
    else:
        lines.append(text("comparison.no_agreements"))
    lines.append("")

    lines += [f"## {text('comparison.contradictions')}", ""]
    if synthesis.contradictions:
        for item in synthesis.contradictions:
            lines.append(f"- **{item.topic}**")
            for position in item.positions:
                names = _run_names(position.runs, registry, language)
                lines.append(
                    f"  - {names}: {position.text} "
                    f"{_citation_marker(position.citations)}".rstrip()
                )
    else:
        # Agreement is a real result. Inventing disagreement would not be.
        lines.append(text("comparison.no_contradictions"))
    lines.append("")

    lines += [f"## {text('comparison.unique')}", ""]
    if synthesis.unique_evidence:
        for point in synthesis.unique_evidence:
            label = _run_label(point.run, registry, language)
            lines.append(
                f"- {label}: {point.text} {_citation_marker(point.citations)}".rstrip()
            )
    else:
        lines.append(text("comparison.no_unique"))
    lines.append("")

    conclusion = synthesis.conclusion.text
    marker = _citation_marker(conclusion_citations(synthesis))
    lines += [f"## {text('comparison.conclusion')}", "", f"{conclusion} {marker}".rstrip(), ""]

    # Source statistics, computed from the registry rather than described by the model.
    lines += [f"## {text('comparison.source_differences')}", ""]
    lines.append(f"- {text('comparison.combined', count=registry.count)}")
    lines.append(f"- {text('comparison.shared', count=len(registry.shared()))}")
    for index, _run in enumerate(runs, 1):
        label = _run_label(index, registry, language)
        lines.append(f"- {text('comparison.unique_to', label=label, count=len(registry.unique_to(index)))}")
    lines.append("")

    sources = [entry.source for entry in registry.entries]
    lines.append(render_sources(sources, cited_numbers(synthesis)))  # type: ignore[operator]
    return "\n".join(lines).rstrip() + "\n"


# -- prompt -------------------------------------------------------------------


def build_evidence_block(
    registry: SourceRegistry,
    runs: list[ResearchRun],
    select_evidence: object,
    max_per_run: int,
    max_chars: int,
) -> str:
    """The numbered source registry, with ownership already resolved.

    Ownership is stated outright so the model never spends output tokens working
    out which run used which source -- that was a measurable share of the budget
    it wasted narrating.
    """
    texts: dict[int, str] = {}
    for run in runs:
        for item in select_evidence(run.evidence, max_per_run):  # type: ignore[operator]
            entry = next(
                (e for e in registry.entries
                 if e.source.normalized_url == item.source.normalized_url),
                None,
            )
            if entry is not None and entry.number not in texts:
                texts[entry.number] = item.content[:max_chars]

    blocks: list[str] = []
    for entry in registry.entries:
        evidence = texts.get(entry.number)
        if not evidence:
            continue
        runs_label = ", ".join(str(n) for n in entry.run_numbers)
        blocks.append(
            f"SOURCE {entry.number}\n"
            f"RUNS: {runs_label}\n"
            f"TITLE: {entry.source.title}\n"
            f"EVIDENCE: {evidence}"
        )
    return "\n\n".join(blocks)
