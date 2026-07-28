"""Tests for the visible table of contents, LoF/LoT, and dot leaders."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.spec import (  # noqa: E402
    Chart,
    ListOfFigures,
    ListOfTables,
    PageBreak,
    Table,
    TableOfContents,
)

pikepdf = pytest.importorskip("pikepdf")

_LITERAL = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _squashed(page) -> bytes:
    stream = bytes(page.Contents.read_bytes())
    text = b"".join(m.group(1) for m in _LITERAL.finditer(stream))
    return text.replace(b" ", b"")


def _toc_number(toc_text: bytes, title: str) -> str | None:
    m = re.search(re.escape(title.encode()) + rb"\.+(\d+)", toc_text)
    return m.group(1).decode() if m else None


def _dest_page_indices(pdf) -> list:
    out = []
    annots = pdf.pages[0].get("/Annots") or []
    for annot in annots:
        dest = annot.get("/Dest")
        if dest is None:
            continue
        page_obj = dest[0]
        for i, page in enumerate(pdf.pages):
            if page.objgen == page_obj.objgen:
                out.append(i)
                break
    return out


def _build_headings_doc() -> Document:
    doc = Document(title="Contents Manual", style="finance", page_numbers=False)
    doc.heading("Contents Manual", level=1)  # suppress the auto title block
    doc.add(TableOfContents(title="Contents", depth=2))
    for name in ("Alpha", "Bravo", "Charlie"):
        doc.add(PageBreak())
        doc.heading(name, level=1)
        doc.paragraph("Section body text for this chapter.")
    return doc


def test_toc_numbers_match_actual_heading_pages():
    doc = _build_headings_doc()
    data = doc.render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        toc = _squashed(pdf.pages[0])
        for name in ("Alpha", "Bravo", "Charlie"):
            shown = _toc_number(toc, name)
            assert shown is not None, f"{name} missing from TOC"
            actual = [
                i
                for i, page in enumerate(pdf.pages)
                if i > 0 and name.encode() in _squashed(page)
            ]
            assert actual, f"{name} not found on any content page"
            # Arabic numbering with no front matter: label == page index + 1.
            assert shown == str(actual[0] + 1)


def test_toc_has_dot_leaders():
    doc = _build_headings_doc()
    data = doc.render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert b"...." in _squashed(pdf.pages[0])


def test_toc_entries_have_clickable_dests():
    doc = _build_headings_doc()
    data = doc.render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        dest_pages = _dest_page_indices(pdf)
        assert len(dest_pages) >= 3
        # Every heading page is reachable from a TOC link.
        for name in ("Alpha", "Bravo", "Charlie"):
            page = [
                i
                for i, p in enumerate(pdf.pages)
                if i > 0 and name.encode() in _squashed(p)
            ][0]
            assert page in dest_pages


def test_toc_convergence_is_deterministic():
    doc = _build_headings_doc()
    assert doc.render() == doc.render()


def test_toc_converges_when_it_shifts_pagination():
    # A long heading list makes the TOC itself span content the numbers
    # must still reconcile against.
    doc = Document(title="Big", style="minimal", page_numbers=False)
    doc.heading("Big", level=1)
    doc.add(TableOfContents(title="Contents", depth=1))
    for i in range(40):
        doc.add(PageBreak())
        doc.heading(f"Chapter {i:02d}", level=1)
        doc.paragraph("body")
    data = doc.render()
    assert data == doc.render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        toc = b"".join(_squashed(p) for p in pdf.pages)
        # Every displayed number matches the real page of its chapter.
        for i in range(40):
            title = f"Chapter{i:02d}"
            shown = _toc_number(toc, title)
            if shown is None:
                continue
            actual = [
                idx
                for idx, page in enumerate(pdf.pages)
                if title.encode() in _squashed(page) and idx > 0
            ]
            if actual:
                assert shown == str(actual[0] + 1)


def test_list_of_figures_and_tables():
    doc = Document(title="Report", style="finance")
    doc.heading("Report", level=1)
    doc.add(ListOfFigures())
    doc.add(ListOfTables())
    doc.add(Chart(chart_type="bar", labels=["a"], values=[1], title="Growth"))
    doc.add(Table(headers=["H"], rows=[["v"]], caption="Quarterly figures"))
    data = doc.render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        joined = b"".join(_squashed(p) for p in pdf.pages)
    # Figure title and table caption appear in the listings.
    assert b"Growth" in joined
    assert b"Quarterlyfigures" in joined


def test_toc_double_render_determinism():
    doc = Document(title="Report", style="finance")
    doc.heading("Report", level=1)
    doc.add(ListOfFigures())
    doc.add(Chart(chart_type="bar", labels=["a"], values=[1], title="Growth"))
    assert doc.render() == doc.render()
