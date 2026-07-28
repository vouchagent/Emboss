"""Reusable document templates and functions.

Templates are factory functions that return pre-configured Document
objects with consistent styling, page setup, headers/footers, and
content structure. They cover the most common document types so
callers only need to fill in their specific content.

Usage:
    from emboss.templates import memo, report, invoice

    doc = memo(title="Q3 Review", author="Finance Team")
    doc.heading("Summary", level=2)
    doc.paragraph("Revenue increased 12%.")
    doc.save("memo.pdf")
"""

from __future__ import annotations

from .spec import Document, HeaderFooter, LegalFeatures, PageSpec

__all__ = [
    "memo",
    "report",
    "letter",
    "invoice",
    "academic_paper",
    "legal_brief",
    "slide_deck",
    "data_sheet",
]


def memo(*, title: str = "", author: str = "", **kw) -> Document:
    """A corporate memo: Helvetica, left-aligned, compact."""
    return Document(
        title=title,
        author=author,
        style="corporate",
        header=HeaderFooter(left=title, right=author, separator_line=True),
        footer=HeaderFooter(right="Page {page} of {pages}"),
        **kw,
    )


def report(
    *, title: str = "", author: str = "", subject: str = "", toc: bool = True, **kw
) -> Document:
    """A formal report with table of contents and structured headers."""
    return Document(
        title=title,
        author=author,
        subject=subject,
        style="corporate",
        toc=toc,
        header=HeaderFooter(center=title, separator_line=True),
        footer=HeaderFooter(
            left=author,
            right="Page {page} of {pages}",
            separator_line=True,
        ),
        **kw,
    )


def letter(*, title: str = "", author: str = "", **kw) -> Document:
    """A simple letter or correspondence."""
    return Document(
        title=title or "Letter",
        author=author,
        style="corporate",
        page_numbers=False,
        **kw,
    )


def invoice(*, title: str = "Invoice", author: str = "", **kw) -> Document:
    """An invoice with financial formatting and page numbers."""
    return Document(
        title=title,
        author=author,
        style="finance",
        header=HeaderFooter(left=title, right=author),
        footer=HeaderFooter(right="Page {page} of {pages}"),
        **kw,
    )


def academic_paper(
    *, title: str = "", author: str = "", subject: str = "", toc: bool = True, **kw
) -> Document:
    """An academic paper: Times body, Helvetica headings, justified."""
    return Document(
        title=title,
        author=author,
        subject=subject,
        style="academic",
        toc=toc,
        header=HeaderFooter(center=title, font_size=8.0),
        footer=HeaderFooter(center="Page {page} of {pages}", font_size=8.0),
        **kw,
    )


def legal_brief(
    *, title: str = "", author: str = "", line_numbering: bool = True, **kw
) -> Document:
    """A legal brief with line numbering and generous margins."""
    return Document(
        title=title,
        author=author,
        style="legal",
        page=PageSpec(
            margin_top=90.0,
            margin_bottom=90.0,
            margin_left=108.0,
            margin_right=72.0,
        ),
        legal=LegalFeatures(line_numbering=line_numbering),
        header=HeaderFooter(center=title),
        footer=HeaderFooter(center="Page {page} of {pages}"),
        **kw,
    )


def slide_deck(
    *,
    title: str = "",
    author: str = "",
    subtitle: str = "",
    date: str = "",
    theme: str = "boardroom",
    aspect_ratio: str = "16:9",
    slide_numbers: bool = True,
) -> Document:
    """A landscape presentation deck with a designed title slide."""
    from .slides import SlideDeck

    deck = SlideDeck(
        title=title,
        presenter=author,
        date=date,
        theme=theme,
        aspect_ratio=aspect_ratio,
    )
    deck.title_slide(subtitle=subtitle)
    doc = deck.build()
    if not slide_numbers:
        doc.footer = None
    return doc


def data_sheet(*, title: str = "", author: str = "", **kw) -> Document:
    """A compact data sheet: minimal style, tight spacing."""
    return Document(
        title=title,
        author=author,
        style="minimal",
        header=HeaderFooter(left=title, right=author, font_size=7.5),
        footer=HeaderFooter(right="{page}/{pages}", font_size=7.5),
        **kw,
    )
