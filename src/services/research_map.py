"""Research Map: how Atlas actually produced one research run.

A deterministic, read-only view over what is already stored:

* the run itself (plan, executed queries, collected evidence with the query
  that found it, numbered cited sources, report, metrics);
* the run's persisted event log (search iterations with their queries,
  per-iteration critic decisions, skips/timeouts, more-research requests,
  cancellation and failure);
* citations parsed from the report (regex only, as ``/claims`` does).

Nothing here calls a model, an embedding, Tavily or the network, and nothing
is invented: a stage appears only if stored data proves it happened. When the
event log is missing (historical runs, or a gap), the map shows what the run
record proves and says which details were not recorded.

Never exposed: model reasoning (``Critique.reasoning``) or any hidden
thinking. Only structured, user-visible outputs are included.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any

from src.evaluation.claims import extract_claims
from src.events.models import EventType, RunEvent
from src.models.runs import ResearchRun, RunStatus
from src.unicode_text import words

#: Node types (``type`` field).
QUESTION, PLAN, QUERY, MEMORY = "question", "plan", "query", "project_memory"
SOURCE, EVIDENCE, CRITIC, SYNTHESIS, REPORT, TERMINAL, BRANCH = (
    "source", "evidence", "critic", "synthesis", "report", "terminal", "branch",
)
#: Node types a new research run may branch from (real research material only;
#: presentation/outcome nodes are not meaningful starting points).
BRANCHABLE_TYPES = frozenset({QUESTION, PLAN, QUERY, SOURCE, EVIDENCE, CRITIC})
#: Branch context given to the child's planner is bounded to this many chars.
BRANCH_CONTEXT_CHARS = 700
#: Node statuses.
COMPLETED, RUNNING, SKIPPED, TIMED_OUT, FAILED, CANCELLED, FALLBACK = (
    "completed", "running", "skipped", "timed_out", "failed", "cancelled", "fallback",
)
#: Edge types.
PLANNED, RETRIEVED, REVIEWED, MORE_RESEARCH, USED_IN_SYNTHESIS, PRODUCED, CITED_IN, CONTEXT, FROM_SOURCE, ENDED, PROCEEDED, BRANCHED = (
    "PLANNED", "RETRIEVED", "REVIEWED", "REQUESTED_MORE_RESEARCH", "USED_IN_SYNTHESIS",
    "PRODUCED", "CITED_IN_REPORT", "PROVIDED_CONTEXT", "FROM_SOURCE", "ENDED", "PROCEEDED_TO_SYNTHESIS", "BRANCHED",
)

_ACTIVE = {
    RunStatus.PENDING, RunStatus.PLANNING, RunStatus.AWAITING_APPROVAL, RunStatus.RESEARCHING,
    RunStatus.CRITIQUING, RunStatus.SYNTHESIZING, RunStatus.CANCELLING,
}


def _short_hash(*parts: str) -> str:
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _ms_between(start, end) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


class _Map:
    def __init__(self) -> None:
        self.nodes: "OrderedDict[str, dict]" = OrderedDict()
        self.edges: "OrderedDict[str, dict]" = OrderedDict()

    def node(self, node_id: str, type_: str, *, label: str = "", status: str = COMPLETED,
             rank: int = 0, iteration: int | None = None, group: str | None = None,
             started_at=None, completed_at=None, duration_ms: int | None = None,
             data: dict | None = None) -> str:
        self.nodes[node_id] = {
            "id": node_id, "type": type_, "label": label, "status": status, "rank": rank,
            "iteration": iteration, "group": group,
            "started_at": _iso(started_at), "completed_at": _iso(completed_at),
            "duration_ms": duration_ms if duration_ms is not None else _ms_between(started_at, completed_at),
            "data": data or {},
        }
        return node_id

    def edge(self, source: str, target: str, type_: str, metadata: dict | None = None) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        edge_id = f"{source}->{target}:{type_}"
        self.edges.setdefault(edge_id, {
            "id": edge_id, "source": source, "target": target, "type": type_,
            "metadata": metadata or {},
        })


def _first(events: list[RunEvent], type_: EventType, iteration: int | None = None) -> RunEvent | None:
    for event in events:
        if event.type == type_ and (iteration is None or event.iteration == iteration):
            return event
    return None


def _node_ms(run: ResearchRun, node: str, iteration: int | None = None) -> int | None:
    total, found = 0, False
    for timing in run.metrics.node_timings or []:
        if timing.get("node") == node and (iteration is None or timing.get("iteration") == iteration):
            total += int(timing.get("ms") or 0)
            found = True
    return total if found else None


def _source_key(source) -> str:
    return (source.url or "").strip().rstrip("/").lower()


def branch_context_for(node: dict) -> tuple[str, str]:
    """(label, bounded context text) for branching from a REAL map node.

    Raises ``ValueError`` for node types that are not research material.
    Everything in the text is stored content of the parent run, verbatim but
    truncated to :data:`BRANCH_CONTEXT_CHARS`.
    """
    node_type, data = node.get("type"), node.get("data", {})
    if node_type not in BRANCHABLE_TYPES:
        raise ValueError(f"Cannot branch from a {node_type or 'unknown'} node.")
    if node_type == QUESTION:
        label, text = "the original research question", str(data.get("question", ""))
    elif node_type == PLAN:
        subs = "".join(f"\n- {s}" for s in data.get("subquestions", []))
        label = "the research plan"
        text = f"Objective: {data.get('objective', '')}{subs}"
    elif node_type == QUERY:
        label, text = "a search query of the parent run", str(data.get("query", ""))
    elif node_type == SOURCE:
        label = f"source [{data.get('citation')}] of the parent run"
        quality = data.get("quality") or {}
        tier = f" (publisher class: {quality.get('tier')})" if quality.get("tier") else ""
        title = data.get("title") or data.get("filename") or ""
        text = f"{title} — {data.get('domain') or ''}{tier}\n{data.get('url') or ''}"
    elif node_type == EVIDENCE:
        source = data.get("source_title") or data.get("filename") or ""
        cite = f" [{data.get('citation')}]" if data.get("citation") else ""
        label = "an evidence excerpt of the parent run"
        text = f"From {source}{cite}:\n{data.get('content', '')}"
    else:  # CRITIC
        gaps = "".join(f"\n- {g}" for g in data.get("missing_information", []))
        label = "the reviewer's gap assessment of the parent run"
        text = f"Coverage: {data.get('coverage') or ''}{gaps}" if (data.get("coverage") or gaps) else (
            f"Review decision: {data.get('decision') or ''} (score {data.get('score')})"
        )
    text = " ".join(str(text).split())
    if len(text) > BRANCH_CONTEXT_CHARS:
        text = text[: BRANCH_CONTEXT_CHARS - 1] + "…"
    return label, text


def build_research_map(
    run: ResearchRun, events: list[RunEvent], children: list[ResearchRun] | None = None
) -> dict[str, Any]:
    """The map for one run. Pure function of the stored run and its events."""
    events = sorted((e for e in events if e.run_id == run.id), key=lambda e: e.seq)
    m = _Map()
    limitations: list[str] = []
    terminal = run.status in (RunStatus.FAILED, RunStatus.CANCELLED)
    active = run.status in _ACTIVE
    has_events = bool(events)
    if not has_events:
        limitations.append("events_not_recorded")

    # --- question ---------------------------------------------------------------------
    started = _first(events, EventType.RUN_STARTED)
    m.node("question", QUESTION, label=run.query, rank=0, started_at=run.started_at or run.created_at, data={
        "question": run.query, "mode": run.mode.value, "source_scope": run.source_scope.value,
        "template": run.template, "output_language": run.output_language,
        "project_id": run.project_id or None, "use_memory": run.use_memory,
        "regenerated_from": run.regenerated_from, "approval_required": run.approval_required,
    })
    m.nodes["question"]["started_at"] = _iso(started.timestamp) if started else m.nodes["question"]["started_at"]
    m.nodes["question"]["duration_ms"] = None

    # --- plan -------------------------------------------------------------------------
    plan_created = _first(events, EventType.PLAN_CREATED)
    plan_started = _first(events, EventType.PLANNING_STARTED)
    edits = [e for e in events if e.type == EventType.PLAN_EDITED]
    approved = _first(events, EventType.PLAN_APPROVED)
    if run.plan is not None or plan_created is not None:
        plan = run.plan
        data = {
            "objective": plan.objective if plan else "",
            "subquestions": [t.subquestion for t in plan.tasks] if plan else list(plan_created.payload.get("subquestions", [])),
            "search_queries": list(plan.search_queries) if plan else list(plan_created.payload.get("queries", [])),
            "approval_required": run.approval_required,
            "approved": approved is not None,
            "approved_at": _iso(approved.timestamp) if approved else None,
            "edited": bool(edits),
            "original_subquestions": list(plan_created.payload.get("subquestions", [])) if (plan_created and edits) else None,
            "original_queries": list(plan_created.payload.get("queries", [])) if (plan_created and edits) else None,
            "planner_attempts": run.metrics.planner_attempts or None,
            "llm": (run.metrics.llm_stage_stats or {}).get("planner"),
        }
        m.node("plan", PLAN, label=data["objective"] or run.query, rank=1,
               started_at=plan_started.timestamp if plan_started else None,
               completed_at=plan_created.timestamp if plan_created else None,
               duration_ms=run.metrics.planner_ms or None, data=data)
        m.edge("question", "plan", PLANNED)
    elif plan_started is not None:
        m.node("plan", PLAN, label=run.query, rank=1, status=_open_status(run),
               started_at=plan_started.timestamp, data={"subquestions": [], "search_queries": []})
        m.edge("question", "plan", PLANNED)

    # --- project memory (only when the run actually retrieved findings) ----------------
    memory_items = run.metrics.memory_items or []
    if run.metrics.project_memory_hits and memory_items:
        m.node("memory:project", MEMORY, label="", rank=1, data={
            "hits": run.metrics.project_memory_hits, "candidates": run.metrics.memory_candidates,
            "threshold": run.metrics.memory_threshold,
            "items": [
                {"text": i.get("text", ""), "question": i.get("question", ""), "run_id": i.get("run_id", ""),
                 "score": i.get("score")} for i in memory_items
            ],
        })
        m.edge("question", "memory:project", PLANNED)

    # --- research iterations ----------------------------------------------------------
    iterations: "OrderedDict[int, dict]" = OrderedDict()
    for e in events:
        if e.type == EventType.SEARCH_STARTED and e.iteration not in iterations:
            iterations[e.iteration] = {"started": e, "queries": list(e.payload.get("queries", []))}
    query_done: dict[tuple[int, str], RunEvent] = {}
    query_start: dict[tuple[int, str], RunEvent] = {}
    for e in events:
        q = str(e.payload.get("query", ""))
        if e.type == EventType.SEARCH_QUERY_COMPLETED:
            query_done.setdefault((e.iteration, q), e)
        elif e.type == EventType.SEARCH_QUERY_STARTED:
            query_start.setdefault((e.iteration, q), e)

    reconstructed = False
    if not iterations and (run.executed_queries or run.evidence):
        # No event log: the run record proves which queries ran, not when.
        iterations[0] = {"started": None, "queries": list(dict.fromkeys(run.executed_queries))}
        reconstructed = True
        limitations.append("iterations_not_recorded")

    scope = run.source_scope.value
    retrieval_kind = {"WEB": "web", "DOCUMENTS": "documents", "WEB_AND_DOCUMENTS": "web_and_documents"}.get(scope, "web")
    rank = 2
    query_nodes: dict[tuple[int, str], str] = {}
    iteration_ranks: dict[int, int] = {}
    previous_critic: str | None = None
    previous_more = False
    for it, info in iterations.items():
        iteration_ranks[it] = rank
        for position, query in enumerate(info["queries"]):
            done = query_done.get((it, query))
            start = query_start.get((it, query))
            status = COMPLETED if (done or reconstructed) else _open_status(run)
            node_id = m.node(
                f"query:{it}:{position}", QUERY, label=query, rank=rank,
                iteration=it if not reconstructed else None, status=status,
                started_at=start.timestamp if start else None, completed_at=done.timestamp if done else None,
                data={
                    "query": query, "retrieval": retrieval_kind,
                    "web_results": done.payload.get("results") if done else None,
                    "document_chunks": done.payload.get("document_chunks") if done else None,
                    "memory_hits": done.payload.get("memory_hits") if done else None,
                },
            )
            query_nodes[(it, query)] = node_id
            if previous_critic and previous_more:
                m.edge(previous_critic, node_id, MORE_RESEARCH)
            elif "plan" in m.nodes:
                m.edge("plan", node_id, PLANNED)
        rank += 2  # evidence sits between queries and the critic
        critic_id = _critic_node(m, run, events, it, rank, reconstructed, last=(it == next(reversed(iterations))))
        rank += 1
        if critic_id:
            more = _first(events, EventType.MORE_RESEARCH_REQUESTED, it)
            previous_more = more is not None
            if more is not None:
                m.nodes[critic_id]["data"]["follow_up_queries"] = list(more.payload.get("follow_up_queries", []))
        previous_critic = critic_id

    # --- sources (citation numbers = position in selected_sources) ----------------------
    source_by_key: dict[str, str] = {}
    sources_rank = rank
    for number, source in enumerate(run.selected_sources, 1):
        node_id = m.node(f"source:{number}", SOURCE, label=source.title or source.filename or source.url,
                         rank=sources_rank, group="sources", data={
                             "citation": number, "title": source.title, "url": source.url, "domain": source.domain,
                             "kind": source.kind, "filename": source.filename, "page": source.page,
                             "quality": source.quality.model_dump(mode="json") if source.quality else None,
                         })
        source_by_key.setdefault(_source_key(source), node_id)

    # --- evidence ---------------------------------------------------------------------
    seen_ids: dict[str, int] = {}
    for item in run.evidence:
        base = _short_hash(item.source.url or "", item.content, item.query or "")
        seen_ids[base] = seen_ids.get(base, 0) + 1
        node_id = f"evidence:{base}" + (f"-{seen_ids[base]}" if seen_ids[base] > 1 else "")
        producing = next((k for k in query_nodes if k[1] == item.query), None)
        it = producing[0] if producing else None
        ev_rank = (iteration_ranks.get(it, 2) + 1) if producing else 3
        source_node = source_by_key.get(_source_key(item.source))
        m.node(node_id, EVIDENCE, label=item.content[:160], rank=ev_rank,
               iteration=it if not reconstructed else None,
               group=f"evidence:{it if producing and not reconstructed else 'all'}", data={
                   "content": item.content, "query": item.query, "origin": item.origin.value,
                   "extraction": item.extraction, "relevance": item.relevance_score,
                   "fetched_at": item.fetched_at or None,
                   "source_title": item.source.title, "source_url": item.source.url,
                   "source_kind": item.source.kind, "filename": item.source.filename, "page": item.source.page,
                   "quality_tier": item.source.quality.tier if item.source.quality else None,
                   "citation": int(source_node.split(":")[1]) if source_node else None,
                   "selected_for_synthesis": source_node is not None,
               })
        if producing:
            m.edge(query_nodes[producing], node_id, RETRIEVED)
        if source_node:
            m.edge(node_id, source_node, FROM_SOURCE)
        if producing and not reconstructed:
            critic = f"critic:{producing[0]}"
            if critic in m.nodes:
                m.edge(node_id, critic, REVIEWED)
        elif "critic:0" in m.nodes:
            m.edge(node_id, "critic:0", REVIEWED)

    # --- synthesis --------------------------------------------------------------------
    synth_started = _first(events, EventType.SYNTHESIS_STARTED)
    rank = sources_rank + 1
    synthesis_happened = (run.status == RunStatus.COMPLETED) or synth_started is not None
    if synthesis_happened:
        metrics = run.metrics
        if run.status == RunStatus.COMPLETED:
            status = FALLBACK if metrics.synthesis_fallback else COMPLETED
        else:
            status = _open_status(run)
        repair = _first(events, EventType.CITATION_REPAIR_COMPLETED)
        m.node("synthesis", SYNTHESIS, label="", rank=rank, status=status,
               started_at=synth_started.timestamp if synth_started else None,
               duration_ms=metrics.synthesis_ms or _node_ms(run, "synthesizer"),
               data={
                   "template": run.template, "output_language": run.output_language,
                   "sources": len(run.selected_sources), "evidence": len(run.evidence),
                   "sources_cited": metrics.sources_cited,
                   "fallback": bool(metrics.synthesis_fallback),
                   "fallback_reason": metrics.synthesis_fallback_reason or None,
                   "citation_repair": (
                       {"succeeded": repair.payload.get("succeeded"), "cited": repair.payload.get("cited")}
                       if repair else None
                   ),
                   "repair_skipped": bool(metrics.repair_skipped),
                   "llm": (metrics.llm_stage_stats or {}).get("synthesis"),
               })
        for node_id, node in m.nodes.items():
            if node["type"] == SOURCE:
                m.edge(node_id, "synthesis", USED_IN_SYNTHESIS)
        last_critic = next((n for n in reversed(m.nodes) if n.startswith("critic:")), None)
        if last_critic:
            m.edge(last_critic, "synthesis", PROCEEDED)
        if "memory:project" in m.nodes:
            m.edge("memory:project", "synthesis", CONTEXT)
        rank += 1

    # --- report / terminal --------------------------------------------------------------
    if run.status == RunStatus.COMPLETED and run.final_report:
        claims = extract_claims(run.final_report, len(run.selected_sources))
        cited = sorted({c for claim in claims for c in claim.citations})
        body = run.final_report.split("\n## Sources", 1)[0]
        m.node("report", REPORT, label=run.title or run.query, rank=rank, status=COMPLETED,
               completed_at=run.completed_at, duration_ms=None, data={
                   "title": run.title, "citations": len(cited), "claims": len(claims),
                   "word_count": len(words(body)), "fallback": bool(run.metrics.synthesis_fallback),
               })
        m.edge("synthesis", "report", PRODUCED)
        for number in cited:
            source_id = f"source:{number}"
            if source_id in m.nodes:
                m.nodes[source_id]["data"]["claims"] = [
                    {"text": c.text, "section": c.section} for c in claims if number in c.citations
                ]
                m.edge(source_id, "report", CITED_IN)
    elif terminal:
        end = _first(events, EventType.RUN_CANCELLED if run.status == RunStatus.CANCELLED else EventType.RUN_FAILED)
        status = CANCELLED if run.status == RunStatus.CANCELLED else FAILED
        m.node("terminal", TERMINAL, label=run.status.value, rank=rank, status=status,
               completed_at=end.timestamp if end else run.completed_at, data={
                   "status": run.status.value, "error": run.error or None,
                   "message": end.message if end else None,
               })
        last = next(
            (n for n in reversed(m.nodes) if m.nodes[n]["type"] not in (SOURCE, EVIDENCE, TERMINAL)), "question",
        )
        m.edge(last, "terminal", ENDED)

    # --- branched child runs (provenance recorded on the child, read-only here)
    for child in children or []:
        if child.branch is None or child.branch.parent_run_id != run.id:
            continue
        origin = child.branch.node_id if child.branch.node_id in m.nodes else "question"
        child_status = {
            RunStatus.COMPLETED: COMPLETED, RunStatus.FAILED: FAILED,
            RunStatus.CANCELLED: CANCELLED,
        }.get(child.status, RUNNING)
        node_id = m.node(
            f"branch:{child.id}", BRANCH, label=child.title or child.query,
            rank=m.nodes[origin]["rank"] + 1, status=child_status,
            started_at=child.created_at, duration_ms=None, data={
                "run_id": child.id, "question": child.query,
                "instruction": child.branch.instruction, "status": child.status.value,
                "mode": child.mode.value, "node_type": child.branch.node_type,
            },
        )
        m.nodes[node_id]["duration_ms"] = None
        m.edge(origin, node_id, BRANCHED)

    groups = _groups(m)
    nodes = list(m.nodes.values())
    edges = list(m.edges.values())
    real_iterations = [i for i in iterations if not reconstructed]
    return {
        "run_id": run.id,
        "run_status": run.status.value,
        "question": run.query,
        "mode": run.mode.value,
        "source_scope": scope,
        "template": run.template,
        "output_language": run.output_language,
        "live": active,
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "summary": {
            "node_count": len(nodes), "edge_count": len(edges),
            "source_count": len(run.selected_sources), "evidence_count": len(run.evidence),
            "query_count": sum(1 for n in nodes if n["type"] == QUERY),
            "iterations": len(real_iterations) if real_iterations else (run.iterations or None),
            "incomplete_history": bool(limitations),
        },
        "limitations": limitations,
    }


def _open_status(run: ResearchRun) -> str:
    """A stage that started but has no completion record."""
    if run.status == RunStatus.CANCELLED:
        return CANCELLED
    if run.status == RunStatus.FAILED:
        return FAILED
    return RUNNING


def _critic_node(m: _Map, run: ResearchRun, events: list[RunEvent], it: int, rank: int,
                 reconstructed: bool, last: bool) -> str | None:
    completed = _first(events, EventType.CRITIC_COMPLETED, it) if not reconstructed else None
    started = _first(events, EventType.CRITIC_STARTED, it) if not reconstructed else None
    metrics = run.metrics
    if completed is None and started is None:
        # Without events, only the stored final critique / fallback proves a review.
        if not (reconstructed and (run.critique is not None or metrics.critic_fallback)):
            return None
    fallback = completed.payload.get("fallback") if completed else (metrics.critic_fallback if reconstructed else None)
    if completed is None and not reconstructed:
        status = _open_status(run)
    elif fallback:
        status = TIMED_OUT if "time" in str(fallback).lower() else SKIPPED
    else:
        status = COMPLETED
    data: dict[str, Any] = {
        "score": completed.payload.get("score") if completed else (
            run.critique.overall_score if (reconstructed and run.critique and not fallback) else None),
        "decision": completed.payload.get("decision") if completed else (
            run.critique.decision.value if (reconstructed and run.critique) else None),
        "fallback_reason": fallback or None,
        "message": completed.message if (completed and fallback) else None,
        "budget_decision": (metrics.budget_decisions or {}).get("critic") if last else None,
    }
    # The full structured critique is stored only for the final review.
    if last and run.critique is not None and not fallback:
        data["coverage"] = run.critique.coverage_assessment
        data["missing_information"] = list(run.critique.missing_information)
    node_id = f"critic:{it}"
    m.node(node_id, CRITIC, label="", rank=rank, status=status,
           iteration=None if reconstructed else it,
           started_at=started.timestamp if started else None,
           completed_at=completed.timestamp if completed else None,
           duration_ms=_node_ms(run, "critic", None if reconstructed else it), data=data)
    return node_id


def _groups(m: _Map) -> list[dict]:
    """Deterministic collapsible groups: members keep stored order."""
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for node in m.nodes.values():
        key = node.get("group")
        if not key:
            continue
        group = groups.setdefault(key, {
            "id": f"group:{key}", "key": key, "type": node["type"], "iteration": node.get("iteration"),
            "rank": node["rank"], "members": [],
        })
        group["members"].append(node["id"])
    return list(groups.values())
