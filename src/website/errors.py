"""User-facing Website Chat failures.

Every failure carries a stable ``code`` the UI translates; ``message`` is a
plain English explanation for logs and API clients. Neither ever contains a
stack trace, a response body or request headers.
"""

from __future__ import annotations


class WebsiteError(Exception):
    #: HTTP status the API should answer with when raised synchronously.
    http_status = 422

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WebsiteNotFoundError(WebsiteError):
    http_status = 404

    def __init__(self, what: str = "Website") -> None:
        super().__init__("not_found", f"{what} not found.")


class WebsiteStateError(WebsiteError):
    http_status = 409


# Codes (kept in one place so the frontend dictionary can mirror them).
INVALID_URL = "invalid_url"
UNSUPPORTED_SCHEME = "unsupported_scheme"
CREDENTIALS_IN_URL = "credentials_in_url"
BLOCKED_ADDRESS = "blocked_address"
DNS_FAILURE = "dns_failure"
REDIRECT_BLOCKED = "redirect_blocked"
TOO_MANY_REDIRECTS = "too_many_redirects"
TIMEOUT = "timeout"
#: The Website Chat answer deadline was reached (distinct from a slow website).
ANSWER_TIMEOUT = "answer_timeout"
CONNECTION_FAILED = "connection_failed"
TOO_LARGE = "too_large"
PDF_CONTENT = "pdf_content"
UNSUPPORTED_CONTENT = "unsupported_content"
HTTP_ERROR = "http_error"
ACCESS_RESTRICTED = "access_restricted"
EMPTY_CONTENT = "empty_content"
JS_REQUIRED = "js_required"
TOO_LONG = "too_long"
EMBEDDING_FAILED = "embedding_failed"
LLM_FAILED = "llm_failed"
UNUSABLE_ANSWER = "unusable_answer"
INTERRUPTED = "interrupted"
PROCESSING_FAILED = "processing_failed"
NOT_READY = "not_ready"
BUSY = "busy"
EMPTY_QUESTION = "empty_question"
QUESTION_TOO_LONG = "question_too_long"
CANCELLED = "cancelled"
