"""Full-page web research: SSRF-safe fetching, HTML text extraction, and
deterministic chunk selection.

Pipeline: candidate URL (from search discovery) → safe fetch → boilerplate-
free text → chunks → keyword-scored relevant excerpts. Page content is
always treated as untrusted evidence text; it is never executed and no
JavaScript runs. Failures degrade to the original search snippet.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

logger = logging.getLogger(__name__)

USER_AGENT = "AtlasResearch/3.0 (local research assistant)"
_MAX_REDIRECTS = 4
_ALLOWED_SCHEMES = ("http", "https")
_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

# Tags whose content is boilerplate or executable, never evidence.
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "nav", "header", "footer", "aside",
     "svg", "form", "button", "iframe", "template", "select", "option"}
)
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
     "section", "article", "blockquote", "pre", "td", "th"}
)


class PageFetchError(Exception):
    """A page could not be fetched safely; callers fall back to the snippet."""


class BlockedUrlError(PageFetchError):
    """The URL (or a redirect hop) targets a blocked network or scheme."""


def _is_blocked_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str, resolver: Any = None) -> None:
    """Reject URLs that could reach internal networks (SSRF defense).

    Validates the scheme and resolves the hostname, blocking loopback,
    RFC1918/private, link-local (incl. cloud metadata 169.254.169.254),
    multicast, and reserved ranges. Called for the original URL AND for
    every redirect hop.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BlockedUrlError(f"Blocked non-http(s) scheme: {parts.scheme!r}")
    host = parts.hostname or ""
    if not host:
        raise BlockedUrlError("URL has no hostname.")
    if host.lower() in ("localhost",) or host.lower().endswith(".localhost"):
        raise BlockedUrlError("Blocked localhost URL.")
    resolver = resolver or socket.getaddrinfo
    try:
        infos = resolver(host, None)
    except OSError as exc:
        raise PageFetchError(f"DNS resolution failed for {host}.") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise PageFetchError(f"No addresses resolved for {host}.")
    for address in addresses:
        if _is_blocked_ip(str(address)):
            raise BlockedUrlError(
                f"Blocked URL resolving to a private/internal address ({host})."
            )


class HttpGet(Protocol):
    """One non-redirect-following GET. Injectable for tests."""

    def __call__(self, url: str, timeout: float, max_bytes: int) -> Any: ...


@dataclass
class FetchedPage:
    url: str  # final URL after redirects
    text: str
    content_type: str = ""


@dataclass
class _HttpResponse:
    status_code: int
    headers: dict
    text: str
    url: str


def _default_http_get(url: str, timeout: float, max_bytes: int) -> _HttpResponse:
    import httpx

    with httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        with client.stream("GET", url) as response:
            declared = int(response.headers.get("content-length") or 0)
            if declared > max_bytes:
                raise PageFetchError(f"Response too large ({declared} bytes).")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise PageFetchError("Response exceeded the size limit.")
                chunks.append(chunk)
            body = b"".join(chunks)
            encoding = response.charset_encoding or "utf-8"
            return _HttpResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                text=body.decode(encoding, errors="replace"),
                url=str(response.url),
            )


class SafePageFetcher:
    """Fetches public web pages with SSRF protection and hard limits."""

    def __init__(
        self,
        timeout: float = 15.0,
        max_bytes: int = 1_500_000,
        http_get: HttpGet | None = None,
        resolver: Any = None,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._http_get = http_get or _default_http_get
        self._resolver = resolver

    def fetch(self, url: str) -> FetchedPage:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            validate_url(current, resolver=self._resolver)
            response = self._http_get(current, self._timeout, self._max_bytes)
            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                if not location:
                    raise PageFetchError("Redirect without a Location header.")
                current = urljoin(current, location)
                continue  # the next loop iteration re-validates the hop
            if response.status_code != 200:
                raise PageFetchError(f"HTTP {response.status_code}.")
            content_type = (response.headers.get("content-type") or "").lower()
            if not any(allowed in content_type for allowed in _ALLOWED_CONTENT_TYPES):
                raise PageFetchError(f"Unsupported content type: {content_type!r}.")
            if "html" in content_type:
                text = extract_text(response.text)
            else:
                text = re.sub(r"\s+", " ", response.text).strip()
            if not text:
                raise PageFetchError("No extractable text on the page.")
            return FetchedPage(url=response.url or current, text=text,
                               content_type=content_type)
        raise PageFetchError("Too many redirects.")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS and self._skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS and self._skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data)


def extract_text(html: str) -> str:
    """Boilerplate-free text from HTML, deterministically (no JS execution)."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed HTML: keep whatever was parsed
        logger.debug("HTML parse ended early; using partial text.")
    text = "".join(parser.parts)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Drop short navigation crumbs that survive tag filtering.
    kept = [line for line in lines if len(line) >= 40 or line.count(" ") >= 5]
    return "\n".join(kept).strip()


def _terms(text: str) -> list[str]:
    """Letter/mark/digit runs of 3+ code points, in any script.

    For ASCII this is exactly the old ``[a-z0-9]{3,}`` on lower-cased text;
    Malayalam/Hindi query terms are no longer discarded. Matching stays
    literal: no stemming, translation or embeddings.
    """
    from src.unicode_text import words

    return [word for word in words(text.lower()) if len(word) >= 3]


def select_relevant_chunks(
    text: str,
    query: str,
    max_chunks: int = 2,
    chunk_size: int = 1200,
    overlap: int = 100,
) -> list[str]:
    """Deterministic keyword-overlap scoring of page chunks against the query.

    No LLM: chunks are scored by distinct query-term hits (then term
    frequency, then document order) and the top ``max_chunks`` are returned
    in their original page order.
    """
    from src.rag.chunking import chunk_pages

    chunks = chunk_pages("page", [(None, text)], chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        return []
    terms = set(_terms(query))
    scored = []
    for index, chunk in enumerate(chunks):
        words = _terms(chunk.content)
        hits = [w for w in words if w in terms]
        scored.append((len(set(hits)), len(hits), -index, chunk.content))
    scored.sort(reverse=True)
    top = scored[:max_chunks]
    # Original page order for readability.
    top.sort(key=lambda item: -item[2])
    return [content for _, _, _, content in top]
