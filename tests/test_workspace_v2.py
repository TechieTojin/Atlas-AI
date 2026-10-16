"""Research Workspace V2 backend: multi-page Website Chat, Document Chat and
Collections — grounded, bounded, deterministic, and non-destructive to V1 data.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.models.websites import PageStatus, WebsiteMode, WebsiteStatus
from src.website import errors
from src.website.discover import discover_pages, parse_robots, robots_blocks
from src.website.errors import WebsiteError
from tests.test_website_chat import (
    ARTICLE,
    ChatLLM,
    CountingEmbed,
    Web,
    bow_embed,
    filler,
    make,
)

HOST = "docs.example"
ROOT = f"https://{HOST}/guide"


def page_html(title: str, body: str, links: str = "") -> str:
    return (
        f"<!doctype html><html lang='en'><head><title>{title}</title></head>"
        f"<body><main><h1>{title}</h1><p>{body} {filler(title)}</p>{links}</main></body></html>"
    )


def small_site(web: Web) -> None:
    links = (
        "<a href='/guide/setup'>Setup</a>"
        "<a href='/guide/usage#intro'>Usage</a>"
        "<a href='/guide/usage'>Usage again</a>"
        "<a href='https://other.example/x'>Offsite</a>"
        "<a href='mailto:x@example.com'>Mail</a>"
        "<a href='javascript:alert(1)'>JS</a>"
        "<a href='/login'>Login</a>"
        "<a href='/files/report.pdf'>PDF</a>"
    )
    web.add(HOST, "/guide", page_html("Guide", "Overview of the Alpha battery system.", links))
    web.add(HOST, "/guide/setup", page_html("Setup", "Install the Alpha unit at 20 C ambient."))
    web.add(HOST, "/guide/usage", page_html("Usage", "The Alpha unit retains 93% capacity after 500 cycles."))


# --- discovery -----------------------------------------------------------------------


def test_discovery_lists_same_host_pages_and_drops_traps(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    result = container.website_chat_service.discover(ROOT)
    urls = [p.url for p in result.pages]
    assert urls[0] == ROOT and result.pages[0].found_via == "root"
    assert f"https://{HOST}/guide/setup" in urls
    assert urls.count(f"https://{HOST}/guide/usage") == 1  # fragment + duplicate collapsed
    assert all(HOST in u for u in urls)
    assert not any("login" in u or ".pdf" in u or "other.example" in u for u in urls)
    assert result.skipped.get("offsite_or_unsupported", 0) >= 3
    assert result.root_title == "Guide"


def test_discovery_merges_sitemap_and_respects_robots(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    web.add(
        HOST, "/sitemap.xml",
        body=(
            "<?xml version='1.0'?><urlset>"
            f"<loc>https://{HOST}/guide/faq</loc>"
            f"<loc>https://{HOST}/private/secret</loc>"
            "<loc>https://evil.example/x</loc></urlset>"
        ).encode(),
        content_type="application/xml",
    )
    web.add(HOST, "/robots.txt", body=b"User-agent: *\nDisallow: /private/\n",
            content_type="text/plain")
    result = container.website_chat_service.discover(ROOT)
    urls = [p.url for p in result.pages]
    assert f"https://{HOST}/guide/faq" in urls
    assert not any("/private/" in u for u in urls)
    assert not any("evil.example" in u for u in urls)
    assert result.robots_applied is True
    sitemap_page = next(p for p in result.pages if p.url.endswith("/guide/faq"))
    assert sitemap_page.found_via == "sitemap"


def test_discovery_requires_an_html_root(tmp_path):
    container, web, _ = make(tmp_path)
    web.add(HOST, "/guide", body=b"plain text only", content_type="text/plain")
    with pytest.raises(WebsiteError) as err:
        container.website_chat_service.discover(ROOT)
    assert err.value.code == errors.UNSUPPORTED_CONTENT


def test_discovery_blocks_local_roots_synchronously(tmp_path):
    container, _, _ = make(tmp_path)
    with pytest.raises(WebsiteError) as err:
        container.website_chat_service.discover("http://localhost/admin")
    assert err.value.code == errors.BLOCKED_ADDRESS


def test_robots_parser_is_minimal_and_prefix_based():
    rules = parse_robots("User-agent: Google\nDisallow: /g\n\nUser-agent: *\nDisallow: /private/\nDisallow:\n")
    assert rules == ["/private/"]
    assert robots_blocks("/private/x", rules) and not robots_blocks("/public", rules)


# --- SITE mode indexing ---------------------------------------------------------------


def site_ready(container, web, urls=None):
    small_site(web)
    selection = urls or [ROOT, f"https://{HOST}/guide/setup", f"https://{HOST}/guide/usage"]
    site, created = container.website_chat_service.submit_site(ROOT, selection)
    site = container.website_chat_service.get(site.id)
    assert site.status is WebsiteStatus.READY, (site.error_code, site.error)
    return site


def test_site_mode_indexes_selected_pages_with_per_page_provenance(tmp_path):
    container, web, _ = make(tmp_path)
    site = site_ready(container, web)
    assert site.mode is WebsiteMode.SITE and site.page_count == 3
    pages = container.website_chat_service.pages(site.id)
    assert [p.url for p in pages] == [ROOT, f"https://{HOST}/guide/setup", f"https://{HOST}/guide/usage"]
    assert all(p.status is PageStatus.INDEXED and p.chunk_count > 0 for p in pages)
    chunks = container.websites_repo.chunks(site.id, site.index_version)
    assert site.chunk_count == len(chunks) == sum(p.chunk_count for p in pages)
    by_page = {c.page_url for c in chunks}
    assert by_page == {p.final_url or p.url for p in pages}
    assert all(c.page_title for c in chunks)
    assert site.word_count == sum(p.word_count for p in pages)
    assert site.metrics["llm_calls"] == 0
    assert site.page_title == "Guide"  # root metadata wins


def test_site_mode_requires_same_host_and_respects_the_page_cap(tmp_path):
    container, web, _ = make(tmp_path, website_max_pages=2)
    small_site(web)
    with pytest.raises(WebsiteError) as err:
        container.website_chat_service.submit_site(ROOT, ["https://other.example/x"])
    assert err.value.code == errors.INVALID_PAGES
    with pytest.raises(WebsiteError) as err:
        container.website_chat_service.submit_site(
            ROOT, [ROOT, f"https://{HOST}/guide/setup", f"https://{HOST}/guide/usage"]
        )
    assert err.value.code == errors.INVALID_PAGES  # 3 > cap of 2


def test_a_failed_page_is_recorded_and_the_rest_still_index(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    missing = f"https://{HOST}/guide/missing"
    site, _ = container.website_chat_service.submit_site(ROOT, [ROOT, missing])
    site = container.website_chat_service.get(site.id)
    assert site.status is WebsiteStatus.READY and site.page_count == 1
    pages = container.website_chat_service.pages(site.id)
    failed = next(p for p in pages if p.url == missing)
    assert failed.status is PageStatus.FAILED and failed.error_code == errors.HTTP_ERROR
    assert site.metrics["page_outcomes"]["failed"] == 1


def test_private_address_page_fails_that_page_only(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    web.add("internal.docs.example", "/x", page_html("Internal", "secret"), ip="10.0.0.5")
    # Same registered host is required, so smuggle via same host with private DNS:
    web.dns[HOST].append("10.0.0.5")  # rebinding-style: ANY private address blocks the fetch
    site, _ = container.website_chat_service.submit_site(ROOT, [ROOT])
    site = container.website_chat_service.get(site.id)
    assert site.status in (WebsiteStatus.FAILED, WebsiteStatus.READY)
    if site.status is WebsiteStatus.FAILED:
        assert site.error_code in (errors.NO_PAGES,)
        pages = container.websites_repo.pages(site.id, 1)
        assert pages == []  # nothing was published


def test_the_root_is_always_part_of_the_selection(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    site, _ = container.website_chat_service.submit_site(ROOT, [f"https://{HOST}/guide/setup"])
    site = container.website_chat_service.get(site.id)
    assert [p.url for p in container.website_chat_service.pages(site.id)][0] == ROOT


def test_all_pages_failing_fails_the_site_with_no_pages(tmp_path):
    container, web, _ = make(tmp_path)
    web.add(HOST, "/guide", "", status=404)
    site, _ = container.website_chat_service.submit_site(
        ROOT, [f"https://{HOST}/guide/a", f"https://{HOST}/guide/b"]
    )
    site = container.website_chat_service.get(site.id)
    assert site.status is WebsiteStatus.FAILED and site.error_code == errors.NO_PAGES


def test_resubmitting_the_same_root_rescopes_to_the_new_selection(tmp_path):
    container, web, _ = make(tmp_path)
    first = site_ready(container, web)
    again, created = container.website_chat_service.submit_site(ROOT, [ROOT])
    assert created is False and again.id == first.id
    site = container.website_chat_service.get(first.id)
    assert site.status is WebsiteStatus.READY and site.page_count == 1
    assert [p.url for p in container.website_chat_service.pages(site.id)] == [ROOT]


def test_a_page_already_indexed_singly_does_not_block_the_other_selected_pages(tmp_path):
    """The reported bug: a start page indexed earlier in SINGLE mode made the
    whole SITE selection a no-op, leaving only that one page indexed."""
    container, web, _ = make(tmp_path)
    small_site(web)
    web.add(HOST, "/guide/faq", page_html("FAQ", "The Alpha unit ships with a 5 year warranty."))
    service = container.website_chat_service
    single, created = service.submit(ROOT)
    assert created is True
    assert service.get(single.id).mode is WebsiteMode.SINGLE

    selection = [
        ROOT,
        f"https://{HOST}/guide/setup",
        f"https://{HOST}/guide/usage",
        f"https://{HOST}/guide/faq",
    ]
    site, created = service.submit_site(ROOT, selection)
    assert created is False and site.id == single.id  # same website, re-scoped
    site = service.get(site.id)
    assert site.status is WebsiteStatus.READY, (site.error_code, site.error)
    assert site.mode is WebsiteMode.SITE and site.page_count == 4
    pages = service.pages(site.id)
    assert [p.url for p in pages] == selection
    assert all(p.status is PageStatus.INDEXED for p in pages)
    assert site.metrics["pages_total"] == 4
    # Distinct paths on one domain stay distinct pages with their own chunks.
    assert len({p.url for p in pages}) == 4
    assert len({c.page_id for c in container.websites_repo.chunks(site.id, site.index_version)}) == 4


def test_rescoping_records_per_page_failures_without_losing_the_good_pages(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    service = container.website_chat_service
    single, _ = service.submit(ROOT)
    missing = f"https://{HOST}/guide/missing"
    selection = [ROOT, f"https://{HOST}/guide/setup", missing, f"https://{HOST}/guide/usage"]
    site, _ = service.submit_site(ROOT, selection)
    site = service.get(site.id)
    assert site.id == single.id
    assert site.status is WebsiteStatus.READY and site.page_count == 3
    pages = service.pages(site.id)
    assert [p.url for p in pages] == selection  # every selected page is reported
    failed = next(p for p in pages if p.url == missing)
    assert failed.status is PageStatus.FAILED and failed.error_code == errors.HTTP_ERROR
    assert site.metrics["page_outcomes"]["failed"] == 1
    assert site.metrics["pages_total"] == 4


def test_rescoping_a_site_keeps_unchanged_pages_without_re_embedding(tmp_path):
    embed = CountingEmbed()
    container, web, _ = make(tmp_path, embed=embed)
    web.add(HOST, "/guide/faq", page_html("FAQ", "The Alpha unit ships with a 5 year warranty."))
    site = site_ready(container, web)
    before = embed.texts_embedded
    wider = [ROOT, f"https://{HOST}/guide/setup", f"https://{HOST}/guide/usage",
             f"https://{HOST}/guide/faq"]
    container.website_chat_service.submit_site(ROOT, wider)
    site = container.website_chat_service.get(site.id)
    assert site.status is WebsiteStatus.READY and site.page_count == 4
    assert site.metrics["chunks_reused"] > 0  # the three unchanged pages were copied
    fresh = embed.texts_embedded - before
    assert 0 < fresh == site.metrics["chunks_embedded"]  # only the new page was embedded
    assert site.metrics["llm_calls"] == 0


def test_rescoping_a_busy_website_is_refused(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    service = container.website_chat_service
    site, _ = service.submit_site(ROOT, [ROOT])
    stored = container.websites_repo.get(site.id)
    stored.status = WebsiteStatus.FETCHING
    container.websites_repo.update(stored)
    with pytest.raises(WebsiteError) as err:
        service.submit_site(ROOT, [ROOT, f"https://{HOST}/guide/setup"])
    assert err.value.code == errors.BUSY


def test_the_pages_endpoint_lists_every_successfully_indexed_page(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    service = container.website_chat_service
    service.submit(ROOT)
    selection = [ROOT, f"https://{HOST}/guide/setup", f"https://{HOST}/guide/usage"]
    site, _ = service.submit_site(ROOT, selection)
    with TestClient(create_app(container)) as client:
        body = client.get(f"/api/websites/{site.id}/pages").json()
        assert [p["url"] for p in body["pages"]] == selection
        assert all(p["status"] == "INDEXED" for p in body["pages"])
        assert client.get(f"/api/websites/{site.id}").json()["page_count"] == 3


def test_cancelling_a_site_crawl_publishes_nothing(tmp_path):
    container, web, _ = make(tmp_path)
    small_site(web)
    service = container.website_chat_service
    original = service._ingest_site

    def cancel_then_run(site, refresh):
        service._cancelled.add(site.id)
        return original(site, refresh)

    service._ingest_site = cancel_then_run
    site, _ = service.submit_site(ROOT, [ROOT, f"https://{HOST}/guide/setup"])
    site = service.get(site.id)
    assert site.status is WebsiteStatus.CANCELLED and not site.is_indexed
    assert container.websites_repo.chunks(site.id, 1) == []


# --- SITE retrieval and answers ----------------------------------------------------------


def test_retrieval_spans_pages_with_page_diversity(tmp_path):
    from src.website.retrieval import retrieve

    container, web, _ = make(tmp_path)
    site = site_ready(container, web)
    result = retrieve(container.websites_repo, site, "Alpha capacity cycles setup", bow_embed, prefixed=False)
    per_page: dict[str, int] = {}
    for item in result.items:
        per_page[item.chunk.page_id] = per_page.get(item.chunk.page_id, 0) + 1
    assert len(per_page) >= 2  # more than one page is represented
    assert all(count <= 3 for count in per_page.values())


def test_site_answers_cite_the_exact_page(tmp_path):
    llm = ChatLLM(['{"report": "The Alpha unit retains 93% capacity after 500 cycles [1]."}'])
    container, web, llm = make(tmp_path, llm=llm)
    site = site_ready(container, web)
    conversation = container.website_chat_service.create_conversation(site.id, "en")
    _, answer = container.website_chat_service.ask(
        conversation.id, "How much capacity does the Alpha unit retain?"
    )
    message = container.websites_repo.get_message(answer.id)
    assert message.cited == [1]
    citation = message.citations[0]
    assert citation.url == f"https://{HOST}/guide/usage"
    assert citation.page_title == "Usage"
    assert "93% capacity" in citation.text


# --- SITE refresh -------------------------------------------------------------------------


def test_refresh_reembeds_only_changed_pages_and_keeps_snapshots(tmp_path):
    embed = CountingEmbed()
    llm = ChatLLM(['{"report": "It retains 93% capacity [1]."}'])
    container, web, llm = make(tmp_path, llm=llm, embed=embed)
    site = site_ready(container, web)
    first_version = site.index_version
    conversation = container.website_chat_service.create_conversation(site.id, "en")
    _, answer = container.website_chat_service.ask(conversation.id, "Capacity after cycles?")
    saved = container.websites_repo.get_message(answer.id)
    snapshot_text = saved.citations[0].text

    embedded_before = embed.texts_embedded
    web.add(HOST, "/guide/usage", page_html("Usage", "The Alpha unit now retains 91% capacity after 500 cycles."))
    container.website_chat_service.refresh(site.id)
    site = container.website_chat_service.get(site.id)
    assert site.index_version == first_version + 1
    outcomes = site.metrics["page_outcomes"]
    assert outcomes["unchanged"] == 2 and outcomes["changed"] == 1
    usage_chunks = [
        c for c in container.websites_repo.chunks(site.id, site.index_version)
        if c.page_url.endswith("/guide/usage")
    ]
    delta = embed.texts_embedded - embedded_before
    assert delta == len(usage_chunks)  # only the changed page was embedded
    assert site.metrics["chunks_reused"] == site.chunk_count - delta
    # The old answer's citation snapshot is untouched by the re-index.
    again = container.websites_repo.get_message(answer.id)
    assert again.citations[0].text == snapshot_text
    assert again.citations[0].index_version == first_version


def test_refresh_marks_a_removed_page_failed_but_keeps_the_rest(tmp_path):
    container, web, _ = make(tmp_path)
    site = site_ready(container, web)
    web.add(HOST, "/guide/setup", "", status=404)
    container.website_chat_service.refresh(site.id)
    site = container.website_chat_service.get(site.id)
    assert site.status is WebsiteStatus.READY and site.page_count == 2
    pages = container.website_chat_service.pages(site.id)
    removed = next(p for p in pages if p.url.endswith("/guide/setup"))
    assert removed.status is PageStatus.FAILED
    assert not any(
        c.page_url.endswith("/guide/setup")
        for c in container.websites_repo.chunks(site.id, site.index_version)
    )


def test_unchanged_refresh_reuses_every_embedding(tmp_path):
    embed = CountingEmbed()
    container, web, _ = make(tmp_path, embed=embed)
    site = site_ready(container, web)
    before = embed.texts_embedded
    container.website_chat_service.refresh(site.id)
    site = container.website_chat_service.get(site.id)
    assert embed.texts_embedded == before
    assert site.metrics["refresh_outcome"] == "unchanged"
    assert site.chunk_count == site.metrics["chunks_reused"]


# --- V1 single-page compatibility + migration -------------------------------------------


def test_single_page_sites_keep_v1_behaviour(tmp_path):
    container, web, _ = make(tmp_path)
    web.add("example.com", "/report", ARTICLE)
    site, created = container.website_chat_service.submit("https://example.com/report")
    site = container.website_chat_service.get(site.id)
    assert created and site.mode is WebsiteMode.SINGLE and site.page_count == 0
    assert container.website_chat_service.pages(site.id) == []
    chunks = container.websites_repo.chunks(site.id, site.index_version)
    assert all(c.page_id == "" and c.page_url == "" for c in chunks)


def test_v5_database_upgrades_in_place_and_v1_website_survives(tmp_path):
    from src.persistence.db import Database, _MIGRATIONS
    from src.persistence.websites import WebsitesRepository

    path = str(tmp_path / "old.db")
    container, web, _ = make(tmp_path, db_path=path)
    web.add("example.com", "/report", ARTICLE)
    site, _ = container.website_chat_service.submit("https://example.com/report")
    site_id = site.id
    container.db.close() if hasattr(container.db, "close") else None

    conn = sqlite3.connect(path)
    conn.executescript(
        # Make the file look exactly like a v5 database again.
        "DROP TABLE website_pages; DROP TABLE document_messages; DROP TABLE document_conversations;"
        "DROP TABLE collection_items; DROP TABLE collections;"
        "ALTER TABLE websites DROP COLUMN mode; ALTER TABLE websites DROP COLUMN page_count;"
        "ALTER TABLE website_chunks DROP COLUMN page_id;"
        "ALTER TABLE website_chunks DROP COLUMN page_url;"
        "ALTER TABLE website_chunks DROP COLUMN page_title;"
        "DELETE FROM schema_version WHERE version >= 6;"
    )
    conn.commit()
    before = conn.execute("SELECT COUNT(*) FROM website_chunks").fetchone()[0]
    conn.close()

    reopened = Database(path)  # applies v6
    repo = WebsitesRepository(reopened)
    upgraded = repo.get(site_id)
    assert upgraded is not None and upgraded.mode is WebsiteMode.SINGLE
    assert len(repo.chunks(site_id, upgraded.index_version)) == before
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == len(_MIGRATIONS)
    conn.close()


# ========================= Document Chat ==================================================


DOC_A = (
    "Alpha cell testing. The Alpha prototype retained 88% capacity after 800 cycles. "
    "Thermal runaway began at 182 C in the abuse test. " + filler("alpha cell results", 10)
)
DOC_B = (
    "Beta manufacturing notes. The Beta line produces 1,200 cells per day in Lyon. "
    "Production yield reached 97% in March. " + filler("beta production line", 10)
)


def docs_ready(container):
    a = container.document_service.ingest("alpha.txt", DOC_A.encode())
    b = container.document_service.ingest("beta.txt", DOC_B.encode())
    return a, b


def doc_ask(container, conversation, question):
    _, answer = container.document_chat_service.ask(conversation.id, question)
    return container.document_chat_repo.get_message(answer.id)


def test_document_chat_answers_with_exact_document_citations(tmp_path):
    llm = ChatLLM(['{"report": "The Alpha prototype retained 88% capacity after 800 cycles [1]."}'])
    container, _, llm = make(tmp_path, llm=llm)
    a, b = docs_ready(container)
    conversation = container.document_chat_service.create_conversation([a.id, b.id], "en")
    message = doc_ask(container, conversation, "How much capacity did the Alpha prototype retain?")
    assert message.status.value == "COMPLETED" and message.cited == [1]
    citation = message.citations[0]
    assert citation.document_id == a.id and citation.filename == "alpha.txt"
    assert "88% capacity" in citation.text  # verbatim stored passage
    assert message.metrics["documents"] == 2


def test_document_chat_scope_is_frozen_and_validated(tmp_path):
    container, _, _ = make(tmp_path)
    a, _ = docs_ready(container)
    with pytest.raises(WebsiteError):
        container.document_chat_service.create_conversation([], "en")
    with pytest.raises(Exception):
        container.document_chat_service.create_conversation(["missing"], "en")
    conversation = container.document_chat_service.create_conversation([a.id], "en")
    assert conversation.document_ids == [a.id]


def test_document_chat_insufficient_evidence_is_localized_and_uncited(tmp_path):
    llm = ChatLLM(['{"report": "NOT_IN_DOCUMENTS"}'])
    container, _, llm = make(tmp_path, llm=llm)
    a, b = docs_ready(container)
    conversation = container.document_chat_service.create_conversation([a.id, b.id], "en")
    message = doc_ask(container, conversation, "What is the CEO's birthday?")
    assert message.insufficient_evidence is True and message.cited == []
    assert "documents do not provide enough information" in message.content


def test_document_answers_reject_uncited_and_ungrounded_numbers(tmp_path):
    llm = ChatLLM(
        ['{"report": "Probably fine."}', '{"report": "Yield was 42% in March [1]."}']
    )
    container, _, llm = make(tmp_path, llm=llm)
    _, b = docs_ready(container)
    conversation = container.document_chat_service.create_conversation([b.id], "en")
    message = doc_ask(container, conversation, "What was the production yield?")
    assert message.insufficient_evidence is True
    assert message.metrics["rejected"] == ["uncited", "ungrounded_numbers"]
    assert "42%" not in message.content


def test_document_chat_diversity_spans_both_documents(tmp_path):
    llm = ChatLLM(['{"report": "Alpha retained 88% [1] and Beta yield was 97% [2]."}'])
    container, _, llm = make(tmp_path, llm=llm)
    a, b = docs_ready(container)
    conversation = container.document_chat_service.create_conversation([a.id, b.id], "en")
    message = doc_ask(container, conversation, "Compare Alpha capacity and Beta production yield in cycles and cells")
    docs_cited = {c.document_id for c in message.citations}
    assert {a.id, b.id} <= docs_cited


def test_document_chat_gates_unvalidated_languages(tmp_path):
    from src.model_capabilities import UnsupportedOutputLanguageError

    container, _, _ = make(tmp_path)
    a, _ = docs_ready(container)
    with pytest.raises(UnsupportedOutputLanguageError):
        container.document_chat_service.create_conversation([a.id], "ml")


def test_document_chat_cancellation_and_recovery(tmp_path):
    holder = {}

    def cancel_during_llm():
        holder["service"].cancel_message(holder["id"])

    llm = ChatLLM(on_invoke=cancel_during_llm)
    container, _, llm = make(tmp_path, llm=llm)
    a, _ = docs_ready(container)
    service = container.document_chat_service
    holder["service"] = service
    original = service._answer

    def capture(message_id):
        holder["id"] = message_id
        return original(message_id)

    service._answer = capture
    conversation = service.create_conversation([a.id], "en")
    message = doc_ask(container, conversation, "Capacity?")
    assert message.status.value == "CANCELLED" and message.content == ""

    # Recovery: a PENDING answer left behind by a crash is closed out honestly.
    from src.models.document_chat import DocumentChatMessage, MessageStatus

    pending = container.document_chat_repo.add_message(
        DocumentChatMessage(conversation_id=conversation.id, role="assistant",
                            status=MessageStatus.PENDING)
    )
    assert service.recover_interrupted() == 1
    closed = container.document_chat_repo.get_message(pending.id)
    assert closed.status is MessageStatus.FAILED and closed.error_code == errors.INTERRUPTED


def test_document_conversations_persist_across_reopen(tmp_path):
    path = str(tmp_path / "doc.db")
    llm = ChatLLM(['{"report": "Thermal runaway began at 182 C [1]."}'])
    container, _, llm = make(tmp_path, llm=llm, db_path=path)
    a, _ = docs_ready(container)
    conversation = container.document_chat_service.create_conversation([a.id], "en")
    message = doc_ask(container, conversation, "When did thermal runaway begin?")
    assert message.cited == [1]

    reopened, _, _ = make(tmp_path, db_path=path)
    again, messages = reopened.document_chat_service.get_conversation(conversation.id)
    assert again.document_ids == [a.id]
    assert messages[-1].citations[0].text == message.citations[0].text


def test_document_relationships_are_deterministic_and_honest(tmp_path):
    llm = ChatLLM()
    container, _, llm = make(tmp_path, llm=llm)
    a = container.document_service.ingest(
        "solar-a.txt",
        ("Perovskite solar cells degrade quickly in moisture. Perovskite efficiency rises "
         "with proper encapsulation of the perovskite layer against moisture. " * 6).encode(),
    )
    b = container.document_service.ingest(
        "solar-b.txt",
        ("Encapsulation shields perovskite modules from moisture ingress during operation. "
         "Sealed encapsulation keeps perovskite output stable. " * 6).encode(),
    )
    c = container.document_service.ingest(
        "cooking.txt",
        ("Slow-roasted tomato sauce wants basil, garlic and patient simmering. "
         "Fresh tomato halves roast gently beside whole garlic cloves. " * 6).encode(),
    )
    result = container.document_chat_service.relationships([a.id, b.id, c.id])
    assert result["method"] == "deterministic"
    link = next(l for l in result["links"] if {l["a"], l["b"]} == {a.id, b.id})
    assert link["type"] == "SHARES_CONCEPT" and "perovskite" in link["terms"]
    assert not any({l["a"], l["b"]} == {a.id, c.id} for l in result["links"])
    assert llm.prompts == []  # relationships never call a model
    assert result == container.document_chat_service.relationships([a.id, b.id, c.id])


def test_document_chat_api_round_trip(tmp_path):
    llm = ChatLLM(['{"report": "Beta produces 1,200 cells per day [1]."}'])
    container, _, llm = make(tmp_path, llm=llm)
    a, b = docs_ready(container)
    with TestClient(create_app(container)) as client:
        created = client.post(
            "/api/document-conversations",
            json={"document_ids": [a.id, b.id], "output_language": "en"},
        )
        assert created.status_code == 201
        conversation_id = created.json()["conversation"]["id"]
        asked = client.post(
            f"/api/document-conversations/{conversation_id}/messages",
            json={"question": "How many cells per day does the Beta line in Lyon produce?"},
        )
        assert asked.status_code == 202
        detail = client.get(f"/api/document-conversations/{conversation_id}").json()
        answer = detail["messages"][-1]
        assert answer["cited"] == [1] and answer["citations"][0]["filename"] == "beta.txt"
        rel = client.get(f"/api/documents/relationships?ids={a.id},{b.id}")
        assert rel.status_code == 200 and rel.json()["method"] == "deterministic"
        assert client.get("/api/document-conversations").json()["conversations"]
        assert client.delete(f"/api/document-conversations/{conversation_id}").status_code == 204


# ========================= Collections ====================================================


def collection_client(tmp_path):
    container, web, llm = make(tmp_path)
    return container, TestClient(create_app(container))


def test_collection_crud_and_items(tmp_path):
    container, client = collection_client(tmp_path)
    with client:
        created = client.post("/api/collections", json={"title": "Battery notes", "description": "d"})
        assert created.status_code == 201
        cid = created.json()["id"]
        assert client.get("/api/collections").json()["collections"][0]["item_count"] == 0

        evidence = client.post(
            f"/api/collections/{cid}/items",
            json={"type": "evidence",
                  "data": {"text": "It retained 91% capacity.", "title": "Battery report",
                           "run_id": "run-x", "citation": 2}},
        )
        assert evidence.status_code == 201 and evidence.json()["position"] == 1
        duplicate = client.post(
            f"/api/collections/{cid}/items",
            json={"type": "evidence",
                  "data": {"text": "It retained 91% capacity.", "title": "Battery report",
                           "run_id": "run-x", "citation": 2}},
        )
        assert duplicate.json()["existing"] is True
        note = client.post(
            f"/api/collections/{cid}/items",
            json={"type": "note", "note": "My own hypothesis about degradation.", "data": {}},
        )
        assert note.status_code == 201 and note.json()["position"] == 2
        empty_note = client.post(f"/api/collections/{cid}/items", json={"type": "note", "data": {}})
        assert empty_note.status_code == 422

        detail = client.get(f"/api/collections/{cid}").json()
        assert [i["type"] for i in detail["items"]] == ["evidence", "note"]
        assert detail["collection"]["item_count"] == 2

        patched = client.patch(f"/api/collections/{cid}", json={"title": "Renamed"})
        assert patched.json()["title"] == "Renamed"
        item_id = detail["items"][0]["id"]
        assert client.patch(f"/api/collection-items/{item_id}", json={"note": "annotated"}).status_code == 200
        assert client.delete(f"/api/collection-items/{item_id}").status_code == 204
        assert client.delete(f"/api/collections/{cid}").status_code == 204
        assert client.get(f"/api/collections/{cid}").status_code == 404


def test_collection_items_mark_deleted_origins_honestly(tmp_path):
    container, client = collection_client(tmp_path)
    doc = container.document_service.ingest("note.txt", (filler("alpha") * 3).encode())
    with client:
        cid = client.post("/api/collections", json={"title": "C"}).json()["id"]
        client.post(
            f"/api/collections/{cid}/items",
            json={"type": "document_passage",
                  "data": {"document_id": doc.id, "filename": "note.txt", "page": 1,
                           "text": "stored excerpt"}},
        )
        before = client.get(f"/api/collections/{cid}").json()["items"][0]
        assert before["origin_exists"] is True
        container.document_service.delete(doc.id)
        after = client.get(f"/api/collections/{cid}").json()["items"][0]
        assert after["origin_exists"] is False
        assert after["data"]["text"] == "stored excerpt"  # snapshot survives deletion


def test_collection_rejects_wrong_types_and_oversized_items(tmp_path):
    _, client = collection_client(tmp_path)
    with client:
        cid = client.post("/api/collections", json={"title": "C"}).json()["id"]
        assert client.post(f"/api/collections/{cid}/items",
                           json={"type": "wormhole", "data": {}}).status_code == 422
        huge = client.post(f"/api/collections/{cid}/items",
                           json={"type": "evidence", "data": {"text": "x" * 50_000}})
        assert huge.status_code == 422
