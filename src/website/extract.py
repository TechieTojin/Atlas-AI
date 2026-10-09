"""Deterministic, structure-preserving text extraction from one HTML page.

Raw HTML never reaches embeddings or the model. The page is parsed with the
standard-library parser into a small element tree (no JavaScript runs, no
network access, nothing is rendered), boilerplate subtrees are dropped, the
main content region is chosen, and the remaining text is emitted as typed
blocks (headings with levels, paragraphs, list items, table rows, captions,
preformatted text) so chunks can carry their section heading.

Cleaning is conservative and Unicode-safe: NFC only (never NFKC, which would
rewrite subscripts and other formula characters), whitespace collapsed
outside ``<pre>``, BOM and soft hyphens removed, but ZWJ/ZWNJ (meaningful in
Malayalam and Devanagari), punctuation, numbers and units kept exactly.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

from src.unicode_text import content_word_count, has_meaningful_text
from src.website import errors
from src.website.errors import WebsiteError

# Subtrees that are never evidence (executable, interactive or chrome).
_DROP_TAGS = frozenset({
    "script", "style", "noscript", "template", "svg", "math", "canvas", "iframe",
    "object", "embed", "form", "button", "select", "option", "input", "textarea",
    "nav", "aside", "dialog", "menu", "head", "link", "meta", "video", "audio", "map",
})
# Page chrome, dropped unless inside the chosen article/main content.
_CHROME_TAGS = frozenset({"header", "footer"})
_DROP_ROLES = frozenset({
    "navigation", "banner", "contentinfo", "complementary", "search", "dialog",
    "alertdialog", "menu", "menubar", "toolbar", "tablist",
})
# class/id tokens that mark boilerplate (matched as whole tokens).
_BOILERPLATE_TOKENS = frozenset({
    "cookie", "cookies", "consent", "gdpr", "advert", "advertisement", "ads", "ad",
    "adsbygoogle", "sponsor", "sponsored", "promo", "promotion", "newsletter",
    "subscribe", "subscription", "share", "sharing", "social", "related",
    "recommended", "comments", "comment", "sidebar", "breadcrumb", "breadcrumbs",
    "menu", "navbar", "nav", "navigation", "footer", "masthead", "popup", "modal",
    "overlay", "skip", "toolbar", "pagination", "pager", "banner", "widget",
    "signup", "paywall", "outbrain", "taboola",
    # Reference apparatus and page notices (MediaWiki and many CMS themes):
    # bibliographies and maintenance banners are not answerable content and
    # would crowd out the article in retrieval.
    "editsection", "reflist", "refbegin", "references", "navbox", "catlinks",
    "printfooter", "ambox", "sitesub", "noprint", "metadata",
})
# Footnote markers such as "[10]", "[a]", "[note 3]", "[citation needed]".
_FOOTNOTE_RE = re.compile(r"^\s*\[\s*(?:\d{1,4}|[a-z]{1,2}|note \d+|citation needed|\w+ \d+)\s*\]\s*$", re.I)
_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
})
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "blockquote", "figure", "figcaption",
    "caption", "dl", "dt", "dd", "ul", "ol", "li", "table", "thead", "tbody", "tfoot",
    "tr", "td", "th", "pre", "address", "details", "summary", "header", "footer", "body",
})
# Implicitly closed when a sibling of the same family starts (HTML5 rules, simplified).
_AUTO_CLOSE = {
    "p": {"p", "div", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "pre",
          "blockquote", "section", "article", "figure"},
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "tr": {"tr"},
    "td": {"td", "th", "tr"},
    "th": {"td", "th", "tr"},
    "option": {"option"},
}
_JS_MARKERS = (
    "enable javascript", "javascript is required", "requires javascript",
    "you need to enable javascript", "please turn on javascript", "javascript is disabled",
    "__next_data__", "id=\"root\"", "id=\"app\"", "id=\"__next\"", "ng-app", "data-reactroot",
)


@dataclass
class _Node:
    tag: str
    attrs: dict
    children: list = field(default_factory=list)
    parent: "_Node | None" = None


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.current = self.root
        self.title = ""
        self.html_lang = ""
        self.meta: dict[str, str] = {}
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and attr.get("lang"):
            self.html_lang = attr["lang"].strip()
        if tag == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            if key in ("og:title", "og:site_name", "twitter:title"):
                self.meta[key] = attr.get("content", "")
            return
        if tag == "title":
            self._in_title = True
            return
        closers = _AUTO_CLOSE
        node = self.current
        while node is not self.root and node.tag in closers and tag in closers[node.tag]:
            node = node.parent
        self.current = node
        element = _Node(tag, attr, parent=self.current)
        self.current.children.append(element)
        if tag not in _VOID_TAGS:
            self.current = element

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS and self.current.tag == tag:
            self.current = self.current.parent or self.root

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:  # unmatched end tags are ignored
            self.current = node.parent or self.root

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        self.current.children.append(data)


@dataclass
class Block:
    kind: str  # heading | paragraph | list_item | table_row | caption | pre | quote
    text: str
    level: int = 0  # heading level 1-6


@dataclass
class ExtractedPage:
    title: str
    language: str
    blocks: list[Block]
    word_count: int
    content_hash: str
    #: parse_ms (HTML tree + boilerplate pruning) and clean_ms (blocks, dedupe, hash).
    timings: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)


def clean_text(text: str, *, preformatted: bool = False) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("﻿", "").replace("­", "")
    text = text.replace(" ", " ").replace(" ", " ")
    if preformatted:
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        return "\n".join(lines).strip("\n")
    return re.sub(r"\s+", " ", text).strip()


def _tokens(node: _Node) -> set[str]:
    raw = f"{node.attrs.get('class', '')} {node.attrs.get('id', '')}".lower()
    return set(re.split(r"[\s_\-]+", raw)) - {""}


def _is_hidden(node: _Node) -> bool:
    if "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true":
        return True
    style = node.attrs.get("style", "").replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _is_boilerplate(node: _Node, in_content: bool) -> bool:
    if node.tag in _DROP_TAGS or _is_hidden(node):
        return True
    if node.attrs.get("role", "").lower() in _DROP_ROLES:
        return True
    if node.tag in _CHROME_TAGS and not in_content:
        return True
    if node.tag in ("main", "article", "body", "html"):
        return False
    return bool(_tokens(node) & _BOILERPLATE_TOKENS)


def _prune(node: _Node, in_content: bool = False) -> None:
    kept = []
    for child in node.children:
        if isinstance(child, str):
            kept.append(child)
            continue
        inside = in_content or child.tag in ("article", "main") or child.attrs.get("role") == "main"
        if _is_boilerplate(child, in_content):
            continue
        if child.tag == "sup" and _FOOTNOTE_RE.match(_collect(child)):
            continue  # a footnote marker, not content
        _prune(child, inside)
        kept.append(child)
    node.children = kept


def _text_len(node: _Node) -> int:
    total = 0
    for child in node.children:
        total += len(child.strip()) if isinstance(child, str) else _text_len(child)
    return total


def _find_all(node: _Node, predicate) -> list[_Node]:
    found = []
    for child in node.children:
        if isinstance(child, _Node):
            if predicate(child):
                found.append(child)
            found.extend(_find_all(child, predicate))
    return found


def _content_root(root: _Node) -> _Node:
    """``<main>``/``<article>`` when it holds most of the text, else the body."""
    total = _text_len(root) or 1
    candidates = _find_all(
        root, lambda n: n.tag in ("main", "article") or n.attrs.get("role") == "main"
    )
    best = max(candidates, key=_text_len, default=None)
    if best is not None and _text_len(best) >= 0.4 * total:
        return best
    return root


class _BlockEmitter:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self._buffer: list[str] = []

    def flush(self, kind: str = "paragraph", level: int = 0) -> None:
        raw = "".join(self._buffer)
        self._buffer = []
        text = clean_text(raw, preformatted=(kind == "pre"))
        if text:
            self.blocks.append(Block(kind, text, level))

    def walk(self, node: _Node, list_depth: int = 0) -> None:
        for child in node.children:
            if isinstance(child, str):
                self._buffer.append(child)
                continue
            tag = child.tag
            if tag in _HEADINGS:
                self.flush()
                self._inline(child)
                self.flush("heading", _HEADINGS[tag])
            elif tag == "br":
                self._buffer.append(" ")
            elif tag == "li":
                self.flush()
                self._walk_mixed(child, "list_item", list_depth + 1)
            elif tag == "tr":
                self.flush()
                cells = [
                    clean_text(_collect(cell))
                    for cell in child.children
                    if isinstance(cell, _Node) and cell.tag in ("td", "th")
                ]
                cells = [cell for cell in cells if cell]
                if cells:
                    self.blocks.append(Block("table_row", " | ".join(cells)))
            elif tag in ("figcaption", "caption"):
                self.flush()
                self._inline(child)
                self.flush("caption")
            elif tag == "pre":
                self.flush()
                self._buffer.append(_collect(child))
                self.flush("pre")
            elif tag == "blockquote":
                self.flush()
                self.walk(child, list_depth)
                self.flush("quote")
            elif tag in ("img",):
                alt = child.attrs.get("alt", "").strip()
                if alt and child.parent is not None and child.parent.tag == "figure":
                    self._buffer.append(f" {alt} ")
            elif tag in _BLOCK_TAGS:
                self.flush()
                self.walk(child, list_depth)
                self.flush()
            else:
                self.walk(child, list_depth)

    def _walk_mixed(self, node: _Node, kind: str, depth: int) -> None:
        """A list item: its own text is one block; nested lists follow."""
        for child in node.children:
            if isinstance(child, _Node) and child.tag in ("ul", "ol", "table", "pre", "blockquote"):
                self.flush(kind)
                self.walk(child, depth)
            elif isinstance(child, str):
                self._buffer.append(child)
            elif child.tag in ("p", "div"):
                self._buffer.append(" " + _collect(child) + " ")
            else:
                self._buffer.append(_collect(child))
        self.flush(kind)

    def _inline(self, node: _Node) -> None:
        self._buffer.append(_collect(node))


def _collect(node: _Node) -> str:
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n" if node.tag == "pre" else " ")
        elif child.tag in _BLOCK_TAGS or child.tag in _HEADINGS:
            parts.append(" " + _collect(child) + " ")
        else:
            parts.append(_collect(child))
    return "".join(parts)


def _dedupe(blocks: list[Block]) -> list[Block]:
    """Drop repeated boilerplate: identical non-heading blocks seen before,
    consecutive duplicates, and blocks with no meaningful word."""
    seen: dict[str, int] = {}
    kept: list[Block] = []
    for block in blocks:
        if block.kind != "heading" and not has_meaningful_text(block.text):
            continue
        key = block.text.casefold()
        if kept and kept[-1].text.casefold() == key:
            continue
        if block.kind not in ("heading",) and key in seen and len(block.text) < 200:
            continue
        seen[key] = seen.get(key, 0) + 1
        kept.append(block)
    # Headings left with nothing under them at the very end are dropped.
    while kept and kept[-1].kind == "heading":
        kept.pop()
    return kept


def content_hash(blocks: list[Block]) -> str:
    canonical = "\n".join(f"{b.kind}:{b.level}:{b.text}" for b in blocks)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decode_body(body: bytes, charset: str) -> str:
    candidates = [charset] if charset else []
    head = body[:4096].decode("ascii", errors="ignore").lower()
    match = re.search(r"<meta[^>]+charset=[\"']?([a-z0-9_\-]+)", head)
    if match:
        candidates.append(match.group(1))
    candidates.append("utf-8")
    for name in candidates:
        try:
            return body.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


MIN_WORDS = 20


def extract_page(html: str, *, is_html: bool = True) -> ExtractedPage:
    """Blocks, title and hash for one page, or a clear ``WebsiteError``."""
    started = time.perf_counter()
    if not is_html:
        paragraphs = [clean_text(p) for p in re.split(r"\n\s*\n", html)]
        blocks = _dedupe([Block("paragraph", p) for p in paragraphs if p])
        return _finish("", "", blocks, html)
    builder = _TreeBuilder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:  # malformed HTML: keep what was parsed
        pass
    root = builder.root
    _prune(root)
    content = _content_root(root)
    parsed = time.perf_counter()
    emitter = _BlockEmitter()
    emitter.walk(content)
    emitter.flush()
    blocks = _dedupe(emitter.blocks)
    title = clean_text(builder.meta.get("og:title") or builder.title)
    if not title:
        first_h1 = next((b.text for b in blocks if b.kind == "heading" and b.level == 1), "")
        title = first_h1
    page = _finish(title, builder.html_lang, blocks, html)
    page.timings = {
        "parse_ms": int((parsed - started) * 1000),
        "clean_ms": int((time.perf_counter() - parsed) * 1000),
    }
    return page


def _finish(title: str, language: str, blocks: list[Block], raw: str) -> ExtractedPage:
    words = sum(content_word_count(b.text) for b in blocks)
    if words < MIN_WORDS:
        lowered = raw.lower()
        scripts = lowered.count("<script")
        if any(marker in lowered for marker in _JS_MARKERS) or scripts >= 5:
            raise WebsiteError(
                errors.JS_REQUIRED,
                "This page requires browser rendering and cannot currently be indexed.",
            )
        raise WebsiteError(
            errors.EMPTY_CONTENT, "No meaningful text was found on this page."
        )
    return ExtractedPage(
        title=title[:300],
        language=language.split("-")[0].lower()[:12] if language else "",
        blocks=blocks,
        word_count=words,
        content_hash=content_hash(blocks),
    )
