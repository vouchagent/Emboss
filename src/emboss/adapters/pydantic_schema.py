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

import re
from typing import TYPE_CHECKING, Annotated, Literal, Union

if TYPE_CHECKING:
    from ..intelligence import ContentAnalysis

from pydantic import BaseModel, Field, field_validator, model_validator

from ..spec import (
    BibliographyBlock,
    BlockQuote,
    BulletList,
    Callout,
    Chart,
    CodeBlock,
    Document,
    Footnote,
    HeaderFooter,
    Heading,
    HorizontalRule,
    Image,
    LegalFeatures,
    MathBlock,
    NumberedList,
    PageBreak,
    PageSpec,
    Paragraph,
    Series,
    SvgBlock,
    Table,
    TableCell,
    TextRun,
)
from ..bibliography import Citation
from ..intelligence import ContentAnalyzer
from ..styles import PRESETS, Style

__all__ = [
    "DocumentSpec",
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

    def to_text_run(self) -> TextRun:
        return TextRun(
            text=self.text,
            bold=self.bold,
            italic=self.italic,
            font_size=self.font_size,
            font_family=self.font_family,
            color=self.color,
            link=self.link,
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

    def to_element(self) -> MathBlock:
        return MathBlock(source=self.source, display=self.display, caption=self.caption)


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
    """Forces subsequent content onto a new page."""

    type: Literal["page_break"] = "page_break"

    def to_element(self) -> PageBreak:
        return PageBreak()


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
        PageBreakSpec,
        HorizontalRuleSpec,
    ],
    Field(discriminator="type"),
]


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

    preset: Literal["letter", "a4", "legal"] | None = Field(
        "letter", description="Page size preset."
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

        if self.width and self.height:
            return PageSpec(width=self.width, height=self.height, **overrides)

        factory = {
            "letter": PageSpec.letter,
            "a4": PageSpec.a4,
            "legal": PageSpec.legal,
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
            page=self.page.to_page_spec(),
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
