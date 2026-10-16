"""Bounded same-site page discovery for Website Chat SITE mode.

Discovery is deliberately shallow and user-directed: Atlas fetches the ROOT
page (and, when available, ``robots.txt`` and ``sitemap.xml``) through the
same SSRF-safe fetcher used for indexing, extracts same-host links, and
returns a bounded candidate list for the USER to choose from. Indexing then
fetches only the pages the user selected. Atlas never follows links from
discovered pages (no recursive crawl), never leaves the root's host, and
never bypasses logins, paywalls or robots rules it can read.

Every candidate URL independently passes ``normalize_url`` (scheme/credential
checks); the indexing fetch then re-applies every DNS/redirect/size check per
page, so discovery grants no security shortcut.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from src.website import errors
from src.website.errors import WebsiteError
from src.website.extract import decode_body
from src.website.fetch import SafeWebsiteFetcher
from src.website.urls import normalize_url

logger = logging.getLogger(__name__)

#: Hard ceiling on candidates returned to the user (selection happens there).
MAX_CANDIDATES = 40
#: Hard ceiling on sitemap entries read.
MAX_SITEMAP_URLS = 200

_SITEMAP_TYPES = ("application/xml", "text/xml", "application/rss+xml")
_LOC_RE = re.compile(r"<loc>\s*([^<\s][^<]*?)\s*</loc>", re.IGNORECASE)

#: Path pieces that are near-certain traps or useless for grounding: session
#: actions, auth, calendars and endless listing variants.
_NOISE_PATH_RE = re.compile(
    r"(^|/)(login|logout|signin|signout|sign-in|sign-out|register|signup|sign-up|"
    r"cart|checkout|account|unsubscribe|calendar|\d{4}/\d{2}/\d{2}/page)(/|$)|"
    r"[&?](action=|session|sid=|phpsessid|replytocom=)",
    re.IGNORECASE,
)
#: File extensions that are not webpages (PDF has its own Atlas home).
_NON_PAGE_EXT_RE = re.compile(
    r"\.(pdf|jpg|jpeg|png|gif|svg|webp|ico|css|js|mjs|json|xml|zip|gz|tar|7z|rar|"
    r"mp3|mp4|avi|mov|webm|woff2?|ttf|eot|exe|dmg|iso|csv|xlsx?|docx?|pptx?)$",
    re.IGNORECASE,
)


@dataclass
class DiscoveredPage:
    url: str
    title: str = ""
    #: "root" | "link" | "sitemap"
    found_via: str = "link"


@dataclass
class DiscoveryResult:
    root_url: str
    root_title: str
    pages: list[DiscoveredPage]
    #: Candidates dropped and why (counts only; no page content is kept).
    skipped: dict = field(default_factory=dict)
    #: True when robots.txt rules excluded at least one candidate.
    robots_applied: bool = False


class _LinkParser(HTMLParser):
    """Collects <a href> targets and their anchor text, plus <title>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []  # (href, text)
        self.title = ""
        self._href: str | None = None
        self._text: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = next((v for k, v in attrs if k == "href" and v), None)
            self._href, self._text = href, []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())[:120]))
            self._href = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
        if self._in_title and not self.title:
            self.title = " ".join(data.split())[:200]


def parse_robots(text: str) -> list[str]:
    """Disallow path prefixes for ``User-agent: *`` (minimal, prefix-only)."""
    disallows: list[str] = []
    applies = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            applies = value == "*"
        elif key == "disallow" and applies and value:
            disallows.append(value)
    return disallows


def robots_blocks(path: str, disallows: list[str]) -> bool:
    return any(path.startswith(rule.rstrip("*")) for rule in disallows if rule.rstrip("*"))


def same_host(url: str, root_host: str) -> bool:
    return (urlsplit(url).hostname or "").lower() == root_host


def _candidate_url(base: str, href: str, root_host: str) -> str | None:
    """Canonical same-host page URL, or None when it is not a candidate."""
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    absolute = urljoin(base, href)
    scheme = urlsplit(absolute).scheme.lower()
    if scheme not in ("http", "https"):
        return None  # mailto:, javascript:, data:, tel:, ftp:, ...
    try:
        canonical = normalize_url(absolute)  # drops fragment, rejects credentials
    except WebsiteError:
        return None
    parts = urlsplit(canonical)
    if (parts.hostname or "").lower() != root_host:
        return None
    if _NON_PAGE_EXT_RE.search(parts.path):
        return None
    if _NOISE_PATH_RE.search(parts.path + ("?" + parts.query if parts.query else "")):
        return None
    return canonical


def discover_pages(
    fetcher: SafeWebsiteFetcher,
    url: str,
    max_candidates: int = MAX_CANDIDATES,
    should_cancel=lambda: False,
) -> DiscoveryResult:
    """Fetch the root page safely and list same-host candidate pages.

    Deterministic: candidates keep first-seen order (root first, then the
    root page's links in document order, then sitemap entries), deduplicated
    on the canonical URL.
    """
    root = normalize_url(url)
    fetched = fetcher.fetch(root, should_cancel=should_cancel)
    if not fetched.is_html:
        raise WebsiteError(
            errors.UNSUPPORTED_CONTENT,
            "Multi-page indexing needs an HTML page to discover links from.",
        )
    root_canonical = normalize_url(fetched.final_url)
    root_host = (urlsplit(root_canonical).hostname or "").lower()
    parser = _LinkParser()
    try:
        parser.feed(decode_body(fetched.body, fetched.charset))
        parser.close()
    except Exception:  # malformed HTML: keep whatever was collected
        logger.debug("Link parsing stopped early for %s", root_canonical, exc_info=True)

    skipped = {"offsite_or_unsupported": 0, "duplicate": 0, "robots": 0, "over_limit": 0}
    seen: dict[str, DiscoveredPage] = {}
    seen[root_canonical] = DiscoveredPage(url=root_canonical, title=parser.title, found_via="root")

    def add(candidate: str | None, title: str, via: str) -> None:
        if candidate is None:
            skipped["offsite_or_unsupported"] += 1
            return
        if candidate in seen:
            skipped["duplicate"] += 1
            return
        seen[candidate] = DiscoveredPage(url=candidate, title=title, found_via=via)

    for href, text in parser.links:
        add(_candidate_url(fetched.final_url, href, root_host), text, "link")

    for loc in _sitemap_locations(fetcher, root_canonical, should_cancel):
        add(_candidate_url(root_canonical, loc, root_host), "", "sitemap")

    disallows = _robots_disallows(fetcher, root_canonical, should_cancel)
    pages: list[DiscoveredPage] = []
    robots_applied = False
    for page in seen.values():
        if disallows and page.found_via != "root" and robots_blocks(urlsplit(page.url).path or "/", disallows):
            skipped["robots"] += 1
            robots_applied = True
            continue
        pages.append(page)
    if len(pages) > max_candidates:
        skipped["over_limit"] = len(pages) - max_candidates
        pages = pages[:max_candidates]
    return DiscoveryResult(
        root_url=root_canonical,
        root_title=parser.title,
        pages=pages,
        skipped={k: v for k, v in skipped.items() if v},
        robots_applied=robots_applied,
    )


def _well_known(fetcher: SafeWebsiteFetcher, root: str, path: str, extra, should_cancel) -> str:
    """Body of a same-host well-known file, or "" (never raises)."""
    parts = urlsplit(root)
    target = f"{parts.scheme}://{parts.netloc}{path}"
    try:
        fetched = fetcher.fetch(target, should_cancel=should_cancel, extra_types=extra)
        return decode_body(fetched.body, fetched.charset)
    except WebsiteError:
        return ""
    except Exception:
        logger.debug("Well-known fetch failed for %s", target, exc_info=True)
        return ""


def _sitemap_locations(fetcher, root: str, should_cancel) -> list[str]:
    body = _well_known(fetcher, root, "/sitemap.xml", _SITEMAP_TYPES, should_cancel)
    if not body:
        return []
    return _LOC_RE.findall(body)[:MAX_SITEMAP_URLS]


def _robots_disallows(fetcher, root: str, should_cancel) -> list[str]:
    body = _well_known(fetcher, root, "/robots.txt", ("text/plain",), should_cancel)
    return parse_robots(body) if body else []
