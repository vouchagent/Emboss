"""Markdown-to-EmbossSpec converter.

Parses standard Markdown into Emboss document elements so that LLM output
(which is naturally Markdown) can be rendered as high-quality PDFs without
any schema wrangling.

    from emboss import Document
    doc = Document.from_markdown("# Hello\\nWorld", style="corporate")
    doc.save("output.pdf")

Inline support: bold, italic, bold-italic, code spans, backslash escapes,
links (inline, reference, and bare autolinks), strikethrough, inline math
(rendered italic), and inline images (reduced to their alt text). Block
support: headings (ATX and setext), paragraphs, nested bullet/numbered
lists, task lists, tables (cells parsed inline), fenced code, fenced
```diagram node/edge graphs, math blocks, blockquotes, callouts,
footnotes, images, rules, and page breaks.

Not supported (by design, see the project plan): multi-paragraph list
items and raw HTML passthrough; both are left as literal text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .spec import (
    BlockQuote,
    BulletList,
    Callout,
    CodeBlock,
    Footnote,
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
from .styles import Style

__all__ = [
    "parse_markdown",
    "parse_front_matter",
    "FrontMatter",
    "MarkdownWarning",
    "BLOCKQUOTE_NATIVE",
]

# When False, plain blockquotes map to indented italic paragraphs; when
# True they emit the dedicated BlockQuote element, rendered natively by
# the writer with an accent bar and attribution support.
BLOCKQUOTE_NATIVE = True

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
_SETEXT_H1_RE = re.compile(r"^=+\s*$")
_SETEXT_H2_RE = re.compile(r"^-+\s*$")
_TASK_RE = re.compile(r"^\[( |x|X)\]\s+(.+)$")
_LINK_DEF_RE = re.compile(r"^\s{0,3}\[([^\]^][^\]]*)\]:\s*(\S+)(?:\s+.*)?$")
_FOOTNOTE_DEF_RE = re.compile(r"^\s{0,3}\[\^([^\]\s]+)\]:\s*(.+)$")
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]\s]+)\]")
_AUTOLINK_RE = re.compile(r"<(https?://[^\s<>]+)>")
_INLINE_MATH = re.compile(r"\$([^$]+)\$")
_INLINE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

_ESCAPABLE = "\\*_`$[]~<>!"
_BULLET_MARKERS = ("•", "-", "·")
_QUOTE_INDENT = 18.0

_FM_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_FM_INT_RE = re.compile(r"^-?\d+$")
_FM_FLOAT_RE = re.compile(r"^-?(?:\d+\.\d*|\.\d+)$")
_FM_STRING_KEYS = frozenset(
    {"title", "author", "subject", "keywords", "style", "language", "color_mode"}
)
_FM_BOOL_KEYS = frozenset({"toc", "number_sections", "page_numbers"})
_FM_COLOR_MODES = frozenset({"rgb", "cmyk"})


@dataclass
class FrontMatter:
    """Parsed front-matter fields, warnings, and the remaining Markdown body."""

    fields: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    body: str = ""


@dataclass
class MarkdownWarning:
    """A construct that parse_markdown dropped or degraded, with its source."""

    kind: str
    message: str
    source: str = ""


_FENCE_ATTR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)=(.*)$")


def _resolve_include_path(file: str, base_dir) -> Path:
    """Resolve a fence file= path against base_dir (default: cwd)."""
    target = Path(file)
    if target.is_absolute():
        return target
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    return root / target


def _parse_fence_info(info: str) -> tuple[str, dict]:
    """Split a fence info string into (language, key=value attributes)."""
    language = ""
    attrs: dict = {}
    for token in info.split():
        match = _FENCE_ATTR_RE.match(token)
        if match:
            attrs[match.group(1)] = match.group(2)
        elif not language:
            language = token
    return language or "text", attrs


def _parse_fm_scalar(raw: str) -> str | bool | int | float:
    """Parse a flat YAML scalar: quoted string, bool, int, float, or string."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    lowered = raw.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if _FM_INT_RE.match(raw):
        return int(raw)
    if _FM_FLOAT_RE.match(raw):
        return float(raw)
    return raw


def parse_front_matter(text: str) -> FrontMatter:
    """Split a leading --- delimited flat key: value block from Markdown text."""
    as_markdown = FrontMatter(body=text)
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return as_markdown
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return as_markdown

    fields: dict = {}
    warnings: list[str] = []
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        matched = _FM_LINE_RE.match(stripped)
        if matched is None:
            return as_markdown
        key, value = matched.group(1), _parse_fm_scalar(matched.group(2))
        if key in _FM_BOOL_KEYS:
            if isinstance(value, bool):
                fields[key] = value
            elif isinstance(value, int):
                fields[key] = bool(value)
            else:
                warnings.append(f"front-matter key {key!r} expects a boolean; ignored")
        elif key in _FM_STRING_KEYS:
            value = value if isinstance(value, str) else str(value)
            if key == "color_mode" and value not in _FM_COLOR_MODES:
                warnings.append(
                    f"front-matter color_mode {value!r} is not rgb/cmyk; ignored"
                )
            else:
                fields[key] = value
        else:
            warnings.append(f"unknown front-matter key ignored: {key!r}")
    return FrontMatter(
        fields=fields, warnings=warnings, body="\n".join(lines[end + 1 :])
    )


def _make_run(text: str, base: dict, **extra) -> TextRun:
    """Build a TextRun applying the inherited inline formatting overlay."""
    return TextRun(text=text, **{**base, **extra})


def _is_plain_run(run: TextRun) -> bool:
    """True when the run carries no formatting beyond its text."""
    return not (
        run.bold
        or run.italic
        or run.small_caps
        or run.strikethrough
        or run.font_family is not None
        or run.color is not None
        or run.link is not None
    )


def _match_bracket(text: str, start: int) -> int:
    """Return the index of the ] matching the [ at `start`, or -1."""
    depth = 0
    j = start
    while j < len(text):
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _emphasis(text: str, i: int, runs: list, flush, refs: dict, base: dict) -> int:
    """Consume an emphasis span at `i`; return the new position or -1."""
    delim = text[i]
    for count, attrs in ((3, {"bold": True, "italic": True}), (2, {"bold": True})):
        token = delim * count
        if text.startswith(token, i):
            end = text.find(token, i + count)
            if end > i + count:
                flush()
                runs.extend(
                    _parse_inline(text[i + count : end], refs, {**base, **attrs})
                )
                return end + count
    end = text.find(delim, i + 1)
    if end > i + 1:
        flush()
        runs.extend(_parse_inline(text[i + 1 : end], refs, {**base, "italic": True}))
        return end + 1
    return -1


def _link_at(text: str, i: int, refs: dict) -> tuple | None:
    """Match a link starting at `i`; return (label, url, end) or None."""
    close = _match_bracket(text, i)
    if close == -1:
        return None
    label = text[i + 1 : close]
    after = close + 1
    if after < len(text) and text[after] == "(":
        end_paren = text.find(")", after)
        if end_paren != -1:
            target = text[after + 1 : end_paren].strip()
            url = target.split()[0] if target.split() else ""
            return label, url, end_paren + 1
    if after < len(text) and text[after] == "[":
        end_ref = text.find("]", after)
        if end_ref != -1:
            ref = text[after + 1 : end_ref].strip() or label
            ref_url = refs.get(ref.lower())
            if ref_url:
                return label, ref_url, end_ref + 1
    return None


def _parse_inline(
    text: str, refs: dict | None = None, base: dict | None = None
) -> list[TextRun]:
    """Tokenize inline Markdown into TextRun objects in a single pass."""
    refs = refs or {}
    base = base or {}
    runs: list[TextRun] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            runs.append(_make_run("".join(buf), base))
            buf.clear()

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == "`":
            end = text.find("`", i + 1)
            if end != -1:
                flush()
                runs.append(_make_run(text[i + 1 : end], base, font_family="Courier"))
                i = end + 1
                continue
        if text.startswith("~~", i):
            end = text.find("~~", i + 2)
            if end > i + 2:
                flush()
                runs.extend(
                    _parse_inline(
                        text[i + 2 : end], refs, {**base, "strikethrough": True}
                    )
                )
                i = end + 2
                continue
        if ch in "*_":
            advanced = _emphasis(text, i, runs, flush, refs, base)
            if advanced != -1:
                i = advanced
                continue
        if text.startswith("![", i):
            m = _INLINE_IMAGE.match(text, i)
            if m:
                flush()
                if m.group(1):
                    runs.append(_make_run(m.group(1), base))
                i = m.end()
                continue
        if ch == "[":
            m = _FOOTNOTE_REF_RE.match(text, i)
            if m:
                flush()
                runs.append(_make_run(f"[{m.group(1)}]", base))
                i = m.end()
                continue
            link = _link_at(text, i, refs)
            if link is not None:
                label, url, end = link
                flush()
                runs.extend(_parse_inline(label, refs, {**base, "link": url}))
                i = end
                continue
        if ch == "<":
            m = _AUTOLINK_RE.match(text, i)
            if m:
                flush()
                runs.append(_make_run(m.group(1), base, link=m.group(1)))
                i = m.end()
                continue
        if ch == "$":
            end = text.find("$", i + 1)
            if end != -1:
                inner = text[i + 1 : end]
                if inner and inner == inner.strip():
                    flush()
                    runs.append(_make_run(inner, base, italic=True))
                    i = end + 1
                    continue
        buf.append(ch)
        i += 1

    flush()
    return runs if runs else [_make_run(text, base)]


def _inline_or_str(text: str, refs: dict):
    """Parse inline Markdown, collapsing unformatted results to plain str."""
    runs = _parse_inline(text, refs)
    if len(runs) == 1 and _is_plain_run(runs[0]):
        return runs[0].text
    return runs


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


def _is_block_start(line: str) -> bool:
    """True when `line` begins a non-paragraph block construct."""
    stripped = line.strip()
    return bool(
        _HEADING_RE.match(line)
        or _HR_RE.match(stripped)
        or stripped.startswith("```")
        or stripped.startswith("|")
        or stripped.startswith(">")
        or _BULLET_RE.match(line)
        or _NUMBERED_RE.match(line)
        or _IMAGE_RE.match(stripped)
        or _MATH_BLOCK_RE.match(stripped)
        or _PAGE_BREAK_RE.match(stripped)
    )


def _collect_list_lines(lines: list[str], start: int) -> tuple[list, int]:
    """Gather consecutive list lines as (indent, kind, text) entries."""
    entries: list = []
    i = start
    while i < len(lines):
        bm = _BULLET_RE.match(lines[i])
        nm = None if bm else _NUMBERED_RE.match(lines[i])
        if bm:
            entries.append((len(bm.group(1)), "bullet", bm.group(2).strip()))
        elif nm:
            entries.append((len(nm.group(1)), "numbered", nm.group(2).strip()))
        else:
            break
        i += 1
    return entries, i


def _build_list(entries: list, pos: int, depth: int, refs: dict) -> tuple:
    """Build one (possibly nested) list from entries; return (element, pos)."""
    base_indent, kind, _ = entries[pos]
    items: list = []
    checked: list = []
    has_task = False
    i = pos
    while i < len(entries):
        indent, entry_kind, text = entries[i]
        if indent < base_indent:
            break
        if indent > base_indent:
            sub, i = _build_list(entries, i, depth + 1, refs)
            items.append(sub)
            checked.append(None)
            continue
        if entry_kind != kind:
            break
        item_checked = None
        if kind == "bullet":
            tm = _TASK_RE.match(text)
            if tm:
                item_checked = tm.group(1).lower() == "x"
                text = ("[x] " if item_checked else "[ ] ") + tm.group(2)
                has_task = True
        items.append(_inline_or_str(text, refs))
        checked.append(item_checked)
        i += 1

    element: BulletList | NumberedList
    if kind == "bullet":
        element = BulletList(
            items=items,
            bullet=_BULLET_MARKERS[min(depth, len(_BULLET_MARKERS) - 1)],
            checked=checked if has_task else None,
        )
    else:
        element = NumberedList(
            items=items, marker_style="alpha" if depth else "decimal"
        )
    return element, i


def _extract_definitions(text: str) -> tuple[list[str], dict, dict]:
    """Pre-scan: pull link/footnote definitions out of the block flow."""
    refs: dict[str, str] = {}
    footnotes: dict[str, str] = {}
    lines: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            lines.append(line)
            continue
        if not in_code:
            fm = _FOOTNOTE_DEF_RE.match(line)
            if fm:
                footnotes[fm.group(1)] = fm.group(2).strip()
                continue
            lm = _LINK_DEF_RE.match(line)
            if lm:
                refs[lm.group(1).strip().lower()] = lm.group(2)
                continue
        lines.append(line)
    return lines, refs, footnotes


def parse_markdown(
    text: str,
    *,
    base_dir=None,
    on_warning=None,
    strict: bool = False,
) -> list:
    """Parse a Markdown string into a list of Emboss block elements.

    Supports: ATX and setext headings, paragraphs, nested bullet/numbered
    lists, task lists, tables, fenced code blocks, math blocks ($$...$$),
    blockquotes, callouts (> [!NOTE]), footnotes ([^1]), images, links,
    horizontal rules, and page breaks. A leading --- front-matter block is
    stripped (Document.from_markdown applies its metadata). Multi-paragraph
    list items and raw HTML passthrough are not supported and stay literal.

    A ```mermaid fence is parsed into a diagram block; a code fence whose
    info string carries ``file=PATH`` (with optional ``lines=A-B`` or
    ``marker=NAME``) loads its body from that file. Relative paths resolve
    against ``base_dir`` (default: the current working directory). When a
    mermaid parse or an include fails, the block degrades to a plain code
    block and, if given, ``on_warning`` is called with a MarkdownWarning;
    with ``strict=True`` the failure is raised instead.
    """
    lines, refs, footnote_defs = _extract_definitions(parse_front_matter(text).body)
    elements: list = []
    emitted_footnotes: set[str] = set()
    i = 0

    def warn(kind: str, message: str, source: str) -> None:
        if on_warning is not None:
            on_warning(MarkdownWarning(kind=kind, message=message, source=source))

    def emit_footnotes(source_text: str) -> None:
        for label in _FOOTNOTE_REF_RE.findall(source_text):
            if label in footnote_defs and label not in emitted_footnotes:
                emitted_footnotes.add(label)
                elements.append(
                    Footnote(
                        content=_inline_or_str(footnote_defs[label], refs),
                        marker=label,
                    )
                )

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
            info = line.strip()[3:].strip()
            language, attrs = _parse_fence_info(info)
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            source_text = "\n".join(code_lines)
            if language == "diagram":
                from .diagrams import diagram_block_from_source

                elements.append(diagram_block_from_source(source_text))
            elif language == "mermaid":
                from .mermaid import MermaidError, parse_mermaid

                try:
                    elements.append(parse_mermaid(source_text))
                except MermaidError as exc:
                    if strict:
                        raise
                    warn("mermaid", str(exc), source_text)
                    elements.append(CodeBlock(code=source_text, language="mermaid"))
            elif "file" in attrs:
                from .include import IncludeError, include_source

                lang = language
                target = _resolve_include_path(attrs["file"], base_dir)
                try:
                    loaded = include_source(
                        target,
                        lines=attrs.get("lines"),
                        marker=attrs.get("marker"),
                    )
                    elements.append(CodeBlock(code=loaded, language=lang))
                except IncludeError as exc:
                    if strict:
                        raise
                    warn("include", str(exc), info)
                    elements.append(
                        CodeBlock(code=f"# include failed: {exc}", language=lang)
                    )
            else:
                elements.append(CodeBlock(code=source_text, language=language))
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

        if line.lstrip().startswith(">"):
            quote_lines = []
            while i < len(lines):
                stripped = lines[i].strip()
                qm = _BLOCKQUOTE_RE.match(stripped)
                if qm:
                    quote_lines.append(qm.group(1).strip())
                    i += 1
                    continue
                if stripped and quote_lines and not _is_block_start(lines[i]):
                    quote_lines.append(stripped)
                    i += 1
                    continue
                break
            quote_text = " ".join(part for part in quote_lines if part)
            if BLOCKQUOTE_NATIVE:
                elements.append(BlockQuote(content=_parse_inline(quote_text, refs)))
            else:
                elements.append(
                    Paragraph(
                        content=_parse_inline(quote_text, refs, {"italic": True}),
                        style=Style(
                            indent_left=_QUOTE_INDENT, indent_right=_QUOTE_INDENT
                        ),
                    )
                )
            emit_footnotes(quote_text)
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
                            content=_inline_or_str(cell, refs),
                            align=align if align != "left" else None,
                        )
                    )
                table_rows.append(table_row)
            header_cells = []
            for ci, header in enumerate(headers):
                align = aligns[ci] if ci < len(aligns) else "left"
                header_cells.append(
                    TableCell(
                        content=_inline_or_str(header, refs),
                        align=align if align != "left" else None,
                    )
                )
            elements.append(Table(headers=header_cells, rows=table_rows))
            continue

        if _BULLET_RE.match(line) or _NUMBERED_RE.match(line):
            entries, i = _collect_list_lines(lines, i)
            pos = 0
            while pos < len(entries):
                element, pos = _build_list(entries, pos, 0, refs)
                elements.append(element)
            continue

        para_lines = [line]
        i += 1
        setext_level = 0
        while i < len(lines) and lines[i].strip():
            next_line = lines[i]
            stripped = next_line.strip()
            if _SETEXT_H1_RE.match(stripped):
                setext_level = 1
                i += 1
                break
            if _SETEXT_H2_RE.match(stripped):
                setext_level = 2
                i += 1
                break
            if _is_block_start(next_line):
                break
            para_lines.append(next_line)
            i += 1

        para_text = " ".join(ln.strip() for ln in para_lines)

        if setext_level:
            elements.append(Heading(text=para_text, level=setext_level))
            continue

        inline_math = _INLINE_MATH.search(para_text)
        if inline_math and para_text.strip() == f"${inline_math.group(1)}$":
            elements.append(MathBlock(source=inline_math.group(1)))
            continue

        runs = _parse_inline(para_text, refs)
        if len(runs) == 1 and _is_plain_run(runs[0]):
            elements.append(Paragraph(content=runs[0].text))
        else:
            elements.append(Paragraph(content=runs))
        emit_footnotes(para_text)

    return elements
