"""Project Knowledge Graph: what a project knows, derived from its stored findings.

This is deliberately *not* the per-run knowledge graph in ``kg_service``. That one
asks the LLM to propose entities and relations for a single run. This one answers a
different question -- "what does this project know, and how is it connected?" -- and
answers it **deterministically from ``project_findings``**, with no LLM call, no web
search and no embedding generation. Opening the graph must stay instant, so every
signal used here is already persisted:

* the report section a finding came from,
* the finding text itself,
* which run and research question produced it,
* which sources it cites.

Concepts are recurring noun phrases; relationships are co-occurrence. Because
similarity is all we can honestly derive, concept-to-concept edges are labelled
``RELATED_TO`` and never something causal.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from src.models.memory import ProjectFinding
from src.models.runs import RunStatus

# Phrases are built from 1..3 word windows that never cross punctuation.
MAX_PHRASE_WORDS = 3
# A concept has to recur: one mention is an anecdote, not project knowledge.
MIN_FINDINGS_PER_CONCEPT = 2
# Keep the default canvas readable (section 7 of the spec).
MAX_CONCEPTS = 10
# A phrase present in most findings describes the project, not a concept within it.
UBIQUITY_RATIO = 0.6
# Below this many findings the ubiquity ratio is noise, so skip that filter.
UBIQUITY_MIN_FINDINGS = 8
# A short phrase is redundant only if a longer one covers this much of its evidence.
SUBSUME_RATIO = 0.8
# Two concepts are the same idea if they share a stem and nearly the same findings.
MERGE_JACCARD = 0.6
# Concepts are linked when they genuinely recur together.
MIN_COOCCURRENCE = 2

_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Sentence and clause boundaries: phrases must not span them.
_BOUNDARY = re.compile(r"[^a-z0-9\s-]+")

_STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can cannot could did do does doing down
    during each few for from further had has have having he her here hers him his how
    however i if in into is it its itself just me more most my no nor not of off on once
    only or other our out over own same she should so some such than that the their them
    then there these they this those through to too under until up very was we were what
    when where which while who whom why will with within would you your
    across among another anything become been being each else enough every everything
    like less many much often per several since still those though thus toward upon via
    whether without yet
    """.split()
)

# Report and research boilerplate. These are real words but carry no project meaning
# on their own; as part of a longer phrase ("production complexity") they survive.
_GENERIC_TERMS = frozenset(
    """
    abstract analysis approach area aspect background basis benefit case challenge change
    comparison conclusion consideration context current data definition detail development
    difference discussion effect evidence example factor feature finding focus form future
    general group growth idea impact importance information introduction issue key kind
    level limitation major method need note number objective observation observer option
    outcome overview part pattern perspective point potential problem process product
    purpose quality question range rate reason recent reference report research respect
    result review role scope section setting significance similar situation solution
    source state step strategy study subject summary support system technology term thing
    time topic trend type understanding use user value variety view way work year
    """.split()
)

# Prose scaffolding: the verbs and adjectives research writing leans on. On their own
# they are not concepts ("remains", "specialized"); inside a longer phrase they survive.
_GENERIC_TERMS |= frozenset(
    """
    according achieve additional address advance affect allow apply available base become
    begin believe combine compare complete consider continue create critical demonstrate
    depend describe determine develop different difficult discuss drive due enable ensure
    especially essential establish exist expect explain extend face focus follow give
    growing help high highlight identify important improve include increase indicate
    introduce involve large lead likely limit low main maintain major make mention need
    note observe occur offer particular perform possible potential present primary produce
    provide recent reduce relate remain report represent require resolve respond
    significant similar specialized specific suggest support take typical various
    """.split()
)


def _stem(word: str) -> str:
    """A deliberately small suffix stripper.

    It only has to make obvious morphological variants collide ("batteries"/"battery",
    "challenges"/"challenge"). It is not a linguistic stemmer and never tries to be
    clever, because a wrong merge silently fuses two distinct concepts.
    """
    for suffix, replacement in (
        ("ies", "y"),
        ("sses", "ss"),
        ("ches", "ch"),
        ("shes", "sh"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
    ):
        if suffix == "s" and word.endswith("ss"):
            break
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)] + replacement
            break
    # A trailing "e" is the last thing separating "challenge" from "challenges"
    # once the plural is gone, so drop it on words long enough to survive it.
    if word.endswith("e") and len(word) >= 5:
        word = word[:-1]
    return word


_GENERIC_STEMS = frozenset(_stem(term) for term in _GENERIC_TERMS)


def _phrase_key(phrase: str) -> tuple[str, ...]:
    """Order-insensitive stemmed identity, so 'scaling manufacturing' == 'manufacturing scaling'."""
    return tuple(sorted(_stem(word) for word in phrase.split()))


def concept_id(project_id: str, key: tuple[str, ...]) -> str:
    """Stable across rebuilds: same project + same stemmed phrase -> same node id."""
    digest = hashlib.sha1(f"{project_id}|{' '.join(key)}".encode()).hexdigest()
    return f"concept-{digest[:16]}"


def candidate_phrases(text: str) -> set[str]:
    """Every 1..3 word phrase in ``text`` that is free of stopwords and punctuation."""
    phrases: set[str] = set()
    for segment in _BOUNDARY.split(text.lower()):
        words = [match.group(0) for match in _WORD.finditer(segment)]
        for start in range(len(words)):
            if words[start] in _STOPWORDS:
                continue
            for size in range(1, MAX_PHRASE_WORDS + 1):
                window = words[start : start + size]
                if len(window) < size:
                    break
                if any(word in _STOPWORDS for word in window):
                    break
                if any(len(word) < 3 or word.isdigit() for word in window):
                    break
                if size == 1 and _stem(window[0]) in _GENERIC_STEMS:
                    continue
                phrases.add(" ".join(window))
    return phrases


@dataclass
class Concept:
    """A recurring idea in the project, with the findings that evidence it."""

    key: tuple[str, ...]
    label: str
    finding_ids: set[str] = field(default_factory=set)
    run_ids: set[str] = field(default_factory=set)
    # Every surface form seen, so a merged concept can explain itself.
    aliases: set[str] = field(default_factory=set)

    @property
    def finding_count(self) -> int:
        return len(self.finding_ids)

    @property
    def support_count(self) -> int:
        """Distinct runs. Several near-duplicate findings from one run count once."""
        return len(self.run_ids)


def _project_terms(name: str, description: str) -> set[str]:
    """Stems of the project's own name: these label the root node, not a concept."""
    words = _WORD.findall(f"{name} {description}".lower())
    return {_stem(word) for word in words if word not in _STOPWORDS and len(word) >= 3}


def extract_concepts(
    findings: list[ProjectFinding],
    *,
    project_id: str,
    project_name: str = "",
    project_description: str = "",
    limit: int = MAX_CONCEPTS,
) -> list[Concept]:
    """Derive the project's concepts from its findings. Pure, deterministic, no I/O."""
    if not findings:
        return []

    by_key: dict[tuple[str, ...], Concept] = {}
    for finding in findings:
        # The section heading is the author's own summary of the passage, so it is
        # treated as part of the finding's text for phrase purposes.
        for phrase in candidate_phrases(f"{finding.section}. {finding.text}"):
            key = _phrase_key(phrase)
            concept = by_key.get(key)
            if concept is None:
                concept = by_key[key] = Concept(key=key, label=phrase)
            concept.aliases.add(phrase)
            concept.finding_ids.add(finding.id)
            concept.run_ids.add(finding.run_id)

    total = len(findings)
    name_terms = _project_terms(project_name, project_description)

    kept: dict[tuple[str, ...], Concept] = {}
    for key, concept in by_key.items():
        if concept.finding_count < MIN_FINDINGS_PER_CONCEPT:
            continue
        # A phrase made only of the project's own name describes the whole project.
        if set(key) <= name_terms:
            continue
        if total >= UBIQUITY_MIN_FINDINGS and concept.finding_count / total > UBIQUITY_RATIO:
            continue
        kept[key] = concept

    # Subsumption runs first because it compares real phrase keys, and merging
    # rewrites those keys to whichever variant was seen first. It runs again after
    # merging, because a merged concept covers more words than its key shows: once
    # "manufacturing scalability" has folded into "manufacturing", a separate
    # "scalability" node is saying the same thing a second time.
    kept = _drop_subsumed(kept)
    kept = _merge_variants(kept)
    kept = _drop_subsumed(kept)

    ordered = sorted(
        kept.values(),
        # Corroboration across runs first, then breadth of evidence, then the more
        # specific phrasing, then alphabetical so the order never wobbles.
        key=lambda c: (-c.support_count, -c.finding_count, -len(_best_label(c).split()), c.label),
    )
    for concept in ordered:
        concept.label = _best_label(concept)
    return ordered[:limit]


def _best_label(concept: Concept) -> str:
    """Pick the most informative surface form, deterministically."""
    return sorted(concept.aliases, key=lambda alias: (-len(alias.split()), len(alias), alias))[0]


def _merge_variants(concepts: dict[tuple[str, ...], Concept]) -> dict[tuple[str, ...], Concept]:
    """Fuse phrasings of one idea.

    Two concepts merge only when they share a stem *and* are evidenced by nearly the
    same findings. Requiring both means the merge is grounded in the project's data
    rather than in a guess about English, so distinct ideas that happen to share a
    word ("production cost" vs "production timeline") stay apart.
    """
    order = sorted(concepts, key=lambda key: (-len(concepts[key].finding_ids), key))
    merged: dict[tuple[str, ...], Concept] = {}
    for key in order:
        concept = concepts[key]
        target = None
        for existing in merged.values():
            if not set(existing.key) & set(concept.key):
                continue
            union = existing.finding_ids | concept.finding_ids
            overlap = len(existing.finding_ids & concept.finding_ids) / len(union)
            if overlap >= MERGE_JACCARD:
                target = existing
                break
        if target is None:
            merged[key] = concept
        else:
            target.finding_ids |= concept.finding_ids
            target.run_ids |= concept.run_ids
            target.aliases |= concept.aliases
    return merged


def _drop_subsumed(concepts: dict[tuple[str, ...], Concept]) -> dict[tuple[str, ...], Concept]:
    """Drop a phrase when a longer phrase containing all of its words is also present.

    Showing both "interface stability" and a bare "stability" node says the same thing
    twice and costs the canvas a slot, so the more specific phrase always wins. The
    shorter form is kept as an alias so search still finds it. Its findings are not
    folded in: a passage that only said "stability" is not evidence for "interface
    stability", and claiming otherwise would overstate the concept's support.
    """
    kept = dict(concepts)
    # Compare the words a concept actually stands for, which after a merge is its
    # richest surface form rather than the key it happens to be filed under.
    effective = {key: set(_phrase_key(_best_label(c))) | set(key) for key, c in concepts.items()}
    for key, concept in concepts.items():
        for other_key, other in concepts.items():
            if other_key == key or not effective[key] < effective[other_key]:
                continue
            covered = len(concept.finding_ids & other.finding_ids) / len(concept.finding_ids)
            if covered < SUBSUME_RATIO:
                # The short phrase carries evidence of its own, so it is a real concept.
                continue
            other.aliases |= concept.aliases
            kept.pop(key, None)
            break
    return kept


class ProjectGraphService:
    """Builds a project's knowledge graph from already-persisted data."""

    def __init__(self, projects_repo, runs_repo, findings_repo) -> None:
        self._projects = projects_repo
        self._runs = runs_repo
        self._findings = findings_repo

    def build(self, project_id: str) -> dict | None:
        """Return the graph payload, or ``None`` when the project does not exist."""
        project = self._projects.get(project_id)
        if project is None:
            return None

        summaries, _ = self._runs.list(limit=200, project_id=project_id)
        # Only completed research contributes knowledge; a failed or cancelled run
        # must never put a concept on the canvas.
        completed_run_ids = {s.id for s in summaries if s.status is RunStatus.COMPLETED}
        questions = {s.id: (s.title or s.query) for s in summaries}

        findings = [
            finding
            for finding in self._findings.list_for_project(project_id)
            if finding.run_id in completed_run_ids
        ]

        concepts = extract_concepts(
            findings,
            project_id=project_id,
            project_name=project.name,
            project_description=project.description or "",
        )

        root_id = f"project-{project_id}"
        nodes: list[dict] = [
            {
                "id": root_id,
                "label": project.name,
                "type": "project",
                "project_id": project_id,
                "support_count": len({f.run_id for f in findings}),
                "finding_count": len(findings),
            }
        ]
        edges: list[dict] = []

        by_id = {finding.id: finding for finding in findings}
        shown: set[str] = set()

        for concept in concepts:
            node_id = concept_id(project_id, concept.key)
            nodes.append(
                {
                    "id": node_id,
                    "label": concept.label,
                    "type": "concept",
                    "project_id": project_id,
                    "support_count": concept.support_count,
                    "finding_count": concept.finding_count,
                }
            )
            edges.append(
                {
                    "id": f"edge-{root_id}-{node_id}",
                    "source": root_id,
                    "target": node_id,
                    "relation": "HAS_TOPIC",
                    "weight": concept.finding_count,
                }
            )
            for finding_id in sorted(concept.finding_ids):
                finding = by_id[finding_id]
                if finding_id not in shown:
                    shown.add(finding_id)
                    nodes.append(
                        {
                            "id": finding_id,
                            "label": finding.text,
                            "type": "finding",
                            "project_id": project_id,
                            "text": finding.text,
                            "section": finding.section,
                            "source_run_id": finding.run_id,
                            "source_question": finding.question
                            or questions.get(finding.run_id, ""),
                            "created_at": finding.created_at.isoformat(),
                            "sources": [
                                {"url": source.url, "title": source.title}
                                for source in finding.sources
                            ],
                            "support_count": 1,
                            "finding_count": 1,
                        }
                    )
                edges.append(
                    {
                        "id": f"edge-{node_id}-{finding_id}",
                        "source": node_id,
                        "target": finding_id,
                        "relation": "SUPPORTED_BY",
                        "weight": 1,
                    }
                )

        edges.extend(_related_edges(project_id, concepts))

        return {
            "project": {"id": project.id, "name": project.name},
            "stats": {
                "concepts": len(concepts),
                "findings": len(findings),
                "runs": len({f.run_id for f in findings}),
            },
            "nodes": nodes,
            "edges": edges,
        }


def _related_edges(project_id: str, concepts: list[Concept]) -> list[dict]:
    """Link concepts that recur together.

    This is co-occurrence and nothing more, so the relation stays neutral. Turning it
    into a causal claim would be inventing knowledge the project does not have.
    """
    edges: list[dict] = []
    for index, left in enumerate(concepts):
        for right in concepts[index + 1 :]:
            shared = left.finding_ids & right.finding_ids
            if len(shared) < MIN_COOCCURRENCE:
                continue
            left_id = concept_id(project_id, left.key)
            right_id = concept_id(project_id, right.key)
            edges.append(
                {
                    "id": f"edge-{left_id}-{right_id}",
                    "source": left_id,
                    "target": right_id,
                    "relation": "RELATED_TO",
                    "weight": len(shared),
                }
            )
    return edges
