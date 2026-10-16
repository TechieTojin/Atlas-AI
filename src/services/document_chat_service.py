"""Document Chat: grounded conversations over SELECTED uploaded documents.

The answering contract is Website Chat's, applied to document passages:

* answers come ONLY from retrieved stored excerpts; every factual sentence
  carries a canonical ``[n]`` citation that opens the exact passage
  (document, page, verbatim text);
* uncited answers, and answers whose figures appear in no excerpt, are
  rejected (one bounded retry inside ONE deadline), then reported as
  insufficient instead of shown;
* document text is untrusted evidence inside unforgeable delimiters, never
  instructions;
* one pending answer per conversation, cancellation, persisted progress
  stages, and startup recovery;
* nothing here fetches the web, and retrieval embeds only the question.

Deterministic document relationships (shared vocabulary) are computed here
too — counting, not generation: no LLM call.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from src.agents.synthesizer import REPORT_JSON_SCHEMA, extract_valid_citations
from src.artifact_text import artifact_text
from src.config import AtlasConfig
from src.languages import language_instruction
from src.models.document_chat import (
    AnswerStage,
    DocumentChatMessage,
    DocumentCitation,
    DocumentConversation,
    MessageRole,
    MessageStatus,
)
from src.models.documents import DocumentStatus
from src.models.runs import utcnow
from src.persistence.document_chat import DocumentChatRepository
from src.prompts.document_chat import (
    DOCUMENT_CHAT_SYSTEM,
    DOCUMENT_CHAT_USER,
    DOCUMENT_HISTORY_BLOCK,
    DOCUMENT_JSON_INSTRUCTION,
    NOT_IN_DOCUMENTS,
)
from src.prompts.website import (
    WEBSITE_LENGTH_BROAD,
    WEBSITE_LENGTH_FOCUSED,
)
from src.services.website_chat_service import (
    ANSWER_TIMEOUT_MESSAGE,
    HISTORY_TURNS,
    MAX_ANSWER_ATTEMPTS,
    MAX_ANSWER_SECONDS,
    MAX_QUESTION_CHARS,
    MIN_RETRY_SECONDS,
    _ollama_timings,
    _RETRY_NOTES,
    WebsiteChatService,
)
from src.website import errors
from src.website.chunking import estimate_tokens
from src.website.context import focus_excerpt, plan_for, question_terms
from src.website.errors import WebsiteError, WebsiteNotFoundError, WebsiteStateError
from src.website.grounding import evidence_numbers, ungrounded_numbers
from src.website.retrieval import content_terms, wants_context

logger = logging.getLogger(__name__)

#: At most this many excerpts may come from ONE document when several are
#: selected (document diversity; mirrors Website Chat's page diversity).
PER_DOCUMENT_CAP = 3
#: Candidate multiplier before the diversity cap trims to the plan size.
CANDIDATE_FACTOR = 3
#: Relationship analysis: top terms kept per document / shared terms required.
TOP_TERMS = 40
MIN_SHARED_TERMS = 3

_BRACKET_NUMBER_RE = re.compile(r"\[(\d{1,4})\]")


def answer_deadline_seconds(config: AtlasConfig) -> int:
    configured = config.document_chat_timeout_seconds or MAX_ANSWER_SECONDS
    return max(1, min(configured, MAX_ANSWER_SECONDS))


class DocumentChatService:
    def __init__(
        self,
        config: AtlasConfig,
        repo: DocumentChatRepository,
        documents_repo,
        document_service,
        *,
        llm_factory,
        executor,
        languages,
    ) -> None:
        self._config = config
        self._repo = repo
        self._documents = documents_repo
        self._document_service = document_service
        self._llm_factory = llm_factory
        self._executor = executor
        self._languages = languages
        self._lock = threading.Lock()
        self._cancelled: set[str] = set()
        self._scopes: dict[str, Any] = {}

    # -- conversations ---------------------------------------------------------

    def _require_documents(self, document_ids: list[str]):
        if not document_ids:
            raise WebsiteError(errors.INVALID_PAGES, "Select at least one document.")
        docs = []
        for document_id in dict.fromkeys(document_ids):
            doc = self._documents.get(document_id)
            if doc is None:
                raise WebsiteNotFoundError("Document")
            if doc.status is not DocumentStatus.READY:
                raise WebsiteStateError(
                    errors.NOT_READY, f"Document {doc.filename} is not ready yet."
                )
            docs.append(doc)
        return docs

    def create_conversation(
        self, document_ids: list[str], output_language: str | None
    ) -> DocumentConversation:
        docs = self._require_documents(document_ids)
        language = self._languages.require(output_language or "en", "document_chat")
        conversation = DocumentConversation(
            document_ids=[d.id for d in docs],
            output_language=language,
            project_id=next((d.project_id for d in docs if d.project_id), ""),
        )
        self._repo.save_conversation(conversation)
        return conversation

    def list_conversations(self) -> list[DocumentConversation]:
        return self._repo.list_conversations()

    def get_conversation(
        self, conversation_id: str
    ) -> tuple[DocumentConversation, list[DocumentChatMessage]]:
        conversation = self._repo.get_conversation(conversation_id)
        if conversation is None:
            raise WebsiteNotFoundError("Conversation")
        return conversation, self._repo.list_messages(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        if not self._repo.delete_conversation(conversation_id):
            raise WebsiteNotFoundError("Conversation")

    def recover_interrupted(self) -> int:
        recovered = 0
        for message in self._repo.list_pending_messages():
            message.status = MessageStatus.FAILED
            message.stage = AnswerStage.QUEUED
            message.error_code = errors.INTERRUPTED
            message.error = (
                "Interrupted: the Atlas server stopped while this answer was being written."
            )
            message.completed_at = utcnow()
            self._repo.update_message(message)
            recovered += 1
        if recovered:
            logger.warning("Closed out %d interrupted Document Chat answer(s).", recovered)
        return recovered

    # -- answering ---------------------------------------------------------------

    def ask(
        self, conversation_id: str, question: str
    ) -> tuple[DocumentChatMessage, DocumentChatMessage]:
        question = (question or "").strip()
        if not question:
            raise WebsiteError(errors.EMPTY_QUESTION, "Ask a question about the documents.")
        if len(question) > MAX_QUESTION_CHARS:
            raise WebsiteError(
                errors.QUESTION_TOO_LONG,
                f"Questions are limited to {MAX_QUESTION_CHARS} characters.",
            )
        conversation, messages = self.get_conversation(conversation_id)
        self._require_documents(conversation.document_ids)
        if any(m.status is MessageStatus.PENDING for m in messages):
            raise WebsiteStateError(errors.BUSY, "Atlas is still answering the previous question.")
        language = self._languages.require(conversation.output_language, "document_chat")
        user = self._repo.add_message(
            DocumentChatMessage(
                conversation_id=conversation_id, role=MessageRole.USER, content=question,
                output_language=language,
            )
        )
        if not conversation.title:
            conversation.title = question[:120]
            conversation.updated_at = utcnow()
            self._repo.save_conversation(conversation)
        answer = self._repo.add_message(
            DocumentChatMessage(
                conversation_id=conversation_id, role=MessageRole.ASSISTANT,
                status=MessageStatus.PENDING, output_language=language,
            )
        )
        self._executor.submit(self._answer, answer.id)
        return user, answer

    def cancel_message(self, message_id: str) -> DocumentChatMessage:
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

    def _writing_config(self, language: str) -> AtlasConfig:
        import dataclasses

        model = self._languages.model_for(language)
        return (
            self._config
            if model == self._config.model
            else dataclasses.replace(self._config, model=model)
        )

    def _set_stage(self, message_id: str, stage: AnswerStage) -> None:
        message = self._repo.get_message(message_id)
        if message is not None and message.status is MessageStatus.PENDING and message.stage is not stage:
            message.stage = stage
            self._repo.update_message(message)

    def _check_cancel(self, message_id: str) -> None:
        from src.cancellation import RunCancelledError

        if message_id in self._cancelled:
            raise RunCancelledError("The answer was cancelled.")

    def _history(self, messages: list[DocumentChatMessage], current_seq: int) -> tuple[str, str]:
        """Earlier user QUESTIONS only (answers are never replayed as context)."""
        questions = [
            m.content for m in messages if m.role is MessageRole.USER and m.seq < current_seq - 1
        ]
        recent = questions[-HISTORY_TURNS:]
        previous = questions[-1] if questions else ""
        block = (
            DOCUMENT_HISTORY_BLOCK.format(turns="\n".join(f"- {q}" for q in recent))
            if recent
            else ""
        )
        return block, previous

    def _retrieve(self, conversation: DocumentConversation, question: str, previous: str):
        """Cross-document retrieval with per-document diversity, deterministic."""
        query = question
        if previous and wants_context(question):
            query = f"{previous} {question}"
        plan = plan_for(question)
        candidates = self._document_service.retrieve(
            query, conversation.document_ids, top_k=plan.passages * CANDIDATE_FACTOR
        )
        chosen, per_doc, seen = [], {}, set()
        overflow = []
        for item in candidates:
            key = (item.source.document_id, item.source.page, item.content)
            if key in seen:
                continue
            seen.add(key)
            doc_id = item.source.document_id or ""
            if len(conversation.document_ids) > 1 and per_doc.get(doc_id, 0) >= PER_DOCUMENT_CAP:
                overflow.append(item)
                continue
            per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
            chosen.append(item)
            if len(chosen) == plan.passages:
                break
        for item in overflow:
            if len(chosen) >= plan.passages:
                break
            chosen.append(item)
        return plan, query, chosen

    @staticmethod
    def _excerpts(items, texts: list[str]) -> str:
        blocks = []
        for number, (item, text) in enumerate(zip(items, texts), 1):
            # Same trust delimiters as Website Chat: the document cannot forge
            # them, and its own bracketed numbers never read as citations.
            body = text.replace("<<<", "‹‹‹").replace(">>>", "›››")
            body = _BRACKET_NUMBER_RE.sub(r"(ref. \1)", body)
            label = item.source.filename or "document"
            page = f" page: {item.source.page}" if item.source.page else ""
            blocks.append(
                f"<<<EXCERPT [{number}] document: {label}{page}>>>\n{body}\n<<<END EXCERPT [{number}]>>>"
            )
        return "\n\n".join(blocks)

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
        budget = answer_deadline_seconds(self._config)
        deadline_at = awake_clock() + budget
        metrics: dict[str, Any] = {"deadline_s": budget}
        try:
            conversation, messages = self.get_conversation(message.conversation_id)
            question = next(
                m.content
                for m in reversed(messages)
                if m.role is MessageRole.USER and m.seq < message.seq
            )
            history, previous = self._history(messages, message.seq)
            self._set_stage(message_id, AnswerStage.RETRIEVING)
            t = time.perf_counter()
            plan, query, items = self._retrieve(conversation, question, previous)
            metrics.update(
                retrieval_ms=int((time.perf_counter() - t) * 1000),
                queries=[query],
                plan=plan.as_metrics(),
                passages=len(items),
                documents=len(conversation.document_ids),
            )
            self._check_cancel(message_id)
            terms = question_terms(question, previous)
            texts = [focus_excerpt(i.content, terms, plan.excerpt_tokens) for i in items]
            citations = [
                DocumentCitation(
                    index=n,
                    document_id=i.source.document_id or "",
                    filename=i.source.filename or "",
                    page=i.source.page,
                    text=i.content,
                    score=round(i.relevance_score or 0.0, 4),
                )
                for n, i in enumerate(items, 1)
            ]
            language = conversation.output_language
            config = self._writing_config(language)
            import dataclasses

            config = dataclasses.replace(
                config,
                document_chat_max_tokens=min(plan.max_tokens, config.document_chat_max_tokens),
            )
            metrics["model"] = config.model
            llm = AbortableLLM(
                lambda: make_llm(self._llm_factory, config, reasoning=False, stage="document_chat"),
                timeout=None,
                run_deadline=lambda: deadline_at,
                scope=scope,
                label="document chat",
            )
            names = ", ".join(
                dict.fromkeys(c.filename for c in citations if c.filename)
            ) or "uploaded documents"
            system = DOCUMENT_CHAT_SYSTEM + language_instruction(language)
            user = DOCUMENT_CHAT_USER.format(
                documents=names,
                excerpts=self._excerpts(items, texts),
                history=history,
                question=question,
                length=WEBSITE_LENGTH_BROAD if plan.broad else WEBSITE_LENGTH_FOCUSED,
            ) + DOCUMENT_JSON_INSTRUCTION
            metrics.update(
                prompt_chars=len(system) + len(user),
                excerpt_tokens=sum(estimate_tokens(t_) for t_ in texts),
            )
            evidence = evidence_numbers(
                question, *(f"{c.filename}\n{text}" for c, text in zip(citations, texts))
            )
            body, cited, insufficient, attempts = "", set(), not items, 0
            rejected: list[str] = []
            calls: list[dict[str, Any]] = []
            metrics.update(calls=calls, rejected=rejected)
            note = ""
            while items and attempts < MAX_ANSWER_ATTEMPTS:
                if attempts and deadline_at - awake_clock() < MIN_RETRY_SECONDS:
                    raise WebsiteError(errors.ANSWER_TIMEOUT, ANSWER_TIMEOUT_MESSAGE)
                attempts += 1
                self._check_cancel(message_id)
                self._set_stage(message_id, AnswerStage.GENERATING)
                t = time.perf_counter()
                response = llm.invoke(
                    [("system", system), ("user", user + note)], format=REPORT_JSON_SCHEMA
                )
                calls.append(_ollama_timings(response, int((time.perf_counter() - t) * 1000)))
                self._set_stage(message_id, AnswerStage.VALIDATING)
                verdict, text, cited = WebsiteChatService._judge(
                    str(getattr(response, "content", response)),
                    len(items),
                    evidence,
                    sentinel=NOT_IN_DOCUMENTS,
                )
                if verdict == "insufficient":
                    insufficient = True
                    break
                if verdict == "ok":
                    body, insufficient = text, False
                    break
                rejected.append(verdict)
                note = _RETRY_NOTES[verdict]
                body = ""
                if verdict != "notation":
                    insufficient = True
            metrics.update(llm_ms=sum(c["wall_ms"] for c in calls), attempts=attempts)
            if not body and not insufficient:
                raise WebsiteError(
                    errors.UNUSABLE_ANSWER,
                    "The model's answer could not be used (corrupted formatting).",
                )
            message = self._repo.get_message(message_id) or message
            if insufficient:
                message.content = artifact_text(language, "documents.insufficient")
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
                "Document answer %s (%s, %s): retrieval %s ms, LLM %s ms, %d attempt(s), cited %s%s.",
                message_id, language, config.model, metrics.get("retrieval_ms"),
                metrics["llm_ms"], attempts, message.cited,
                ", insufficient evidence" if insufficient else "",
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
                    logger.exception("Document answer %s failed.", message_id)
                    code, text = (
                        errors.LLM_FAILED,
                        "The local model could not answer. Check that Ollama is running.",
                    )
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

    # -- deterministic relationships ------------------------------------------------

    def relationships(self, document_ids: list[str]) -> dict:
        """Shared-vocabulary links between the selected documents.

        Pure counting over stored chunks (no LLM, no embeddings): each
        document's most frequent content terms, and SHARES_CONCEPT links where
        two documents have enough overlap. Honest semantics only — no
        "agrees"/"contradicts" claims.
        """
        docs = self._require_documents(document_ids)
        profiles = []
        for doc in docs:
            counts: dict[str, int] = {}
            for chunk in self._documents.chunks(doc.id):
                for term in content_terms(chunk.content):
                    counts[term] = counts.get(term, 0) + 1
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TERMS]
            profiles.append((doc, dict(top)))
        links = []
        for a in range(len(profiles)):
            for b in range(a + 1, len(profiles)):
                doc_a, terms_a = profiles[a]
                doc_b, terms_b = profiles[b]
                shared = sorted(
                    set(terms_a) & set(terms_b),
                    key=lambda t: (-(terms_a[t] + terms_b[t]), t),
                )
                if len(shared) >= MIN_SHARED_TERMS:
                    links.append(
                        {
                            "a": doc_a.id,
                            "b": doc_b.id,
                            "type": "SHARES_CONCEPT",
                            "terms": shared[:8],
                            "strength": len(shared),
                        }
                    )
        return {
            "documents": [
                {
                    "id": doc.id,
                    "filename": doc.filename,
                    "top_terms": list(terms)[:10],
                }
                for doc, terms in profiles
            ],
            "links": links,
            "method": "deterministic",
        }
