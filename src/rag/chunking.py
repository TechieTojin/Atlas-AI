"""Deterministic text chunking with page provenance."""

from __future__ import annotations

from src.models.documents import DocumentChunk


def chunk_pages(
    document_id: str,
    pages: list[tuple[int | None, str]],
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[DocumentChunk]:
    """Split page texts into overlapping character chunks.

    Chunks never cross page boundaries, so each chunk carries an exact page
    number for citation provenance. Splits prefer paragraph/sentence breaks
    near the target size.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size // 2))
    chunks: list[DocumentChunk] = []
    index = 0
    for page, text in pages:
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            if end < len(text):
                # Prefer a natural break in the last 20% of the window.
                window = text[start:end]
                for sep in ("\n\n", ". ", "\n", " "):
                    cut = window.rfind(sep)
                    if cut >= int(chunk_size * 0.8):
                        end = start + cut + len(sep)
                        break
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=index,
                        page=page,
                        content=piece,
                    )
                )
                index += 1
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks
