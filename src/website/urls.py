"""URL normalization for Website Chat.

Conservative by design: the scheme and host are canonicalised (lower case,
IDNA, default port dropped, fragment removed), but the path and query are
kept exactly, because query parameters often identify the actual content
(``?id=42``, ``?page=3``). Two URLs normalize equal only when they certainly
address the same resource.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from src.website import errors
from src.website.errors import WebsiteError

MAX_URL_LENGTH = 2048
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _bare_host_like(raw: str) -> bool:
    """``example.com/article`` (no scheme) rather than ``mailto:x``."""
    head = raw.split("/", 1)[0]
    if ":" not in head:
        return True
    # host:port with a numeric port, e.g. example.com:8080/path
    host, _, port = head.rpartition(":")
    return bool(host) and port.isdigit()


def normalize_url(raw: str) -> str:
    """Canonical http(s) URL for ``raw`` or a ``WebsiteError``."""
    text = (raw or "").strip()
    if not text:
        raise WebsiteError(errors.INVALID_URL, "Enter a webpage URL.")
    if len(text) > MAX_URL_LENGTH:
        raise WebsiteError(errors.INVALID_URL, "The URL is too long.")
    if any(ch.isspace() for ch in text) or any(ord(ch) < 32 for ch in text):
        raise WebsiteError(errors.INVALID_URL, "The URL contains spaces or control characters.")
    if "://" not in text and _bare_host_like(text):
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise WebsiteError(errors.INVALID_URL, "The URL could not be parsed.") from exc
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise WebsiteError(
            errors.UNSUPPORTED_SCHEME,
            f"Only http and https webpages can be indexed (got {scheme or 'no'} scheme).",
        )
    if parts.username is not None or parts.password is not None:
        raise WebsiteError(
            errors.CREDENTIALS_IN_URL, "URLs containing a username or password are not accepted."
        )
    try:
        host = parts.hostname or ""
        port = parts.port
    except ValueError as exc:  # invalid port
        raise WebsiteError(errors.INVALID_URL, "The URL has an invalid port.") from exc
    host = host.rstrip(".")
    if not host:
        raise WebsiteError(errors.INVALID_URL, "The URL has no hostname.")
    if ":" not in host:  # IPv6 literals stay as they are
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise WebsiteError(errors.INVALID_URL, "The URL has an invalid hostname.") from exc
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def display_domain(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host
