"""Bibliography and citation management.

Formats academic references in IEEE, APA, and numbered styles.
Zero external dependencies — all formatting is done with string operations.

Usage::

    from emboss.bibliography import Citation, format_citation

    ref = Citation(
        key="einstein1905",
        authors=["Albert Einstein"],
        title="On the Electrodynamics of Moving Bodies",
        year=1905,
        journal="Annalen der Physik",
        volume="17",
        pages="891-921",
    )
    print(format_citation(ref, "ieee"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

__all__ = [
    "Citation",
    "BibliographyBlock",
    "format_citation",
    "format_bibliography",
]

BibStyle = Literal["ieee", "apa", "numbered"]


@dataclass
class Citation:
    """A single bibliographic reference."""

    key: str
    authors: list = field(default_factory=list)
    title: str = ""
    year: int | str = ""
    journal: str | None = None
    volume: str | None = None
    pages: str | None = None
    publisher: str | None = None
    doi: str | None = None
    url: str | None = None
    edition: str | None = None
    book_title: str | None = None
    entry_type: Literal["article", "book", "inproceedings", "misc"] = "article"


@dataclass
class BibliographyBlock:
    """A formatted bibliography section."""

    citations: Sequence = field(default_factory=list)
    bib_style: str = "ieee"
    title: str | None = "References"
    heading_level: int = 2
    style: object | None = None

    @property
    def structure_tag(self) -> str:
        return "Div"


def _format_authors_ieee(authors: list) -> str:
    if not authors:
        return ""
    parts = []
    for author in authors:
        names = author.strip().split()
        if len(names) >= 2:
            initials = " ".join(n[0] + "." for n in names[:-1])
            parts.append(f"{initials} {names[-1]}")
        else:
            parts.append(author)
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def _format_authors_apa(authors: list) -> str:
    if not authors:
        return ""
    parts = []
    for author in authors:
        names = author.strip().split()
        if len(names) >= 2:
            last = names[-1]
            initials = " ".join(n[0] + "." for n in names[:-1])
            parts.append(f"{last}, {initials}")
        else:
            parts.append(author)
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}, & {parts[1]}"
    return ", ".join(parts[:-1]) + ", & " + parts[-1]


def format_citation(citation: Citation, style: str = "ieee",
                    number: int = 1) -> str:
    if style in ("ieee", "numbered"):
        return _format_ieee(citation, number)
    if style == "apa":
        return _format_apa(citation)
    return _format_ieee(citation, number)


def _format_ieee(citation: Citation, number: int) -> str:
    parts = [f"[{number}]"]
    authors = _format_authors_ieee(citation.authors)
    if authors:
        parts.append(f"{authors},")

    if citation.entry_type == "book":
        parts.append(f"{citation.title}.")
        if citation.edition:
            parts.append(f"{citation.edition} ed.")
        if citation.publisher:
            parts.append(f"{citation.publisher},")
        if citation.year:
            parts.append(f"{citation.year}.")
    elif citation.entry_type == "inproceedings":
        parts.append(f'"{citation.title},"')
        if citation.book_title:
            parts.append(f"in {citation.book_title},")
        if citation.year:
            parts.append(f"{citation.year},")
        if citation.pages:
            parts.append(f"pp. {citation.pages}.")
        else:
            if parts[-1].endswith(","):
                parts[-1] = parts[-1][:-1] + "."
    else:
        parts.append(f'"{citation.title},"')
        if citation.journal:
            parts.append(f"{citation.journal},")
        if citation.volume:
            parts.append(f"vol. {citation.volume},")
        if citation.pages:
            parts.append(f"pp. {citation.pages},")
        if citation.year:
            parts.append(f"{citation.year}.")
        else:
            if parts[-1].endswith(","):
                parts[-1] = parts[-1][:-1] + "."

    if citation.doi:
        parts.append(f"doi: {citation.doi}.")

    return " ".join(parts)


def _format_apa(citation: Citation) -> str:
    parts = []
    authors = _format_authors_apa(citation.authors)
    if authors:
        parts.append(f"{authors}")

    year = f"({citation.year})" if citation.year else "(n.d.)"
    parts.append(f"{year}.")

    if citation.entry_type == "book":
        parts.append(f"{citation.title}.")
        if citation.edition:
            parts.append(f"({citation.edition} ed.).")
        if citation.publisher:
            parts.append(f"{citation.publisher}.")
    elif citation.entry_type == "inproceedings":
        parts.append(f"{citation.title}.")
        if citation.book_title:
            parts.append(f"In {citation.book_title}")
        if citation.pages:
            parts.append(f"(pp. {citation.pages}).")
        else:
            if parts[-1] and not parts[-1].endswith("."):
                parts[-1] += "."
    else:
        parts.append(f"{citation.title}.")
        if citation.journal:
            journal_part = citation.journal
            if citation.volume:
                journal_part += f", {citation.volume}"
            if citation.pages:
                journal_part += f", {citation.pages}"
            parts.append(f"{journal_part}.")

    if citation.doi:
        parts.append(f"https://doi.org/{citation.doi}")

    return " ".join(parts)


def format_bibliography(citations: Sequence, style: str = "ieee") -> list[str]:
    result = []
    for i, citation in enumerate(citations, start=1):
        if isinstance(citation, dict):
            citation = Citation(**citation)
        result.append(format_citation(citation, style, number=i))
    return result
