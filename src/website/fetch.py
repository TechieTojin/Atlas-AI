"""SSRF-safe fetching of ONE public webpage.

Threat model: the URL is chosen by the user (or by a page they chose), so it
may point at the Atlas host, the LAN, or a cloud metadata service, directly
or via redirects and DNS tricks. Mitigations, all applied to EVERY hop:

* only ``http``/``https``; no credentials in URLs (``urls.normalize_url``);
* obviously internal hostnames are refused before any lookup (``localhost``,
  ``*.local``, ``*.internal``, single-label intranet names, ...);
* the hostname is resolved once, and EVERY resolved address must be a public
  unicast address (``ipaddress.is_global``; loopback, RFC 1918, CGNAT,
  link-local incl. 169.254.169.254, multicast, reserved, unspecified,
  IPv4-mapped/6to4/Teredo wrappers of those are all refused);
* DNS-rebinding defence: the TCP connection is made to the exact address
  that was validated (the request URL carries the IP, the ``Host`` header and
  TLS SNI carry the hostname, and the certificate is verified against the
  hostname). The name is never re-resolved between check and connect;
* redirects are followed manually (at most ``max_redirects``) and each
  Location is normalized, re-resolved and re-validated like the first URL;
* environment proxies are ignored (``trust_env=False``) so a proxy cannot
  bypass the address checks;
* connect/read timeouts plus a total wall-clock deadline, a size cap that
  counts DECODED bytes (so compressed bombs stop at the cap), and a content
  type allowlist.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

from src.website import errors
from src.website.errors import WebsiteError
from src.website.urls import normalize_url

logger = logging.getLogger(__name__)

USER_AGENT = "AtlasWebsiteChat/1.0 (+local research assistant; single-page fetch)"
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_HTML_TYPES = ("text/html", "application/xhtml+xml")
_TEXT_TYPES = ("text/plain",)
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".internal", ".intranet", ".lan", ".home",
    ".home.arpa", ".corp", ".localdomain",
)


class Resolver(Protocol):
    def __call__(self, host: str, port: int) -> list[str]: ...


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public_address(address: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_address(str(ip.ipv4_mapped))
        if ip.sixtofour is not None:
            return is_public_address(str(ip.sixtofour))
        if ip.teredo is not None:
            return False
        if ip in _NAT64:
            # Well-known NAT64 prefix: judged by the IPv4 address it wraps
            # (64:ff9b::a9fe:a9fe is 169.254.169.254), independent of how a
            # Python version classifies the prefix itself.
            return is_public_address(str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)))
    return bool(
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_private
    )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def check_hostname(host: str) -> None:
    lowered = host.lower().rstrip(".")
    if _is_ip_literal(lowered):
        return  # judged by address below
    if lowered == "localhost" or lowered.endswith(_BLOCKED_SUFFIXES):
        raise WebsiteError(errors.BLOCKED_ADDRESS, "Local and internal hostnames cannot be fetched.")
    if "." not in lowered:
        raise WebsiteError(
            errors.BLOCKED_ADDRESS, "Single-label (intranet) hostnames cannot be fetched."
        )


def resolve_public(host: str, port: int, resolver: Resolver) -> str:
    """The first resolved address, after checking that ALL are public."""
    check_hostname(host)
    if _is_ip_literal(host):
        addresses = [host]
    else:
        try:
            addresses = resolver(host, port)
        except (OSError, UnicodeError) as exc:
            raise WebsiteError(errors.DNS_FAILURE, f"The hostname {host} could not be resolved.") from exc
    if not addresses:
        raise WebsiteError(errors.DNS_FAILURE, f"The hostname {host} did not resolve to any address.")
    for address in addresses:
        if not is_public_address(address):
            raise WebsiteError(
                errors.BLOCKED_ADDRESS,
                "The address resolves to a private, local or reserved network and cannot be fetched.",
            )
    return addresses[0]


@dataclass
class FetchLimits:
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    total_timeout: float = 25.0
    max_redirects: int = 5
    max_bytes: int = 3_000_000


@dataclass
class FetchResult:
    final_url: str
    status_code: int
    content_type: str
    charset: str
    body: bytes
    elapsed_ms: int
    redirects: int

    @property
    def is_html(self) -> bool:
        return self.content_type in _HTML_TYPES


def _pinned_url(url: str, address: str) -> str:
    parts = urlsplit(url)
    host = f"[{address}]" if ":" in address else address
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _parse_content_type(value: str) -> tuple[str, str]:
    media, _, params = (value or "").partition(";")
    charset = ""
    for param in params.split(";"):
        key, _, val = param.strip().partition("=")
        if key.lower() == "charset":
            charset = val.strip().strip("\"'").lower()
    return media.strip().lower(), charset


class SafeWebsiteFetcher:
    def __init__(
        self,
        limits: FetchLimits | None = None,
        *,
        resolver: Resolver | None = None,
        transport=None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits or FetchLimits()
        self._resolver = resolver or system_resolver
        self._transport = transport  # httpx transport, injectable for tests
        self._clock = clock

    def fetch(self, url: str, should_cancel: Callable[[], bool] = lambda: False) -> FetchResult:
        import httpx

        limits = self._limits
        started = self._clock()
        deadline = started + limits.total_timeout
        current = normalize_url(url)
        redirects = 0
        timeout = httpx.Timeout(
            connect=limits.connect_timeout,
            read=limits.read_timeout,
            write=limits.read_timeout,
            pool=limits.connect_timeout,
        )
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8,*/*;q=0.1",
            },
        ) as client:
            while True:
                parts = urlsplit(current)
                host = parts.hostname or ""
                port = parts.port or (443 if parts.scheme == "https" else 80)
                try:
                    address = resolve_public(host, port, self._resolver)
                except WebsiteError as exc:
                    if redirects and exc.code == errors.BLOCKED_ADDRESS:
                        raise WebsiteError(
                            errors.REDIRECT_BLOCKED,
                            "The page redirected to a private or local address, which was blocked.",
                        ) from exc
                    raise
                host_header = parts.netloc
                extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
                request = client.build_request(
                    "GET", _pinned_url(current, address), headers={"Host": host_header},
                    extensions=extensions,
                )
                if self._clock() > deadline:
                    raise WebsiteError(errors.TIMEOUT, "The page took too long to load.")
                try:
                    response = client.send(request, stream=True)
                except httpx.TimeoutException as exc:
                    raise WebsiteError(errors.TIMEOUT, "The page took too long to respond.") from exc
                except httpx.HTTPError as exc:
                    raise WebsiteError(
                        errors.CONNECTION_FAILED, "A connection to the website could not be established."
                    ) from exc
                try:
                    if response.status_code in _REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise WebsiteError(errors.HTTP_ERROR, "The page redirected without a destination.")
                        redirects += 1
                        if redirects > limits.max_redirects:
                            raise WebsiteError(
                                errors.TOO_MANY_REDIRECTS,
                                f"The page redirected more than {limits.max_redirects} times.",
                            )
                        try:
                            current = normalize_url(urljoin(current, location))
                        except WebsiteError as exc:
                            raise WebsiteError(
                                errors.REDIRECT_BLOCKED,
                                "The page redirected to a destination that cannot be fetched.",
                            ) from exc
                        continue
                    return self._read(response, current, started, deadline, redirects, should_cancel)
                finally:
                    response.close()

    def _read(self, response, url, started, deadline, redirects, should_cancel) -> FetchResult:
        import httpx

        status = response.status_code
        if status in (401, 403, 407, 451):
            raise WebsiteError(
                errors.ACCESS_RESTRICTED,
                f"The website refused access (HTTP {status}). Pages behind logins, paywalls or "
                "bot protection cannot be indexed.",
            )
        if not 200 <= status < 300:
            raise WebsiteError(errors.HTTP_ERROR, f"The website answered with HTTP {status}.")
        media, charset = _parse_content_type(response.headers.get("content-type", ""))
        if media == "application/pdf":
            raise WebsiteError(
                errors.PDF_CONTENT, "This URL is a PDF. Upload PDFs in Documents instead."
            )
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._limits.max_bytes:
            raise WebsiteError(errors.TOO_LARGE, "The page is too large to index.")
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self._limits.max_bytes:
                    raise WebsiteError(errors.TOO_LARGE, "The page is too large to index.")
                if self._clock() > deadline:
                    raise WebsiteError(errors.TIMEOUT, "The page took too long to load.")
                if should_cancel():
                    raise WebsiteError(errors.CANCELLED, "Indexing was cancelled.")
                chunks.append(chunk)
        except httpx.TimeoutException as exc:
            raise WebsiteError(errors.TIMEOUT, "The page took too long to load.") from exc
        except httpx.HTTPError as exc:
            raise WebsiteError(errors.CONNECTION_FAILED, "The connection was interrupted.") from exc
        body = b"".join(chunks)
        if body.lstrip()[:5] == b"%PDF-":
            raise WebsiteError(
                errors.PDF_CONTENT, "This URL is a PDF. Upload PDFs in Documents instead."
            )
        if not media:
            head = body[:512].lstrip().lower()
            media = "text/html" if head.startswith((b"<!doctype html", b"<html")) else ""
        if media not in _HTML_TYPES + _TEXT_TYPES:
            raise WebsiteError(
                errors.UNSUPPORTED_CONTENT,
                f"This URL returns {media or 'unknown content'}, not a webpage.",
            )
        elapsed = int((self._clock() - started) * 1000)
        logger.info(
            "Website fetch: %s -> HTTP %d, %s, %d bytes, %d redirect(s), %d ms.",
            url, status, media, size, redirects, elapsed,
        )
        return FetchResult(
            final_url=url,
            status_code=status,
            content_type=media,
            charset=charset,
            body=body,
            elapsed_ms=elapsed,
            redirects=redirects,
        )
