"""Export a Document to Markdown.

Markdown is the lingua franca of LLMs. This adapter converts a Document
back to clean Markdown, enabling:
  - Round-trip: LLM -> JSON spec -> Document -> Markdown -> LLM
  - Conversion: Markdown -> pandoc -> PPTX, DOCX, LaTeX
  - Preview: render in any Markdown viewer
  - Editing: modify the document in a text editor, re-render to PDF
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..spec import Document

__all__ = ["to_markdown"]


def to_markdown(document: "Document", *, include_metadata: bool = True) -> str:
    """Convert a Document to clean Markdown."""
    from ..spec import (
        BulletList,
        BibliographyBlock,
        Callout,
        Chart,
        CodeBlock,
        DocumentControl,
        Footnote,
        Heading,
        HorizontalRule,
        Image,
        MathBlock,
        NumberedList,
        PageBreak,
        Paragraph,
        Table,
    )

    parts: list[str] = []

    if include_metadata and (document.title or document.author):
        parts.append("---")
        if document.title:
            parts.append(f"title: {_yaml_str(document.title)}")
        if document.author:
            parts.append(f"author: {_yaml_str(document.author)}")
        if document.subject:
            parts.append(f"subject: {_yaml_str(document.subject)}")
        if document.language:
            parts.append(f"lang: {document.language}")
        parts.append("---")
        parts.append("")

    for element in document.content:
        if isinstance(element, Heading):
            prefix = "#" * element.level
            numbering = f"{element.numbering} " if element.numbering else ""
            parts.append(f"{prefix} {numbering}{element.text}")
            parts.append("")

        elif isinstance(element, Paragraph):
            parts.append(_render_runs_md(element.runs))
            parts.append("")

        elif isinstance(element, BulletList):
            for item_runs in element.item_runs:
                text = _render_runs_md(item_runs)
                parts.append(f"- {text}")
            parts.append("")

        elif isinstance(element, NumberedList):
            for i, item_runs in enumerate(element.item_runs):
                text = _render_runs_md(item_runs)
                parts.append(f"{element.start + i}. {text}")
            parts.append("")

        elif isinstance(element, Table):
            parts.append(_render_table_md(element))
            parts.append("")

        elif isinstance(element, Image):
            src = element.source if isinstance(element.source, str) else "image"
            alt = element.alt_text or "image"
            parts.append(f"![{alt}]({src})")
            if element.caption:
                parts.append(f"*{element.caption}*")
            parts.append("")

        elif isinstance(element, Chart):
            if element.title:
                parts.append(f"**{element.title}**")
                parts.append("")
            headers = [str(lab) for lab in element.labels]
            values = [str(v) for v in element.values]
            parts.append("| " + " | ".join(headers) + " |")
            parts.append("| " + " | ".join("---" for _ in headers) + " |")
            parts.append("| " + " | ".join(values) + " |")
            parts.append("")

        elif isinstance(element, Footnote):
            marker = element.marker or "*"
            text = _render_runs_md(element.runs)
            parts.append(f"[^{marker}]: {text}")
            parts.append("")

        elif isinstance(element, Callout):
            title = f"**{element.title}**\n> " if element.title else ""
            text = _render_runs_md(element.runs)
            icon = f"{element.icon} " if element.icon else ""
            parts.append(f"> {icon}{title}{text}")
            parts.append("")

        elif isinstance(element, CodeBlock):
            lang = element.language if element.language != "text" else ""
            parts.append(f"```{lang}")
            parts.append(element.code)
            parts.append("```")
            if element.caption:
                parts.append(f"*{element.caption}*")
            parts.append("")

        elif isinstance(element, MathBlock):
            if element.display:
                parts.append(f"$${element.source}$$")
            else:
                parts.append(f"${element.source}$")
            if element.caption:
                parts.append(f"*{element.caption}*")
            parts.append("")

        elif isinstance(element, BibliographyBlock):
            from ..bibliography import format_bibliography

            if element.title:
                prefix = "#" * element.heading_level
                parts.append(f"{prefix} {element.title}")
                parts.append("")
            entries = format_bibliography(element.citations, element.bib_style)
            for entry in entries:
                parts.append(entry)
                parts.append("")

        elif isinstance(element, HorizontalRule):
            parts.append("---")
            parts.append("")

        elif isinstance(element, PageBreak):
            parts.append("\\newpage")
            parts.append("")

        elif isinstance(element, DocumentControl):
            for sub in element.to_blocks():
                if isinstance(sub, Table):
                    parts.append(_render_table_md(sub))
                else:
                    parts.append(_render_runs_md(sub.runs))
                parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _yaml_str(value: str) -> str:
    if any(c in value for c in ":{}[]#&*!|>'\"%@`"):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _render_runs_md(runs: list) -> str:
    parts = []
    for run in runs:
        text = run.text
        if run.bold and run.italic:
            text = f"***{text}***"
        elif run.bold:
            text = f"**{text}**"
        elif run.italic:
            text = f"*{text}*"
        if run.link:
            text = f"[{text}]({run.link})"
        parts.append(text)
    return "".join(parts)


def _render_table_md(table) -> str:
    headers = [cell.plain_text for cell in table.header_cells]
    rows = [[cell.plain_text for cell in row] for row in table.body_rows]

    col_count = max(
        len(headers),
        *(len(r) for r in rows) if rows else [0],
    )

    while len(headers) < col_count:
        headers.append("")

    col_widths = [len(h) for h in headers]
    for row in rows:
        while len(row) < col_count:
            row.append("")
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    col_widths = [max(w, 3) for w in col_widths]

    def format_row(cells: list[str]) -> str:
        formatted = [cell.ljust(col_widths[i]) for i, cell in enumerate(cells)]
        return "| " + " | ".join(formatted) + " |"

    alignments = []
    for i, cell in enumerate(table.header_cells):
        align = getattr(cell, "align", "left")
        if align in ("right", "decimal"):
            alignments.append("-" * (col_widths[i] - 1) + ":")
        elif align == "center":
            alignments.append(":" + "-" * (col_widths[i] - 2) + ":")
        else:
            alignments.append("-" * col_widths[i])
    while len(alignments) < col_count:
        alignments.append("-" * col_widths[len(alignments)])

    separator = "| " + " | ".join(alignments) + " |"

    lines = [format_row(headers), separator]
    for row in rows:
        lines.append(format_row(row))

    if table.caption:
        lines.append("")
        lines.append(f"*{table.caption}*")

    return "\n".join(lines)
