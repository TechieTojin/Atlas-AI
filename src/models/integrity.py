"""Research integrity domain: claims, citation verification, contradictions
and a transparent research quality score.

Design rules that the rest of Atlas depends on:

* A claim is never invented. It is a cited sentence lifted verbatim from a
  persisted report body (see :func:`src.evaluation.claims.extract_claims`),
  so every claim can be pointed back at the exact text a user read.
* A verification verdict is never "trust the citation because it exists".
  The claim text is compared against the passages it actually cites.
* Confidence is an interpretable band, not a fabricated probability. We do
  not pretend to mathematical certainty we cannot justify.
* Anything Atlas cannot compute truthfully is reported as NOT AVAILABLE
  rather than guessed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class VerificationStatus(str, Enum):
    """Does the cited evidence actually support the claim?"""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    #: No usable evidence text was stored for the cited source, so the claim
    #: cannot be checked either way. This is an honest "unknown", not a fail.
    NOT_VERIFIABLE = "NOT_VERIFIABLE"

    @property
    def is_problem(self) -> bool:
        return self in (VerificationStatus.UNSUPPORTED, VerificationStatus.CONTRADICTED)


class ConfidenceBand(str, Enum):
    """Interpretable confidence. Deliberately not a percentage."""

    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


class VerifierKind(str, Enum):
    """Which mechanism produced a verdict, so users can judge its weight."""

    #: Lexical/numeric overlap between claim and cited passage. Always runs.
    DETERMINISTIC = "DETERMINISTIC"
    #: Deterministic signals refined by a bounded structured model call.
    MODEL_ASSISTED = "MODEL_ASSISTED"


class ContradictionType(str, Enum):
    """Why two pieces of evidence disagree.

    Different wording is NOT a contradiction; these types exist so Atlas can
    say what kind of disagreement it found instead of flattening everything
    into "conflict".
    """

    DIRECT_CONTRADICTION = "DIRECT_CONTRADICTION"
    CONTEXTUAL_DISAGREEMENT = "CONTEXTUAL_DISAGREEMENT"
    MIXED_EVIDENCE = "MIXED_EVIDENCE"
    OUTDATED_VS_CURRENT = "OUTDATED_VS_CURRENT"
    DIFFERENT_SCOPE = "DIFFERENT_SCOPE"


class VerificationSignal(BaseModel):
    """One transparent, reproducible input to a verdict.

    Shown verbatim in the UI so a user can see *why* Atlas decided what it
    decided rather than being handed an opaque score.
    """

    name: str
    #: Normalised 0..1 where meaningful; None when the signal is categorical.
    value: float | None = None
    #: Short human-readable statement, e.g. "3 of 4 figures appear in the passage".
    detail: str = ""


class ClaimRecord(BaseModel):
    """A cited assertion taken verbatim from a persisted report."""

    id: str = Field(default_factory=new_id)
    run_id: str
    project_id: str | None = None
    #: Report heading the claim sits under ("" when before any heading).
    section: str = ""
    text: str
    #: Normalised text used only for de-duplicating identical claims per run.
    text_norm: str = ""
    #: 1-based source numbers cited by this claim, as written in the report.
    citations: list[int] = Field(default_factory=list)
    #: Document order within the report, so the UI can list claims as read.
    position: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class ClaimVerification(BaseModel):
    """The verdict for one claim against the evidence it cites."""

    id: str = Field(default_factory=new_id)
    claim_id: str
    run_id: str
    status: VerificationStatus
    confidence: ConfidenceBand
    verifier: VerifierKind = VerifierKind.DETERMINISTIC
    #: Transparent inputs behind the verdict.
    signals: list[VerificationSignal] = Field(default_factory=list)
    #: One or two sentences a non-expert can read.
    explanation: str = ""
    #: Source numbers whose passages were actually examined.
    checked_citations: list[int] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class Contradiction(BaseModel):
    """A recorded disagreement between two cited passages."""

    id: str = Field(default_factory=new_id)
    run_id: str
    #: The claim the disagreement was found under, when it is claim-scoped.
    claim_id: str | None = None
    kind: ContradictionType
    #: 1-based source numbers of the two disagreeing passages.
    source_a: int
    source_b: int
    #: Verbatim excerpts, so the user judges the disagreement themselves.
    excerpt_a: str = ""
    excerpt_b: str = ""
    explanation: str = ""
    resolved: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class QualityComponent(BaseModel):
    """One dimension of the research quality score.

    ``available`` is False when Atlas genuinely cannot compute the dimension
    for this run; the UI must render NOT AVAILABLE rather than a zero.
    """

    name: str
    available: bool = True
    #: 0..1 when available.
    value: float | None = None
    weight: float = 0.0
    detail: str = ""


class QualityScore(BaseModel):
    """Transparent, recomputable quality assessment for a run.

    The overall score is a weighted mean of the *available* components only,
    renormalised by their weights — so a run that cannot compute a dimension
    is not silently punished for it.
    """

    run_id: str
    #: Bump when the formula changes so stored scores stay interpretable.
    formula_version: int = 1
    components: list[QualityComponent] = Field(default_factory=list)
    #: 0..1, or None when no component could be computed at all.
    overall: float | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def available_components(self) -> list[QualityComponent]:
        return [c for c in self.components if c.available and c.value is not None]

    def recompute_overall(self) -> float | None:
        usable = [c for c in self.available_components if c.weight > 0]
        total_weight = sum(c.weight for c in usable)
        if not usable or total_weight <= 0:
            self.overall = None
            return None
        self.overall = sum((c.value or 0.0) * c.weight for c in usable) / total_weight
        return self.overall


class IntegritySummary(BaseModel):
    """Report-level citation integrity.

    Deliberately keeps *coverage* (how much of the report is cited at all)
    separate from *support* (whether those citations hold up).
    """

    run_id: str
    total_claims: int = 0
    supported: int = 0
    partially_supported: int = 0
    unsupported: int = 0
    contradicted: int = 0
    not_verifiable: int = 0
    contradiction_count: int = 0

    @property
    def verified_claims(self) -> int:
        """Claims Atlas could actually reach a support decision on."""
        return self.total_claims - self.not_verifiable

    @property
    def support_rate(self) -> float | None:
        """Share of verifiable claims that are fully supported.

        None when nothing was verifiable — never fabricate a percentage.
        """
        if self.verified_claims <= 0:
            return None
        return self.supported / self.verified_claims
