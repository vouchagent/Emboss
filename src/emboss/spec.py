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
    "Appendix",
    "Index",
    "GlossaryEntry",
    "Glossary",
    "Approval",
    "RevisionEntry",
    "DocumentControl",
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
    underline: bool = False
    index_terms: tuple = field(default_factory=tuple)

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
                    index_terms=r.index_terms,
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
    headline: str | None = None
    subtitle: str | None = None
    source_line: str | None = None
    attach_data: bool = False
    verify_totals: bool = False

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
    patterns: bool = False
    headline: str | None = None
    subtitle: str | None = None
    source_line: str | None = None
    verify_facts: bool = False
    attach_data: bool = False

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
    """Forces content after this point onto a new page.

    ``page_style`` names an entry in ``Document.page_styles``; content
    after this break uses that page's geometry until another `PageBreak`
    switches again, or reverts to the document's default page when a
    later `PageBreak` carries no ``page_style``.
    """

    page_style: str | None = None
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


@dataclass
class Appendix:
    """A titled section with alphabetic numbering (Appendix A, B, ...).

    Expanded before layout into a lettered title heading followed by its
    content, with any headings inside numbered ``A.1``, ``A.2``, restarting
    at the next top-level ``Appendix``.
    """

    title: str
    content: list = field(default_factory=list)
    style: Style | None = None
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Sect"


@dataclass
class Index:
    """A back-of-book index: alphabetized terms with page numbers.

    Terms are gathered from ``TextRun.index_terms`` marks anywhere in the
    document and resolved to real page numbers in a two-pass layout, the
    same mechanism the visible `TableOfContents` uses. Use at most one
    per document.
    """

    title: str = "Index"
    style: Style | None = None
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Div"


@dataclass
class GlossaryEntry:
    """One glossary term and its definition."""

    term: str
    definition: str = ""


@dataclass
class Glossary:
    """A definition list of terms, alphabetized by term, tagged /Div.

    The bold term is rendered inline with its regular-weight definition,
    hanging-indented so wrapped lines align under the definition. The
    first document-wide body-text occurrence of each term is linked to
    this block.
    """

    entries: Sequence = field(default_factory=list)
    title: str = "Glossary"
    style: Style | None = None
    id: str | None = None

    @property
    def entry_list(self) -> list:
        out = []
        for entry in self.entries:
            if isinstance(entry, GlossaryEntry):
                out.append(entry)
            elif isinstance(entry, dict):
                out.append(GlossaryEntry(**entry))
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                out.append(GlossaryEntry(term=str(entry[0]), definition=str(entry[1])))
            else:
                out.append(GlossaryEntry(term=str(entry), definition=""))
        return out

    @property
    def structure_tag(self) -> str:
        return "Div"


@dataclass
class Approval:
    """One approver's sign-off row in a controlled document."""

    name: str = ""
    role: str = ""
    date: str = ""
    statement: str = "Approved"


@dataclass
class RevisionEntry:
    """One row of a controlled document's revision history."""

    version: str = ""
    date: str = ""
    author: str = ""
    summary: str = ""


@dataclass
class DocumentControl:
    """A controlled-document control block: metadata, approvals, revisions.

    Renders as a labeled panel: a metadata grid of label/value pairs, an
    approvals table, and a revision-history table, each reusing the table
    machinery so pagination and PDF/UA /Table tagging come for free. Dates
    are plain string fields, never computed, so output stays deterministic.
    """

    doc_id: str | None = None
    title: str | None = None
    version: str | None = None
    status: str | None = None
    effective_date: str | None = None
    classification: str | None = None
    owner: str | None = None
    approvals: Sequence = field(default_factory=list)
    revisions: Sequence = field(default_factory=list)
    style: Style | None = None
    id: str | None = None

    @property
    def structure_tag(self) -> str:
        return "Div"

    @property
    def approval_list(self) -> list:
        out = []
        for entry in self.approvals:
            if isinstance(entry, Approval):
                out.append(entry)
            elif isinstance(entry, dict):
                out.append(Approval(**entry))
            elif isinstance(entry, (list, tuple)):
                out.append(Approval(*entry))
            else:
                out.append(Approval(name=str(entry)))
        return out

    @property
    def revision_list(self) -> list:
        out = []
        for entry in self.revisions:
            if isinstance(entry, RevisionEntry):
                out.append(entry)
            elif isinstance(entry, dict):
                out.append(RevisionEntry(**entry))
            elif isinstance(entry, (list, tuple)):
                out.append(RevisionEntry(*entry))
            else:
                out.append(RevisionEntry(version=str(entry)))
        return out

    @property
    def metadata_pairs(self) -> list:
        """Return present (label, value) metadata pairs in display order."""
        fields = [
            ("Document ID", self.doc_id),
            ("Title", self.title),
            ("Version", self.version),
            ("Status", self.status),
            ("Effective Date", self.effective_date),
            ("Classification", self.classification),
            ("Owner", self.owner),
        ]
        return [(label, value) for label, value in fields if value]

    def to_blocks(self) -> list:
        """Expand into concrete label paragraphs and tables for rendering."""
        label_style = Style(bold=True, space_before=10.0, space_after=2.0)
        sub_style = Style(bold=True, space_before=8.0, space_after=1.0)
        blocks: list = [
            Paragraph(
                [TextRun("Document Control", bold=True)],
                style=label_style,
                id=self.id,
            )
        ]
        pairs = self.metadata_pairs
        if pairs:
            blocks.append(
                Table(
                    headers=[],
                    rows=[
                        [TableCell(label, bold=True), TableCell(str(value))]
                        for label, value in pairs
                    ],
                    column_widths=[0.32, 0.68],
                )
            )
        approvals = self.approval_list
        if approvals:
            blocks.append(Paragraph([TextRun("Approvals", bold=True)], style=sub_style))
            blocks.append(
                Table(
                    headers=["Name", "Role", "Statement", "Date"],
                    rows=[[a.name, a.role, a.statement, a.date] for a in approvals],
                    repeat_header=True,
                    stripe=True,
                )
            )
        revisions = self.revision_list
        if revisions:
            blocks.append(
                Paragraph([TextRun("Revision History", bold=True)], style=sub_style)
            )
            blocks.append(
                Table(
                    headers=["Version", "Date", "Author", "Summary"],
                    rows=[[r.version, r.date, r.author, r.summary] for r in revisions],
                    repeat_header=True,
                    stripe=True,
                )
            )
        return blocks


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
    Appendix,
    Index,
    Glossary,
    DocumentControl,
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
    landscape: bool = False

    def __post_init__(self) -> None:
        if self.landscape and self.width < self.height:
            self.width, self.height = self.height, self.width

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
    page_styles: dict[str, PageSpec] = field(default_factory=dict)
    content: list = field(default_factory=list)
    header_text: str | None = None
    footer_text: str | None = None
    header: HeaderFooter | None = None
    footer: HeaderFooter | None = None
    page_numbers: bool = True
    tagged: bool = True
    legal: LegalFeatures | None = None
    pdfa: bool = False
    pdfx: bool = False
    pdfx_condition: str | None = None
    pdfx_output_profile: bytes | None = None
    wtpdf: bool = False
    redactions: list | None = None
    signatures: list | None = None
    toc: bool = False
    color_mode: Literal["rgb", "cmyk"] = "rgb"
    page_number_format: Literal["arabic", "roman", "ROMAN"] = "arabic"
    front_matter_pages: int = 0
    creator: str = "Emboss"
    producer: str = "Emboss"
    predecessor: str | None = None

    def __post_init__(self) -> None:
        from .typography.font_metrics import FontRegistry

        self._fonts = FontRegistry()
        #: FileAttachments queued by `attach_encrypted`; always included
        #: by `render`/`save`, independent of `embed_spec`/`manifest`.
        self._extra_attachments: list = []
        #: FacturXMeta recorded by `attach_facturx`; threaded into the XMP.
        self._facturx_meta = None

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

    def table_from_csv(self, source, *, has_header: bool = True, **kw) -> "Document":
        """Build a table from a CSV path, file object, CSV text, or DataFrame.

        Reads once, then builds a normal ``Table`` -- ``verify_totals``,
        ``attach_data``, ``caption``, and every other table keyword compose
        exactly as they do for a hand-typed table.
        """
        from .data_binding import read_csv_rows

        headers, rows = read_csv_rows(source, has_header=has_header)
        return self.table(headers, rows, **kw)

    def chart_from_csv(
        self,
        source,
        *,
        has_header: bool = True,
        category_column=0,
        value_columns=None,
        chart_type: str = "bar",
        **kw,
    ) -> "Document":
        """Build a chart from a CSV path, file object, CSV text, or DataFrame.

        The category column (default: the first) supplies ``labels``; every
        other column that parses as numeric across all rows becomes a
        ``Series``, unless ``value_columns`` names or indexes them
        explicitly. Composes with ``attach_data=True`` so the exact CSV that
        fed the chart also travels inside the PDF.
        """
        from .data_binding import numeric_columns, read_csv_rows, series_from_columns

        headers, rows = read_csv_rows(source, has_header=has_header)
        cat_idx = (
            headers.index(category_column)
            if isinstance(category_column, str)
            else category_column
        )
        labels = [row[cat_idx] if cat_idx < len(row) else "" for row in rows]

        indices = numeric_columns(
            headers, rows, value_columns=value_columns, category_column=cat_idx
        )
        if not indices:
            raise ValueError(
                "no numeric columns found for chart series; pass value_columns "
                "explicitly if the CSV's numbers are formatted unusually"
            )
        series = series_from_columns(headers, rows, indices)

        if len(series) == 1:
            return self.add(
                Chart(
                    chart_type=chart_type,
                    labels=labels,
                    values=series[0].values,
                    **kw,
                )
            )
        return self.add(
            Chart(chart_type=chart_type, labels=labels, values=[], series=series, **kw)
        )

    def page_break(self, page_style: str | None = None) -> "Document":
        return self.add(PageBreak(page_style=page_style))

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

    def architecture_diagram(
        self, nodes, edges=(), groups=None, direction="down", caption=None, **kw
    ) -> "Document":
        """Append an architecture diagram of service glyphs, groups, and edges."""
        from .diagrams import architecture_svg_block

        return self.add(
            architecture_svg_block(
                nodes, edges, groups=groups, direction=direction, caption=caption, **kw
            )
        )

    def sequence_diagram(
        self, participants, messages=(), caption=None, **kw
    ) -> "Document":
        """Append a sequence diagram of participant lifelines and messages."""
        from .diagrams import sequence_svg_block

        return self.add(
            sequence_svg_block(participants, messages, caption=caption, **kw)
        )

    def er_diagram(self, entities, relationships=(), caption=None, **kw) -> "Document":
        """Append an entity-relationship diagram of entities and relationships."""
        from .diagrams import er_svg_block

        return self.add(er_svg_block(entities, relationships, caption=caption, **kw))

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

    def appendix(self, title: str, *blocks) -> "Document":
        """Append a lettered appendix (Appendix A, B, ...) wrapping `blocks`."""
        return self.add(Appendix(title=title, content=list(blocks)))

    def index(self, title: str = "Index", **kw) -> "Document":
        """Append the document's index, resolved from `TextRun.index_terms` marks."""
        return self.add(Index(title=title, **kw))

    def glossary(self, entries, title: str = "Glossary", **kw) -> "Document":
        return self.add(Glossary(entries=entries, title=title, **kw))

    def document_control(self, **kwargs) -> "Document":
        """Append a controlled-document control block (metadata + tables)."""
        return self.add(DocumentControl(**kwargs))

    @property
    def stylesheet(self) -> StyleSheet:
        if isinstance(self.style, StyleSheet):
            base = self.style
        else:
            base = resolve_preset(self.style)
        if self.brand is not None:
            return apply_brand(base, self.brand)
        return base

    def render(
        self,
        linearize: bool = False,
        *,
        embed_spec: bool = False,
        manifest: bool = False,
        predecessor_sha256: str | None = None,
        predecessor_manifest_sha256: str | None = None,
    ) -> bytes:
        """Render to PDF bytes.

        ``linearize=True`` rewrites the output for Fast Web View.
        ``embed_spec=True`` attaches the document's own EmbossSpec JSON,
        layout map, and a Markdown twin as /AF files — ``from_pdf`` uses
        the first to reconstruct an equivalent Document even if the
        original spec is lost. It forces PDF/A part 3 when ``pdfa`` is
        also set, since PDF/A-2 forbids arbitrary attachments; on a
        non-PDF/A document it embeds normally without forcing anything.
        ``manifest=True`` additionally attaches ``emboss-manifest.json``
        (see ``reproducibility_manifest``): the spec's sha256, the
        Emboss version, every embedded font's sha256, and any
        non-default render options, so ``emboss reproduce`` can later
        verify a re-render matches. ``predecessor_sha256`` /
        ``predecessor_manifest_sha256`` (or setting ``Document.
        predecessor``) record a lineage pointer to the document this one
        was derived from; combine with a DocMDP certification signature
        (``signing.sign_pdf(..., certify=True)``) for a verifiable,
        signed chain of custody. Attachments queued by
        ``attach_encrypted`` are always included, regardless of these
        flags.
        """
        from .writer import render_document

        embed_files: list = []
        if embed_spec:
            embed_files.extend(self._embed_spec_files())
        embed_files.extend(self._extra_attachments)
        if manifest:
            embed_files.append(
                self._manifest_attachment(
                    embed_spec, predecessor_sha256, predecessor_manifest_sha256
                )
            )
        data = render_document(self, embed_files=embed_files or None)
        if linearize:
            data = _linearize_pdf(data)
        return data

    def save(
        self,
        path,
        linearize: bool = False,
        *,
        embed_spec: bool = False,
        manifest: bool = False,
        predecessor_sha256: str | None = None,
        predecessor_manifest_sha256: str | None = None,
    ) -> None:
        """Render and write to path. See ``render`` for what each flag does."""
        from pathlib import Path

        Path(path).write_bytes(
            self.render(
                linearize=linearize,
                embed_spec=embed_spec,
                manifest=manifest,
                predecessor_sha256=predecessor_sha256,
                predecessor_manifest_sha256=predecessor_manifest_sha256,
            )
        )

    def _embed_spec_files(self) -> list:
        """Build the /AF attachments for ``render(embed_spec=True)``."""
        from .nodeid import layout_map_json
        from .pdf.attachments import FileAttachment
        from .recovery import document_to_spec_dict, spec_dict_to_json
        from .textmap import text_map_json
        from .adapters.markdown_export import to_markdown

        spec_json = spec_dict_to_json(document_to_spec_dict(self))
        return [
            FileAttachment(
                name="emboss-textmap.json",
                data=text_map_json(self).encode("utf-8"),
                mime="application/json",
                description="Node id to per-character text-position index.",
                relationship="Supplement",
            ),
            FileAttachment(
                name="emboss-spec.json",
                data=spec_json,
                mime="application/json",
                description="EmbossSpec source document, for exact reconstruction.",
                relationship="Source",
            ),
            FileAttachment(
                name="emboss-layout.json",
                data=layout_map_json(self).encode("utf-8"),
                mime="application/json",
                description="Node id to page/bounding-box layout map.",
                relationship="Supplement",
            ),
            FileAttachment(
                name="emboss-doc.md",
                data=to_markdown(self).encode("utf-8"),
                mime="text/markdown",
                description="Reflowable Markdown twin of the document.",
                relationship="Alternative",
            ),
        ]

    def reproducibility_manifest(
        self,
        *,
        embed_spec: bool = False,
        predecessor_sha256: str | None = None,
        predecessor_manifest_sha256: str | None = None,
    ) -> dict:
        """Build this document's reproducibility manifest without rendering.

        Runs (and caches) a layout pass first, via ``layout_map``, so the
        manifest's font list reflects every font this document's render
        actually resolves. See ``manifest.build_manifest`` for the
        manifest's shape; pass the same ``embed_spec`` value you intend
        to pass to ``render``/``save``, since it is recorded under
        ``render_options``. ``predecessor_sha256`` falls back to
        ``self.predecessor`` when not given explicitly.
        """
        from .manifest import build_manifest

        self.layout_map()
        return build_manifest(
            self,
            embed_spec=embed_spec,
            predecessor_sha256=predecessor_sha256,
            predecessor_manifest_sha256=predecessor_manifest_sha256,
        )

    def _manifest_attachment(
        self,
        embed_spec: bool,
        predecessor_sha256: str | None,
        predecessor_manifest_sha256: str | None,
    ):
        """Build the /AF attachment for ``render(manifest=True)``."""
        from .manifest import MANIFEST_FILENAME, manifest_json
        from .pdf.attachments import FileAttachment

        manifest_dict = self.reproducibility_manifest(
            embed_spec=embed_spec,
            predecessor_sha256=predecessor_sha256,
            predecessor_manifest_sha256=predecessor_manifest_sha256,
        )
        return FileAttachment(
            name=MANIFEST_FILENAME,
            data=manifest_json(manifest_dict),
            mime="application/json",
            description=(
                "Reproducibility manifest: spec hash, Emboss version, "
                "embedded font hashes, and non-default render options."
            ),
            relationship="Supplement",
        )

    def redact(self, rules: list) -> "Document":
        """Return a NEW Document with ``rules`` applied before rendering.

        Each ``RedactionRule`` (see ``redaction.RedactionRule``) matches
        whole content blocks -- by node id, by a regex/predicate over
        the block's plain text, or by element type -- before any layout
        or content stream is produced, so a match's original text never
        reaches the rendered PDF: ``mode="remove"`` drops the block
        outright, ``mode="placeholder"`` replaces it with same-shaped
        filler text and covers it with an opaque box sized from the
        placeholder's own rendered bounding box (an honest black box: it
        conceals filler, not the redacted content, which was already
        gone before rendering).

        The audit trail of what was removed (plain text, by which rule,
        where) is written to the *returned* document's ``redaction_log``
        attribute -- not a dataclass field, so ``document_to_spec_dict``,
        ``reproducibility_manifest``, and ``render(embed_spec=True)``
        never see it, and it is never auto-attached to the redacted
        document's own /AF files. Callers who want it in the output must
        attach it themselves, explicitly (e.g. via ``attach_encrypted``).
        """
        from .redaction import redact_document

        redacted, log = redact_document(self, rules)
        redacted.redaction_log = log
        return redacted

    def attach_encrypted(
        self,
        name: str,
        data: bytes,
        password: str,
        *,
        mime: str = "application/octet-stream",
    ) -> "Document":
        """Queue *data* as an AES-256-GCM-encrypted /AF attachment.

        See ``redaction.encrypt_attachment`` for the ciphertext format.
        Included by the next ``render``/``save`` regardless of
        ``embed_spec``/``manifest``. Uses a fresh random salt and nonce
        each call, so calling this twice with identical arguments still
        yields different ciphertext bytes -- this is the one legitimate
        use of randomness in the library, and it never runs unless a
        caller opts in here. Mutates and returns self so calls can chain
        like ``add``.
        """
        from .pdf.attachments import FileAttachment
        from .redaction import encrypt_attachment

        blob = encrypt_attachment(data, password)
        self._extra_attachments.append(
            FileAttachment(
                name=name,
                data=blob,
                mime=mime,
                description=(
                    "AES-256-GCM encrypted payload; see redaction.decrypt_attachment."
                ),
                relationship="EncryptedPayload",
            )
        )
        return self

    def attach_facturx(self, invoice, profile: str = "EN 16931") -> "Document":
        """Queue a Factur-X ``factur-x.xml`` invoice and force PDF/A-3.

        Builds the EN 16931 CII XML from *invoice* (a ``facturx.Invoice``),
        embeds it as an /AF ``Alternative`` attachment, sets ``pdfa`` so
        part 3 is declared, and records the ``fx`` XMP metadata so
        ``render`` threads it into ``build_xmp_metadata``. The invoice is
        validated here, so inconsistent totals raise before rendering.
        Mutates and returns self so calls can chain like ``add``.
        """
        from .facturx import FacturXMeta, facturx_attachment

        attachment = facturx_attachment(invoice, profile=profile)
        self._extra_attachments.append(attachment)
        self.pdfa = True
        self._facturx_meta = FacturXMeta(conformance_level=profile)
        return self

    def patch(self, node_id: str, **changes) -> "Document":
        """Return a new Document with the block matching node_id replaced.

        Applies ``dataclasses.replace(block, **changes)`` to a deep copy
        of the one content element carrying ``node_id`` — everything
        else, and the original Document, is left untouched. Lets a
        caller (an LLM given one block's id and a small diff) patch a
        single block without regenerating the whole document. Raises
        ``ValueError`` listing the ids actually present when no block
        carries ``node_id`` — typically because ids have not been
        assigned yet (they are assigned on render, ``from_pdf``
        recovery, or an earlier ``patch`` call, not on construction).
        """
        import copy
        import dataclasses

        new_content = copy.deepcopy(self.content)
        for index, element in enumerate(new_content):
            if getattr(element, "id", None) == node_id:
                new_content[index] = dataclasses.replace(element, **changes)
                return dataclasses.replace(self, content=new_content)

        available = sorted(el.id for el in new_content if getattr(el, "id", None))
        raise ValueError(
            f"no block with id {node_id!r} in this document; available ids: {available}"
        )

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

    def text_index(self):
        """Return a `TextIndex` resolving page rectangles to node char ranges.

        Renders once and caches; the cache is keyed to the current content so
        mutating the document and calling again recomputes it.
        """
        from .textmap import TextIndex
        from .writer import render_document

        token = id(self.content), len(self.content)
        cached = getattr(self, "_text_index_cache", None)
        if cached is not None and cached[0] == token:
            return cached[1]
        result = render_document(self, return_result=True)
        index = TextIndex(result.text_index, result.layout_map)
        self._text_index_cache = (token, index)
        return index

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

    @classmethod
    def from_pdf(cls, source, *, strict: bool = False) -> "Document":
        """Reconstruct a Document from a rendered PDF (bytes, path, or str).

        Tries the embedded ``emboss-spec.json`` /AF attachment first — an
        exact reconstruction, present when the PDF was made with
        ``render(embed_spec=True)``. Failing that, falls back to a
        degraded reconstruction from the PDF/UA structure tree: headings,
        paragraphs, tables, and lists come back with correct text and
        order, but styling and exact spec fields are lost. Pass
        ``strict=True`` to raise instead of taking that degraded path.
        """
        from .recovery import recover_from_attachment, recover_from_structure_tree

        document = recover_from_attachment(source)
        if document is not None:
            return document
        if strict:
            raise ValueError(
                "no emboss-spec.json attachment found; strict=True refuses "
                "the degraded structure-tree recovery path"
            )
        return recover_from_structure_tree(source)


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
