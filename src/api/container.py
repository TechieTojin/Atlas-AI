"""Dependency container wiring Atlas services for the API (and tests)."""

from __future__ import annotations

from concurrent.futures import Executor

from src.config import AtlasConfig, load_config
from src.events import RunEventBus
from src.memory.project_memory import ProjectMemoryService
from src.memory.service import MemoryService
from src.persistence import (
    Database,
    DocumentsRepository,
    EventsRepository,
    MemoryRepository,
    RunsRepository,
)
from src.persistence.findings import FindingsRepository
from src.persistence.workspace import (
    ComparisonsRepository,
    FollowUpsRepository,
    KGRepository,
    ProjectsRepository,
)
from src.rag.embeddings import EmbedFn
from src.rag.service import DocumentService
from src.services.comparison_service import ComparisonService
from src.services.followup_service import FollowUpService
from src.services.kg_service import KGService
from src.services.overview_service import ProjectOverviewService
from src.services.project_graph import ProjectGraphService
from src.services.research_service import ResearchService


class Container:
    """Builds and holds the application's long-lived services."""

    def __init__(
        self,
        config: AtlasConfig | None = None,
        *,
        db_path: str | None = None,
        embed_fn: EmbedFn | None = None,
        llm_factory=None,
        search_factory=None,
        executor: Executor | None = None,
        page_fetcher_factory=None,
    ) -> None:
        self.config = config or load_config()
        self.db = Database(db_path or self.config.database_path)
        self.runs_repo = RunsRepository(self.db)
        self.events_repo = EventsRepository(self.db)
        self.memory_repo = MemoryRepository(self.db)
        self.documents_repo = DocumentsRepository(self.db)
        self.projects_repo = ProjectsRepository(self.db)
        self.followups_repo = FollowUpsRepository(self.db)
        self.comparisons_repo = ComparisonsRepository(self.db)
        self.kg_repo = KGRepository(self.db)
        self.findings_repo = FindingsRepository(self.db)
        self.bus = RunEventBus()
        if embed_fn is None:
            from src.rag.embeddings import create_ollama_embedder

            embed_fn = create_ollama_embedder(self.config)
        self.embed_fn = embed_fn
        self.document_service = DocumentService(
            self.config, self.documents_repo, embed_fn
        )
        self.memory_service = MemoryService(
            self.memory_repo,
            self.config.memory_ttl_hours,
            embed_query=lambda q: embed_fn([q])[0],
            semantic_threshold=self.config.memory_semantic_threshold,
        )
        # Project research memory reuses the same local embedding model as
        # document RAG, so retrieval costs one embedding call per run.
        self.project_memory = ProjectMemoryService(
            self.findings_repo,
            embed_texts=embed_fn,
            threshold=self.config.project_memory_threshold,
            max_items=self.config.project_memory_items,
        )
        self.research_service = ResearchService(
            self.config,
            self.runs_repo,
            self.events_repo,
            self.bus,
            memory=self.memory_service,
            project_memory=self.project_memory,
            documents=self.document_service,
            llm_factory=llm_factory,
            search_factory=search_factory,
            executor=executor,
            projects=self.projects_repo,
            page_fetcher_factory=page_fetcher_factory,
        )
        # Follow-ups, comparisons, and the knowledge graph share the research
        # service's worker pool, LLM factory, and search factory.
        shared_executor = self.research_service._executor
        shared_llm = self.research_service._llm_factory
        shared_search = self.research_service._search_factory
        self.followup_service = FollowUpService(
            self.config,
            self.followups_repo,
            self.runs_repo,
            self.bus,
            llm_factory=shared_llm,
            search_factory=shared_search,
            documents=self.document_service,
            executor=shared_executor,
        )
        self.comparison_service = ComparisonService(
            self.config,
            self.comparisons_repo,
            self.runs_repo,
            self.bus,
            llm_factory=shared_llm,
            executor=shared_executor,
        )
        self.overview_service = ProjectOverviewService(
            self.projects_repo, self.runs_repo, self.findings_repo, self.documents_repo
        )
        self.project_graph_service = ProjectGraphService(
            self.projects_repo, self.runs_repo, self.findings_repo
        )
        self.kg_service = KGService(
            self.config,
            self.kg_repo,
            self.runs_repo,
            self.bus,
            llm_factory=shared_llm,
            executor=shared_executor,
        )
