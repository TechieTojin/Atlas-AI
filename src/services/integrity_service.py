"""Research integrity: claim extraction, citation verification, contradiction
detection and a transparent research quality score.

The verification engine is deliberately **deterministic**. It compares the
text of a cited claim against the passages that claim actually cites, using
reproducible lexical and numeric signals. That matters for three reasons:

1. A user can be shown exactly why a verdict was reached, and can disagree
   with it on inspectable grounds.
2. Re-running analysis on the same report always yields the same verdict,
   so "citation integrity" is a property of the report, not of model mood.
3. It cannot hallucinate support that is not in the passage.

Where Atlas cannot judge something it says so (``NOT_VERIFIABLE``) instead
of guessing, and quality dimensions it cannot compute are marked NOT
AVAILABLE rather than defaulted to zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.evaluation.claims import extract_claims
from src.models.integrity import (
    ClaimRecord,
    ClaimVerification,
    ConfidenceBand,
    Contradiction,
    ContradictionType,
    IntegritySummary,
    QualityComponent,
    QualityScore,
    VerificationSignal,
    VerificationStatus,
    VerifierKind,
)
from src.models.research import Evidence, Source
from src.persistence.integrity import IntegrityRepository

# --- deterministic text helpers ------------------------------------------------

#: Unicode-aware word tokens, so Malayalam/Hindi reports tokenise too.
_WORD_RE = re.compile(r"\w+", re.UNICODE)
#: Integers, decimals and percentages ("25.7", "1,200", "93%").
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_CITATION_RE = re.compile(r"\[\d+\]")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

#: Function words carry no evidential weight; dropping them keeps overlap
#: honest for English. Other scripts simply have nothing filtered, which is
#: safe because overlap is measured as a ratio within the same claim.
_STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those of in on at to for from by with
    as is are was were be been being has have had do does did not no nor can could may might
    will would shall should must it its their his her our your my they them we you he she
    which who whom whose what when where why how there here also such more most some any
    both each few other own same so very into over under about across between during within
    """.split()
)

#: Explicit polarity markers used for conservative contradiction detection.
_NEGATORS = frozenset(
    """not no never none cannot cant isnt arent wasnt werent doesnt dont didnt
    without fails failed lacks lacking absent unable neither""".split()
)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def _stem(token: str) -> str:
    """Very light suffix folding so "barriers" matches "barrier".

    Applied only to ASCII alphabetic tokens: other scripts (Malayalam,
    Devanagari) have different morphology and are left untouched rather than
    mangled by English rules.
    """
    if len(token) <= 4 or not token.isascii() or not token.isalpha():
        return token
    for suffix in ("ingly", "edly", "ing", "ies", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            base = token[: -len(suffix)]
            return base + "y" if suffix == "ies" else base
    return token


def _content_terms(text: str) -> set[str]:
    """Distinctive terms of a claim: no stopwords, no 1-2 char noise.

    Terms are suffix-folded so trivial inflection differences between a claim
    and its cited passage are not mistaken for missing support.
    """
    return {_stem(t) for t in _tokens(text) if len(t) > 2 and t not in _STOPWORDS}


def _numbers(text: str) -> set[str]:
    """Normalised numeric figures, thousands separators removed."""
    out: set[str] = set()
    for raw in _NUMBER_RE.findall(text):
        cleaned = raw.replace(",", "")
        cleaned = cleaned.rstrip(".")
        if cleaned:
            out.add(cleaned)
    return out


def _strip_citations(text: str) -> str:
    return _CITATION_RE.sub(" ", text)


def _negated(text: str) -> bool:
    return bool(_NEGATORS & set(_tokens(text)))


def _ratio(found: int, total: int) -> float:
    return 1.0 if total == 0 else found / total


# --- verification --------------------------------------------------------------

#: Thresholds are named constants so the UI can explain them and tests can
#: assert against the documented contract.
SUPPORT_STRONG = 0.60
SUPPORT_PARTIAL = 0.30


@dataclass(frozen=True)
class _Verdict:
    status: VerificationStatus
    confidence: ConfidenceBand
    signals: list[VerificationSignal]
    explanation: str


def verify_claim_text(claim_text: str, passages: list[str]) -> _Verdict:
    """Check one claim against the passages it cites. Pure and deterministic.

    Exposed at module level so the rules can be unit-tested without a DB.
    """
    claim_body = _strip_citations(claim_text)
    terms = _content_terms(claim_body)
    figures = _numbers(claim_body)
    joined = "\n".join(p for p in passages if p)

    if not joined.strip():
        return _Verdict(
            VerificationStatus.NOT_VERIFIABLE,
            ConfidenceBand.HIGH,
            [
                VerificationSignal(
                    name="evidence_available",
                    value=0.0,
                    detail="No stored passage text for the cited source(s).",
                )
            ],
            "Atlas has no stored passage for the cited source, so this claim "
            "could not be checked either way.",
        )

    passage_terms = _content_terms(joined)
    passage_numbers = _numbers(joined)

    matched_terms = terms & passage_terms
    term_overlap = _ratio(len(matched_terms), len(terms))
    matched_numbers = figures & passage_numbers
    number_match = _ratio(len(matched_numbers), len(figures))

    signals = [
        VerificationSignal(
            name="term_overlap",
            value=round(term_overlap, 3),
            detail=f"{len(matched_terms)} of {len(terms)} distinctive terms appear in the cited passage(s).",
        ),
        VerificationSignal(
            name="numeric_match",
            value=round(number_match, 3),
            detail=(
                f"{len(matched_numbers)} of {len(figures)} figures appear in the cited passage(s)."
                if figures
                else "The claim states no figures to check."
            ),
        ),
        VerificationSignal(
            name="evidence_available",
            value=1.0,
            detail=f"{len([p for p in passages if p])} cited passage(s) examined.",
        ),
    ]

    # Polarity conflict: the claim asserts something the passage denies (or
    # vice versa) while otherwise talking about the same terms. Requires solid
    # topical overlap so that unrelated text is never called a contradiction.
    polarity_conflict = (
        term_overlap >= SUPPORT_PARTIAL and _negated(claim_body) != _negated(joined)
    )
    #: A figure stated by the claim that the passage contradicts with a
    #: different figure in the same sentence space.
    numeric_conflict = bool(figures) and number_match == 0.0 and bool(passage_numbers)

    if polarity_conflict and numeric_conflict:
        signals.append(
            VerificationSignal(
                name="polarity_conflict",
                value=1.0,
                detail="The claim and the cited passage disagree in direction and in figures.",
            )
        )
        return _Verdict(
            VerificationStatus.CONTRADICTED,
            ConfidenceBand.MODERATE,
            signals,
            "The cited passage appears to state the opposite of this claim and "
            "reports different figures.",
        )

    if term_overlap >= SUPPORT_STRONG and (not figures or number_match >= 0.5):
        confidence = (
            ConfidenceBand.HIGH
            if len(terms) >= 4 and (not figures or number_match == 1.0)
            else ConfidenceBand.MODERATE
        )
        return _Verdict(
            VerificationStatus.SUPPORTED,
            confidence,
            signals,
            "The cited passage contains the substance of this claim, including "
            "its figures." if figures else "The cited passage contains the substance of this claim.",
        )

    if term_overlap >= SUPPORT_PARTIAL or (figures and number_match > 0):
        detail = (
            "The cited passage is on topic and supports part of this claim, but "
            "does not contain all of it."
        )
        if figures and number_match < 1.0:
            detail += " Some stated figures were not found in the passage."
        return _Verdict(
            VerificationStatus.PARTIALLY_SUPPORTED,
            ConfidenceBand.MODERATE if len(terms) >= 4 else ConfidenceBand.LOW,
            signals,
            detail,
        )

    return _Verdict(
        VerificationStatus.UNSUPPORTED,
        ConfidenceBand.MODERATE if len(terms) >= 4 else ConfidenceBand.LOW,
        signals,
        "The cited passage does not contain the substance of this claim.",
    )


# --- contradictions ------------------------------------------------------------

#: Two figures are treated as materially different beyond this relative gap.
NUMERIC_DISAGREEMENT = 0.10


#: Two figures are only treated as *the same quantity* when they sit within
#: this magnitude band of each other.
COMPARABLE_MAGNITUDE = 0.5

#: Units that make two figures comparable. A bare number carries no meaning we
#: can trust across passages ("5" reviews vs "5" volts is not a disagreement),
#: so only figures carrying the SAME unit are ever compared.
_UNIT_ALIASES = {
    "%": "%",
    "percent": "%",
    "percentage": "%",
    "pct": "%",
    "ev": "ev",
    "nm": "nm",
    "µm": "um",
    "um": "um",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "km": "km",
    "v": "v",
    "mv": "mv",
    "w": "w",
    "kw": "kw",
    "mw": "mw",
    "gw": "gw",
    "wh": "wh",
    "kwh": "kwh",
    "mwh": "mwh",
    "gwh": "gwh",
    "k": "k",
    "hours": "hours",
    "hour": "hours",
    "h": "hours",
    "days": "days",
    "day": "days",
    "years": "years",
    "year": "years",
}

#: number followed by an optional unit token (or a % sign)
_NUMBER_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)*)\s*(%|[a-zA-Zµ]{1,10}\b)?",
    re.UNICODE,
)


def _is_year(value: float) -> bool:
    """Calendar years are handled as periods, never as measured quantities."""
    return value.is_integer() and 1900 <= value <= 2099


def _measured_quantities(text: str) -> set[tuple[float, str]]:
    """(value, unit) pairs for figures that actually carry a unit.

    Unitless numbers are deliberately dropped: they are the dominant source of
    spurious "disagreements" between passages that are not even discussing the
    same quantity.
    """
    out: set[tuple[float, str]] = set()
    for raw, rawunit in _NUMBER_UNIT_RE.findall(text):
        unit = _UNIT_ALIASES.get((rawunit or "").strip().lower())
        if not unit:
            continue
        try:
            value = float(raw.replace(",", "").rstrip("."))
        except ValueError:
            continue
        if _is_year(value):
            continue
        out.add((value, unit))
    return out


def _agrees_on_quantity(a: set[tuple[float, str]], b: set[tuple[float, str]]) -> bool:
    """True when both passages state essentially the same figure in the same unit."""
    for x, unit_x in a:
        for y, unit_y in b:
            if unit_x != unit_y:
                continue
            bigger = max(abs(x), abs(y))
            if bigger == 0:
                continue
            if abs(x - y) / bigger <= NUMERIC_DISAGREEMENT:
                return True
    return False


def _material_numeric_gap(
    a: set[tuple[float, str]], b: set[tuple[float, str]]
) -> tuple[float, float] | None:
    """Largest materially different pair of *same-unit* figures, if any.

    Conservative by design: a contradiction claimed on the strength of two
    unrelated numbers is worse than a missed one, because it tells the user a
    disagreement exists where none does.
    """
    if not a or not b:
        return None
    worst: tuple[float, float] | None = None
    worst_gap = 0.0
    for x, unit_x in a:
        for y, unit_y in b:
            if unit_x != unit_y:
                continue  # different quantities entirely
            if x == 0 and y == 0:
                continue
            bigger = max(abs(x), abs(y))
            smaller = min(abs(x), abs(y))
            if bigger == 0 or smaller / bigger < COMPARABLE_MAGNITUDE:
                continue
            gap = abs(x - y) / bigger
            if gap <= NUMERIC_DISAGREEMENT:
                # The passages state the same figure in the same unit, so they
                # agree about this quantity. A larger gap elsewhere is then far
                # more likely to be two different referents sharing a unit
                # (silicon's 1.12 eV vs an optimal 1.34 eV) than a real
                # disagreement — agreement wins, and nothing is reported.
                return None
            if gap > worst_gap:
                worst_gap = gap
                worst = (x, y)
    return worst


def detect_contradiction(passage_a: str, passage_b: str) -> tuple[ContradictionType, str] | None:
    """Conservative pairwise disagreement check between two passages.

    Returns None unless there is concrete evidence of disagreement. Different
    wording about the same thing is explicitly NOT a contradiction.
    """
    if not passage_a.strip() or not passage_b.strip():
        return None

    terms_a, terms_b = _content_terms(passage_a), _content_terms(passage_b)
    if not terms_a or not terms_b:
        return None

    shared = terms_a & terms_b
    topical = len(shared) / min(len(terms_a), len(terms_b))
    if topical < 0.15:
        return None  # not even discussing the same thing

    quantities_a = _measured_quantities(passage_a)
    quantities_b = _measured_quantities(passage_b)
    # Hard stop: if the passages state the same measured quantity, they agree.
    # Negation words are everywhere in technical prose ("cannot exceed 33%"),
    # so polarity alone must never override demonstrated agreement.
    if _agrees_on_quantity(quantities_a, quantities_b):
        return None

    gap = _material_numeric_gap(quantities_a, quantities_b)
    years_a = {m.group(0) for m in _YEAR_RE.finditer(passage_a)}
    years_b = {m.group(0) for m in _YEAR_RE.finditer(passage_b)}

    polarity = _negated(passage_a) != _negated(passage_b)

    # "Different periods" requires genuinely disjoint years. Sources that both
    # mention 1961 are agreeing about a date, not disagreeing about an era.
    if gap and years_a and years_b and years_a.isdisjoint(years_b):
        return (
            ContradictionType.OUTDATED_VS_CURRENT,
            f"The sources report different figures ({gap[0]:g} vs {gap[1]:g}) for "
            f"different periods ({', '.join(sorted(years_a))} vs {', '.join(sorted(years_b))}).",
        )
    if gap and polarity:
        return (
            ContradictionType.DIRECT_CONTRADICTION,
            f"The sources disagree in direction and report different figures "
            f"({gap[0]:g} vs {gap[1]:g}).",
        )
    if gap:
        return (
            ContradictionType.MIXED_EVIDENCE,
            f"The sources report materially different figures ({gap[0]:g} vs {gap[1]:g}) "
            "for what appears to be the same quantity.",
        )
    if polarity and topical >= 0.3:
        return (
            ContradictionType.CONTEXTUAL_DISAGREEMENT,
            "The sources discuss the same points but state them in opposite terms.",
        )
    return None


# --- quality -------------------------------------------------------------------

QUALITY_FORMULA_VERSION = 1

#: Documented weights. The overall score is the weighted mean of the
#: components Atlas could actually compute, renormalised by their weights.
QUALITY_WEIGHTS = {
    "citation_coverage": 0.20,
    "citation_support": 0.30,
    "source_diversity": 0.15,
    "source_authority": 0.15,
    "evidence_agreement": 0.10,
    "evidence_relevance": 0.10,
}


class IntegrityService:
    """Derives and persists integrity artifacts for a completed run."""

    def __init__(self, repo: IntegrityRepository) -> None:
        self._repo = repo

    # -- public API ---------------------------------------------------------------

    def analyze_run(self, run) -> IntegritySummary:
        """Extract claims, verify them, record contradictions, score quality.

        Safe to call repeatedly: derived rows for the run are replaced, and no
        part of the run itself is modified.
        """
        sources: list[Source] = list(getattr(run, "selected_sources", []) or [])
        evidence: list[Evidence] = list(getattr(run, "evidence", []) or [])
        report = getattr(run, "final_report", "") or ""

        claims = self._build_claims(run, report, len(sources))
        self._repo.replace_claims(run.id, claims)

        passages_by_index = self._passages_by_source_index(sources, evidence)

        verifications: list[ClaimVerification] = []
        contradictions: list[Contradiction] = []
        for claim in claims:
            cited = [n for n in claim.citations if 1 <= n <= len(sources)]
            passages = [p for n in cited for p in passages_by_index.get(n, [])]
            verdict = verify_claim_text(claim.text, passages)
            verifications.append(
                ClaimVerification(
                    claim_id=claim.id,
                    run_id=run.id,
                    status=verdict.status,
                    confidence=verdict.confidence,
                    verifier=VerifierKind.DETERMINISTIC,
                    signals=verdict.signals,
                    explanation=verdict.explanation,
                    checked_citations=cited,
                )
            )
            contradictions.extend(
                self._claim_contradictions(run.id, claim, cited, passages_by_index)
            )

        self._repo.save_verifications(run.id, verifications)
        self._repo.save_contradictions(run.id, contradictions)

        summary = self.summarize(run.id, verifications, contradictions)
        score = self.compute_quality(run, claims, verifications, contradictions)
        self._repo.save_quality(score)
        return summary

    def summarize(
        self,
        run_id: str,
        verifications: list[ClaimVerification],
        contradictions: list[Contradiction],
    ) -> IntegritySummary:
        summary = IntegritySummary(run_id=run_id, total_claims=len(verifications))
        for v in verifications:
            if v.status is VerificationStatus.SUPPORTED:
                summary.supported += 1
            elif v.status is VerificationStatus.PARTIALLY_SUPPORTED:
                summary.partially_supported += 1
            elif v.status is VerificationStatus.UNSUPPORTED:
                summary.unsupported += 1
            elif v.status is VerificationStatus.CONTRADICTED:
                summary.contradicted += 1
            else:
                summary.not_verifiable += 1
        summary.contradiction_count = len(contradictions)
        return summary

    def compute_quality(
        self,
        run,
        claims: list[ClaimRecord],
        verifications: list[ClaimVerification],
        contradictions: list[Contradiction],
    ) -> QualityScore:
        sources: list[Source] = list(getattr(run, "selected_sources", []) or [])
        evidence: list[Evidence] = list(getattr(run, "evidence", []) or [])
        evaluation = getattr(run, "evaluation", None)
        components: list[QualityComponent] = []

        # 1. Citation coverage — how much of the report is cited at all.
        coverage = getattr(evaluation, "citation_coverage", None) if evaluation else None
        components.append(
            QualityComponent(
                name="citation_coverage",
                available=coverage is not None,
                value=float(coverage) if coverage is not None else None,
                weight=QUALITY_WEIGHTS["citation_coverage"],
                detail=(
                    f"{float(coverage) * 100:.0f}% of report claims carry a citation."
                    if coverage is not None
                    else "No citation-coverage evaluation stored for this run."
                ),
            )
        )

        # 2. Citation support — of the claims we could check, how many hold up.
        verifiable = [v for v in verifications if v.status is not VerificationStatus.NOT_VERIFIABLE]
        if verifiable:
            # Partial support counts as half; contradicted/unsupported count as zero.
            earned = sum(
                1.0
                if v.status is VerificationStatus.SUPPORTED
                else 0.5
                if v.status is VerificationStatus.PARTIALLY_SUPPORTED
                else 0.0
                for v in verifiable
            )
            support = earned / len(verifiable)
            detail = (
                f"{sum(1 for v in verifiable if v.status is VerificationStatus.SUPPORTED)} of "
                f"{len(verifiable)} verifiable claims fully supported "
                "(partial support counts as a half)."
            )
        else:
            support, detail = None, "No claim could be checked against stored passages."
        components.append(
            QualityComponent(
                name="citation_support",
                available=support is not None,
                value=support,
                weight=QUALITY_WEIGHTS["citation_support"],
                detail=detail,
            )
        )

        # 3. Source diversity — distinct domains over cited sources.
        if sources:
            domains = {(s.domain or s.url or "").lower() for s in sources if (s.domain or s.url)}
            diversity = len(domains) / len(sources)
            components.append(
                QualityComponent(
                    name="source_diversity",
                    available=True,
                    value=diversity,
                    weight=QUALITY_WEIGHTS["source_diversity"],
                    detail=f"{len(domains)} distinct domains across {len(sources)} sources.",
                )
            )
        else:
            components.append(
                QualityComponent(
                    name="source_diversity",
                    available=False,
                    weight=QUALITY_WEIGHTS["source_diversity"],
                    detail="No sources recorded for this run.",
                )
            )

        # 4. Source authority — only when the run actually stored quality tiers.
        scored = [s.quality.score for s in sources if s.quality is not None]
        components.append(
            QualityComponent(
                name="source_authority",
                available=bool(scored),
                value=(sum(scored) / len(scored) / 100.0) if scored else None,
                weight=QUALITY_WEIGHTS["source_authority"],
                detail=(
                    f"Mean publisher-class score across {len(scored)} rated sources."
                    if scored
                    else "This run stored no source-authority ratings."
                ),
            )
        )

        # 5. Evidence agreement — penalised by unresolved contradictions.
        if claims:
            unresolved = len([c for c in contradictions if not c.resolved])
            agreement = max(0.0, 1.0 - (unresolved / len(claims)))
            components.append(
                QualityComponent(
                    name="evidence_agreement",
                    available=True,
                    value=agreement,
                    weight=QUALITY_WEIGHTS["evidence_agreement"],
                    detail=f"{unresolved} unresolved disagreement(s) across {len(claims)} claims.",
                )
            )
        else:
            components.append(
                QualityComponent(
                    name="evidence_agreement",
                    available=False,
                    weight=QUALITY_WEIGHTS["evidence_agreement"],
                    detail="No claims were extracted, so agreement cannot be assessed.",
                )
            )

        # 6. Evidence relevance — mean retrieval relevance, when recorded.
        rels = [e.relevance_score for e in evidence if e.relevance_score is not None]
        components.append(
            QualityComponent(
                name="evidence_relevance",
                available=bool(rels),
                value=(sum(rels) / len(rels)) if rels else None,
                weight=QUALITY_WEIGHTS["evidence_relevance"],
                detail=(
                    f"Mean retrieval relevance across {len(rels)} evidence passages."
                    if rels
                    else "No relevance scores stored for this run's evidence."
                ),
            )
        )

        score = QualityScore(
            run_id=run.id,
            formula_version=QUALITY_FORMULA_VERSION,
            components=components,
        )
        score.recompute_overall()
        return score

    # -- internals ----------------------------------------------------------------

    def _build_claims(self, run, report: str, source_count: int) -> list[ClaimRecord]:
        extracted = extract_claims(report, source_count)
        claims: list[ClaimRecord] = []
        seen: set[str] = set()
        for position, c in enumerate(extracted):
            norm = " ".join(_tokens(_strip_citations(c.text)))
            if not norm or norm in seen:
                continue  # identical restatements add no integrity information
            seen.add(norm)
            claims.append(
                ClaimRecord(
                    run_id=run.id,
                    project_id=getattr(run, "project_id", None),
                    section=c.section,
                    text=c.text,
                    text_norm=norm,
                    citations=list(c.citations),
                    position=position,
                )
            )
        return claims

    def _passages_by_source_index(
        self, sources: list[Source], evidence: list[Evidence]
    ) -> dict[int, list[str]]:
        """Map 1-based citation numbers to the passages of that source."""
        by_index: dict[int, list[str]] = {}
        for i, source in enumerate(sources, start=1):
            key = (source.url or "").strip()
            passages = [
                e.content
                for e in evidence
                if e.content and (e.source.url or "").strip() == key
            ]
            if not passages and i - 1 < len(evidence):
                # Parallel-list fallback for runs stored before URLs were kept.
                candidate = evidence[i - 1]
                if candidate.content:
                    passages = [candidate.content]
            by_index[i] = passages
        return by_index

    def _claim_contradictions(
        self,
        run_id: str,
        claim: ClaimRecord,
        cited: list[int],
        passages_by_index: dict[int, list[str]],
    ) -> list[Contradiction]:
        """Pairwise disagreement between the sources a single claim cites."""
        found: list[Contradiction] = []
        for a_pos in range(len(cited)):
            for b_pos in range(a_pos + 1, len(cited)):
                a, b = cited[a_pos], cited[b_pos]
                text_a = "\n".join(passages_by_index.get(a, []))
                text_b = "\n".join(passages_by_index.get(b, []))
                hit = detect_contradiction(text_a, text_b)
                if hit is None:
                    continue
                kind, explanation = hit
                found.append(
                    Contradiction(
                        run_id=run_id,
                        claim_id=claim.id,
                        kind=kind,
                        source_a=a,
                        source_b=b,
                        excerpt_a=text_a[:600],
                        excerpt_b=text_b[:600],
                        explanation=explanation,
                    )
                )
        return found
