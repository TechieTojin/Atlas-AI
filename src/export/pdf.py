"""PDF export for Atlas research reports.

Generates the PDF from persisted report data (never screenshots or a
browser) with fpdf2, rendering a safe subset of Markdown: headings, bullet /
numbered lists, bold markers stripped, links flattened to "text (url)", and
simple tables as aligned text. All report content is written as TEXT — there
is no HTML path, so script/HTML injection in evidence cannot execute.

Unicode: a system TTF (configurable via ATLAS_PDF_FONT) is used when
available; otherwise text degrades gracefully to Latin-1 with replacement.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from fpdf import FPDF

from src.models.runs import ResearchRun

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
_BOLD_CANDIDATES = (
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_MD_EMPHASIS_RE = re.compile(r"(\*\*|\*|__|`)")


class _AtlasPdf(FPDF):
    def __init__(self, unicode_ok: bool) -> None:
        super().__init__(format="A4")
        self.unicode_ok = unicode_ok
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self) -> None:  # page numbers
        self.set_y(-12)
        self.set_font_size(8)
        self.cell(0, 8, f"Atlas · page {self.page_no()}", align="C")


def _find_font(configured: str, candidates: tuple[str, ...]) -> str | None:
    paths = ([configured] if configured else []) + list(candidates)
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None


def _clean_inline(text: str) -> str:
    """Flatten inline markdown deterministically."""
    text = _MD_LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    return _MD_EMPHASIS_RE.sub("", text)


def _sanitize(text: str, unicode_ok: bool) -> str:
    text = text.replace("\r", "")
    if unicode_ok:
        return text
    return text.encode("latin-1", errors="replace").decode("latin-1")


def render_run_pdf(run: ResearchRun, font_path: str = "") -> bytes:
    """Render a completed run's report to PDF bytes."""
    body_font = _find_font(font_path, _FONT_CANDIDATES)
    bold_font = _find_font("", _BOLD_CANDIDATES)
    unicode_ok = body_font is not None

    pdf = _AtlasPdf(unicode_ok)
    if body_font:
        pdf.add_font("atlas", "", body_font)
        pdf.add_font("atlas", "B", bold_font or body_font)
        family = "atlas"
    else:
        family = "helvetica"
        logger.warning("No TTF font found; PDF falls back to Latin-1 text.")

    def text(content: str, size: int = 10, style: str = "", leading: float = 5.2):
        pdf.set_font(family, style, size)
        pdf.multi_cell(
            0, leading, _sanitize(content, unicode_ok),
            new_x="LMARGIN", new_y="NEXT",
        )

    pdf.add_page()

    # --- Branding / metadata header ---
    pdf.set_font(family, "B", 22)
    pdf.cell(0, 12, "Atlas", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(family, "", 10)
    pdf.cell(0, 6, "Research Report", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    text(f"Question: {run.query}", size=12, style="B", leading=6)
    meta = [
        f"Mode: {run.mode.value}",
        f"Template: {run.template}",
        f"Created: {run.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    if run.completed_at:
        meta.append(f"Completed: {run.completed_at.strftime('%Y-%m-%d %H:%M UTC')}")
    if run.project_id:
        meta.append(f"Project: {run.project_id}")
    text(" · ".join(meta), size=9)
    pdf.ln(2)
    pdf.set_draw_color(150, 150, 150)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)

    # --- Report body (safe markdown subset) ---
    for raw_line in run.final_report.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            pdf.ln(2)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            pdf.ln(2)
            text(_clean_inline(heading.group(2)), size=max(16 - 2 * level, 11),
                 style="B", leading=7)
            pdf.ln(1)
        elif stripped.startswith(("- ", "* ")):
            text("  •  " + _clean_inline(stripped[2:]))
        elif re.match(r"^\d+\.\s", stripped):
            text("  " + _clean_inline(stripped))
        elif stripped.startswith("|"):
            # Simple table row -> aligned text; separator rows skipped.
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                text("  " + "   ".join(_clean_inline(c) for c in cells), size=9)
        else:
            text(_clean_inline(stripped))

    # --- Metrics summary ---
    m = run.metrics
    pdf.ln(4)
    text("Run Metrics", size=12, style="B", leading=6)
    tiers = ", ".join(f"{k}: {v}" for k, v in sorted(m.source_quality_tiers.items()))
    metrics_lines = [
        f"Total runtime: {m.total_ms / 1000:.0f}s · Iterations: {m.iterations} · "
        f"Queries: {m.search_queries_executed}",
        f"Sources collected/selected/cited: {m.sources_collected}/"
        f"{m.sources_selected}/{m.sources_cited} · "
        f"Citation coverage: {m.citation_coverage:.0%}",
    ]
    if tiers:
        metrics_lines.append(f"Source quality tiers: {tiers}")
    if m.pages_fetched or m.pages_attempted:
        metrics_lines.append(
            f"Pages fetched: {m.pages_fetched}/{m.pages_attempted} "
            f"(snippet fallbacks: {m.snippet_fallbacks})"
        )
    for line in metrics_lines:
        text(line, size=9)

    pdf.set_creation_date(datetime.now())
    return bytes(pdf.output())


def safe_pdf_filename(run: ResearchRun) -> str:
    """``atlas-<question-slug>.pdf``; the run id when the question has no usable characters.

    ASCII questions slug exactly as before. Unicode letters, marks and digits
    are kept (never cut inside a syllable); Windows-invalid characters,
    symbols and emoji are dropped.
    """
    from src.unicode_text import filename_safe, truncate_clusters

    base = truncate_clusters(filename_safe(run.query), 40).strip().replace(" ", "-")
    return f"atlas-{base or run.id[:8]}.pdf"


def pdf_content_disposition(run: ResearchRun) -> str:
    """Attachment header for the PDF export.

    HTTP header values must be Latin-1, so a Unicode file name goes in the
    RFC 5987 ``filename*`` parameter with an ASCII ``filename`` fallback.
    ASCII names produce exactly the old header.
    """
    from urllib.parse import quote

    name = safe_pdf_filename(run)
    if name.isascii():
        return f'attachment; filename="{name}"'
    fallback = f"atlas-{run.id[:8]}.pdf"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"
