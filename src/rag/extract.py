"""Text extraction for uploaded documents (PDF / TXT / Markdown)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}


class ExtractionError(Exception):
    """Raised when a document cannot be read or contains no text."""


def file_type_for(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".md", ".markdown")):
        return "md"
    if name.endswith(".txt"):
        return "txt"
    raise ExtractionError(
        "Unsupported file type. Allowed: PDF, TXT, Markdown (.md)."
    )


def extract_pages(data: bytes, file_type: str) -> list[tuple[int | None, str]]:
    """Return [(page_number_or_None, text)] for a document's raw bytes."""
    if file_type == "pdf":
        return _extract_pdf(data)
    try:
        text = data.decode("utf-8", errors="replace").strip()
    except Exception as exc:  # pragma: no cover - decode with replace rarely fails
        raise ExtractionError(f"Could not decode text file: {exc}") from exc
    if not text:
        raise ExtractionError("The file contains no extractable text.")
    return [(None, text)]


def _extract_pdf(data: bytes) -> list[tuple[int | None, str]]:
    import io

    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages: list[tuple[int | None, str]] = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append((number, text))
    except PyPdfError as exc:
        raise ExtractionError(f"Invalid or unreadable PDF: {exc}") from exc
    if not pages:
        raise ExtractionError(
            "No extractable text found in the PDF (it may be scanned images)."
        )
    return pages
