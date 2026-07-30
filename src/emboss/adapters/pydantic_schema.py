"""Pydantic v2 models for LLM structured-output pipelines.

These models mirror the dataclass spec but add:
  - JSON Schema generation with rich descriptions and examples
  - Self-healing validation that fixes common LLM mistakes
  - Type coercion so "12" becomes 12.0 for font sizes
  - Content-aware defaults (numeric columns get decimal alignment)

Usage with any LLM:
    from emboss.adapters.pydantic_schema import DocumentSpec
    spec = DocumentSpec.model_validate_json(llm_output)
    pdf_bytes = spec.to_document().render()

Usage with Claude structured output:
    response = client.messages.create(
        model="claude-sonnet-5",
        messages=[...],
        response_format=DocumentSpec,
    )
    spec = DocumentSpec.model_validate(response.parsed)
    spec.to_document().save("output.pdf")
"""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING, Annotated, Literal, Union

if TYPE_CHECKING:
    from ..intelligence import ContentAnalysis

from pydantic import BaseModel, Field, field_validator, model_validator

from ..spec import (
    Abstract,
    Appendix,
    Approval,
    Author,
    Authors,
    BibliographyBlock,
    BlockQuote,
    BulletList,
    Callout,
    CheckboxField,
    Chart,
    CodeBlock,
    CoverPage,
    Document,
    DocumentControl,
    DropdownField,
    Footnote,
    Glossary,
    GlossaryEntry,
    HeaderFooter,
    Heading,
    HorizontalRule,
    Image,
    Index,
    LegalFeatures,
    MathBlock,
    NumberedList,
    PageBreak,
    PageSpec,
    Paragraph,
    PullQuote,
    RevisionEntry,
    Series,
    Stat,
    StatTiles,
    SvgBlock,
    Table,
    TableCell,
    TableOfContents,
    TextField,
    TextRun,
)
from ..bibliography import Citation
from ..brandkit import BrandKit
from ..intelligence import ContentAnalyzer
from ..styles import PRESETS, Style

__all__ = [
    "DocumentSpec",
    "BrandKitSpec",
    "HeadingSpec",
    "ParagraphSpec",
    "TableSpec",
    "BulletListSpec",
    "NumberedListSpec",
    "ImageSpec",
    "ChartSpec",
    "SeriesSpec",
    "FootnoteSpec",
    "CalloutSpec",
    "BlockQuoteSpec",
    "SvgBlockSpec",
    "CoverPageSpec",
    "AbstractSpec",
    "AuthorSpec",
    "AuthorsSpec",
    "PullQuoteSpec",
    "StatSpec",
    "StatTilesSpec",
    "TableOfContentsSpec",
    "AppendixSpec",
    "IndexSpec",
    "GlossaryEntrySpec",
    "GlossarySpec",
    "ApprovalSpec",
    "RevisionEntrySpec",
    "DocumentControlSpec",
    "TextFieldSpec",
    "CheckboxFieldSpec",
    "DropdownFieldSpec",
    "DiagramSpec",
    "DiagramNodeSpec",
    "DiagramEdgeSpec",
    "ArchitectureDiagramSpec",
    "ArchNodeSpec",
    "ArchGroupSpec",
    "SequenceDiagramSpec",
    "SequenceParticipantSpec",
    "SequenceMessageSpec",
    "ErDiagramSpec",
    "EntitySpec",
    "EntityAttributeSpec",
    "RelationshipSpec",
    "HeaderFooterSpec",
    "TextRunSpec",
    "TableCellSpec",
    "PageConfig",
    "LegalConfig",
    "StyleOverride",
    "generate_json_schema",
]

_analyzer = ContentAnalyzer()

_DECIMAL_RE = re.compile(r"^[($\-\s]*\d[\d,]*\.?\d*[%)\s]*$")


class StyleOverride(BaseModel):
    """Per-element style overrides. Only set fields you want to change."""

    model_config = {"json_schema_extra": {"title": "Style Override"}}

    font_family: str | None = Field(
        None,
        description="Font family name: 'Helvetica', 'Times', 'Courier', or a registered custom font.",
    )
    font_size: float | None = Field(
        None, ge=4, le=96, description="Font size in points (4-96)."
    )
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = Field(
        None,
        pattern=r"^[0-9a-fA-F]{6}$",
        description="Hex color without '#' prefix, e.g. '1a1a1a'.",
    )
    align: Literal["left", "center", "right", "justify"] | None = Field(
        None, description="Text alignment."
    )
    line_height: float | None = Field(
        None,
        ge=0.8,
        le=3.0,
        description="Line height multiplier (1.0 = single-spaced).",
    )
    space_before: float | None = Field(
        None, ge=0, description="Space before element in points."
    )
    space_after: float | None = Field(
        None, ge=0, description="Space after element in points."
    )
    indent_first: float | None = Field(
        None, ge=0, description="First-line indent in points."
    )

    def to_style(self) -> Style | None:
        values = self.model_dump(exclude_none=True)
        if not values:
            return None
        return Style(**values)


class TextRunSpec(BaseModel):
    """A span of text with uniform formatting within a paragraph."""

    model_config = {
        "json_schema_extra": {
            "title": "Text Run",
            "examples": [
                {"text": "Revenue increased "},
                {"text": "24.1%", "bold": True, "color": "0d6e3f"},
                {"text": " year over year.", "italic": True},
            ],
        }
    }

    text: str = Field(..., min_length=1, description="The text content of this run.")
    bold: bool = Field(False, description="Whether this text is bold.")
    italic: bool = Field(False, description="Whether this text is italic.")
    font_size: float | None = Field(
        None, ge=4, le=96, description="Override font size in points."
    )
    font_family: str | None = Field(None, description="Override font family.")
    color: str | None = Field(
        None,
        pattern=r"^[0-9a-fA-F]{6}$",
        description="Hex color without '#', e.g. 'cc0000' for red.",
    )
    link: str | None = Field(None, description="URL this text links to.")
    index_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Tag this run's text as index term(s) with no visible effect; "
            "collected into a document's Index block by page number."
        ),
    )

    def to_text_run(self) -> TextRun:
        return TextRun(
            text=self.text,
            bold=self.bold,
            italic=self.italic,
            font_size=self.font_size,
            font_family=self.font_family,
            color=self.color,
            link=self.link,
            index_terms=tuple(self.index_terms),
        )


class HeadingSpec(BaseModel):
    """A section heading. Level determines both visual size and PDF structure tag (H1-H6)."""

    model_config = {
        "json_schema_extra": {
            "title": "Heading",
            "examples": [
                {"type": "heading", "text": "Executive Summary", "level": 1},
                {"type": "heading", "text": "Risk Factors", "level": 2},
            ],
        }
    }

    type: Literal["heading"] = "heading"
    text: str = Field(..., min_length=1, description="Heading text.")
    level: int = Field(
        1, ge=1, le=6, description="Heading level 1 (largest) through 6 (smallest)."
    )
    numbering: str | None = Field(
        None, description="Optional section number prefix, e.g. '3.2'."
    )
    style: StyleOverride | None = None

    @field_validator("text")
    @classmethod
    def strip_heading(cls, v: str) -> str:
        return v.strip()

    def to_element(self) -> Heading:
        return Heading(
            text=self.text,
            level=self.level,
            numbering=self.numbering,
            style=self.style.to_style() if self.style else None,
        )


class ParagraphSpec(BaseModel):
    """A body paragraph. Content can be plain text or a list of styled text runs."""

    model_config = {
        "json_schema_extra": {
            "title": "Paragraph",
            "examples": [
                {"type": "paragraph", "text": "Revenue increased 12% year over year."},
                {
                    "type": "paragraph",
                    "runs": [
                        {"text": "Revenue increased "},
                        {"text": "12%", "bold": True},
                        {"text": " year over year."},
                    ],
                },
            ],
        }
    }

    type: Literal["paragraph"] = "paragraph"
    text: str | None = Field(
        None, description="Plain text content. Use 'runs' instead for mixed formatting."
    )
    runs: list[TextRunSpec] | None = Field(
        None, description="Styled text spans for mixed formatting within the paragraph."
    )
    style: StyleOverride | None = None

    @model_validator(mode="after")
    def require_content(self):
        if not self.text and not self.runs:
            self.text = " "
        return self

    def to_element(self) -> Paragraph:
        if self.runs:
            content = [r.to_text_run() for r in self.runs]
        else:
            content = self.text or ""
        return Paragraph(
            content=content,
            style=self.style.to_style() if self.style else None,
        )


class TableCellSpec(BaseModel):
    """A single table cell. Supports alignment overrides and bold formatting."""

    model_config = {
        "json_schema_extra": {
            "title": "Table Cell",
            "examples": [
                {"value": "$1,234.56", "align": "decimal"},
                {"value": "Total", "bold": True},
            ],
        }
    }

    value: str = Field("", description="Cell content as text.")
    align: Literal["left", "center", "right", "decimal"] | None = Field(
        None,
        description="Cell alignment. Use 'decimal' for numbers to align on the decimal point.",
    )
    bold: bool = False
    background: str | None = Field(
        None, pattern=r"^[0-9a-fA-F]{6}$", description="Cell background hex color."
    )

    def to_table_cell(self) -> TableCell:
        return TableCell(
            content=self.value,
            align=self.align,
            bold=self.bold,
            background=self.background,
        )


class TableSpec(BaseModel):
    """A data table with headers and rows. Column widths are auto-computed from content metrics.

    For financial/numeric data, use align='decimal' on cells to align numbers on the decimal point.
    The engine computes optimal column widths automatically - you rarely need to set them manually.
    """

    model_config = {
        "json_schema_extra": {
            "title": "Table",
            "examples": [
                {
                    "type": "table",
                    "headers": ["Region", "Q3 Revenue", "Change"],
                    "rows": [
                        ["North America", "$2,431,000", "+11.5%"],
                        ["Europe", "$1,204,300", "+4.7%"],
                    ],
                }
            ],
        }
    }

    type: Literal["table"] = "table"
    headers: list[str | TableCellSpec] = Field(
        ..., min_length=1, description="Column header labels."
    )
    rows: list[list[str | TableCellSpec]] = Field(
        ..., min_length=1, description="Data rows. Each row is a list of cell values."
    )
    column_widths: list[float] | None = Field(
        None,
        description="Relative column widths (auto-computed if omitted). e.g. [1, 2, 1] makes the middle column twice as wide.",
    )
    caption: str | None = Field(None, description="Table caption text.")
    stripe: bool = Field(False, description="Alternate row background shading.")
    repeat_header: bool = Field(
        True, description="Repeat header row when table spans multiple pages."
    )
    style: StyleOverride | None = None
    headline: str | None = Field(
        None, description="Bold headline drawn above the table."
    )
    subtitle: str | None = Field(
        None, description="Lighter subtitle drawn below the headline."
    )
    source_line: str | None = Field(
        None, description="Small gray source attribution below the table."
    )
    attach_data: bool = Field(
        False, description="Embed the table's headers and rows as a CSV /AF attachment."
    )
    verify_totals: bool = Field(
        False,
        description="Refuse to render if a Total row or column does not equal "
        "the sum of its cells.",
    )

    @model_validator(mode="after")
    def auto_detect_numeric_alignment(self):
        """Content-aware: auto-detect numeric columns and apply decimal alignment."""
        if not self.rows:
            return self
        col_count = len(self.headers)
        for col_idx in range(col_count):
            values = []
            for row in self.rows:
                if col_idx < len(row):
                    cell = row[col_idx]
                    if isinstance(cell, str):
                        values.append(cell)
                    elif isinstance(cell, TableCellSpec) and cell.align is None:
                        values.append(cell.value)
                    else:
                        values = []
                        break
            if not values:
                continue
            numeric_count = sum(1 for v in values if _DECIMAL_RE.match(v.strip()))
            if numeric_count >= len(values) * 0.7 and numeric_count >= 2:
                for row in self.rows:
                    if col_idx < len(row):
                        cell = row[col_idx]
                        if isinstance(cell, str):
                            row[col_idx] = TableCellSpec(value=cell, align="decimal")
                        elif isinstance(cell, TableCellSpec) and cell.align is None:
                            cell.align = "decimal"
        return self

    def _to_header_cell(self, h) -> TableCell:
        if isinstance(h, TableCellSpec):
            return h.to_table_cell()
        return TableCell(content=str(h))

    def _to_row_cell(self, c) -> str | TableCell:
        if isinstance(c, TableCellSpec):
            return c.to_table_cell()
        return str(c)

    def to_element(self) -> Table:
        headers = [self._to_header_cell(h) for h in self.headers]
        rows = [[self._to_row_cell(c) for c in row] for row in self.rows]
        return Table(
            headers=headers,
            rows=rows,
            column_widths=self.column_widths,
            caption=self.caption,
            stripe=self.stripe,
            repeat_header=self.repeat_header,
            style=self.style.to_style() if self.style else None,
            headline=self.headline,
            subtitle=self.subtitle,
            source_line=self.source_line,
            attach_data=self.attach_data,
            verify_totals=self.verify_totals,
        )


class BulletListSpec(BaseModel):
    """A bulleted list."""

    model_config = {
        "json_schema_extra": {
            "title": "Bullet List",
            "examples": [
                {
                    "type": "bullets",
                    "items": [
                        "Revenue grew 12% year over year",
                        "Operating margin improved to 18.2%",
                        "Customer count exceeded 500",
                    ],
                }
            ],
        }
    }

    type: Literal["bullets"] = "bullets"
    items: list[str] = Field(
        ..., min_length=1, description="List items as plain text strings."
    )
    bullet: str = Field("•", description="Bullet character.")
    style: StyleOverride | None = None

    def to_element(self) -> BulletList:
        return BulletList(
            items=self.items,
            bullet=self.bullet,
            style=self.style.to_style() if self.style else None,
        )


class NumberedListSpec(BaseModel):
    """A numbered (ordered) list."""

    model_config = {
        "json_schema_extra": {
            "title": "Numbered List",
            "examples": [
                {
                    "type": "numbered",
                    "items": [
                        "Collect requirements",
                        "Design architecture",
                        "Implement solution",
                    ],
                }
            ],
        }
    }

    type: Literal["numbered"] = "numbered"
    items: list[str] = Field(
        ..., min_length=1, description="List items as plain text strings."
    )
    start: int = Field(1, ge=1, description="Starting number.")
    style: StyleOverride | None = None

    def to_element(self) -> NumberedList:
        return NumberedList(
            items=self.items,
            start=self.start,
            style=self.style.to_style() if self.style else None,
        )


class ImageSpec(BaseModel):
    """An embedded image (JPEG or PNG file path)."""

    model_config = {
        "json_schema_extra": {
            "title": "Image",
            "examples": [
                {"type": "image", "source": "chart.png", "alt_text": "Sales chart"},
            ],
        }
    }

    type: Literal["image"] = "image"
    source: str = Field(..., description="File path to a JPEG or PNG image.")
    alt_text: str = Field("", description="Alt text for accessibility.")
    width: float | None = Field(None, ge=1, description="Display width in points.")
    height: float | None = Field(None, ge=1, description="Display height in points.")
    caption: str | None = Field(None, description="Image caption.")
    align: Literal["left", "center", "right"] = Field(
        "center", description="Horizontal alignment."
    )

    def to_element(self) -> Image:
        return Image(
            source=self.source,
            alt_text=self.alt_text,
            width=self.width,
            height=self.height,
            caption=self.caption,
            align=self.align,
        )


class SeriesSpec(BaseModel):
    """One named data series within a chart."""

    label: str = Field("", description="Series name shown in the legend.")
    values: list[float] = Field(..., min_length=1, description="Series values.")

    def to_element(self) -> Series:
        return Series(label=self.label, values=self.values)


class ChartSpec(BaseModel):
    """A data chart rendered as vector graphics."""

    model_config = {
        "json_schema_extra": {
            "title": "Chart",
            "examples": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "labels": ["Q1", "Q2", "Q3", "Q4"],
                    "values": [100, 150, 130, 180],
                    "title": "Quarterly Revenue",
                },
                {
                    "type": "chart",
                    "chart_type": "line",
                    "labels": ["Q1", "Q2"],
                    "series": [
                        {"label": "North", "values": [100, 150]},
                        {"label": "South", "values": [90, 120]},
                    ],
                    "x_title": "Quarter",
                    "y_title": "Units",
                },
            ],
        }
    }

    type: Literal["chart"] = "chart"
    chart_type: Literal["bar", "line", "pie", "scatter"] = Field(
        "bar", description="Chart type."
    )
    labels: list[str] = Field(..., min_length=1, description="Category labels.")
    values: list[float] | None = Field(
        None, description="Data values for a single-series chart."
    )
    series: list[SeriesSpec] | None = Field(
        None, description="Named series for multi-series charts."
    )
    colors: list[str] | None = Field(None, description="Hex colors for data series.")
    title: str | None = Field(None, description="Chart title.")
    x_title: str | None = Field(None, description="X-axis title.")
    y_title: str | None = Field(None, description="Y-axis title.")
    legend: bool = Field(True, description="Show a legend for named series.")
    width: float = Field(400.0, ge=50, description="Chart width in points.")
    height: float = Field(250.0, ge=50, description="Chart height in points.")
    patterns: bool = Field(
        False, description="Overlay per-series vector patterns for grayscale print."
    )
    headline: str | None = Field(
        None, description="Bold headline drawn above the chart."
    )
    subtitle: str | None = Field(
        None, description="Lighter subtitle drawn below the headline."
    )
    source_line: str | None = Field(
        None, description="Small gray source attribution below the chart."
    )
    verify_facts: bool = Field(
        False,
        description=(
            "Verify the headline's numbers against the chart data, falling "
            "back to an auto-generated finding when unsupported."
        ),
    )
    attach_data: bool = Field(
        False, description="Embed the chart's series data as a CSV /AF attachment."
    )

    @model_validator(mode="after")
    def _require_data(self) -> "ChartSpec":
        if not self.values and not self.series:
            raise ValueError("chart requires either 'values' or 'series'")
        return self

    def to_element(self) -> Chart:
        return Chart(
            chart_type=self.chart_type,
            labels=self.labels,
            values=self.values or [],
            series=[s.to_element() for s in self.series] if self.series else None,
            colors=self.colors,
            title=self.title,
            x_title=self.x_title,
            y_title=self.y_title,
            legend=self.legend,
            width=self.width,
            height=self.height,
            patterns=self.patterns,
            headline=self.headline,
            subtitle=self.subtitle,
            source_line=self.source_line,
            verify_facts=self.verify_facts,
            attach_data=self.attach_data,
        )


class FootnoteSpec(BaseModel):
    """A footnote rendered at the bottom of the page."""

    model_config = {
        "json_schema_extra": {
            "title": "Footnote",
            "examples": [
                {
                    "type": "footnote",
                    "text": "Source: Annual Report 2024",
                    "marker": "1",
                },
            ],
        }
    }

    type: Literal["footnote"] = "footnote"
    text: str = Field(..., description="Footnote text content.")
    marker: str | None = Field(None, description="Footnote marker (e.g. '1', '*').")

    def to_element(self) -> Footnote:
        return Footnote(content=self.text, marker=self.marker)


class CalloutSpec(BaseModel):
    """A styled container block for callouts, warnings, tips, etc."""

    model_config = {
        "json_schema_extra": {
            "title": "Callout",
            "examples": [
                {
                    "type": "callout",
                    "text": "This action cannot be undone.",
                    "variant": "warning",
                    "title": "Warning",
                },
            ],
        }
    }

    type: Literal["callout"] = "callout"
    text: str = Field(..., description="Callout body text.")
    variant: Literal["info", "warning", "success", "danger", "note"] = Field(
        "note",
        description="Visual variant: info (blue), warning (amber), success (green), danger (red), note (gray).",
    )
    title: str | None = Field(None, description="Optional callout title.")

    def to_element(self) -> Callout:
        return Callout(
            content=self.text,
            variant=self.variant,
            title=self.title,
        )


class BlockQuoteSpec(BaseModel):
    """A pull-quote or quoted passage set off from the body text."""

    model_config = {
        "json_schema_extra": {
            "title": "Block Quote",
            "examples": [
                {
                    "type": "blockquote",
                    "text": "Simplicity is the ultimate sophistication.",
                    "attribution": "Leonardo da Vinci",
                },
            ],
        }
    }

    type: Literal["blockquote"] = "blockquote"
    text: str = Field(..., min_length=1, description="Quoted text.")
    attribution: str | None = Field(
        None, description="Source of the quote, shown after an em dash."
    )

    def to_element(self) -> BlockQuote:
        return BlockQuote(content=self.text, attribution=self.attribution)


class CodeBlockSpec(BaseModel):
    """A code block with syntax highlighting."""

    model_config = {
        "json_schema_extra": {
            "title": "Code Block",
            "examples": [
                {
                    "type": "code_block",
                    "code": "def hello():\n    print('Hello, world!')",
                    "language": "python",
                },
            ],
        }
    }

    type: Literal["code_block"] = "code_block"
    code: str = Field(..., description="The source code to display.")
    language: str = Field(
        "text", description="Programming language for syntax highlighting."
    )
    line_numbers: bool = Field(True, description="Show line numbers in the gutter.")
    theme: str = Field(
        "dark_modern",
        description="Color theme: dark_modern, light_clean, or night_owl.",
    )
    start_line: int = Field(1, ge=1, description="Starting line number.")
    highlight_lines: list[int] = Field(
        default_factory=list, description="Line numbers to highlight."
    )
    caption: str | None = Field(
        None, description="Optional caption below the code block."
    )

    def to_element(self) -> CodeBlock:
        return CodeBlock(
            code=self.code,
            language=self.language,
            line_numbers=self.line_numbers,
            theme=self.theme,
            start_line=self.start_line,
            highlight_lines=self.highlight_lines,
            caption=self.caption,
        )


class MathBlockSpec(BaseModel):
    """A mathematical expression rendered in the document."""

    model_config = {
        "json_schema_extra": {
            "title": "Math Block",
            "examples": [{"type": "math", "source": "E = mc^{2}"}],
        }
    }

    type: Literal["math"] = "math"
    source: str = Field(..., description="LaTeX-subset math expression.")
    display: bool = Field(
        True, description="Display mode (centered, larger) vs inline."
    )
    caption: str | None = Field(
        None, description="Optional caption below the equation."
    )
    label: str | None = Field(
        None, description="Cross-reference key, e.g. 'eq:energy' for @eq:energy."
    )
    number: bool = Field(
        False, description="Right-flush an auto-assigned equation number."
    )
    tag: str | None = Field(
        None, description="Override the equation number text, e.g. '(3a)'."
    )

    def to_element(self) -> MathBlock:
        return MathBlock(
            source=self.source,
            display=self.display,
            caption=self.caption,
            label=self.label,
            number=self.number,
            tag=self.tag,
        )


class CitationSpec(BaseModel):
    """A bibliographic reference."""

    key: str = Field(..., description="Unique citation key.")
    authors: list[str] = Field(default_factory=list, description="Author names.")
    title: str = Field("", description="Title of the work.")
    year: int | str = Field("", description="Publication year.")
    journal: str | None = Field(None, description="Journal name.")
    volume: str | None = None
    pages: str | None = None
    publisher: str | None = None
    doi: str | None = None
    url: str | None = None
    entry_type: Literal["article", "book", "inproceedings", "misc"] = "article"

    def to_citation(self) -> Citation:
        return Citation(
            key=self.key,
            authors=self.authors,
            title=self.title,
            year=self.year,
            journal=self.journal,
            volume=self.volume,
            pages=self.pages,
            publisher=self.publisher,
            doi=self.doi,
            url=self.url,
            entry_type=self.entry_type,
        )


class BibliographySpec(BaseModel):
    """A formatted bibliography section."""

    model_config = {
        "json_schema_extra": {
            "title": "Bibliography",
            "examples": [
                {
                    "type": "bibliography",
                    "citations": [
                        {
                            "key": "ref1",
                            "authors": ["A. Author"],
                            "title": "A Paper",
                            "year": 2024,
                        }
                    ],
                }
            ],
        }
    }

    type: Literal["bibliography"] = "bibliography"
    citations: list[CitationSpec] = Field(default_factory=list)
    bib_style: str = Field(
        "ieee", description="Citation style: ieee, apa, or numbered."
    )
    title: str | None = Field("References", description="Section heading.")
    heading_level: int = Field(2, ge=1, le=6)

    def to_element(self) -> BibliographyBlock:
        return BibliographyBlock(
            citations=[c.to_citation() for c in self.citations],
            bib_style=self.bib_style,
            title=self.title,
            heading_level=self.heading_level,
        )


class PageBreakSpec(BaseModel):
    """Forces subsequent content onto a new page.

    ``page_style`` names an entry in ``DocumentSpec.page_styles``; content
    after this break uses that page's geometry until another page break
    switches again, or reverts to the document default with none set.
    """

    type: Literal["page_break"] = "page_break"
    page_style: str | None = None

    def to_element(self) -> PageBreak:
        return PageBreak(page_style=self.page_style)


class HorizontalRuleSpec(BaseModel):
    """A horizontal divider line."""

    type: Literal["rule"] = "rule"
    thickness: float = Field(0.5, ge=0.1, le=4.0)
    color: str = Field("cccccc", pattern=r"^[0-9a-fA-F]{6}$")

    def to_element(self) -> HorizontalRule:
        return HorizontalRule(thickness=self.thickness, color=self.color)


class SvgBlockSpec(BaseModel):
    """An embedded SVG image rendered as vector graphics in the PDF."""

    type: Literal["svg"] = "svg"
    source: str = Field(..., description="SVG markup string.")
    width: float | None = Field(None, description="Display width in points.")
    height: float | None = Field(None, description="Display height in points.")
    caption: str | None = Field(None, description="Caption below the SVG.")
    label: str | None = Field(None, description="Cross-reference label.")
    alt_text: str = Field("", description="Alt text for accessibility.")
    align: Literal["left", "center", "right"] = "center"

    def to_element(self) -> SvgBlock:
        return SvgBlock(
            source=self.source,
            width=self.width,
            height=self.height,
            caption=self.caption,
            label=self.label,
            alt_text=self.alt_text,
            align=self.align,
        )


class DiagramNodeSpec(BaseModel):
    """One node in an architecture/workflow diagram."""

    id: str = Field(..., min_length=1, description="Unique node identifier.")
    label: str = Field(..., min_length=1, description="Text shown inside the node.")
    shape: Literal["box", "decision", "store", "rounded", "start_end"] = Field(
        "box",
        description=(
            "Node shape: box (component), decision (diamond), store "
            "(database cylinder), rounded, start_end (stadium terminator)."
        ),
    )
    group: str | None = Field(None, description="Optional logical grouping name.")


class DiagramEdgeSpec(BaseModel):
    """A directed connection between two diagram nodes."""

    src: str = Field(..., min_length=1, description="Source node id.")
    dst: str = Field(..., min_length=1, description="Destination node id.")
    label: str | None = Field(None, description="Optional edge label.")
    style: Literal["solid", "dashed"] = Field(
        "solid", description="Line style; use dashed for optional/async paths."
    )


class DiagramSpec(BaseModel):
    """A node/edge graph laid out automatically and rendered as vector art.

    Describe systems and workflows as nodes and edges; the engine computes
    a layered layout (cycles allowed), routes the arrows, and renders the
    result as an accessible vector figure with generated alt text.
    """

    model_config = {
        "json_schema_extra": {
            "title": "Diagram",
            "examples": [
                {
                    "type": "diagram",
                    "nodes": [
                        {"id": "api", "label": "API Gateway"},
                        {"id": "db", "label": "User Store", "shape": "store"},
                    ],
                    "edges": [{"src": "api", "dst": "db", "label": "query"}],
                    "direction": "down",
                }
            ],
        }
    }

    type: Literal["diagram"] = "diagram"
    nodes: list[DiagramNodeSpec] = Field(
        ..., min_length=1, description="Diagram nodes."
    )
    edges: list[DiagramEdgeSpec] = Field(
        default_factory=list, description="Directed connections between node ids."
    )
    direction: Literal["down", "right"] = Field(
        "down", description="Main flow direction of the layout."
    )
    caption: str | None = Field(None, description="Caption below the diagram.")

    @model_validator(mode="after")
    def _check_graph(self) -> "DiagramSpec":
        ids: set[str] = set()
        for node in self.nodes:
            if node.id in ids:
                raise ValueError(f"duplicate diagram node id: {node.id!r}")
            ids.add(node.id)
        for edge in self.edges:
            for endpoint in (edge.src, edge.dst):
                if endpoint not in ids:
                    raise ValueError(
                        f"diagram edge references unknown node id: {endpoint!r}"
                    )
        return self

    def to_element(self) -> SvgBlock:
        from ..diagrams import DiagramEdge, DiagramNode, diagram_svg_block

        return diagram_svg_block(
            [
                DiagramNode(id=n.id, label=n.label, shape=n.shape, group=n.group)
                for n in self.nodes
            ],
            [
                DiagramEdge(src=e.src, dst=e.dst, label=e.label, style=e.style)
                for e in self.edges
            ],
            direction=self.direction,
            caption=self.caption,
        )


class ArchNodeSpec(BaseModel):
    """One service node in an architecture diagram."""

    id: str = Field(..., min_length=1, description="Unique node identifier.")
    label: str = Field(..., min_length=1, description="Text shown under the glyph.")
    service: Literal[
        "compute",
        "database",
        "storage",
        "queue",
        "gateway",
        "cache",
        "cdn",
        "function",
        "loadbalancer",
        "user",
        "external",
        "generic",
    ] = Field(
        "generic",
        description=(
            "Service glyph: compute (server), database (cylinder), storage "
            "(bucket), queue, gateway (hexagon), cache, cdn, function, "
            "loadbalancer, user, external (cloud), generic."
        ),
    )
    group: str | None = Field(None, description="Id of the group this node sits in.")


class ArchGroupSpec(BaseModel):
    """A container region enclosing nodes and/or nested groups by id."""

    id: str = Field(..., min_length=1, description="Unique group identifier.")
    label: str = Field("", description="Title drawn in the group's top-left.")
    node_ids: list[str] = Field(
        default_factory=list,
        description="Ids of member nodes and/or nested group ids.",
    )
    color: str | None = Field(
        None, pattern=r"^#?[0-9a-fA-F]{6}$", description="Border/title hex color."
    )


class ArchitectureDiagramSpec(BaseModel):
    """A cloud/service architecture diagram with grouped service glyphs.

    Nodes render as built-in vector glyphs (server, database, queue, ...);
    groups draw labeled boundary zones (VPC / subnet / account) that can
    nest; edges connect services with labeled solid or dashed arrows.
    """

    model_config = {
        "json_schema_extra": {
            "title": "Architecture Diagram",
            "examples": [
                {
                    "type": "architecture_diagram",
                    "nodes": [
                        {"id": "u", "label": "User", "service": "user"},
                        {
                            "id": "api",
                            "label": "API",
                            "service": "compute",
                            "group": "vpc",
                        },
                        {
                            "id": "db",
                            "label": "Store",
                            "service": "database",
                            "group": "vpc",
                        },
                    ],
                    "groups": [
                        {"id": "vpc", "label": "VPC", "node_ids": ["api", "db"]}
                    ],
                    "edges": [
                        {"src": "u", "dst": "api", "label": "https"},
                        {"src": "api", "dst": "db", "style": "dashed"},
                    ],
                    "direction": "down",
                }
            ],
        }
    }

    type: Literal["architecture_diagram"] = "architecture_diagram"
    nodes: list[ArchNodeSpec] = Field(..., min_length=1, description="Service nodes.")
    edges: list[DiagramEdgeSpec] = Field(
        default_factory=list, description="Directed connections between node ids."
    )
    groups: list[ArchGroupSpec] = Field(
        default_factory=list, description="Boundary zones enclosing nodes/groups."
    )
    direction: Literal["down", "right"] = Field(
        "down", description="Main layout flow direction."
    )
    caption: str | None = Field(None, description="Caption below the diagram.")

    @model_validator(mode="after")
    def _check_graph(self) -> "ArchitectureDiagramSpec":
        node_ids: set[str] = set()
        for node in self.nodes:
            if node.id in node_ids:
                raise ValueError(f"duplicate architecture node id: {node.id!r}")
            node_ids.add(node.id)
        group_ids: set[str] = set()
        for group in self.groups:
            if group.id in group_ids or group.id in node_ids:
                raise ValueError(f"duplicate architecture group id: {group.id!r}")
            group_ids.add(group.id)
        for edge in self.edges:
            for endpoint in (edge.src, edge.dst):
                if endpoint not in node_ids:
                    raise ValueError(
                        f"architecture edge references unknown node id: {endpoint!r}"
                    )
        for group in self.groups:
            for member in group.node_ids:
                if member not in node_ids and member not in group_ids:
                    raise ValueError(
                        f"architecture group references unknown id: {member!r}"
                    )
        return self

    def to_element(self) -> SvgBlock:
        from ..diagrams import (
            ArchGroup,
            ArchNode,
            DiagramEdge,
            architecture_svg_block,
        )

        return architecture_svg_block(
            [
                ArchNode(id=n.id, label=n.label, service=n.service, group=n.group)
                for n in self.nodes
            ],
            [
                DiagramEdge(src=e.src, dst=e.dst, label=e.label, style=e.style)
                for e in self.edges
            ],
            groups=[
                ArchGroup(
                    id=g.id,
                    label=g.label,
                    node_ids=tuple(g.node_ids),
                    color=(g.color if not g.color else "#" + g.color.lstrip("#")),
                )
                for g in self.groups
            ],
            direction=self.direction,
            caption=self.caption,
        )


class SequenceParticipantSpec(BaseModel):
    """A participant (lifeline) in a sequence diagram."""

    id: str = Field(..., min_length=1, description="Unique participant identifier.")
    label: str = Field("", description="Display label (defaults to the id).")


class SequenceMessageSpec(BaseModel):
    """One message between participants at a vertical time step."""

    src: str = Field(..., min_length=1, description="Sending participant id.")
    dst: str = Field(..., min_length=1, description="Receiving participant id.")
    label: str = Field("", description="Message label centered above the arrow.")
    style: Literal["sync", "async", "return"] = Field(
        "sync",
        description=(
            "sync (filled arrowhead), async (open arrowhead), return "
            "(dashed line, open arrowhead)."
        ),
    )
    activate: bool = Field(
        False, description="Start an activation bar on the receiver's lifeline."
    )


class SequenceDiagramSpec(BaseModel):
    """A UML-style sequence diagram: lifelines and time-ordered messages."""

    model_config = {
        "json_schema_extra": {
            "title": "Sequence Diagram",
            "examples": [
                {
                    "type": "sequence_diagram",
                    "participants": [
                        {"id": "u", "label": "User"},
                        {"id": "api", "label": "API"},
                    ],
                    "messages": [
                        {
                            "src": "u",
                            "dst": "api",
                            "label": "login",
                            "style": "sync",
                            "activate": True,
                        },
                        {"src": "api", "dst": "u", "label": "token", "style": "return"},
                    ],
                }
            ],
        }
    }

    type: Literal["sequence_diagram"] = "sequence_diagram"
    participants: list[SequenceParticipantSpec] = Field(
        ..., min_length=1, description="Ordered participants across the top."
    )
    messages: list[SequenceMessageSpec] = Field(
        default_factory=list, description="Ordered messages, top to bottom."
    )
    caption: str | None = Field(None, description="Caption below the diagram.")

    @model_validator(mode="after")
    def _check_graph(self) -> "SequenceDiagramSpec":
        ids: set[str] = set()
        for part in self.participants:
            if part.id in ids:
                raise ValueError(f"duplicate sequence participant id: {part.id!r}")
            ids.add(part.id)
        for msg in self.messages:
            for endpoint in (msg.src, msg.dst):
                if endpoint not in ids:
                    raise ValueError(
                        f"sequence message references unknown participant: {endpoint!r}"
                    )
        return self

    def to_element(self) -> SvgBlock:
        from ..diagrams import (
            SequenceMessage,
            SequenceParticipant,
            sequence_svg_block,
        )

        return sequence_svg_block(
            [
                SequenceParticipant(id=p.id, label=p.label or p.id)
                for p in self.participants
            ],
            [
                SequenceMessage(
                    src=m.src,
                    dst=m.dst,
                    label=m.label,
                    style=m.style,
                    activate=m.activate,
                )
                for m in self.messages
            ],
            caption=self.caption,
        )


class EntityAttributeSpec(BaseModel):
    """One attribute row of an entity."""

    name: str = Field(..., min_length=1, description="Attribute name.")
    key: Literal["PK", "FK"] | None = Field(
        None, description="Key marker: PK (primary) or FK (foreign)."
    )
    type: str | None = Field(None, description="Optional data type shown at right.")


class EntitySpec(BaseModel):
    """A named entity box with attribute rows."""

    id: str = Field(..., min_length=1, description="Unique entity identifier.")
    name: str = Field("", description="Entity name shown in the title bar.")
    attributes: list[EntityAttributeSpec] = Field(
        default_factory=list, description="Attribute rows."
    )


class RelationshipSpec(BaseModel):
    """A relationship line between two entities with cardinality labels."""

    src: str = Field(..., min_length=1, description="Source entity id.")
    dst: str = Field(..., min_length=1, description="Destination entity id.")
    label: str | None = Field(None, description="Relationship label at the midpoint.")
    src_card: str | None = Field(
        None, description="Cardinality near the source, e.g. '1', 'N', '0..1'."
    )
    dst_card: str | None = Field(None, description="Cardinality near the destination.")


class ErDiagramSpec(BaseModel):
    """An entity-relationship diagram: entity tables and their relationships."""

    model_config = {
        "json_schema_extra": {
            "title": "Entity-Relationship Diagram",
            "examples": [
                {
                    "type": "er_diagram",
                    "entities": [
                        {
                            "id": "user",
                            "name": "User",
                            "attributes": [
                                {"name": "id", "key": "PK", "type": "int"},
                                {"name": "email", "type": "text"},
                            ],
                        },
                        {
                            "id": "order",
                            "name": "Order",
                            "attributes": [
                                {"name": "id", "key": "PK"},
                                {"name": "user_id", "key": "FK", "type": "int"},
                            ],
                        },
                    ],
                    "relationships": [
                        {
                            "src": "user",
                            "dst": "order",
                            "label": "places",
                            "src_card": "1",
                            "dst_card": "N",
                        }
                    ],
                }
            ],
        }
    }

    type: Literal["er_diagram"] = "er_diagram"
    entities: list[EntitySpec] = Field(..., min_length=1, description="Entity tables.")
    relationships: list[RelationshipSpec] = Field(
        default_factory=list, description="Relationships between entities."
    )
    caption: str | None = Field(None, description="Caption below the diagram.")

    @model_validator(mode="after")
    def _check_graph(self) -> "ErDiagramSpec":
        ids: set[str] = set()
        for entity in self.entities:
            if entity.id in ids:
                raise ValueError(f"duplicate entity id: {entity.id!r}")
            ids.add(entity.id)
        for rel in self.relationships:
            for endpoint in (rel.src, rel.dst):
                if endpoint not in ids:
                    raise ValueError(
                        f"relationship references unknown entity: {endpoint!r}"
                    )
        return self

    def to_element(self) -> SvgBlock:
        from ..diagrams import (
            Entity,
            EntityAttribute,
            Relationship,
            er_svg_block,
        )

        return er_svg_block(
            [
                Entity(
                    id=e.id,
                    name=e.name or e.id,
                    attributes=tuple(
                        EntityAttribute(name=a.name, key=a.key, type=a.type)
                        for a in e.attributes
                    ),
                )
                for e in self.entities
            ],
            [
                Relationship(
                    src=r.src,
                    dst=r.dst,
                    label=r.label,
                    src_card=r.src_card,
                    dst_card=r.dst_card,
                )
                for r in self.relationships
            ],
            caption=self.caption,
        )


class CoverPageSpec(BaseModel):
    """A full-page cover: centered title, subtitle, authors, and accent rule."""

    model_config = {
        "json_schema_extra": {
            "title": "Cover Page",
            "examples": [
                {
                    "type": "cover_page",
                    "title": "Annual Report",
                    "subtitle": "Fiscal Year 2025",
                    "authors": ["Jane Doe", "John Roe"],
                    "date": "July 2026",
                    "kicker": "Confidential",
                }
            ],
        }
    }

    type: Literal["cover_page"] = "cover_page"
    title: str = Field(..., min_length=1, description="Cover title.")
    subtitle: str = Field("", description="Subtitle under the title.")
    authors: list[str] = Field(default_factory=list, description="Author names.")
    date: str = Field("", description="Date line.")
    kicker: str = Field("", description="Small uppercase label above the title.")

    def to_element(self) -> CoverPage:
        return CoverPage(
            title=self.title,
            subtitle=self.subtitle,
            authors=tuple(self.authors),
            date=self.date,
            kicker=self.kicker,
        )


class AbstractSpec(BaseModel):
    """An indented abstract with a label and optional keywords line."""

    model_config = {
        "json_schema_extra": {
            "title": "Abstract",
            "examples": [
                {
                    "type": "abstract",
                    "text": "We present a method for ...",
                    "keywords": ["typography", "layout"],
                }
            ],
        }
    }

    type: Literal["abstract"] = "abstract"
    text: str = Field(..., min_length=1, description="Abstract body text.")
    keywords: list[str] = Field(
        default_factory=list, description="Optional keyword list."
    )

    def to_element(self) -> Abstract:
        return Abstract(text=self.text, keywords=tuple(self.keywords))


class AuthorSpec(BaseModel):
    """One author entry for an author grid."""

    name: str = Field(..., min_length=1, description="Author name.")
    affiliation: str = Field("", description="Affiliation or organization.")
    email: str = Field("", description="Contact email.")

    def to_author(self) -> Author:
        return Author(name=self.name, affiliation=self.affiliation, email=self.email)


class AuthorsSpec(BaseModel):
    """A centered grid of author entries."""

    model_config = {
        "json_schema_extra": {
            "title": "Authors",
            "examples": [
                {
                    "type": "authors",
                    "authors": [
                        {"name": "Ada Lovelace", "affiliation": "Analytical Engine"},
                        {"name": "Alan Turing", "email": "alan@npl.uk"},
                    ],
                }
            ],
        }
    }

    type: Literal["authors"] = "authors"
    authors: list[AuthorSpec] = Field(..., min_length=1, description="Author entries.")

    def to_element(self) -> Authors:
        return Authors(authors=[a.to_author() for a in self.authors])


class PullQuoteSpec(BaseModel):
    """A large-type offset pull quote with optional attribution."""

    model_config = {
        "json_schema_extra": {
            "title": "Pull Quote",
            "examples": [
                {
                    "type": "pull_quote",
                    "text": "The best way to predict the future is to invent it.",
                    "attribution": "Alan Kay",
                }
            ],
        }
    }

    type: Literal["pull_quote"] = "pull_quote"
    text: str = Field(..., min_length=1, description="Quoted text.")
    attribution: str = Field("", description="Source of the quote.")

    def to_element(self) -> PullQuote:
        return PullQuote(text=self.text, attribution=self.attribution)


class StatSpec(BaseModel):
    """One statistic tile: a value with a label and optional signed delta."""

    label: str = Field(..., description="Short uppercase label.")
    value: str = Field(..., description="Large headline value, e.g. '$4.5M'.")
    delta: str | None = Field(
        None, description="Signed change, e.g. '+12%' or '-3%'; colored by sign."
    )

    def to_stat(self) -> Stat:
        return Stat(label=self.label, value=self.value, delta=self.delta)


class StatTilesSpec(BaseModel):
    """A row of bordered statistic tiles."""

    model_config = {
        "json_schema_extra": {
            "title": "Stat Tiles",
            "examples": [
                {
                    "type": "stat_tiles",
                    "stats": [
                        {"label": "Revenue", "value": "$4.5M", "delta": "+12%"},
                        {"label": "Churn", "value": "2.1%", "delta": "-0.3%"},
                        {"label": "NPS", "value": "61"},
                    ],
                }
            ],
        }
    }

    type: Literal["stat_tiles"] = "stat_tiles"
    stats: list[StatSpec] = Field(..., min_length=1, description="Tiles to render.")

    def to_element(self) -> StatTiles:
        return StatTiles(stats=[s.to_stat() for s in self.stats])


class TableOfContentsSpec(BaseModel):
    """A visible contents / figures / tables listing with dot leaders."""

    model_config = {
        "json_schema_extra": {
            "title": "Table of Contents",
            "examples": [
                {"type": "toc", "title": "Contents", "depth": 3},
                {"type": "toc", "title": "List of Figures", "source": "figures"},
            ],
        }
    }

    type: Literal["toc"] = "toc"
    title: str = Field("Contents", description="Heading shown above the listing.")
    depth: int = Field(3, ge=1, le=6, description="Deepest heading level to list.")
    source: Literal["headings", "figures", "tables"] = Field(
        "headings",
        description="What to list: document headings, figures, or tables.",
    )

    def to_element(self) -> TableOfContents:
        return TableOfContents(title=self.title, depth=self.depth, source=self.source)


class HeaderFooterSpec(BaseModel):
    """Structured header or footer with left/center/right slots."""

    left: str | None = Field(
        None,
        description=(
            "Left-aligned text. Use {page}, {pages}, and {section} placeholders."
        ),
    )
    center: str | None = Field(None, description="Center-aligned text.")
    right: str | None = Field(None, description="Right-aligned text.")
    font_size: float | None = Field(None, ge=4, le=24)
    font_family: str | None = None
    color: str | None = Field(None, pattern=r"^[0-9a-fA-F]{6}$")
    separator_line: bool = Field(False, description="Draw a separator line.")
    first_page: bool = Field(
        True, description="Set false to suppress this header/footer on page 1."
    )
    first_page_override: "HeaderFooterSpec | None" = Field(
        None, description="Replacement header/footer used only on page 1."
    )

    def to_header_footer(self) -> HeaderFooter:
        return HeaderFooter(
            left=self.left,
            center=self.center,
            right=self.right,
            font_size=self.font_size,
            font_family=self.font_family,
            color=self.color,
            separator_line=self.separator_line,
            first_page=self.first_page,
            first_page_override=(
                self.first_page_override.to_header_footer()
                if self.first_page_override
                else None
            ),
        )


class AppendixSpec(BaseModel):
    """A titled section using alphabetic numbering (Appendix A, B, ...).

    Headings nested in ``content`` get flat ``A.1``, ``A.2`` prefixes,
    restarting at the next top-level appendix.
    """

    model_config = {
        "json_schema_extra": {
            "title": "Appendix",
            "examples": [
                {
                    "type": "appendix",
                    "title": "Survey Instrument",
                    "content": [
                        {"type": "heading", "text": "Questions", "level": 2},
                        {"type": "paragraph", "text": "1. How satisfied are you?"},
                    ],
                }
            ],
        }
    }

    type: Literal["appendix"] = "appendix"
    title: str = Field(..., min_length=1, description="Appendix title.")
    content: list["ContentBlock"] = Field(
        default_factory=list, description="Blocks nested inside this appendix."
    )

    def to_element(self) -> Appendix:
        return Appendix(
            title=self.title, content=[b.to_element() for b in self.content]
        )


class IndexSpec(BaseModel):
    """A back-of-book index page.

    Entries come from ``index_terms`` marks on paragraph text runs
    elsewhere in the document, resolved to real page numbers automatically.
    Include at most one per document.
    """

    model_config = {
        "json_schema_extra": {
            "title": "Index",
            "examples": [{"type": "index", "title": "Index"}],
        }
    }

    type: Literal["index"] = "index"
    title: str = Field("Index", description="Heading shown above the index.")

    def to_element(self) -> Index:
        return Index(title=self.title)


class GlossaryEntrySpec(BaseModel):
    """One glossary term and its definition."""

    term: str = Field(..., min_length=1, description="The term being defined.")
    definition: str = Field(..., min_length=1, description="The term's definition.")

    def to_glossary_entry(self) -> GlossaryEntry:
        return GlossaryEntry(term=self.term, definition=self.definition)


class GlossarySpec(BaseModel):
    """A glossary of terms and definitions, alphabetized by term.

    The first document-wide body-text occurrence of each term is
    automatically linked to its entry here.
    """

    model_config = {
        "json_schema_extra": {
            "title": "Glossary",
            "examples": [
                {
                    "type": "glossary",
                    "entries": [
                        {"term": "Latency", "definition": "Time to first byte."},
                        {"term": "Throughput", "definition": "Requests per second."},
                    ],
                }
            ],
        }
    }

    type: Literal["glossary"] = "glossary"
    title: str = Field("Glossary", description="Heading shown above the glossary.")
    entries: list[GlossaryEntrySpec] = Field(
        ..., min_length=1, description="Term/definition entries."
    )

    def to_element(self) -> Glossary:
        return Glossary(
            title=self.title,
            entries=[e.to_glossary_entry() for e in self.entries],
        )


class ApprovalSpec(BaseModel):
    """One approver's sign-off row in a controlled document."""

    name: str = Field(..., min_length=1, description="Approver's name.")
    role: str = Field("", description="Approver's role or title.")
    date: str = Field("", description="Approval date as a display string.")
    statement: str = Field("Approved", description="Sign-off statement.")

    def to_approval(self) -> Approval:
        return Approval(
            name=self.name, role=self.role, date=self.date, statement=self.statement
        )


class RevisionEntrySpec(BaseModel):
    """One row of a controlled document's revision history."""

    version: str = Field(..., min_length=1, description="Version or revision label.")
    date: str = Field("", description="Revision date as a display string.")
    author: str = Field("", description="Who made the revision.")
    summary: str = Field("", description="Summary of what changed.")

    def to_revision(self) -> RevisionEntry:
        return RevisionEntry(
            version=self.version,
            date=self.date,
            author=self.author,
            summary=self.summary,
        )


class DocumentControlSpec(BaseModel):
    """A controlled-document control block for ISO 9001 / IEC 62304 workflows."""

    model_config = {
        "json_schema_extra": {
            "title": "Document Control",
            "examples": [
                {
                    "type": "document_control",
                    "doc_id": "QMS-001",
                    "version": "3.0",
                    "status": "Released",
                    "effective_date": "2026-01-15",
                    "classification": "Controlled",
                    "owner": "Quality",
                    "approvals": [
                        {"name": "A. Reviewer", "role": "QA Lead", "date": "2026-01-10"}
                    ],
                    "revisions": [
                        {
                            "version": "3.0",
                            "date": "2026-01-15",
                            "author": "J. Doe",
                            "summary": "Annual review.",
                        }
                    ],
                }
            ],
        }
    }

    type: Literal["document_control"] = "document_control"
    doc_id: str | None = Field(None, description="Document identifier.")
    title: str | None = Field(None, description="Document title.")
    version: str | None = Field(None, description="Version or revision label.")
    status: str | None = Field(None, description="Status, e.g. 'Released', 'Draft'.")
    effective_date: str | None = Field(
        None, description="Effective date as a display string."
    )
    classification: str | None = Field(
        None, description="Classification, e.g. 'Controlled'."
    )
    owner: str | None = Field(None, description="Owning person or department.")
    approvals: list[ApprovalSpec] = Field(
        default_factory=list, description="Approver sign-off rows."
    )
    revisions: list[RevisionEntrySpec] = Field(
        default_factory=list, description="Revision-history rows."
    )

    def to_element(self) -> DocumentControl:
        return DocumentControl(
            doc_id=self.doc_id,
            title=self.title,
            version=self.version,
            status=self.status,
            effective_date=self.effective_date,
            classification=self.classification,
            owner=self.owner,
            approvals=[a.to_approval() for a in self.approvals],
            revisions=[r.to_revision() for r in self.revisions],
        )


class TextFieldSpec(BaseModel):
    """A fillable single- or multi-line text input (AcroForm /Tx)."""

    model_config = {
        "json_schema_extra": {
            "title": "Text Field",
            "examples": [
                {
                    "type": "text_field",
                    "name": "full_name",
                    "label": "Full Name",
                    "required": True,
                },
            ],
        }
    }

    type: Literal["text_field"] = "text_field"
    name: str = Field(
        ..., min_length=1, description="AcroForm field name (/T); unique per document."
    )
    label: str | None = Field(None, description="Visible label drawn above the box.")
    default: str = Field("", description="Pre-filled value (/V).")
    multiline: bool = Field(
        False, description="Allow line breaks; reserves a taller box."
    )
    required: bool = Field(
        False, description="Marks the field required in the AcroForm."
    )

    def to_element(self) -> TextField:
        return TextField(
            name=self.name,
            label=self.label,
            default=self.default,
            multiline=self.multiline,
            required=self.required,
        )


class CheckboxFieldSpec(BaseModel):
    """A fillable checkbox (AcroForm /Btn)."""

    model_config = {
        "json_schema_extra": {
            "title": "Checkbox Field",
            "examples": [
                {
                    "type": "checkbox_field",
                    "name": "agree_terms",
                    "label": "I agree to the terms and conditions",
                },
            ],
        }
    }

    type: Literal["checkbox_field"] = "checkbox_field"
    name: str = Field(
        ..., min_length=1, description="AcroForm field name (/T); unique per document."
    )
    label: str | None = Field(None, description="Visible label drawn beside the box.")
    checked: bool = Field(False, description="Pre-checked state (/V and /AS).")

    def to_element(self) -> CheckboxField:
        return CheckboxField(name=self.name, label=self.label, checked=self.checked)


class DropdownFieldSpec(BaseModel):
    """A fillable dropdown / combo-box choice field (AcroForm /Ch)."""

    model_config = {
        "json_schema_extra": {
            "title": "Dropdown Field",
            "examples": [
                {
                    "type": "dropdown_field",
                    "name": "country",
                    "label": "Country",
                    "options": ["United States", "Canada", "Mexico"],
                },
            ],
        }
    }

    type: Literal["dropdown_field"] = "dropdown_field"
    name: str = Field(
        ..., min_length=1, description="AcroForm field name (/T); unique per document."
    )
    options: list[str] = Field(
        ..., min_length=1, description="Choices populating /Opt; must be non-empty."
    )
    label: str | None = Field(None, description="Visible label drawn above the box.")
    default: str | None = Field(None, description="Pre-selected option (/V).")

    def to_element(self) -> DropdownField:
        return DropdownField(
            name=self.name,
            options=self.options,
            label=self.label,
            default=self.default,
        )


ContentBlock = Annotated[
    Union[
        HeadingSpec,
        ParagraphSpec,
        TableSpec,
        BulletListSpec,
        NumberedListSpec,
        ImageSpec,
        ChartSpec,
        FootnoteSpec,
        CalloutSpec,
        BlockQuoteSpec,
        CodeBlockSpec,
        MathBlockSpec,
        BibliographySpec,
        SvgBlockSpec,
        CoverPageSpec,
        AbstractSpec,
        AuthorsSpec,
        PullQuoteSpec,
        StatTilesSpec,
        TableOfContentsSpec,
        AppendixSpec,
        IndexSpec,
        GlossarySpec,
        DocumentControlSpec,
        DiagramSpec,
        ArchitectureDiagramSpec,
        SequenceDiagramSpec,
        ErDiagramSpec,
        PageBreakSpec,
        HorizontalRuleSpec,
        TextFieldSpec,
        CheckboxFieldSpec,
        DropdownFieldSpec,
    ],
    Field(discriminator="type"),
]

AppendixSpec.model_rebuild()


class PageConfig(BaseModel):
    """Page geometry. All measurements in PDF points (72 points = 1 inch)."""

    model_config = {
        "json_schema_extra": {
            "title": "Page Configuration",
            "examples": [
                {"preset": "letter"},
                {"preset": "a4", "margin_left": 108},
            ],
        }
    }

    preset: Literal["letter", "a4", "a5", "legal", "compact"] | None = Field(
        "letter",
        description=(
            "Page size preset. 'compact' is A5 with tight margins, suited to "
            "phone and tablet reading."
        ),
    )
    width: float | None = Field(
        None, ge=72, description="Page width in points (overrides preset)."
    )
    height: float | None = Field(
        None, ge=72, description="Page height in points (overrides preset)."
    )
    margin_top: float | None = Field(None, ge=0, description="Top margin in points.")
    margin_right: float | None = Field(
        None, ge=0, description="Right margin in points."
    )
    margin_bottom: float | None = Field(
        None, ge=0, description="Bottom margin in points."
    )
    margin_left: float | None = Field(None, ge=0, description="Left margin in points.")
    columns: int = Field(1, ge=1, le=4, description="Number of text columns (1-4).")
    column_gap: float | None = Field(
        None, ge=0, description="Gap between columns in points."
    )
    mirror_margins: bool = Field(
        False,
        description=(
            "Swap left/right margins on even (verso) pages for bound documents."
        ),
    )
    landscape: bool = Field(
        False,
        description="Rotate the page to landscape orientation (width > height).",
    )

    def to_page_spec(self) -> PageSpec:
        overrides = {}
        for name in ("margin_top", "margin_right", "margin_bottom", "margin_left"):
            val = getattr(self, name)
            if val is not None:
                overrides[name] = val
        if self.columns != 1:
            overrides["columns"] = self.columns
        if self.column_gap is not None:
            overrides["column_gap"] = self.column_gap
        if self.mirror_margins:
            overrides["mirror_margins"] = True
        if self.landscape:
            overrides["landscape"] = True

        if self.width and self.height:
            return PageSpec(width=self.width, height=self.height, **overrides)

        factory = {
            "letter": PageSpec.letter,
            "a4": PageSpec.a4,
            "a5": PageSpec.a5,
            "legal": PageSpec.legal,
            "compact": PageSpec.compact,
        }.get(self.preset or "letter", PageSpec.letter)
        return factory(**overrides)


class LegalConfig(BaseModel):
    """Legal and financial document features."""

    model_config = {
        "json_schema_extra": {
            "title": "Legal Features",
            "examples": [
                {"watermark": "CONFIDENTIAL"},
                {"bates_prefix": "ACME-", "line_numbering": True},
            ],
        }
    }

    watermark: str | None = Field(
        None, description="Diagonal watermark text across every page."
    )
    watermark_opacity: float = Field(0.12, ge=0.01, le=1.0)
    line_numbering: bool = Field(
        False,
        description="Continuous line numbering in the left margin (for court pleadings).",
    )
    bates_prefix: str | None = Field(
        None,
        description="Bates number prefix, e.g. 'ACME-'. Numbers auto-increment per page.",
    )
    bates_start: int = Field(1, ge=0)
    bates_digits: int = Field(6, ge=1, le=12)
    bates_position: Literal["bottom-right", "bottom-left", "top-right"] = "bottom-right"

    def to_legal_features(self) -> LegalFeatures:
        return LegalFeatures(
            watermark=self.watermark,
            watermark_opacity=self.watermark_opacity,
            line_numbering=self.line_numbering,
            bates_prefix=self.bates_prefix,
            bates_start=self.bates_start,
            bates_digits=self.bates_digits,
            bates_position=self.bates_position,
        )


_HEX = r"^[0-9a-fA-F]{6}$"


class BrandKitSpec(BaseModel):
    """A versioned brand applied programmatically over the document style.

    Set by the integrator, not the LLM: colors, fonts, footer, and an
    optional logo (a file path via 'logo', or base64 PNG bytes via 'logo_b64').
    """

    model_config = {"json_schema_extra": {"title": "Brand Kit"}}

    name: str = Field(..., min_length=1, description="Brand name.")
    version: str = Field("1.0", description="Brand version tag.")
    primary: str = Field(
        ..., pattern=_HEX, description="Primary brand color (headings)."
    )
    accent: str = Field(..., pattern=_HEX, description="Accent color (rules, marks).")
    ink: str = Field("1a1a1a", pattern=_HEX, description="Body text color.")
    muted: str = Field("6b7280", pattern=_HEX, description="Secondary/rule tint.")
    palette: list[str] = Field(
        default_factory=list, description="Chart series colors as hex strings."
    )
    heading_font: str | None = Field(None, description="Heading font family.")
    body_font: str | None = Field(None, description="Body font family.")
    mono_font: str | None = Field(None, description="Monospace font family.")
    footer_text: str = Field("", description="Standard footer line.")
    logo: str | None = Field(None, description="Logo file path.")
    logo_b64: str | None = Field(None, description="Logo PNG bytes, base64-encoded.")

    def to_brandkit(self) -> BrandKit:
        if self.logo_b64:
            logo: bytes | str | None = base64.b64decode(self.logo_b64)
        else:
            logo = self.logo
        return BrandKit(
            name=self.name,
            version=self.version,
            primary=self.primary,
            accent=self.accent,
            ink=self.ink,
            muted=self.muted,
            palette=tuple(self.palette),
            heading_font=self.heading_font,
            body_font=self.body_font,
            mono_font=self.mono_font,
            footer_text=self.footer_text,
            logo=logo,
        )


class DocumentSpec(BaseModel):
    """Complete document specification for PDF generation.

    This is the top-level model that LLMs should produce. Every field has sensible
    defaults, so a minimal spec only needs a title and content blocks.

    The engine handles all layout, typography, and accessibility tagging automatically.
    You never specify coordinates, page breaks for overflow, or structure tags.
    """

    model_config = {
        "json_schema_extra": {
            "title": "Emboss Document",
            "description": (
                "A complete document specification. The rendering engine handles "
                "typography (Knuth-Plass optimal line breaking, hyphenation, kerning), "
                "layout (pagination, widow/orphan control, table splitting), and "
                "accessibility (PDF/UA structure tree) automatically. "
                "Output is deterministic: identical specs produce identical bytes."
            ),
            "examples": [
                {
                    "title": "Q3 Financial Report",
                    "style": "finance",
                    "content": [
                        {"type": "heading", "text": "Executive Summary", "level": 1},
                        {
                            "type": "paragraph",
                            "text": "Revenue reached $4.53M, up 11.8% sequentially.",
                        },
                        {
                            "type": "table",
                            "headers": ["Region", "Revenue", "Change"],
                            "rows": [
                                ["North America", "$2.4M", "+11.5%"],
                                ["Europe", "$1.2M", "+4.7%"],
                            ],
                            "stripe": True,
                        },
                    ],
                }
            ],
        }
    }

    title: str = Field(
        ...,
        min_length=1,
        description="Document title. Required for PDF/UA accessibility compliance.",
    )
    author: str = Field("", description="Document author.")
    subject: str = Field("", description="Document subject or summary.")
    keywords: str = Field(
        "", description="Comma-separated keywords for document metadata."
    )
    language: str = Field(
        "en-US", description="BCP-47 language tag, e.g. 'en-US', 'de-DE'."
    )

    style: Literal[
        "legal", "finance", "academic", "corporate", "minimal", "journal", "brief"
    ] = Field(
        "corporate",
        description=(
            "Visual preset: 'legal' (serif, justified, generous leading), "
            "'finance' (sans, tight, tabular), 'academic' (serif, justified, classic), "
            "'corporate' (sans, readable, roomy), 'minimal' (compact, data-heavy), 'journal' (serif, justified, forest accent), 'brief' (executive, bold accents)."
        ),
    )

    page: PageConfig = Field(default_factory=PageConfig, description="Page geometry.")
    page_styles: dict[str, PageConfig] = Field(
        default_factory=dict,
        description=(
            "Named page geometries (e.g. a wide landscape page for a table "
            "or diagram) that a page_break's page_style can switch to "
            "mid-document, reverting to `page` on a page break with no "
            "page_style."
        ),
    )
    brand: BrandKitSpec | None = Field(
        None,
        description=(
            "Versioned brand (colors, fonts, footer, logo) applied over the "
            "style. Set by the integrator, not the model."
        ),
    )
    content: list[ContentBlock] = Field(
        ...,
        min_length=1,
        description="Document content as an ordered list of blocks: headings, paragraphs, tables, bullet lists, page breaks, and horizontal rules.",
    )

    header_text: str | None = Field(
        None, description="Simple running header text on every page."
    )
    footer_text: str | None = Field(
        None, description="Simple running footer text on every page."
    )
    header: HeaderFooterSpec | None = Field(
        None, description="Structured header with left/center/right slots."
    )
    footer: HeaderFooterSpec | None = Field(
        None, description="Structured footer with left/center/right slots."
    )
    page_numbers: bool = Field(True, description="Show page numbers in the footer.")
    page_number_format: Literal["arabic", "roman", "ROMAN"] = Field(
        "arabic",
        description="Page number style: arabic (1, 2), roman (i, ii), ROMAN (I, II).",
    )
    front_matter_pages: int = Field(
        0,
        ge=0,
        description=(
            "Number the first N pages i, ii, iii; body numbering restarts at 1."
        ),
    )
    tagged: bool = Field(True, description="Generate PDF/UA accessibility tags.")
    toc: bool = Field(
        False, description="Insert an automatically generated table of contents."
    )

    legal: LegalConfig | None = Field(
        None,
        description="Legal/financial features: watermarks, Bates numbering, line numbering.",
    )
    smart: bool = Field(
        True,
        description=(
            "Enable content intelligence: smart typography (curly quotes, "
            "proper dashes, ellipses), auto-detection of table summary rows, "
            "and domain-aware style recommendations. Set to false for raw pass-through."
        ),
    )

    @field_validator("style")
    @classmethod
    def validate_style(cls, v: str) -> str:
        if v not in PRESETS:
            available = ", ".join(sorted(PRESETS))
            raise ValueError(f"Unknown style '{v}'. Available: {available}")
        return v

    @model_validator(mode="after")
    def heal_heading_hierarchy(self):
        """Self-healing: fix heading level jumps that LLMs commonly produce."""
        prev_level = 0
        for block in self.content:
            if isinstance(block, HeadingSpec):
                if prev_level > 0 and block.level > prev_level + 1:
                    block.level = prev_level + 1
                prev_level = block.level
        return self

    def to_document(self) -> Document:
        """Convert this spec to the internal Document model and render-ready state."""
        doc = Document(
            title=self.title,
            author=self.author,
            subject=self.subject,
            keywords=self.keywords,
            language=self.language,
            style=self.style,
            brand=self.brand.to_brandkit() if self.brand else None,
            page=self.page.to_page_spec(),
            page_styles={
                name: cfg.to_page_spec() for name, cfg in self.page_styles.items()
            },
            header_text=self.header_text,
            footer_text=self.footer_text,
            header=self.header.to_header_footer() if self.header else None,
            footer=self.footer.to_header_footer() if self.footer else None,
            page_numbers=self.page_numbers,
            page_number_format=self.page_number_format,
            front_matter_pages=self.front_matter_pages,
            tagged=self.tagged,
            toc=self.toc,
            legal=self.legal.to_legal_features() if self.legal else None,
        )
        for block in self.content:
            doc.add(block.to_element())
        return doc

    def render(self) -> bytes:
        """Shortcut: convert to Document and render to PDF bytes."""
        return self.to_document().render()

    def save(self, path: str) -> None:
        """Shortcut: convert to Document and save to a file."""
        self.to_document().save(path)

    def analyze(self) -> "ContentAnalysis":
        """Run content intelligence analysis and return the report."""
        return _analyzer.analyze_spec(self.model_dump())

    @classmethod
    def from_smart(cls, data: dict) -> "DocumentSpec":
        """Create a DocumentSpec with content intelligence applied.

        Runs the ContentAnalyzer on the raw dict before validation:
        smart typography, table intelligence, and auto-style detection.
        """
        enhanced = _analyzer.enhance_spec(
            data,
            auto_style=("style" not in data),
            smart_typography=data.get("smart", True),
            smart_tables=data.get("smart", True),
        )
        return cls.model_validate(enhanced)


def generate_json_schema(*, indent: int = 2) -> str:
    """Export the complete JSON Schema for LLM prompt engineering.

    Include this schema in an LLM's system prompt so it can produce
    valid document specifications in a single generation pass.
    """
    import json

    schema = DocumentSpec.model_json_schema()
    return json.dumps(schema, indent=indent)
