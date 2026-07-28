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

from .brandkit import BrandKit
from .styles import Style, StyleSheet, apply_brand, resolve_preset

__all__ = [
    "TextRun",
    "Heading",
    "Paragraph",
    "BulletList",
    "NumberedList",
    "Table",
    "TableCell",
    "BlockQuote",
    "Image",
    "Chart",
    "Series",
    "Footnote",
    "Callout",
    "MathBlock",
    "CodeBlock",
    "SvgBlock",
    "BibliographyBlock",
    "Citation",
    "CoverPage",
    "Abstract",
    "Author",
    "Authors",
    "PullQuote",
    "Stat",
    "StatTiles",
    "TableOfContents",
    "ListOfFigures",
    "ListOfTables",
    "PageBreak",
    "HorizontalRule",
    "PageSpec",
    "Document",
    "BrandKit",
    "LegalFeatures",
    "HeaderFooter",
    "BlockElement",
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
    strikethrough: bool = False

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
    id: str | None = None

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
    id: str | None = None

    def __post_init__(self) -> None:
        self.runs = _as_runs(self.content)

    @property
    def structure_tag(self) -> str:
        return "P"

    @property
    def plain_text(self) -> str:
        return "".join(run.text for run in self.runs)


def _list_item_entry(item, nested_factory) -> tuple:
    """Classify one list item as (runs, None) text or (None, list) nesting."""
    if isinstance(item, (BulletList, NumberedList)):
        return None, item
    if isinstance(item, (list, tuple)) and not any(
        isinstance(entry, TextRun) for entry in item
    ):
        return None, nested_factory(item)
    return _as_runs(item), None


def _alpha_label(value: int) -> str:
    """Spreadsheet-style letters for nested numbered markers: 1 -> a."""
    label = ""
    while value > 0:
        value, rem = divmod(value - 1, 26)
        label = chr(ord("a") + rem) + label
    return label


@dataclass
class BulletList:
    """A list, tagged /L with /LI children."""

    items: Sequence = field(default_factory=list)
    bullet: str = "\u2022"
    checked: Sequence | None = None
    style: Style | None = None
    id: str | None = None

    @property
    def flat_items(self) -> list:
        """Return (runs_or_None, sub_list_or_None) for each item."""
        return [
            _list_item_entry(item, lambda sub: BulletList(items=sub, bullet="-"))
            for item in self.items
        ]

    @property
    def item_runs(self) -> list:
        return [runs for runs, sub in self.flat_items if runs is not None]

    @property
    def structure_tag(self) -> str:
        return "L"


@dataclass
class NumberedList:
    """A numbered list, tagged /L with /LI children."""

    items: Sequence = field(default_factory=list)
    start: int = 1
    marker_style: Literal["decimal", "alpha"] = "decimal"
    style: Style | None = None
    id: str | None = None

    @property
    def flat_items(self) -> list:
        """Return (runs_or_None, sub_list_or_None) for each item."""
        return [
            _list_item_entry(
                item, lambda sub: NumberedList(items=sub, marker_style="alpha")
            )
            for item in self.items
        ]

    @property
    def item_runs(self) -> list:
        return [runs for runs, sub in self.flat_items if runs is not None]

    def marker(self, index: int) -> str:
        value = self.start + index
        if self.marker_style == "alpha" and value >= 1:
            return _alpha_label(value) + "."
        return f"{value}."

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
                TextRun(
                    r.text,
                    bold=True,
                    italic=r.italic,
                    small_caps=r.small_caps,
                    font_size=r.font_size,
                    font_family=r.font_family,
                    color=r.color,
                    link=r.link,
                    strikethrough=r.strikethrough,
                )
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
    id: str | None = None

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
class BlockQuote:
    """A quoted passage set off from body text, tagged /BlockQuote."""

    content: Union[str, TextRun, Sequence] = ""
    attribution: str | None = None
    style: Style | None = None
    runs: list = field(default_factory=list, init=False)
    id: str | None = None

    def __post_init__(self) -> None:
        self.runs = _as_runs(self.content)

    @property
    def plain_text(self) -> str:
        return "".join(run.text for run in self.runs)

    @property
    def structure_tag(self) -> str:
        return "BlockQuote"


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
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Figure"


@dataclass
class Series:
    """One named data series within a chart."""

    label: str = ""
    values: Sequence = field(default_factory=list)


@dataclass
class Chart:
    """A data chart rendered as vector graphics.

    Provide either ``labels`` + ``values`` (one unnamed series) or
    ``labels`` + ``series`` for multi-series charts.
    """

    chart_type: Literal["bar", "line", "pie", "scatter"] = "bar"
    labels: Sequence = field(default_factory=list)
    values: Sequence = field(default_factory=list)
    colors: Sequence | None = None
    title: str | None = None
    label: str | None = None
    alt_text: str | None = None
    width: float = 400.0
    height: float = 250.0
    style: Style | None = None
    float: Literal["here", "top", "bottom", "auto"] | None = None
    series: Sequence | None = None
    x_title: str | None = None
    y_title: str | None = None
    legend: bool = True
    id: str | None = None

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
    id: str | None = None

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
    id: str | None = None

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

    id: str | None = None
    structure_tag: str = field(default="Artifact", init=False)


@dataclass
class HorizontalRule:
    thickness: float = 0.5
    color: str = "cccccc"
    space_before: float = 6.0
    space_after: float = 6.0
    id: str | None = None
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
    id: str | None = None

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
    number: bool = False
    tag: str | None = None
    style: Style | None = None
    id: str | None = None

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
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Figure"


@dataclass
class CoverPage:
    """A full-page cover with centered title composition and accent rule."""

    title: str
    subtitle: str = ""
    authors: Sequence = field(default_factory=tuple)
    date: str = ""
    kicker: str = ""
    style: Style | None = None
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Div"


@dataclass
class Abstract:
    """An indented abstract block with a label and optional keywords line."""

    text: str
    keywords: Sequence = field(default_factory=tuple)
    style: Style | None = None
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Div"


@dataclass
class Author:
    """One author's name, affiliation, and email for an author grid."""

    name: str
    affiliation: str = ""
    email: str = ""


@dataclass
class Authors:
    """A centered grid of author entries under a title."""

    authors: Sequence = field(default_factory=list)
    style: Style | None = None
    id: str | None = None

    @property
    def author_list(self) -> list:
        out = []
        for entry in self.authors:
            if isinstance(entry, Author):
                out.append(entry)
            elif isinstance(entry, dict):
                out.append(Author(**entry))
            else:
                out.append(Author(name=str(entry)))
        return out

    @property
    def structure_tag(self) -> str:
        return "Div"


@dataclass
class PullQuote:
    """A large-type offset quotation, tagged /BlockQuote."""

    text: str
    attribution: str = ""
    style: Style | None = None
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "BlockQuote"


@dataclass
class Stat:
    """One statistic tile: a value with a label and optional signed delta."""

    label: str
    value: str
    delta: str | None = None


@dataclass
class StatTiles:
    """A row of bordered statistic tiles, drawn as vector graphics."""

    stats: Sequence = field(default_factory=list)
    style: Style | None = None
    id: str | None = None

    @property
    def stat_list(self) -> list:
        out = []
        for entry in self.stats:
            if isinstance(entry, Stat):
                out.append(entry)
            elif isinstance(entry, dict):
                out.append(Stat(**entry))
            else:
                out.append(Stat(label="", value=str(entry)))
        return out

    @property
    def structure_tag(self) -> str:
        return "Div"


@dataclass
class TableOfContents:
    """A visible contents / figures / tables listing with dot leaders.

    ``source`` selects the entries: ``"headings"`` lists document headings
    up to ``depth``; ``"figures"`` and ``"tables"`` list captioned figures
    and tables from the cross-reference index.
    """

    title: str = "Contents"
    depth: int = 3
    source: Literal["headings", "figures", "tables"] = "headings"
    style: Style | None = None
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Div"


def ListOfFigures(title: str = "List of Figures", **kw) -> TableOfContents:
    """A table-of-contents variant listing captioned figures."""
    return TableOfContents(title=title, source="figures", **kw)


def ListOfTables(title: str = "List of Tables", **kw) -> TableOfContents:
    """A table-of-contents variant listing captioned tables."""
    return TableOfContents(title=title, source="tables", **kw)


from .bibliography import BibliographyBlock, Citation  # noqa: E402


BlockElement = Union[
    Heading,
    Paragraph,
    BulletList,
    NumberedList,
    Table,
    BlockQuote,
    Image,
    Chart,
    Footnote,
    Callout,
    CodeBlock,
    MathBlock,
    BibliographyBlock,
    SvgBlock,
    CoverPage,
    Abstract,
    Authors,
    PullQuote,
    StatTiles,
    TableOfContents,
    PageBreak,
    HorizontalRule,
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
    mirror_margins: bool = False

    @classmethod
    def letter(cls, **kw) -> "PageSpec":
        return cls(width=612.0, height=792.0, **kw)

    @classmethod
    def a4(cls, **kw) -> "PageSpec":
        return cls(width=595.276, height=841.89, **kw)

    @classmethod
    def legal(cls, **kw) -> "PageSpec":
        return cls(width=612.0, height=1008.0, **kw)

    @classmethod
    def a5(cls, **kw) -> "PageSpec":
        return cls(width=419.528, height=595.276, **kw)

    @classmethod
    def compact(cls, **kw) -> "PageSpec":
        """A5 page with tight margins, tuned for phone and tablet PDF readers."""
        for margin in ("margin_top", "margin_right", "margin_bottom", "margin_left"):
            kw.setdefault(margin, 40.0)
        return cls(width=419.528, height=595.276, **kw)

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

    Use ``{page}``, ``{pages}``, and ``{section}`` placeholders in text
    fields; they are replaced with the current page number, the page
    count of the current numbering sequence, and the text of the most
    recent level-1/2 heading at or before this page (falling back to
    the document title). On page 1, ``first_page_override`` replaces
    this header/footer when set; otherwise ``first_page=False``
    suppresses it entirely.
    """

    left: str | None = None
    center: str | None = None
    right: str | None = None
    font_size: float | None = None
    font_family: str | None = None
    color: str | None = None
    separator_line: bool = False
    first_page: bool = True
    first_page_override: "HeaderFooter | None" = None


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
    bates_position: Literal["bottom-right", "bottom-left", "top-right"] = "bottom-right"
    bates_font_size: float = 8.0

    @property
    def enabled(self) -> bool:
        return bool(self.watermark or self.line_numbering or self.bates_prefix)


@dataclass
class Document:
    """A complete document specification."""

    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    language: str = "en-US"
    style: Union[str, StyleSheet] = "corporate"
    brand: BrandKit | None = None
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
    page_number_format: Literal["arabic", "roman", "ROMAN"] = "arabic"
    front_matter_pages: int = 0
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
        return self.add(
            Chart(chart_type=chart_type, labels=labels, values=values, **kw)
        )

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

    def diagram(
        self, nodes, edges=(), direction="down", caption=None, **kw
    ) -> "Document":
        """Append an auto-laid-out node/edge diagram rendered as vector art."""
        from .diagrams import diagram_svg_block

        return self.add(
            diagram_svg_block(nodes, edges, direction=direction, caption=caption, **kw)
        )

    def rule(self, **kw) -> "Document":
        return self.add(HorizontalRule(**kw))

    def cover(self, title, **kw) -> "Document":
        return self.add(CoverPage(title=title, **kw))

    def abstract(self, text, **kw) -> "Document":
        return self.add(Abstract(text=text, **kw))

    def authors(self, authors, **kw) -> "Document":
        return self.add(Authors(authors=authors, **kw))

    def pull_quote(self, text, **kw) -> "Document":
        return self.add(PullQuote(text=text, **kw))

    def stat_tiles(self, stats, **kw) -> "Document":
        return self.add(StatTiles(stats=stats, **kw))

    def table_of_contents(self, **kw) -> "Document":
        return self.add(TableOfContents(**kw))

    @property
    def stylesheet(self) -> StyleSheet:
        if isinstance(self.style, StyleSheet):
            base = self.style
        else:
            base = resolve_preset(self.style)
        if self.brand is not None:
            return apply_brand(base, self.brand)
        return base

    def render(self, linearize: bool = False) -> bytes:
        """Render to PDF bytes; linearize=True rewrites for Fast Web View."""
        from .writer import render_document

        data = render_document(self)
        if linearize:
            data = _linearize_pdf(data)
        return data

    def save(self, path, linearize: bool = False) -> None:
        """Render and write to path; linearize=True enables Fast Web View."""
        from pathlib import Path

        Path(path).write_bytes(self.render(linearize=linearize))

    def layout_map(self) -> dict:
        """Return node id -> list of {page, x0, y0, x1, y1} placements.

        Renders once and caches; call again to reuse the same map. The
        cache is keyed to the current content so mutating the document and
        calling again recomputes it.
        """
        from .writer import render_document

        token = id(self.content), len(self.content)
        cached = getattr(self, "_layout_map_cache", None)
        if cached is not None and cached[0] == token:
            return cached[1]
        result = render_document(self, return_result=True)
        self._layout_map_cache = (token, result.layout_map)
        return result.layout_map

    @classmethod
    def from_markdown(cls, text: str, **kw) -> "Document":
        """Create a Document from a Markdown string.

        A leading --- front-matter block supplies document metadata
        (title, author, style, toc, ...); explicit keyword arguments win.
        Any keyword arguments are passed to the Document constructor
        (style, page, legal, header, footer, etc.).
        """
        from .markdown import parse_front_matter, parse_markdown

        matter = parse_front_matter(text)
        elements = parse_markdown(matter.body)
        meta = {**matter.fields, **kw}
        number_sections = meta.pop("number_sections", None)
        title = meta.pop("title", "")
        if not title:
            for el in elements:
                if isinstance(el, Heading) and el.level == 1:
                    title = el.text
                    break
        doc = cls(title=title, content=elements, **meta)
        if number_sections is not None:
            doc.number_sections = number_sections
        return doc

    @classmethod
    def from_llm(cls, text: str, **kw) -> "Document":
        """Create a Document from raw LLM output, auto-detecting the format.

        Routing order: fenced ```json block, bare JSON object containing
        "content", MathML fragment, then Markdown. Never raises on
        ambiguous input; Markdown is the final fallback.
        """
        from .generate import document_from_llm_text

        return document_from_llm_text(text, **kw)

    @classmethod
    def from_json(cls, json_str: str, **kw) -> "Document":
        """Create a Document from an EmbossSpec JSON string.

        Handles common LLM quirks: markdown fences, trailing commas.
        Any keyword arguments override fields in the JSON.
        """
        from .generate import parse_spec_json

        return parse_spec_json(json_str, **kw)


def _linearize_pdf(data: bytes) -> bytes:
    """Rewrite PDF bytes linearized (Fast Web View) via pikepdf, deterministically."""
    import io

    try:
        import pikepdf
    except ImportError as exc:
        raise ImportError(
            "pikepdf is required for linearized output.\n"
            "  pip install emboss-pdf[verify]"
        ) from exc

    buffer = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.save(buffer, linearize=True, deterministic_id=True)
    return buffer.getvalue()
