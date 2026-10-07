"""Project Overview: a deterministic research-intelligence view model.

Everything here is derived from already-persisted data (runs, findings and
their stored embeddings, documents). No LLM call, no web request and no new
embedding is made when the Overview loads — opening a project must feel
instant next to a research run.

Selection and deduplication are deterministic: the same database state always
produces the same Overview.
"""

from __future__ import annotations

import logging
from collections import Counter

import numpy as np

from src.models.memory import ProjectFinding
from src.models.runs import ResearchRun, RunStatus
from src.persistence.findings import FindingsRepository

logger = logging.getLogger(__name__)

# Cosine similarity above which two findings are treated as the same claim.
# Measured on this project's real findings (nomic-embed-text): 0.95 and 0.93
# were plain restatements of one sentence, and 0.906 two runs reporting the
# same pilot-production fact — all worth merging into one corroborated item.
# Clearly different claims sat at 0.87 or below ("raw material cost" vs
# "specialised equipment"). 0.90 splits those groups; pairs landing near it
# are a judgement call, and merging only ever loses a restatement, never a
# source (every member run is kept in the cluster's support).
DUPLICATE_THRESHOLD = 0.90
MAX_UNDERSTANDING = 5
MIN_UNDERSTANDING = 3
MAX_KEY_FINDINGS = 6
MAX_GAPS = 5
RECENT_RUNS = 5


class FindingCluster:
    """A group of near-identical findings and the runs that produced them."""

    def __init__(self, representative: ProjectFinding) -> None:
        self.representative = representative
        self.members: list[ProjectFinding] = [representative]

    @property
    def run_ids(self) -> list[str]:
        seen: list[str] = []
        for member in self.members:
            if member.run_id not in seen:
                seen.append(member.run_id)
        return seen

    @property
    def support(self) -> int:
        """How many distinct runs independently produced this finding."""
        return len(self.run_ids)

    def add(self, finding: ProjectFinding) -> None:
        self.members.append(finding)
        # The clearest member represents the cluster: most provenance first,
        # then the fuller sentence, then the earliest (stable) id.
        self.members.sort(
            key=lambda f: (-len(f.sources), -len(f.text), f.created_at, f.id)
        )
        self.representative = self.members[0]


def cluster_findings(
    findings: list[ProjectFinding],
    vectors: dict[str, np.ndarray],
    threshold: float = DUPLICATE_THRESHOLD,
) -> list[FindingCluster]:
    """Greedy, order-stable clustering of near-duplicate findings.

    Findings without a stored embedding fall back to exact-text matching, so
    they are never silently dropped.
    """
    ordered = sorted(findings, key=lambda f: (f.created_at, f.id))
    clusters: list[FindingCluster] = []
    for finding in ordered:
        vector = vectors.get(finding.id)
        placed = False
        for cluster in clusters:
            other = vectors.get(cluster.representative.id)
            if vector is not None and other is not None:
                denom = float(np.linalg.norm(vector)) * float(np.linalg.norm(other))
                similar = denom and float(np.dot(vector, other) / denom) >= threshold
            else:
                similar = finding.text_norm == cluster.representative.text_norm
            if similar:
                cluster.add(finding)
                placed = True
                break
        if not placed:
            clusters.append(FindingCluster(finding))
    return clusters


def rank_clusters(clusters: list[FindingCluster]) -> list[FindingCluster]:
    """Strongest first: corroborated across runs, then recent, then cited."""
    return sorted(
        clusters,
        key=lambda c: (
            -c.support,
            -c.representative.created_at.timestamp(),
            -len(c.representative.sources),
            c.representative.id,
        ),
    )


def pick_diverse(clusters: list[FindingCluster], limit: int) -> list[FindingCluster]:
    """Top clusters, preferring one per report section before repeating."""
    chosen: list[FindingCluster] = []
    used_sections: set[str] = set()
    for cluster in clusters:
        section = (cluster.representative.section or "").lower()
        if section and section in used_sections:
            continue
        chosen.append(cluster)
        used_sections.add(section)
        if len(chosen) >= limit:
            return chosen
    for cluster in clusters:  # top up if sections were too few
        if cluster not in chosen:
            chosen.append(cluster)
            if len(chosen) >= limit:
                break
    return chosen


def _cluster_payload(cluster: FindingCluster) -> dict:
    rep = cluster.representative
    return {
        "id": rep.id,
        "text": rep.text,
        "section": rep.section,
        "run_id": rep.run_id,
        "question": rep.question,
        "created_at": rep.created_at.isoformat(),
        "support": cluster.support,
        "run_ids": cluster.run_ids,
        "sources": [s.model_dump() for s in rep.sources],
    }


def knowledge_gaps(runs: list[ResearchRun]) -> list[dict]:
    """Open questions Atlas can state honestly, from stored run data only.

    Only signals the pipeline explicitly recorded are used:

    1. the critic's own ``missing_information`` for a completed run;
    2. follow-up queries the critic asked for when the iteration cap stopped
       further research;
    3. a question whose report could not be synthesized (fallback summary);
    4. a question whose run failed or was cancelled, so it was never answered.

    Planner subquestions were evaluated as a fifth signal and rejected: with
    real embeddings, an off-topic control question scored 0.53 against this
    project's findings while a genuinely answered subquestion scored 0.59, so
    "uncovered subquestion" cannot be told apart from "differently worded".
    Nothing here is generated; an empty list means no gap is known.
    """
    gaps: list[dict] = []
    seen: set[str] = set()

    def add(text: str, reason: str, run: ResearchRun) -> None:
        text = " ".join(text.split())
        key = text.lower()
        if not text or key in seen:
            return
        seen.add(key)
        gaps.append(
            {"text": text, "reason": reason, "run_id": run.id, "question": run.query}
        )

    for run in sorted(runs, key=lambda r: r.created_at, reverse=True):
        critique = run.critique
        if run.status is RunStatus.COMPLETED and critique is not None:
            for item in critique.missing_information:
                add(item, "The critic flagged this as missing evidence.", run)
            if critique.decision.value == "MORE_RESEARCH":
                for query in critique.follow_up_queries:
                    add(query, "The critic asked for more research, but the "
                               "iteration limit was reached.", run)
        if run.status is RunStatus.COMPLETED and run.metrics.synthesis_fallback:
            add(run.query, "Research completed, but no narrative report could "
                           "be written within the time budget.", run)
        if run.status in (RunStatus.FAILED, RunStatus.CANCELLED):
            reason = ("This research was cancelled before it finished."
                      if run.status is RunStatus.CANCELLED
                      else "This research did not complete, so the question is "
                           "still unanswered.")
            add(run.query, reason, run)
    return gaps[:MAX_GAPS]


class ProjectOverviewService:
    """Builds the Overview view model from persisted project data."""

    def __init__(
        self,
        projects_repo,
        runs_repo,
        findings_repo: FindingsRepository,
        documents_repo,
    ) -> None:
        self._projects = projects_repo
        self._runs = runs_repo
        self._findings = findings_repo
        self._documents = documents_repo

    def build(self, project_id: str) -> dict | None:
        project = self._projects.get(project_id)
        if project is None:
            return None

        # Three bounded queries, no per-run round trips.
        summaries, total_runs = self._runs.list(limit=200, project_id=project_id)
        runs = [run for s in summaries if (run := self._runs.get(s.id)) is not None]
        findings = self._findings.list_for_project(project_id)
        vectors = self._findings.embeddings_for_project(project_id)
        documents = [d for d in self._documents.list() if d.project_id == project_id]

        completed = [r for r in runs if r.status is RunStatus.COMPLETED]
        unique_sources = {
            source.normalized_url for run in completed for source in run.selected_sources
        }

        clusters = rank_clusters(cluster_findings(findings, vectors))
        understanding = pick_diverse(clusters, MAX_UNDERSTANDING)
        if len(understanding) < MIN_UNDERSTANDING:
            understanding = clusters[:MIN_UNDERSTANDING]
        chosen_ids = {c.representative.id for c in understanding}
        # Key findings continue the ranked list, so the two sections never
        # show the same finding twice.
        key = [c for c in clusters if c.representative.id not in chosen_ids][
            :MAX_KEY_FINDINGS
        ]

        findings_per_run = Counter(f.run_id for f in findings)
        recent = [
            {
                "id": run.id,
                "query": run.query,
                "title": run.title,
                "status": run.status.value,
                "mode": run.mode.value,
                "created_at": run.created_at.isoformat(),
                "findings_added": findings_per_run.get(run.id, 0),
            }
            for run in sorted(runs, key=lambda r: r.created_at, reverse=True)[:RECENT_RUNS]
        ]

        return {
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "created_at": project.created_at.isoformat(),
                "updated_at": project.updated_at.isoformat(),
            },
            "stats": {
                "runs": total_runs,
                "completed_runs": len(completed),
                "findings": len(findings),
                "unique_sources": len(unique_sources),
                "documents": len(documents),
            },
            "current_understanding": [_cluster_payload(c) for c in understanding],
            "key_findings": [_cluster_payload(c) for c in key],
            "knowledge_gaps": knowledge_gaps(runs),
            "recent_runs": recent,
        }
