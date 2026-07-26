"""Table of Contents generation and PDF outline (bookmark) construction.

Scans rendered pages for Heading elements, builds a TOC data structure,
and creates the PDF /Outlines dictionary tree for bookmark navigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfString
from .spec import Heading

__all__ = ["TOCEntry", "build_toc_entries", "build_outline_dict"]


@dataclass
class TOCEntry:
    """One table-of-contents entry."""

    text: str
    level: int
    page_index: int
    y_position: float
    children: list["TOCEntry"] = field(default_factory=list)


def build_toc_entries(pages) -> list[TOCEntry]:
    """Scan rendered pages for headings and build a hierarchical TOC.

    `pages` is a list of Page objects whose `.blocks` contain PlacedBlock
    instances. Each PlacedBlock has `.block.element` which may be a Heading.
    """
    flat: list[TOCEntry] = []

    for page_index, page in enumerate(pages):
        for placed in page.blocks:
            element = placed.block.element
            if isinstance(element, Heading):
                flat.append(TOCEntry(
                    text=element.text,
                    level=element.level,
                    page_index=page_index,
                    y_position=placed.y,
                ))

    return _nest(flat)


def _nest(flat: list[TOCEntry]) -> list[TOCEntry]:
    """Convert a flat heading list into a nested hierarchy.

    H1 is top-level; H2 nests under the most recent H1, H3 under the
    most recent H2, and so on.
    """
    if not flat:
        return []

    root: list[TOCEntry] = []
    stack: list[TOCEntry] = []

    for entry in flat:
        while stack and stack[-1].level >= entry.level:
            stack.pop()
        if stack:
            stack[-1].children.append(entry)
        else:
            root.append(entry)
        stack.append(entry)

    return root


def build_outline_dict(
    assembler,
    entries: list[TOCEntry],
    page_refs: list[PdfRef],
) -> PdfRef | None:
    """Create a PDF /Outlines object tree for bookmark navigation.

    Returns a reference to the root Outlines dict, or None if there are
    no entries.
    """
    if not entries:
        return None

    root_id = assembler.allocate()

    items = _build_items(assembler, entries, page_refs, PdfRef(root_id))

    root = PdfDict()
    root["Type"] = PdfName("Outlines")
    if items:
        root["First"] = items[0]
        root["Last"] = items[-1]
    root["Count"] = _count_all(entries)

    assembler.add(root, obj_id=root_id)
    return PdfRef(root_id)


def _build_items(
    assembler,
    entries: list[TOCEntry],
    page_refs: list[PdfRef],
    parent_ref: PdfRef,
) -> list[PdfRef]:
    """Recursively build outline item dicts and return their refs."""
    refs: list[PdfRef] = []
    items_data: list[tuple[PdfRef, int, TOCEntry]] = []

    for entry in entries:
        item_id = assembler.allocate()
        ref = PdfRef(item_id)
        refs.append(ref)
        items_data.append((ref, item_id, entry))

    for idx, (ref, item_id, entry) in enumerate(items_data):
        item = PdfDict()
        item["Title"] = PdfString(entry.text)
        item["Parent"] = parent_ref

        page_ref = page_refs[min(entry.page_index, len(page_refs) - 1)]
        item["Dest"] = PdfArray([
            page_ref, PdfName("XYZ"), 0, round(entry.y_position, 2), 0,
        ])

        if idx > 0:
            item["Prev"] = refs[idx - 1]
        if idx < len(refs) - 1:
            item["Next"] = refs[idx + 1]

        if entry.children:
            child_refs = _build_items(
                assembler, entry.children, page_refs, ref
            )
            item["First"] = child_refs[0]
            item["Last"] = child_refs[-1]
            item["Count"] = _count_all(entry.children)

        assembler.add(item, obj_id=item_id)

    return refs


def _count_all(entries: list[TOCEntry]) -> int:
    """Total number of entries including all descendants."""
    count = 0
    for entry in entries:
        count += 1
        count += _count_all(entry.children)
    return count
