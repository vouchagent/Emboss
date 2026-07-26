"""Document specification model.

The document is a semantic tree, not a sequence of drawing commands.
Layout, appearance, and the PDF/UA structure tree are all derived from
this one description, which is what keeps them from drifting apart.

Dataclasses are used rather than pydantic so the core has no required
third-party model dependency; `emboss.adapters.pydantic_schema`
exposes a pydantic view for LLM structured-output pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence, Union

from .styles import Style, StyleSheet, resolve_preset

__all__ = [
    "TextRun", "Heading", "Paragraph", "BulletList", "NumberedList",
    "Table", "TableCell",
    "Image", "Chart", "Footnote", "Callout", "MathBlock", "CodeBlock",
    "SvgBlock", "BibliographyBlock", "Citation", "PageBreak", "HorizontalRule",
    "PageSpec", "Document", "LegalFeatures", "HeaderFooter", "BlockElement",
]

Alignment = Literal["left", "center", "right", "justify"]
CellAlignment = Literal["left", "center", "right", "decimal", None]


@dataclass
class TextRun:
    """A span of text with uniform formatting."""

    text: str
    bold: bool = False
    italic: bool = False
    small_caps: bool = False
    font_size: float | None = None
    font_family: str | None = None
    color: str | None = None
    link: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("TextRun.text must be a string")


def _as_runs(content: Union[str, TextRun, Sequence]) -> list:
    """Normalize loose text input into a list of TextRun."""
    if isinstance(content, str):
        return [TextRun(content)]
    if isinstance(content, TextRun):
        return [content]
    runs = []
    for item in content:
        if isinstance(item, str):
            runs.append(TextRun(item))
        elif isinstance(item, TextRun):
            runs.append(item)
        else:
            raise TypeError(f"expected str or TextRun, got {type(item).__name__}")
    return runs


@dataclass
class Heading:
    """A section heading. Level drives both appearance and the /Hn tag."""

    text: str
    level: int = 1
    numbering: str | None = None
    anchor: str | None = None
    style: Style | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.level <= 6:
            raise ValueError(f"heading level must be 1-6, got {self.level}")

    @property
    def runs(self) -> list:
        prefix = f"{self.numbering} " if self.numbering else ""
        return [TextRun(prefix + self.text, bold=True)]

    @property
    def structure_tag(self) -> str:
        return f"H{self.level}"


@dataclass
class Paragraph:
    """A body paragraph, tagged /P."""

    content: Union[str, TextRun, Sequence] = ""
    style: Style | None = None
    runs: list = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.runs = _as_runs(self.content)

    @property
    def structure_tag(self) -> str:
        return "P"

    @property
    def plain_text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass
class BulletList:
    """A list, tagged /L with /LI children."""

    items: Sequence = field(default_factory=list)
    bullet: str = "\u2022"
    style: Style | None = None

    @property
    def flat_items(self) -> list:
        """Return (runs_or_None, sub_list_or_None) for each item."""
        result = []
        for item in self.items:
            if isinstance(item, (BulletList, NumberedList)):
                result.append((None, item))
            else:
                result.append((_as_runs(item), None))
        return result

    @property
    def item_runs(self) -> list:
        return [_as_runs(item) for item in self.items
                if not isinstance(item, (BulletList, NumberedList))]

    @property
    def structure_tag(self) -> str:
        return "L"


@dataclass
class NumberedList:
    """A numbered list, tagged /L with /LI children."""

    items: Sequence = field(default_factory=list)
    start: int = 1
    style: Style | None = None

    @property
    def flat_items(self) -> list:
        """Return (runs_or_None, sub_list_or_None) for each item."""
        result = []
        for item in self.items:
            if isinstance(item, (BulletList, NumberedList)):
                result.append((None, item))
            else:
                result.append((_as_runs(item), None))
        return result

    @property
    def item_runs(self) -> list:
        return [_as_runs(item) for item in self.items
                if not isinstance(item, (BulletList, NumberedList))]

    def marker(self, index: int) -> str:
        return f"{self.start + index}."

    @property
    def structure_tag(self) -> str:
        return "L"


@dataclass
class TableCell:
    """One table cell. `align='decimal'` aligns numbers on the decimal point."""

    content: Union[str, TextRun, Sequence] = ""
    align: CellAlignment = None
    bold: bool = False
    colspan: int = 1
    background: str | None = None

    @property
    def runs(self) -> list:
        runs = _as_runs(self.content)
        if self.bold:
            runs = [
                TextRun(r.text, bold=True, italic=r.italic,
                        font_size=r.font_size, font_family=r.font_family,
                        color=r.color, link=r.link)
                for r in runs
            ]
        return runs

    @property
    def plain_text(self) -> str:
        return "".join(r.text for r in _as_runs(self.content))


def _as_cell(value) -> TableCell:
    if isinstance(value, TableCell):
        return value
    return TableCell(content=str(value))


@dataclass
class Table:
    """A data table, tagged /Table with proper /TH scope on headers."""

    headers: Sequence = field(default_factory=list)
    rows: Sequence = field(default_factory=list)
    column_widths: Sequence | None = None
    caption: str | None = None
    label: str | None = None
    stripe: bool = False
    repeat_header: bool = True
    style: Style | None = None

    @property
    def header_cells(self) -> list:
        return [_as_cell(h) for h in self.headers]

    @property
    def body_rows(self) -> list:
        return [[_as_cell(c) for c in row] for row in self.rows]

    @property
    def column_count(self) -> int:
        counts = [len(self.header_cells)] + [len(r) for r in self.body_rows]
        return max(counts) if counts else 0

    @property
    def structure_tag(self) -> str:
        return "Table"


@dataclass
class Image:
    """An embedded image (JPEG or PNG), tagged /Figure with alt text."""

    source: Union[str, bytes] = ""
    alt_text: str = ""
    width: float | None = None
    height: float | None = None
    caption: str | None = None
    label: str | None = None
    align: Literal["left", "center", "right"] = "center"
    style: Style | None = None
    float: Literal["here", "top", "bottom", "auto"] | None = None

    @property
    def structure_tag(self) -> str:
        return "Figure"


@dataclass
class Chart:
    """A data chart rendered as vector graphics."""

    chart_type: Literal["bar", "line", "pie"] = "bar"
    labels: Sequence = field(default_factory=list)
    values: Sequence = field(default_factory=list)
    colors: Sequence | None = None
    title: str | None = None
    label: str | None = None
    width: float = 400.0
    height: float = 250.0
    style: Style | None = None
    float: Literal["here", "top", "bottom", "auto"] | None = None

    @property
    def structure_tag(self) -> str:
        return "Figure"


@dataclass
class Footnote:
    """A footnote rendered at the bottom of the page."""

    content: Union[str, TextRun, Sequence] = ""
    marker: str | None = None
    style: Style | None = None
    runs: list = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.runs = _as_runs(self.content)

    @property
    def structure_tag(self) -> str:
        return "Note"


@dataclass
class Callout:
    """A styled container block with optional icon and background."""

    content: Union[str, TextRun, Sequence] = ""
    variant: Literal["info", "warning", "success", "danger", "note"] = "note"
    title: str | None = None
    icon: str | None = None
    background: str | None = None
    border_color: str | None = None
    border_radius: float = 4.0
    style: Style | None = None
    runs: list = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.runs = _as_runs(self.content)
        if self.background is None:
            self.background = _CALLOUT_BACKGROUNDS.get(self.variant, "f5f5f4")
        if self.border_color is None:
            self.border_color = _CALLOUT_BORDERS.get(self.variant, "a8a29e")
        if self.icon is None:
            self.icon = _CALLOUT_ICONS.get(self.variant)

    @property
    def structure_tag(self) -> str:
        return "Div"


_CALLOUT_BACKGROUNDS = {
    "info": "eff6ff",
    "warning": "fffbeb",
    "success": "f0fdf4",
    "danger": "fef2f2",
    "note": "f5f5f4",
}
_CALLOUT_BORDERS = {
    "info": "3b82f6",
    "warning": "f59e0b",
    "success": "22c55e",
    "danger": "ef4444",
    "note": "a8a29e",
}
_CALLOUT_ICONS = {
    "info": "i",
    "warning": "!",
    "success": "*",
    "danger": "x",
    "note": ">",
}


@dataclass
class PageBreak:
    """Forces content after this point onto a new page."""

    structure_tag: str = field(default="Artifact", init=False)


@dataclass
class HorizontalRule:
    thickness: float = 0.5
    color: str = "cccccc"
    space_before: float = 6.0
    space_after: float = 6.0
    structure_tag: str = field(default="Artifact", init=False)


@dataclass
class CodeBlock:
    """A code block with optional syntax highlighting."""
    code: str
    language: str = "text"
    line_numbers: bool = True
    theme: str = "dark_modern"
    start_line: int = 1
    highlight_lines: list = field(default_factory=list)
    caption: str | None = None
    label: str | None = None
    style: Style | None = None

    @property
    def structure_tag(self) -> str:
        return "Code"


@dataclass
class MathBlock:
    """A block-level mathematical expression."""
    source: str
    display: bool = True
    caption: str | None = None
    label: str | None = None
    style: Style | None = None

    @property
    def structure_tag(self) -> str:
        return "Formula"


@dataclass
class SvgBlock:
    """An embedded SVG image rendered as vector graphics."""
    source: str | bytes
    width: float | None = None
    height: float | None = None
    caption: str | None = None
    label: str | None = None
    alt_text: str = ""
    align: Literal["left", "center", "right"] = "center"
    style: Style | None = None
    float: Literal["here", "top", "bottom", "auto"] | None = None

    @property
    def structure_tag(self) -> str:
        return "Figure"


from .bibliography import BibliographyBlock, Citation  # noqa: E402


BlockElement = Union[
    Heading, Paragraph, BulletList, NumberedList, Table, Image, Chart,
    Footnote, Callout, CodeBlock, MathBlock, BibliographyBlock,
    SvgBlock, PageBreak, HorizontalRule,
]


@dataclass
class PageSpec:
    """Page geometry in PDF points (72 per inch)."""

    width: float = 612.0
    height: float = 792.0
    margin_top: float = 72.0
    margin_right: float = 72.0
    margin_bottom: float = 72.0
    margin_left: float = 72.0
    columns: int = 1
    column_gap: float = 18.0

    @classmethod
    def letter(cls, **kw) -> "PageSpec":
        return cls(width=612.0, height=792.0, **kw)

    @classmethod
    def a4(cls, **kw) -> "PageSpec":
        return cls(width=595.276, height=841.89, **kw)

    @classmethod
    def legal(cls, **kw) -> "PageSpec":
        return cls(width=612.0, height=1008.0, **kw)

    @property
    def content_width(self) -> float:
        return self.width - self.margin_left - self.margin_right

    @property
    def content_height(self) -> float:
        return self.height - self.margin_top - self.margin_bottom

    @property
    def content_top(self) -> float:
        """Y coordinate of the top of the text area (PDF origin is bottom-left)."""
        return self.height - self.margin_top

    @property
    def content_bottom(self) -> float:
        return self.margin_bottom


@dataclass
class HeaderFooter:
    """Structured header or footer with left/center/right slots.

    Use ``{page}`` and ``{pages}`` placeholders in text fields;
    they are replaced with the current page number and total pages.
    """

    left: str | None = None
    center: str | None = None
    right: str | None = None
    font_size: float | None = None
    font_family: str | None = None
    color: str | None = None
    separator_line: bool = False


@dataclass
class LegalFeatures:
    """Domain features for legal and financial documents."""

    watermark: str | None = None
    watermark_opacity: float = 0.12
    line_numbering: bool = False
    line_number_start: int = 1
    line_number_font_size: float = 8.0
    bates_prefix: str | None = None
    bates_start: int = 1
    bates_digits: int = 6
    bates_position: Literal["bottom-right", "bottom-left", "top-right"] = (
        "bottom-right"
    )
    bates_font_size: float = 8.0

    @property
    def enabled(self) -> bool:
        return bool(
            self.watermark or self.line_numbering or self.bates_prefix
        )


@dataclass
class Document:
    """A complete document specification."""

    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    language: str = "en-US"
    style: Union[str, StyleSheet] = "corporate"
    page: PageSpec = field(default_factory=PageSpec)
    content: list = field(default_factory=list)
    header_text: str | None = None
    footer_text: str | None = None
    header: HeaderFooter | None = None
    footer: HeaderFooter | None = None
    page_numbers: bool = True
    tagged: bool = True
    legal: LegalFeatures | None = None
    pdfa: bool = False
    redactions: list | None = None
    signatures: list | None = None
    toc: bool = False
    color_mode: Literal["rgb", "cmyk"] = "rgb"
    creator: str = "Emboss"
    producer: str = "Emboss"

    def __post_init__(self) -> None:
        from .typography.font_metrics import FontRegistry
        self._fonts = FontRegistry()

    @property
    def fonts(self):
        return self._fonts

    def add(self, element: BlockElement) -> "Document":
        """Append a block element. Returns self so calls can chain."""
        self.content.append(element)
        return self

    def extend(self, elements: Sequence) -> "Document":
        for element in elements:
            self.add(element)
        return self

    # Convenience constructors that keep call sites readable.

    def heading(self, text: str, level: int = 1, **kw) -> "Document":
        return self.add(Heading(text, level=level, **kw))

    def paragraph(self, content, **kw) -> "Document":
        return self.add(Paragraph(content, **kw))

    def bullets(self, items, **kw) -> "Document":
        return self.add(BulletList(items, **kw))

    def bullet_list(self, items, **kw) -> "Document":
        return self.add(BulletList(items, **kw))

    def numbered(self, items, **kw) -> "Document":
        return self.add(NumberedList(items, **kw))

    def numbered_list(self, items, **kw) -> "Document":
        return self.add(NumberedList(items, **kw))

    def table(self, headers, rows, **kw) -> "Document":
        return self.add(Table(headers=headers, rows=rows, **kw))

    def page_break(self) -> "Document":
        return self.add(PageBreak())

    def image(self, source, **kw) -> "Document":
        return self.add(Image(source=source, **kw))

    def chart(self, chart_type, labels, values, **kw) -> "Document":
        return self.add(Chart(chart_type=chart_type, labels=labels,
                              values=values, **kw))

    def footnote(self, content, **kw) -> "Document":
        return self.add(Footnote(content=content, **kw))

    def callout(self, content, variant="note", **kw) -> "Document":
        return self.add(Callout(content=content, variant=variant, **kw))

    def code_block(self, code, language="text", **kw) -> "Document":
        return self.add(CodeBlock(code=code, language=language, **kw))

    def math(self, source, **kw) -> "Document":
        return self.add(MathBlock(source=source, **kw))

    def bibliography(self, citations, **kw) -> "Document":
        return self.add(BibliographyBlock(citations=citations, **kw))

    def svg(self, source, **kw) -> "Document":
        return self.add(SvgBlock(source=source, **kw))

    def rule(self, **kw) -> "Document":
        return self.add(HorizontalRule(**kw))

    @property
    def stylesheet(self) -> StyleSheet:
        if isinstance(self.style, StyleSheet):
            return self.style
        return resolve_preset(self.style)

    def render(self) -> bytes:
        """Render this document to PDF bytes."""
        from .writer import render_document

        return render_document(self)

    def save(self, path) -> None:
        from pathlib import Path

        Path(path).write_bytes(self.render())

    @classmethod
    def from_markdown(cls, text: str, **kw) -> "Document":
        """Create a Document from a Markdown string.

        Any keyword arguments are passed to the Document constructor
        (style, page, legal, header, footer, etc.).
        """
        from .markdown import parse_markdown

        elements = parse_markdown(text)
        title = kw.pop("title", "")
        if not title:
            for el in elements:
                if isinstance(el, Heading) and el.level == 1:
                    title = el.text
                    break
        doc = cls(title=title, content=elements, **kw)
        return doc

    @classmethod
    def from_json(cls, json_str: str, **kw) -> "Document":
        """Create a Document from an EmbossSpec JSON string.

        Handles common LLM quirks: markdown fences, trailing commas.
        Any keyword arguments override fields in the JSON.
        """
        from .generate import parse_spec_json

        return parse_spec_json(json_str, **kw)
