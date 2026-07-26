"""Export a Document to a structured representation for DOCX/PPTX conversion.

Rather than depending on python-docx or python-pptx directly (which would
add heavy dependencies), this module exports a clean intermediate dict
that any conversion tool can consume:

    from emboss.adapters.docx_export import to_office_dict
    data = to_office_dict(document)
    # Feed to python-docx, pandoc, or any converter

The dict mirrors the Open XML structure closely enough that conversion
is mechanical, but uses plain Python types so no Office libraries are
required at export time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..spec import Document

__all__ = ["to_office_dict"]


def to_office_dict(document: "Document") -> dict:
    """Convert a Document to a structured dict for Office format conversion.

    Returns a dict with:
      - metadata: title, author, subject, keywords, language
      - styles: resolved style presets as CSS-like properties
      - content: ordered list of typed blocks with full formatting
    """
    from ..spec import (
        BibliographyBlock,
        BulletList,
        Callout,
        Chart,
        CodeBlock,
        Footnote,
        Heading,
        HorizontalRule,
        Image,
        MathBlock,
        PageBreak,
        Paragraph,
        Table,
    )

    sheet = document.stylesheet
    blocks = []

    for element in document.content:
        if isinstance(element, Heading):
            blocks.append({
                "type": "heading",
                "level": element.level,
                "text": element.text,
                "numbering": element.numbering,
                "runs": _serialize_runs(element.runs),
            })

        elif isinstance(element, Paragraph):
            style = sheet.resolved(sheet.body, element.style)
            blocks.append({
                "type": "paragraph",
                "runs": _serialize_runs(element.runs),
                "align": style.require("align"),
                "indent_first": style.indent_first or 0,
            })

        elif isinstance(element, BulletList):
            items = []
            for item_runs in element.item_runs:
                items.append({"runs": _serialize_runs(item_runs)})
            blocks.append({
                "type": "list",
                "bullet": element.bullet,
                "items": items,
            })

        elif isinstance(element, Table):
            blocks.append(_serialize_table(element))

        elif isinstance(element, Image):
            blocks.append({
                "type": "image",
                "source": element.source if isinstance(element.source, str) else "<bytes>",
                "alt_text": element.alt_text,
                "width": element.width,
                "height": element.height,
                "caption": element.caption,
                "align": element.align,
            })

        elif isinstance(element, Chart):
            blocks.append({
                "type": "chart",
                "chart_type": element.chart_type,
                "labels": list(element.labels),
                "values": list(element.values),
                "title": element.title,
                "width": element.width,
                "height": element.height,
            })

        elif isinstance(element, Footnote):
            blocks.append({
                "type": "footnote",
                "marker": element.marker,
                "runs": _serialize_runs(element.runs),
            })

        elif isinstance(element, Callout):
            blocks.append({
                "type": "callout",
                "variant": element.variant,
                "title": element.title,
                "runs": _serialize_runs(element.runs),
                "background": element.background,
                "border_color": element.border_color,
            })

        elif isinstance(element, CodeBlock):
            blocks.append({
                "type": "code_block",
                "code": element.code,
                "language": element.language,
                "line_numbers": element.line_numbers,
                "caption": element.caption,
            })

        elif isinstance(element, MathBlock):
            blocks.append({
                "type": "math",
                "source": element.source,
                "display": element.display,
                "caption": element.caption,
            })

        elif isinstance(element, BibliographyBlock):
            from ..bibliography import format_bibliography
            blocks.append({
                "type": "bibliography",
                "title": element.title,
                "heading_level": element.heading_level,
                "entries": format_bibliography(
                    element.citations, element.bib_style
                ),
            })

        elif isinstance(element, HorizontalRule):
            blocks.append({"type": "horizontal_rule"})

        elif isinstance(element, PageBreak):
            blocks.append({"type": "page_break"})

    page = document.page
    return {
        "metadata": {
            "title": document.title,
            "author": document.author,
            "subject": document.subject,
            "keywords": document.keywords,
            "language": document.language,
        },
        "page": {
            "width_pt": page.width,
            "height_pt": page.height,
            "margin_top_pt": page.margin_top,
            "margin_right_pt": page.margin_right,
            "margin_bottom_pt": page.margin_bottom,
            "margin_left_pt": page.margin_left,
        },
        "content": blocks,
    }


def _serialize_runs(runs: list) -> list[dict]:
    return [
        {
            "text": run.text,
            "bold": run.bold,
            "italic": run.italic,
            "font_size": run.font_size,
            "font_family": run.font_family,
            "color": run.color,
            "link": run.link,
        }
        for run in runs
    ]


def _serialize_table(table) -> dict:
    headers = []
    for cell in table.header_cells:
        headers.append({
            "text": cell.plain_text,
            "align": cell.align,
            "bold": cell.bold,
        })

    rows = []
    for row in table.body_rows:
        cells = []
        for cell in row:
            cells.append({
                "text": cell.plain_text,
                "align": cell.align,
                "bold": cell.bold,
                "background": cell.background,
            })
        rows.append(cells)

    return {
        "type": "table",
        "headers": headers,
        "rows": rows,
        "caption": table.caption,
        "stripe": table.stripe,
    }
