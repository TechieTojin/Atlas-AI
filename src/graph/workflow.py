"""LangGraph workflow wiring for Atlas.

Graph shape:

    START -> planner -> researcher -> critic
                             ^           |
                             |   (conditional)
                             +-- more ---+--- sufficient --> synthesizer -> END

V2 adds non-invasive instrumentation around the same architecture: nodes are
wrapped to emit typed progress events, record real per-node timings into
state, and honor cooperative cancellation. For human-in-the-loop runs the
service executes the planner separately and resumes a research-entry graph
(``include_planner=False``) with the approved/edited plan — a persisted
pause, not a busy wait.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from src.agents.critic import CriticAgent, route_after_critic
from src.agents.planner import PlannerAgent
from src.agents.researcher import ResearcherAgent
from src.agents.synthesizer import SynthesizerAgent
from src.cancellation import RunCancelledError  # noqa: F401  (re-exported)
from src.config import AtlasConfig
from src.events import EventType, NullEmitter
from src.graph.state import AtlasState
from src.tools.search import SearchFn, create_tavily_search

logger = logging.getLogger(__name__)




def _instrument(
    name: str,
    agent: Callable[[AtlasState], dict],
    emitter: Any,
    cancel_check: Callable[[], None] | None,
    before: Callable[[AtlasState], None] | None = None,
    after: Callable[[AtlasState, dict], None] | None = None,
) -> Callable[[AtlasState], dict]:
    """Wrap a node with cancellation, events, and real duration measurement."""

    def node(state: AtlasState) -> dict:
        if cancel_check is not None:
            cancel_check()
        if before is not None:
            before(state)
        start = time.perf_counter()
        result = agent(state)
        if cancel_check is not None:
            # A node that finishes after cancellation must not hand its
            # result to the next stage (or complete the run).
            cancel_check()
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        timing = {
            "node": name,
            "ms": elapsed_ms,
            "iteration": result.get("iteration", state.get("iteration", 0)),
        }
        result = {**result, "node_timings": [timing]}
        if after is not None:
            after(state, result)
        return result

    return node


def build_workflow(
    llm: Any,
    search_fn: SearchFn | None,
    config: AtlasConfig,
    synthesis_llm: Any | None = None,
    *,
    emitter: Any = None,
    cancel_check: Callable[[], None] | None = None,
    include_planner: bool = True,
    memory: Any = None,
    documents: Any = None,
    document_ids: list[str] | None = None,
    page_fetcher: Any = None,
    structure: str = "",
    project_id: str = "",
    critic_llm: Any | None = None,
    repair_llm: Any | None = None,
    deadline: float | None = None,
    budget: Any = None,
    memory_context: str = "",
    output_language: str = "en",
):
    """Compile the Atlas graph with injected LLM and search dependencies.

    ``synthesis_llm`` optionally gives the synthesizer its own model handle
    (e.g. reasoning disabled for speed); it defaults to ``llm``.
    ``include_planner=False`` compiles the same graph entered at the
    researcher, used to resume after human plan approval.
    """
    emitter = emitter or NullEmitter()
    graph = StateGraph(AtlasState)

    researcher = ResearcherAgent(
        search_fn,
        config.search_results_per_query,
        memory=memory,
        documents=documents,
        document_ids=document_ids,
        emitter=emitter,
        page_fetcher=page_fetcher,
        page_fetch_per_query=config.page_fetch_per_query if search_fn else 0,
        page_chunks_per_page=config.page_chunks_per_page,
        project_id=project_id,
        workers=config.retrieval_workers,
        cancel_check=cancel_check,
    )
    critic = CriticAgent(
        critic_llm if critic_llm is not None else llm,
        config.max_queries_per_iteration,
        sufficiency_threshold=config.sufficiency_threshold,
        max_evidence=config.max_evidence_for_critic,
        chars_per_evidence=config.critic_chars_per_evidence,
        deadline=deadline,
        # The critic is optional; synthesis is not. Only run the critic if
        # the remaining run budget covers both worst cases.
        min_seconds_required=(
            config.critic_timeout_seconds + config.synthesis_timeout_seconds
        ),
        skip_check=budget.critic_skip_reason if budget is not None else None,
    )
    synthesizer = SynthesizerAgent(
        synthesis_llm if synthesis_llm is not None else llm,
        max_evidence=config.max_evidence_for_synthesis,
        target_words=config.report_target_words,
        emitter=emitter,
        structure=structure,
        repair_llm=repair_llm,
        chars_per_source=config.synthesis_chars_per_source,
        context_chars=config.synthesis_context_chars,
        deadline=deadline,
        repair_min_seconds=config.repair_timeout_seconds,
        max_words=config.synthesis_max_words,
        json_mode=config.synthesis_json_mode,
        clean_evidence=config.synthesis_clean_evidence,
        repair_check=budget.repair_check if budget is not None else None,
        retry_check=budget.synthesis_retry_check if budget is not None else None,
        memory_context=memory_context,
        output_language=output_language,
    )

    def plan_created(state: AtlasState, result: dict) -> None:
        plan = result.get("plan")
        if plan is not None:
            emitter.emit(
                EventType.PLAN_CREATED,
                message=f"Plan ready: {len(plan.tasks)} subquestions, "
                        f"{len(result.get('pending_queries', []))} queries.",
                agent="planner",
                subquestions=[t.subquestion for t in plan.tasks],
                queries=list(result.get("pending_queries", [])),
            )

    def critic_completed(state: AtlasState, result: dict) -> None:
        critique = result.get("critique")
        fallback = result.get("critic_fallback")
        if critique is not None and fallback:
            # No score in the payload: a skipped critic evaluated nothing.
            emitter.emit(
                EventType.CRITIC_COMPLETED,
                message=f"Critic skipped ({fallback}); continuing to synthesis.",
                agent="critic",
                iteration=state.get("iteration", 0),
                decision=critique.decision.value,
                fallback=fallback,
            )
        elif critique is not None:
            emitter.emit(
                EventType.CRITIC_COMPLETED,
                message=f"Critic score {critique.overall_score}/10 "
                        f"({critique.decision.value}).",
                agent="critic",
                iteration=state.get("iteration", 0),
                score=critique.overall_score,
                decision=critique.decision.value,
            )

    if include_planner:
        graph.add_node(
            "planner",
            _instrument(
                "planner",
                PlannerAgent(
                    llm,
                    config.max_queries_per_iteration,
                    emitter=emitter,
                    max_tasks=config.planner_max_tasks,
                    memory_context=memory_context,
                    output_language=output_language,
                ),
                emitter,
                cancel_check,
                before=lambda s: emitter.emit(
                    EventType.PLANNING_STARTED,
                    message="Planning research...",
                    agent="planner",
                ),
                after=plan_created,
            ),
        )
    graph.add_node(
        "researcher",
        _instrument(
            "researcher",
            researcher,
            emitter,
            cancel_check,
            before=lambda s: emitter.emit(
                EventType.SEARCH_STARTED,
                message=f"Researching with {len(s.get('pending_queries', []))} queries...",
                agent="researcher",
                iteration=s.get("iteration", 0) + 1,
                queries=list(s.get("pending_queries", [])),
            ),
        ),
    )
    graph.add_node(
        "critic",
        _instrument(
            "critic",
            critic,
            emitter,
            cancel_check,
            before=lambda s: emitter.emit(
                EventType.CRITIC_STARTED,
                message="Evaluating evidence...",
                agent="critic",
                iteration=s.get("iteration", 0),
            ),
            after=critic_completed,
        ),
    )
    graph.add_node(
        "synthesizer",
        _instrument(
            "synthesizer",
            synthesizer,
            emitter,
            cancel_check,
            before=lambda s: emitter.emit(
                EventType.SYNTHESIS_STARTED,
                message="Synthesizing final report...",
                agent="synthesizer",
                iteration=s.get("iteration", 0),
            ),
        ),
    )

    def route(state: AtlasState) -> str:
        decision = route_after_critic(state)
        if decision == "researcher":
            emitter.emit(
                EventType.MORE_RESEARCH_REQUESTED,
                message="Critic requested additional research.",
                agent="critic",
                iteration=state.get("iteration", 0),
                follow_up_queries=list(state.get("pending_queries", [])),
            )
        return decision

    graph.add_edge(START, "planner" if include_planner else "researcher")
    if include_planner:
        graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "critic")
    graph.add_conditional_edges(
        "critic", route, {"researcher": "researcher", "synthesizer": "synthesizer"}
    )
    graph.add_edge("synthesizer", END)
    return graph.compile()


def initial_state(question: str, config: AtlasConfig) -> AtlasState:
    return {
        "question": question,
        "evidence": [],
        "executed_queries": [],
        "iteration": 0,
        "max_iterations": config.max_research_iterations,
        "memory_hits": 0,
        "document_chunks_retrieved": 0,
        "web_sources_new": 0,
        "node_timings": [],
        "citation_repair_ms": 0,
    }


def recursion_limit(config: AtlasConfig) -> int:
    # Sized to the worst-case loop length plus headroom.
    return 4 + 2 * config.max_research_iterations + 4


def run_atlas(
    question: str,
    config: AtlasConfig,
    llm: Any | None = None,
    search_fn: SearchFn | None = None,
    **kwargs: Any,
) -> AtlasState:
    """Run the full Atlas workflow for one research question.

    ``llm``/``search_fn`` default to the configured local Ollama model and a
    live Tavily client, but can be injected for testing. Extra keyword
    arguments are forwarded to :func:`build_workflow`.
    """
    synthesis_llm = kwargs.pop("synthesis_llm", None)
    if llm is None:
        from src.llm import create_llm

        # Reasoning on for structured planner/critic calls (reliable fields),
        # off for the long synthesis generation (speed).
        llm = create_llm(config, reasoning=config.ollama_structured_reasoning)
        synthesis_llm = create_llm(config, reasoning=False)
    if search_fn is None and kwargs.get("use_web", True):
        search_fn = create_tavily_search(config.tavily_api_key)
    kwargs.pop("use_web", None)

    app = build_workflow(llm, search_fn, config, synthesis_llm, **kwargs)
    return app.invoke(
        initial_state(question, config),
        config={"recursion_limit": recursion_limit(config)},
    )
