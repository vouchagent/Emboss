"""Slide and presentation layout support.

Provides preset page specs and style sheets for creating
presentation-style PDFs with landscape orientation, large fonts,
and slide-specific layouts.

Usage::

    from emboss.slides import slide_document

    doc = slide_document("Quarterly Results", subtitle="Q3 2026")
    doc.heading("Revenue Growth", level=2)
    doc.paragraph("Revenue grew 18% year over year.")
    doc.page_break()
    doc.heading("Key Metrics", level=2)
    doc.bullets(["ARR: $12.4M", "NRR: 118%", "Churn: 2.1%"])
    doc.save("presentation.pdf")
"""

from __future__ import annotations

from dataclasses import dataclass

from .spec import Document, PageSpec
from .styles import Style, StyleSheet

__all__ = [
    "slide_document",
    "SlideConfig",
    "SLIDE_16_9",
    "SLIDE_4_3",
]

SLIDE_16_9 = PageSpec(
    width=720.0,
    height=405.0,
    margin_top=36.0,
    margin_right=48.0,
    margin_bottom=36.0,
    margin_left=48.0,
)

SLIDE_4_3 = PageSpec(
    width=720.0,
    height=540.0,
    margin_top=40.0,
    margin_right=48.0,
    margin_bottom=40.0,
    margin_left=48.0,
)


@dataclass
class SlideConfig:
    """Configuration for slide-based documents."""

    aspect_ratio: str = "16:9"
    theme: str = "default"
    slide_numbers: bool = True

    @property
    def page_spec(self) -> PageSpec:
        if self.aspect_ratio == "4:3":
            return SLIDE_4_3
        return SLIDE_16_9


def slide_document(
    title: str,
    subtitle: str = "",
    author: str = "",
    aspect_ratio: str = "16:9",
    theme: str = "default",
    slide_numbers: bool = True,
) -> Document:
    """Create a Document pre-configured for slide presentation.

    Returns a Document with a title slide already added. Subsequent
    content separated by ``page_break()`` becomes additional slides.
    """
    config = SlideConfig(
        aspect_ratio=aspect_ratio,
        theme=theme,
        slide_numbers=slide_numbers,
    )
    sheet = _build_slide_sheet(theme)

    doc = Document(
        title=title,
        author=author,
        page=config.page_spec,
        style=sheet,
        page_numbers=config.slide_numbers,
    )

    doc.heading(title, level=1)
    if subtitle:
        doc.paragraph(
            subtitle,
            style=Style(
                font_size=20.0,
                italic=True,
                color="64748b",
                align="center",
            ),
        )
    if author:
        doc.paragraph(
            author,
            style=Style(
                font_size=16.0,
                color="94a3b8",
                align="center",
            ),
        )
    doc.page_break()

    return doc


_THEMES: dict[str, dict] = {
    "default": {
        "body_color": "1e293b",
        "heading_color": "0f172a",
        "accent_color": "1e40af",
        "muted_color": "64748b",
        "table_header_rule": "0f172a",
        "table_rule": "cbd5e1",
        "table_stripe": "f8fafc",
    },
    "dark": {
        "body_color": "e2e8f0",
        "heading_color": "f1f5f9",
        "accent_color": "60a5fa",
        "muted_color": "94a3b8",
        "table_header_rule": "e2e8f0",
        "table_rule": "475569",
        "table_stripe": "1e293b",
    },
    "minimal": {
        "body_color": "334155",
        "heading_color": "1e293b",
        "accent_color": "475569",
        "muted_color": "94a3b8",
        "table_header_rule": "334155",
        "table_rule": "e2e8f0",
        "table_stripe": "f8fafc",
    },
}


def _build_slide_sheet(theme: str) -> StyleSheet:
    """Build a stylesheet tuned for slide presentations."""
    colors = _THEMES.get(theme, _THEMES["default"])

    body_size = 18.0
    scale = (2.0, 1.55, 1.22, 1.0, 1.0, 1.0)
    h_space_before = (14.0, 12.0, 10.0, 8.0, 8.0, 8.0)
    h_space_after = (12.0, 10.0, 8.0, 6.0, 6.0, 6.0)

    headings = {}
    for i, factor in enumerate(scale, start=1):
        headings[f"h{i}"] = Style(
            font_family="Helvetica",
            font_size=round(body_size * factor, 2),
            bold=True,
            color=colors["heading_color"],
            align="center" if i == 1 else "left",
            line_height=1.2,
            space_before=h_space_before[i - 1],
            space_after=h_space_after[i - 1],
            keep_with_next=True,
            hyphenate=False,
        )

    return StyleSheet(
        name=f"slide-{theme}",
        body=Style(
            font_family="Helvetica",
            font_size=body_size,
            color=colors["body_color"],
            align="left",
            line_height=1.5,
            space_after=10.0,
            hyphenate=False,
        ),
        list_item=Style(
            align="left",
            font_size=body_size,
            space_after=8.0,
            indent_left=24.0,
            line_height=1.5,
            hyphenate=False,
        ),
        table_header=Style(
            font_family="Helvetica",
            font_size=round(body_size * 0.85, 2),
            bold=True,
            align="left",
            line_height=1.25,
            color=colors["heading_color"],
            hyphenate=False,
        ),
        table_cell=Style(
            font_family="Helvetica",
            font_size=round(body_size * 0.85, 2),
            align="left",
            line_height=1.3,
            hyphenate=False,
        ),
        caption=Style(
            font_family="Helvetica",
            font_size=round(body_size * 0.75, 2),
            italic=True,
            color=colors["muted_color"],
            align="left",
            space_before=4.0,
            space_after=8.0,
            hyphenate=False,
        ),
        header_footer=Style(
            font_family="Helvetica",
            font_size=9.0,
            color=colors["muted_color"],
            align="left",
            line_height=1.2,
            hyphenate=False,
        ),
        **headings,
        table_rule_color=colors["table_rule"],
        table_header_rule_color=colors["table_header_rule"],
        table_stripe_color=colors["table_stripe"],
    )
