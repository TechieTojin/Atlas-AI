"""Evidence-grounded knowledge graph extraction.

The LLM proposes entities/relations with supporting evidence numbers via
structured output; Atlas then deterministically validates every proposal:
relations must reference real evidence numbers (which map to real collected
sources), unknown entities/types are coerced or discarded, entity names are
normalized for deduplication, and hard node/edge limits apply. Nothing
unsupported is ever persisted, and URLs come only from collected sources.

Generation runs on demand (or post-run) as a bounded background step; it
never blocks report completion.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from src.config import AtlasConfig
from src.events import EventType, RunEmitter, RunEventBus
from src.models.runs import RunStatus
from src.models.workspace import (
    KG_EDGE_TYPES,
    KG_NODE_TYPES,
    KGEdge,
    KGNode,
    KGSupport,
    KnowledgeGraph,
)
from src.persistence.workspace import KGRepository
from src.prompts.research import KG_SYSTEM, KG_USER
from src.tools.selection import select_evidence

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_ITEMS = 8
_MAX_CHARS_PER_EVIDENCE = 400


class KGError(Exception):
    pass


class ProposedEntity(BaseModel):
    name: str
    type: str = "concept"
    description: str = ""


class ProposedRelation(BaseModel):
    source: str
    target: str
    relation: str = "associated_with"
    evidence_numbers: list[int] = Field(default_factory=list)


class KGExtraction(BaseModel):
    entities: list[ProposedEntity] = Field(default_factory=list)
    relations: list[ProposedRelation] = Field(default_factory=list)


def normalize_entity_name(name: str) -> str:
    return " ".join(name.lower().split())


def validate_extraction(
    extraction: KGExtraction,
    run_id: str,
    numbered_sources: list,
    max_nodes: int,
    max_edges: int,
) -> tuple[list[KGNode], list[KGEdge]]:
    """Deterministic validation of LLM proposals against real evidence.

    Returns persistable nodes/edges; everything unsupported is discarded.
    """
    nodes_by_norm: dict[str, KGNode] = {}
    for entity in extraction.entities:
        name = entity.name.strip()
        norm = normalize_entity_name(name)
        if not norm or len(norm) > 120:
            continue
        if norm in nodes_by_norm:
            continue
        node_type = entity.type.strip().lower()
        if node_type not in KG_NODE_TYPES:
            node_type = "concept"
        nodes_by_norm[norm] = KGNode(
            run_id=run_id,
            name=name,
            norm_name=norm,
            type=node_type,
            description=entity.description.strip()[:300],
        )
        if len(nodes_by_norm) >= max_nodes:
            break

    edges: list[KGEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    valid_numbers = range(1, len(numbered_sources) + 1)
    for relation in extraction.relations:
        source_node = nodes_by_norm.get(normalize_entity_name(relation.source))
        target_node = nodes_by_norm.get(normalize_entity_name(relation.target))
        if source_node is None or target_node is None:
            continue  # relation references an unknown entity
        if source_node.id == target_node.id:
            continue
        numbers = sorted(
            {n for n in relation.evidence_numbers if n in valid_numbers}
        )
        if not numbers:
            continue  # no REAL supporting evidence -> discarded
        rel_type = relation.relation.strip().lower()
        if rel_type not in KG_EDGE_TYPES:
            rel_type = "associated_with"
        key = (source_node.id, target_node.id, rel_type)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        support = [
            KGSupport(
                source_url=numbered_sources[n - 1].url,
                source_title=numbered_sources[n - 1].title,
            )
            for n in numbers
        ]
        edges.append(
            KGEdge(
                run_id=run_id,
                source_node_id=source_node.id,
                target_node_id=target_node.id,
                relation=rel_type,
                support=support,
            )
        )
        if len(edges) >= max_edges:
            break

    # Drop orphan nodes that ended up in no relation only if over limits;
    # otherwise keep them (standalone entities are still useful).
    return list(nodes_by_norm.values()), edges


class KGService:
    def __init__(
        self,
        config: AtlasConfig,
        repo: KGRepository,
        runs_repo,
        bus: RunEventBus,
        llm_factory,
        executor,
    ) -> None:
        self._config = config
        self._repo = repo
        self._runs = runs_repo
        self._bus = bus
        self._llm_factory = llm_factory
        self._executor = executor

    def get(self, run_id: str) -> KnowledgeGraph:
        return self._repo.get_graph(run_id)

    def get_for_project(self, run_ids: list[str]) -> KnowledgeGraph:
        """Deterministically merge per-run graphs (nodes by name+type)."""
        merged_nodes: dict[tuple[str, str], KGNode] = {}
        node_remap: dict[str, str] = {}
        edges: dict[tuple[str, str, str], KGEdge] = {}
        for run_id in run_ids:
            graph = self._repo.get_graph(run_id)
            for node in graph.nodes:
                key = (node.norm_name, node.type)
                if key not in merged_nodes:
                    merged_nodes[key] = node
                node_remap[node.id] = merged_nodes[key].id
            for edge in graph.edges:
                src = node_remap.get(edge.source_node_id)
                dst = node_remap.get(edge.target_node_id)
                if not src or not dst:
                    continue
                ekey = (src, dst, edge.relation)
                if ekey in edges:
                    existing_urls = {s.source_url for s in edges[ekey].support}
                    edges[ekey].support.extend(
                        s for s in edge.support if s.source_url not in existing_urls
                    )
                else:
                    edges[ekey] = edge.model_copy(
                        update={"source_node_id": src, "target_node_id": dst}
                    )
        status = "READY" if merged_nodes else "NONE"
        return KnowledgeGraph(
            nodes=list(merged_nodes.values()), edges=list(edges.values()),
            status=status,
        )

    def generate(self, run_id: str) -> None:
        """Start bounded on-demand graph generation for a completed run."""
        run = self._runs.get(run_id)
        if run is None:
            raise KGError("Run not found.")
        if run.status is not RunStatus.COMPLETED or not run.evidence:
            raise KGError("Knowledge graphs require a completed run with evidence.")
        current = self._repo.get_graph(run_id)
        if current.status == "RUNNING":
            raise KGError("Knowledge graph generation is already running.")
        self._repo.set_status(run_id, "RUNNING")
        self._executor.submit(self._execute, run_id)

    def _execute(self, run_id: str) -> None:
        emitter = RunEmitter(self._bus, f"kg-{run_id}")
        start = time.perf_counter()
        try:
            emitter.emit(
                EventType.KNOWLEDGE_GRAPH_STARTED,
                message="Extracting knowledge graph from evidence...",
            )
            run = self._runs.get(run_id)
            selected = select_evidence(run.evidence, _MAX_EVIDENCE_ITEMS)
            from src.agents.synthesizer import build_numbered_sources

            sources = run.selected_sources or build_numbered_sources(selected)
            index = {s.normalized_url: i for i, s in enumerate(sources, 1)}
            blocks = []
            seen_numbers = set()
            for item in selected:
                n = index.get(item.source.normalized_url)
                if n is None or n in seen_numbers:
                    continue
                seen_numbers.add(n)
                blocks.append(
                    f"[{n}] {item.source.title}\n"
                    f"{item.content[:_MAX_CHARS_PER_EVIDENCE]}"
                )

            # Reasoning stays OFF here: on local Qwen, thinking combined with
            # this nested JSON schema is pathologically slow (observed >30min
            # per call), while constrained decoding without thinking is fast.
            # Deterministic validation below catches weak proposals safely.
            llm = self._llm_factory(self._config, reasoning=False)
            extraction: KGExtraction = llm.with_structured_output(KGExtraction).invoke(
                [
                    (
                        "system",
                        KG_SYSTEM.format(
                            node_types=", ".join(KG_NODE_TYPES),
                            edge_types=", ".join(KG_EDGE_TYPES),
                        ),
                    ),
                    (
                        "user",
                        KG_USER.format(
                            question=run.query,
                            evidence="\n\n".join(blocks),
                            max_nodes=self._config.kg_max_nodes,
                            max_edges=self._config.kg_max_edges,
                        ),
                    ),
                ]
            )
            nodes, edges = validate_extraction(
                extraction,
                run_id,
                sources,
                self._config.kg_max_nodes,
                self._config.kg_max_edges,
            )
            self._repo.save_graph(run_id, nodes, edges)
            self._repo.set_status(run_id, "READY")
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Knowledge graph for run %s: %d nodes, %d edges (%d ms).",
                run_id, len(nodes), len(edges), elapsed_ms,
            )
            emitter.emit(
                EventType.KNOWLEDGE_GRAPH_COMPLETED,
                message=f"Knowledge graph ready: {len(nodes)} entities, "
                        f"{len(edges)} relations.",
                nodes=len(nodes),
                edges=len(edges),
                duration_ms=elapsed_ms,
            )
        except Exception as exc:
            logger.exception("Knowledge graph for run %s failed.", run_id)
            self._repo.set_status(run_id, "FAILED", f"{type(exc).__name__}: {exc}")
            emitter.emit(
                EventType.KNOWLEDGE_GRAPH_FAILED,
                message="Knowledge graph generation failed.",
            )
