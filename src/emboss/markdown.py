"""Markdown-to-EmbossSpec converter.

Parses standard Markdown into Emboss document elements so that LLM output
(which is naturally Markdown) can be rendered as high-quality PDFs without
any schema wrangling.

    from emboss import Document
    doc = Document.from_markdown("# Hello\\nWorld", style="corporate")
    doc.save("output.pdf")
"""

from __future__ import annotations

import re

from .spec import (
    BulletList,
    Callout,
    CodeBlock,
    Heading,
    HorizontalRule,
    Image,
    MathBlock,
    NumberedList,
    PageBreak,
    Paragraph,
    Table,
    TextRun,
)

__all__ = ["parse_markdown"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#*)?$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^(\s*)\d+[.)]\s+(.+)$")
_IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")
_HR_RE = re.compile(r"^(?:[-*_]\s*){3,}$")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_MATH_BLOCK_RE = re.compile(r"^\$\$\s*$")
_CALLOUT_RE = re.compile(
    r"^>\s*\[!(NOTE|TIP|WARNING|CAUTION|IMPORTANT)\]\s*$", re.IGNORECASE
)
_BLOCKQUOTE_RE = re.compile(r"^>\s?(.*)")
_PAGE_BREAK_RE = re.compile(r"^\\newpage\s*$|^---pagebreak---\s*$", re.IGNORECASE)

_INLINE_BOLD_ITALIC = re.compile(r"\*\*\*(.+?)\*\*\*|___(.+?)___")
_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_INLINE_ITALIC = re.compile(r"\*(.+?)\*|_(.+?)_")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_INLINE_MATH = re.compile(r"\$([^$]+)\$")
_INLINE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _parse_inline(text: str) -> list[TextRun]:
    """Parse inline Markdown formatting into TextRun objects."""
    runs: list[TextRun] = []
    pos = 0

    patterns = [
        (
            _INLINE_BOLD_ITALIC,
            lambda m: TextRun(text=m.group(1) or m.group(2), bold=True, italic=True),
        ),
        (_INLINE_BOLD, lambda m: TextRun(text=m.group(1) or m.group(2), bold=True)),
        (_INLINE_ITALIC, lambda m: TextRun(text=m.group(1) or m.group(2), italic=True)),
        (_INLINE_CODE, lambda m: TextRun(text=m.group(1), font_family="Courier")),
    ]

    while pos < len(text):
        best_match = None
        best_start = len(text)
        best_handler = None

        for pattern, handler in patterns:
            m = pattern.search(text, pos)
            if m and m.start() < best_start:
                best_match = m
                best_start = m.start()
                best_handler = handler

        if best_match is None:
            remainder = text[pos:]
            if remainder:
                runs.append(TextRun(text=remainder))
            break

        if best_start > pos:
            runs.append(TextRun(text=text[pos:best_start]))

        runs.append(best_handler(best_match))
        pos = best_match.end()

    return runs if runs else [TextRun(text=text)]


def _parse_table_row(line: str) -> list[str]:
    """Parse a Markdown table row into cell strings."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _parse_table_alignment(sep_line: str) -> list[str]:
    """Parse table separator to determine column alignments."""
    cells = _parse_table_row(sep_line)
    aligns = []
    for cell in cells:
        cell = cell.strip()
        if cell.startswith(":") and cell.endswith(":"):
            aligns.append("center")
        elif cell.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    return aligns


def _collect_list_items(
    lines: list[str], start: int, pattern: re.Pattern, base_indent: int = 0
) -> tuple[list, int]:
    """Collect list items, handling nesting."""
    items: list = []
    i = start

    while i < len(lines):
        m = pattern.match(lines[i])
        if not m:
            bm = (
                _BULLET_RE.match(lines[i])
                if pattern == _NUMBERED_RE
                else _NUMBERED_RE.match(lines[i])
            )
            if bm and len(bm.group(1)) > base_indent:
                sub_pattern = _NUMBERED_RE if pattern == _BULLET_RE else _BULLET_RE
                sub_items, i = _collect_list_items(
                    lines, i, sub_pattern, len(bm.group(1))
                )
                if items:
                    items[-1] = (
                        [items[-1]] + sub_items
                        if isinstance(items[-1], str)
                        else items[-1] + sub_items
                    )
                continue
            break

        indent = len(m.group(1))
        if indent > base_indent and items:
            sub_items, i = _collect_list_items(lines, i, pattern, indent)
            last = items[-1]
            if isinstance(last, str):
                items[-1] = [last] + sub_items
            else:
                items[-1] = last + sub_items
            continue

        if indent < base_indent:
            break

        items.append(m.group(2).strip())
        i += 1

    return items, i


def parse_markdown(text: str) -> list:
    """Parse a Markdown string into a list of Emboss block elements.

    Supports: headings, paragraphs, bullet lists, numbered lists, tables,
    code blocks (fenced), math blocks ($$...$$), images, horizontal rules,
    callout/admonition blocks (> [!NOTE] syntax), and page breaks.
    """
    lines = text.split("\n")
    elements: list = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        if _PAGE_BREAK_RE.match(line.strip()):
            elements.append(PageBreak())
            i += 1
            continue

        hm = _HEADING_RE.match(line)
        if hm:
            level = len(hm.group(1))
            elements.append(Heading(text=hm.group(2).strip(), level=level))
            i += 1
            continue

        if _HR_RE.match(line.strip()):
            elements.append(HorizontalRule())
            i += 1
            continue

        if line.strip().startswith("```"):
            language = line.strip()[3:].strip() or "text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            elements.append(CodeBlock(code="\n".join(code_lines), language=language))
            continue

        if _MATH_BLOCK_RE.match(line.strip()):
            math_lines = []
            i += 1
            while i < len(lines) and not _MATH_BLOCK_RE.match(lines[i].strip()):
                math_lines.append(lines[i])
                i += 1
            i += 1
            elements.append(MathBlock(source="\n".join(math_lines).strip()))
            continue

        cm = _CALLOUT_RE.match(line.strip())
        if cm:
            variant = cm.group(1).lower()
            variant_map = {
                "note": "note",
                "tip": "tip",
                "warning": "warning",
                "caution": "caution",
                "important": "important",
            }
            callout_variant = variant_map.get(variant, "note")
            content_lines = []
            i += 1
            while i < len(lines):
                bq = _BLOCKQUOTE_RE.match(lines[i])
                if bq:
                    content_lines.append(bq.group(1))
                    i += 1
                else:
                    break
            elements.append(
                Callout(
                    content="\n".join(content_lines).strip(),
                    variant=callout_variant,
                )
            )
            continue

        im = _IMAGE_RE.match(line.strip())
        if im:
            alt_text = im.group(1)
            source = im.group(2)
            elements.append(
                Image(source=source, alt_text=alt_text, caption=alt_text or None)
            )
            i += 1
            continue

        if (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1].strip())
        ):
            headers = _parse_table_row(line)
            aligns = _parse_table_alignment(lines[i + 1])
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_parse_table_row(lines[i]))
                i += 1
            from .spec import TableCell

            table_rows = []
            for row in rows:
                table_row = []
                for ci, cell in enumerate(row):
                    align = aligns[ci] if ci < len(aligns) else "left"
                    table_row.append(
                        TableCell(
                            content=cell, align=align if align != "left" else None
                        )
                    )
                table_rows.append(table_row)
            header_cells = []
            for ci, h in enumerate(headers):
                align = aligns[ci] if ci < len(aligns) else "left"
                header_cells.append(
                    TableCell(content=h, align=align if align != "left" else None)
                )
            elements.append(Table(headers=header_cells, rows=table_rows))
            continue

        bm = _BULLET_RE.match(line)
        if bm:
            items, i = _collect_list_items(lines, i, _BULLET_RE)
            elements.append(BulletList(items=items))
            continue

        nm = _NUMBERED_RE.match(line)
        if nm:
            items, i = _collect_list_items(lines, i, _NUMBERED_RE)
            elements.append(NumberedList(items=items))
            continue

        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip():
            next_line = lines[i]
            if (
                _HEADING_RE.match(next_line)
                or _HR_RE.match(next_line.strip())
                or next_line.strip().startswith("```")
                or next_line.strip().startswith("|")
                or _BULLET_RE.match(next_line)
                or _NUMBERED_RE.match(next_line)
                or _IMAGE_RE.match(next_line.strip())
                or _MATH_BLOCK_RE.match(next_line.strip())
                or _CALLOUT_RE.match(next_line.strip())
                or _PAGE_BREAK_RE.match(next_line.strip())
            ):
                break
            para_lines.append(next_line)
            i += 1

        para_text = " ".join(ln.strip() for ln in para_lines)

        inline_math = _INLINE_MATH.search(para_text)
        if inline_math and para_text.strip() == f"${inline_math.group(1)}$":
            elements.append(MathBlock(source=inline_math.group(1)))
            continue

        runs = _parse_inline(para_text)
        if (
            len(runs) == 1
            and not runs[0].bold
            and not runs[0].italic
            and runs[0].font_family is None
        ):
            elements.append(Paragraph(content=runs[0].text))
        else:
            elements.append(Paragraph(content=runs))

    return elements
