"""PDF export for Atlas research reports.

Generates the PDF from persisted report data (never screenshots or a
browser) with fpdf2, rendering a safe subset of Markdown: headings, bullet /
numbered lists, bold markers stripped, links flattened to "text (url)", and
simple tables as aligned text. All report content is written as TEXT — there
is no HTML path, so script/HTML injection in evidence cannot execute.

Unicode: a system TTF (configurable via ATLAS_PDF_FONT) is used for Latin
text; bundled Noto Sans Malayalam and Noto Sans Devanagari fonts are fallbacks
for those scripts, shaped with HarfBuzz (``uharfbuzz``) so conjuncts, chillus
and vowel signs render correctly. Shaping is only switched on for documents
that contain such text, so English PDFs are produced exactly as before.
Without any TTF, text degrades to Latin-1 with replacement.
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

#: Bundled script fonts (SIL OFL 1.1, see fonts/OFL.txt). Backend-only files.
_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_SCRIPT_FONTS = (
    # family, regular, bold, Unicode block
    ("atlas-ml", "NotoSansMalayalam-Regular.ttf", "NotoSansMalayalam-Bold.ttf", (0x0D00, 0x0D7F)),
    ("atlas-hi", "NotoSansDevanagari-Regular.ttf", "NotoSansDevanagari-Bold.ttf", (0x0900, 0x097F)),
)

#: Labels Atlas writes into the PDF itself, in the report's own language.
_LABELS = {
    "en": ("Research Report", "Question", "Mode", "Template", "Created", "Completed", "Project", "Run Metrics"),
    "es": ("Informe de investigación", "Pregunta", "Modo", "Plantilla", "Creado", "Completado", "Proyecto", "Métricas de la investigación"),
    "fr": ("Rapport de recherche", "Question", "Mode", "Modèle", "Créé", "Terminé", "Projet", "Métriques de la recherche"),
    "de": ("Recherchebericht", "Frage", "Modus", "Vorlage", "Erstellt", "Abgeschlossen", "Projekt", "Recherche-Metriken"),
    "hi": ("अनुसंधान रिपोर्ट", "प्रश्न", "मोड", "टेम्पलेट", "बनाया गया", "पूरा हुआ", "प्रोजेक्ट", "रन मेट्रिक्स"),
    "ml": ("ഗവേഷണ റിപ്പോർട്ട്", "ചോദ്യം", "മോഡ്", "ടെംപ്ലേറ്റ്", "സൃഷ്ടിച്ചത്", "പൂർത്തിയായത്", "പ്രോജക്റ്റ്", "റൺ മെട്രിക്സ്"),
}


def _needs_shaping(text: str) -> bool:
    """Whether ``text`` contains a script that needs HarfBuzz shaping."""
    return any(
        start <= ord(char) <= end
        for char in text
        for _family, _regular, _bold, (start, end) in _SCRIPT_FONTS
    )


def _enable_script_fonts(pdf: FPDF, language: str = "en") -> bool:
    """Register the bundled script fonts as fallbacks and turn shaping on.

    The report language's own script is tried first: both fonts carry shared
    marks such as the danda, which must come from the matching typeface.
    """
    try:
        import uharfbuzz  # noqa: F401  (fpdf2 shapes text through it)
    except ImportError:
        logger.warning("uharfbuzz is not installed; Indic text in PDFs cannot be shaped.")
        return False
    families = []
    ordered = sorted(_SCRIPT_FONTS, key=lambda font: font[0] != f"atlas-{language}")
    for family, regular, bold, _block in ordered:
        pdf.add_font(family, "", os.path.join(_FONT_DIR, regular))
        pdf.add_font(family, "B", os.path.join(_FONT_DIR, bold))
        families.append(family)
    pdf.set_fallback_fonts(families)
    pdf.set_text_shaping(True)
    return True


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


def pdf_labels(language: str) -> dict[str, str]:
    from src.languages import stored_output_language

    keys = ("report", "question", "mode", "template", "created", "completed", "project", "metrics")
    return dict(zip(keys, _LABELS[stored_output_language(language)]))


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
    from src.languages import stored_output_language

    if unicode_ok and _needs_shaping(f"{run.query}\n{run.final_report}"):
        _enable_script_fonts(pdf, stored_output_language(run.output_language))

    (label_report, label_question, label_mode, label_template, label_created,
     label_completed, label_project, label_metrics) = _LABELS[stored_output_language(run.output_language)]

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
    pdf.cell(0, 6, label_report, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    text(f"{label_question}: {run.query}", size=12, style="B", leading=6)
    meta = [
        f"{label_mode}: {run.mode.value}",
        f"{label_template}: {run.template}",
        f"{label_created}: {run.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    if run.completed_at:
        meta.append(f"{label_completed}: {run.completed_at.strftime('%Y-%m-%d %H:%M UTC')}")
    if run.project_id:
        meta.append(f"{label_project}: {run.project_id}")
    text(" · ".join(meta), size=9)
    pdf.ln(2)
    pdf.set_draw_color(150, 150, 150)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)

    # --- Report body (safe markdown subset) ---
    from src.export.labels import export_labels, localize_report_markers

    labels = export_labels(run.output_language)
    for raw_line in localize_report_markers(run.final_report, run.output_language).splitlines():
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
    text(label_metrics, size=12, style="B", leading=6)
    tiers = ", ".join(f"{k}: {v}" for k, v in sorted(m.source_quality_tiers.items()))
    metrics_lines = [
        labels["runtime"].format(
            seconds=f"{m.total_ms / 1000:.0f}", iterations=m.iterations,
            queries=m.search_queries_executed,
        ),
        labels["counts"].format(
            collected=m.sources_collected, selected=m.sources_selected,
            cited=m.sources_cited, coverage=f"{m.citation_coverage:.0%}",
        ),
    ]
    if tiers:
        metrics_lines.append(labels["tiers"].format(tiers=tiers))
    if m.pages_fetched or m.pages_attempted:
        metrics_lines.append(labels["pages"].format(
            fetched=m.pages_fetched, attempted=m.pages_attempted, fallbacks=m.snippet_fallbacks,
        ))
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
