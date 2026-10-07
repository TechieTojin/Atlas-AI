"""Project research memory: what a project already learned, reused later.

Distinct from evidence memory (``MemoryService``), which caches raw web
evidence per search query. This layer stores compact, cited FINDINGS
distilled from completed runs in a project, and retrieves the few relevant
to a new research question so the planner and synthesizer know what the
project has already established.

Extraction is deterministic (cited sentences of the final report, mapped
back to that run's real sources) — no extra LLM call, so FAST budgets are
unaffected. Retrieval costs one embedding of the question.
"""

from __future__ import annotations

import logging
import re

from src.evaluation.claims import extract_claims
from src.models.memory import FindingSource, MemoryHit, MemoryReport, ProjectFinding
from src.models.runs import ResearchRun, RunStatus
from src.persistence.findings import FindingsRepository
from src.tools.excerpts import is_claim_sentence, normalize_text

logger = logging.getLogger(__name__)

MAX_FINDINGS_PER_RUN = 12
MAX_FINDING_CHARS = 400
MIN_FINDING_CHARS = 50
# Question-to-finding similarity, measured with nomic-embed-text on real
# Atlas runs (see tests/test_project_memory.py for the recorded values):
#   same-topic follow-up  -> 0.75-0.83   (reuse)
#   off-topic, same project -> 0.54-0.58 (ignore: solar vs. batteries)
#   unrelated question      -> 0.39      (ignore)
DEFAULT_RELEVANCE_THRESHOLD = 0.65
DEFAULT_MAX_ITEMS = 4


def unwrap_markdown(text: str) -> str:
    """Join soft-wrapped lines so a sentence is never split into fragments.

    Claim extraction works line by line, which is right for the UI inspector
    (it anchors each claim to a line) but would chop a wrapped sentence —
    and its citation — into unusable pieces here. Headings, list items and
    blank lines stay as their own lines.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        starts_block = (
            not stripped
            or stripped.startswith(("#", "-", "*", ">", "|"))
            or re.match(r"^\d+[.)]\s", stripped) is not None
        )
        if out and not starts_block and out[-1].strip() and not out[-1].strip().startswith(
            ("#", "-", "*", ">", "|")
        ):
            out[-1] = f"{out[-1].rstrip()} {stripped}"
        else:
            out.append(stripped)
    return "\n".join(out)


def extract_findings(run: ResearchRun) -> list[ProjectFinding]:
    """Compact, cited findings from a completed project run's report.

    Only sentences that carry valid citations become findings, and each one
    keeps the real sources it cited, so reused knowledge always says where
    it came from. Nothing is generated: the text is the report's own.
    """
    if not run.project_id or not run.final_report or not run.selected_sources:
        return []
    claims = extract_claims(unwrap_markdown(run.final_report), len(run.selected_sources))
    findings: list[ProjectFinding] = []
    seen: set[str] = set()
    for claim in claims:
        text = normalize_text(claim.text)
        if len(text) < MIN_FINDING_CHARS or not is_claim_sentence(text):
            continue
        if len(text) > MAX_FINDING_CHARS:
            text = text[:MAX_FINDING_CHARS].rsplit(" ", 1)[0] + "…"
        finding = ProjectFinding(
            project_id=run.project_id,
            run_id=run.id,
            question=run.query,
            section=claim.section,
            text=text,
            sources=[
                FindingSource(
                    url=run.selected_sources[n - 1].url,
                    title=run.selected_sources[n - 1].title,
                )
                for n in claim.citations
                if 1 <= n <= len(run.selected_sources)
            ],
        )
        if finding.text_norm in seen or not finding.sources:
            continue
        seen.add(finding.text_norm)
        findings.append(finding)
        if len(findings) >= MAX_FINDINGS_PER_RUN:
            break
    return findings


class ProjectMemoryService:
    def __init__(
        self,
        repo: FindingsRepository,
        embed_texts=None,
        threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> None:
        self._repo = repo
        self._embed = embed_texts  # list[str] -> list[list[float]]
        self._threshold = threshold
        self._max_items = max_items

    # -- writing -----------------------------------------------------------

    def remember_run(self, run: ResearchRun) -> int:
        """Store a completed project run's findings (idempotent)."""
        if run.status is not RunStatus.COMPLETED:
            return 0
        findings = extract_findings(run)
        if not findings:
            return 0
        embeddings = None
        if self._embed is not None:
            try:
                embeddings = self._embed([f.text for f in findings])
            except Exception:
                # Store unembedded; they are embedded lazily on next recall.
                logger.warning("Finding embedding failed; will embed later.",
                               exc_info=True)
        added = self._repo.add_many(findings, embeddings)
        if added:
            logger.info("Project memory: stored %d finding(s) from run %s.",
                        added, run.id)
        return added

    def backfill(self, runs: list[ResearchRun]) -> int:
        """Index completed project runs that have no findings yet.

        Idempotent twice over: already-indexed runs are skipped, and the
        unique (project, text) constraint ignores repeats.
        """
        indexed = self._repo.run_ids_with_findings()
        total = 0
        for run in runs:
            if run.id in indexed or not run.project_id:
                continue
            total += self.remember_run(run)
        if total:
            logger.info("Project memory backfill: indexed %d finding(s).", total)
        return total

    def _embed_missing(self, project_id: str) -> None:
        """Embed findings stored while embeddings were unavailable."""
        if self._embed is None:
            return
        pending = self._repo.unembedded(project_id)
        if not pending:
            return
        vectors = self._embed([f.text for f in pending])
        for finding, vector in zip(pending, vectors):
            self._repo.set_embedding(finding.id, vector)

    # -- reading -----------------------------------------------------------

    def recall(self, question: str, project_id: str) -> tuple[list[MemoryHit], MemoryReport]:
        """Findings from THIS project relevant to ``question``.

        Returns the hits and a report that always distinguishes "disabled",
        "nothing relevant" and "retrieval failed".
        """
        report = MemoryReport(
            enabled=True,
            scope="PROJECT" if project_id else "NONE",
            threshold=self._threshold,
        )
        if not project_id:
            return [], report
        if self._embed is None:
            report.error = "No embedding model is configured for project memory."
            return [], report
        try:
            self._embed_missing(project_id)
            vector = self._embed([question])[0]
            scored, candidates = self._repo.search(
                project_id, vector, self._max_items, self._threshold
            )
        except Exception as exc:
            logger.warning("Project memory retrieval failed.", exc_info=True)
            report.error = f"{type(exc).__name__}: {exc}"
            return [], report
        hits = [MemoryHit(finding=f, score=round(s, 4)) for f, s in scored]
        report.candidates = candidates
        report.hits = len(hits)
        report.items = [
            {
                "text": h.finding.text,
                "question": h.finding.question,
                "run_id": h.finding.run_id,
                "score": h.score,
                "sources": [s.model_dump() for s in h.finding.sources],
            }
            for h in hits
        ]
        if hits:
            logger.info(
                "Project memory: reusing %d of %d finding(s) (top score %.2f).",
                len(hits), candidates, hits[0].score,
            )
        return hits, report


def format_memory_block(hits: list[MemoryHit], max_chars: int = 1200) -> str:
    """Render hits as a clearly separated, NON-citable context block."""
    if not hits:
        return ""
    lines: list[str] = []
    used = 0
    for hit in hits:
        line = f"- {hit.finding.text}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    return "\n".join(lines)
