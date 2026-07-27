"""Cross-reference auto-numbering for figures, tables, and headings.

Scans document content, assigns sequential numbers by type, and
provides resolved labels that can be referenced in text.

Usage:
    from emboss.crossref import CrossReferenceIndex

    index = CrossReferenceIndex(document)
    index.label("fig:revenue")     # -> "Figure 1"
    index.label("tbl:quarterly")   # -> "Table 2"
    index.number("fig:revenue")    # -> 1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .spec import Document

__all__ = ["CrossReferenceIndex", "RefEntry"]


@dataclass
class RefEntry:
    """One numbered reference entry."""

    kind: str
    number: int
    text: str
    anchor: str
    element_index: int
    display: str | None = None

    @property
    def label(self) -> str:
        return f"{self.kind} {self.display or self.number}"


class CrossReferenceIndex:
    """Builds and resolves cross-references for a document."""

    def __init__(
        self,
        document: "Document",
        section_numbers: dict[int, str] | None = None,
    ) -> None:
        self._entries: dict[str, RefEntry] = {}
        self._counters: dict[str, int] = {}
        self._section_numbers = dict(section_numbers or {})
        self._build(document)

    def _build(self, document: "Document") -> None:
        from .spec import Chart, CodeBlock, Heading, Image, MathBlock, SvgBlock, Table

        for idx, element in enumerate(document.content):
            if isinstance(element, Heading):
                anchor = getattr(element, "anchor", None)
                if anchor:
                    num = self._next("Section")
                    self._entries[anchor] = RefEntry(
                        kind="Section",
                        number=num,
                        text=element.text,
                        anchor=anchor,
                        element_index=idx,
                        display=self._section_numbers.get(idx),
                    )

            elif isinstance(element, Table):
                caption = getattr(element, "caption", None)
                if caption:
                    num = self._next("Table")
                    label = getattr(element, "label", None) or f"tbl:{num}"
                    self._entries[label] = RefEntry(
                        kind="Table",
                        number=num,
                        text=caption,
                        anchor=label,
                        element_index=idx,
                    )

            elif isinstance(element, Image):
                caption = getattr(element, "caption", None)
                alt = getattr(element, "alt_text", "")
                if caption or alt:
                    num = self._next("Figure")
                    label = getattr(element, "label", None) or f"fig:{num}"
                    self._entries[label] = RefEntry(
                        kind="Figure",
                        number=num,
                        text=caption or alt,
                        anchor=label,
                        element_index=idx,
                    )

            elif isinstance(element, Chart):
                title = getattr(element, "title", None)
                if title:
                    num = self._next("Figure")
                    label = getattr(element, "label", None) or f"chart:{num}"
                    self._entries[label] = RefEntry(
                        kind="Figure",
                        number=num,
                        text=title,
                        anchor=label,
                        element_index=idx,
                    )

            elif isinstance(element, MathBlock):
                caption = getattr(element, "caption", None)
                if caption:
                    num = self._next("Equation")
                    label = getattr(element, "label", None) or f"eq:{num}"
                    self._entries[label] = RefEntry(
                        kind="Equation",
                        number=num,
                        text=caption,
                        anchor=label,
                        element_index=idx,
                    )

            elif isinstance(element, CodeBlock):
                caption = getattr(element, "caption", None)
                if caption:
                    num = self._next("Listing")
                    label = getattr(element, "label", None) or f"lst:{num}"
                    self._entries[label] = RefEntry(
                        kind="Listing",
                        number=num,
                        text=caption,
                        anchor=label,
                        element_index=idx,
                    )

            elif isinstance(element, SvgBlock):
                caption = getattr(element, "caption", None)
                if caption:
                    num = self._next("Figure")
                    label = getattr(element, "label", None) or f"svg:{num}"
                    self._entries[label] = RefEntry(
                        kind="Figure",
                        number=num,
                        text=caption,
                        anchor=label,
                        element_index=idx,
                    )

    def _next(self, kind: str) -> int:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return self._counters[kind]

    def label(self, key: str) -> str:
        entry = self._entries.get(key)
        if entry is None:
            return f"[{key}?]"
        return entry.label

    def number(self, key: str) -> int | None:
        entry = self._entries.get(key)
        return entry.number if entry else None

    def get(self, key: str) -> RefEntry | None:
        return self._entries.get(key)

    def all_entries(self) -> list[RefEntry]:
        return list(self._entries.values())

    def figures(self) -> list[RefEntry]:
        return [e for e in self._entries.values() if e.kind == "Figure"]

    def tables(self) -> list[RefEntry]:
        return [e for e in self._entries.values() if e.kind == "Table"]

    def equations(self) -> list[RefEntry]:
        return [e for e in self._entries.values() if e.kind == "Equation"]

    def listings(self) -> list[RefEntry]:
        return [e for e in self._entries.values() if e.kind == "Listing"]

    def sections(self) -> list[RefEntry]:
        return [e for e in self._entries.values() if e.kind == "Section"]

    def resolve_text(self, text: str) -> str:
        """Replace ``@key`` references in text with their resolved labels."""
        import re

        def _replace(match):
            key = match.group(1)
            entry = self._entries.get(key)
            if entry:
                return entry.label
            return match.group(0)

        return re.sub(r"@([\w:.-]+)", _replace, text)
