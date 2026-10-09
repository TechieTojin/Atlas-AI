"""Section-aware chunking of extracted page blocks.

Chunks are built from whole blocks (paragraphs, list items, table rows),
never from a blind character window, and a heading of level <= 3 starts a new
chunk once the current one holds some content. Each chunk records the
heading trail where its content begins, plus character offsets into the
cleaned page text, for citation provenance.

Size is measured in ESTIMATED tokens so English and Indic pages get similar
budgets: about four ASCII characters per token, and about 1.5 characters per
token for other scripts (Devanagari/Malayalam split into many more tokens).
Target ~550 tokens, hard ceiling ~800, with a modest overlap: the last short
block of a chunk is repeated at the start of the next chunk of the same
section. A single block larger than the ceiling is split at sentence
boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.unicode_text import SENTENCE_BOUNDARY_RE
from src.website.extract import Block

TARGET_TOKENS = 550
MAX_TOKENS = 800
#: A size-based split happens only once a chunk holds this much.
MIN_TOKENS = 120
#: A heading closes the current chunk once it holds this much content.
MIN_SECTION_TOKENS = 60
OVERLAP_MAX_TOKENS = 120
#: Overlap carried from a long final block: its last sentences, at most this many tokens.
OVERLAP_SENTENCE_TOKENS = 80


def estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    other = len(text) - ascii_chars
    return max(1, round(ascii_chars / 4 + other / 1.5))


@dataclass
class ChunkDraft:
    chunk_index: int
    section_title: str
    heading_path: list[str]
    text: str
    char_start: int
    char_end: int
    tokens: int = 0


@dataclass
class _Piece:
    block: Block
    start: int
    end: int
    tokens: int
    #: Heading trail in effect where this piece appears.
    path: list[str] = field(default_factory=list)


def _render(block: Block) -> str:
    if block.kind == "heading":
        return f"{'#' * min(block.level, 6)} {block.text}"
    if block.kind == "list_item":
        return f"- {block.text}"
    return block.text


class _Builder:
    def __init__(self) -> None:
        self.drafts: list[ChunkDraft] = []
        self.pieces: list[_Piece] = []
        self.heading_path: list[str] = []

    def content_tokens(self) -> int:
        return sum(p.tokens for p in self.pieces if p.block.kind != "heading")

    def tokens(self) -> int:
        return sum(p.tokens for p in self.pieces)

    def emit(self, keep_overlap: bool) -> None:
        content = [p for p in self.pieces if p.block.kind != "heading"]
        if not content:
            return
        # A chunk spanning sections (a short intro merged with the next
        # section) is labelled with the section holding most of its content;
        # ties go to the earlier section.
        weights: dict[tuple[str, ...], int] = {}
        for piece in content:
            weights[tuple(piece.path)] = weights.get(tuple(piece.path), 0) + piece.tokens
        path = list(max(weights, key=lambda key: weights[key]))
        self.drafts.append(
            ChunkDraft(
                chunk_index=len(self.drafts),
                section_title=path[-1] if path else "",
                heading_path=list(path),
                text="\n".join(_render(p.block) for p in self.pieces),
                char_start=self.pieces[0].start,
                char_end=self.pieces[-1].end,
                tokens=self.tokens(),
            )
        )
        last = self.pieces[-1]
        self.pieces = []
        if not keep_overlap or last.block.kind == "heading":
            return
        if last.tokens <= OVERLAP_MAX_TOKENS:
            self.pieces = [last]
            return
        # A long final block carries only its closing sentences forward.
        tail: list[str] = []
        for sentence in reversed(SENTENCE_BOUNDARY_RE.split(last.block.text)):
            if estimate_tokens(" ".join([sentence, *tail])) > OVERLAP_SENTENCE_TOKENS:
                break
            tail.insert(0, sentence)
        if tail and len(tail) < len(SENTENCE_BOUNDARY_RE.split(last.block.text)):
            text = " ".join(tail)
            self.pieces = [
                _Piece(Block(last.block.kind, text, last.block.level), last.end - len(text), last.end,
                       estimate_tokens(text), last.path)
            ]


def _split_large(block: Block) -> list[Block]:
    sentences = [s for s in SENTENCE_BOUNDARY_RE.split(block.text) if s.strip()]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and estimate_tokens(candidate) > TARGET_TOKENS:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    # A "sentence" still too long (no terminators) is cut at a space.
    result: list[Block] = []
    for text in parts:
        while estimate_tokens(text) > MAX_TOKENS:
            cut = len(text) // 2
            space = text.rfind(" ", 0, cut)
            cut = space if space > len(text) // 4 else cut
            result.append(Block(block.kind, text[:cut].strip(), block.level))
            text = text[cut:].strip()
        if text:
            result.append(Block(block.kind, text, block.level))
    return result


def chunk_blocks(blocks: list[Block]) -> list[ChunkDraft]:
    builder = _Builder()
    offset = 0
    for block in blocks:
        start, end = offset, offset + len(block.text)
        offset = end + 2  # blocks are joined by a blank line in the page text
        if block.kind == "heading":
            if block.level <= 3 and builder.content_tokens() >= MIN_SECTION_TOKENS:
                builder.emit(keep_overlap=False)
            level = min(block.level, 6)
            builder.heading_path = builder.heading_path[: level - 1] + [block.text]
            builder.pieces.append(
                _Piece(block, start, end, estimate_tokens(block.text), list(builder.heading_path))
            )
            continue
        parts = [block] if estimate_tokens(block.text) <= MAX_TOKENS else _split_large(block)
        for part in parts:
            tokens = estimate_tokens(part.text)
            if builder.tokens() + tokens > TARGET_TOKENS and builder.content_tokens() >= MIN_TOKENS:
                builder.emit(keep_overlap=True)
            builder.pieces.append(_Piece(part, start, end, tokens, list(builder.heading_path)))
    builder.emit(keep_overlap=False)
    return builder.drafts
