"""Tests for appendices (lettered numbering), the index, and the glossary."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.spec import (  # noqa: E402
    Appendix,
    GlossaryEntry,
    Heading,
    Index,
    PageBreak,
    Paragraph,
    TextRun,
)

pikepdf = pytest.importorskip("pikepdf")

_LITERAL = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")
_TOKEN = re.compile(rb"/(F\d+)\s+[\d.]+\s+Tf|\(((?:[^()\\]|\\.)*)\)\s*Tj")


def _squashed(page) -> bytes:
    stream = bytes(page.Contents.read_bytes())
    text = b"".join(m.group(1) for m in _LITERAL.finditer(stream))
    return text.replace(b" ", b"")


def _all_text(pdf) -> bytes:
    return b"".join(_squashed(p) for p in pdf.pages)


def _text_fonts(page) -> list:
    """Return [(font_key_bytes_or_None, text_bytes), ...] in stream order."""
    stream = bytes(page.Contents.read_bytes())
    current = None
    out = []
    for m in _TOKEN.finditer(stream):
        if m.group(1):
            current = m.group(1)
        else:
            out.append((current, m.group(2)))
    return out


def _goto_annots(pdf) -> list:
    found = []
    for page_index, page in enumerate(pdf.pages):
        for annot in page.get("/Annots") or []:
            if annot.get("/Subtype") == pikepdf.Name("/Link") and "/Dest" in annot:
                found.append((page_index, annot))
    return found


def _outline_titles(pdf) -> list:
    """Flatten the PDF outline (bookmark) tree into a list of titles."""
    titles: list = []

    def walk(items):
        for item in items:
            titles.append(str(item.title))
            walk(item.children)

    with pdf.open_outline() as outline:
        walk(outline.root)
    return titles


# ---------------------------------------------------------------------------
# Appendices
# ---------------------------------------------------------------------------


class TestAppendix:
    def _doc(self) -> Document:
        doc = Document(title="Report", toc=True)
        doc.heading("Report", level=1)
        doc.appendix(
            "First Appendix",
            Heading("Sub A", level=2),
            Heading("Sub B", level=2),
        )
        doc.appendix("Second Appendix", Heading("Sub C", level=2))
        return doc

    def test_flat_numbering_restarts_per_appendix(self):
        data = self._doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            text = _all_text(pdf)
        assert b"A.1SubA" in text
        assert b"A.2SubB" in text
        assert b"B.1SubC" in text
        # Never "B.2": the second appendix's counter restarted at 1.
        assert b"B.2" not in text

    def test_bookmark_titles_carry_the_letter_prefix(self):
        data = self._doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            titles = _outline_titles(pdf)
        assert "Appendix A: First Appendix" in titles
        assert "Appendix B: Second Appendix" in titles
        assert "A.1 Sub A" in titles
        assert "A.2 Sub B" in titles
        assert "B.1 Sub C" in titles

    def test_appendix_does_not_double_number_with_number_sections(self):
        doc = Document(title="Report")
        doc.number_sections = True
        doc.heading("Intro", level=1)
        doc.heading("Method", level=1)
        doc.appendix("Data Tables", Heading("Raw Counts", level=2))
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            text = _all_text(pdf)
        assert b"1Intro" in text
        assert b"2Method" in text
        # The appendix heading is lettered only, never "3 Appendix A: ...".
        assert b"AppendixA:DataTables" in text
        assert b"3AppendixA" not in text

    def test_constructing_appendix_directly_also_expands(self):
        doc = Document(title="Report")
        doc.heading("Report", level=1)
        doc.add(Appendix(title="Notes", content=[Heading("Detail", level=2)]))
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            text = _all_text(pdf)
        assert b"AppendixA:Notes" in text
        assert b"A.1Detail" in text


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


def _index_doc() -> Document:
    doc = Document(title="Idx", page_numbers=False)
    doc.heading("Idx", level=1)
    doc.paragraph(
        [TextRun("See "), TextRun("Alpha", index_terms=("Alpha",)), TextRun(" here.")]
    )
    doc.paragraph(
        [TextRun("See "), TextRun("Delta", index_terms=("Delta",)), TextRun(" too.")]
    )
    doc.add(PageBreak())
    doc.paragraph(
        [TextRun("See "), TextRun("Beta", index_terms=("Beta",)), TextRun(" here.")]
    )
    doc.paragraph(
        [TextRun("See "), TextRun("Beta", index_terms=("Beta",)), TextRun(" again.")]
    )
    doc.add(PageBreak())
    doc.add(PageBreak())
    doc.add(PageBreak())
    doc.paragraph(
        [TextRun("See "), TextRun("Gamma", index_terms=("Gamma",)), TextRun(" here.")]
    )
    doc.paragraph(
        [TextRun("See "), TextRun("Delta", index_terms=("Delta",)), TextRun(" again.")]
    )
    doc.add(Index())
    return doc


class TestIndex:
    def test_terms_resolve_to_actual_placement_pages(self):
        data = _index_doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert len(pdf.pages) == 5
            # Confirm the fixture's actual placement before checking the index.
            assert b"Alpha" in _squashed(pdf.pages[0])
            assert b"Beta" in _squashed(pdf.pages[1])
            assert b"Gamma" in _squashed(pdf.pages[4])
            index_text = _squashed(pdf.pages[-1])
        assert b"Alpha,1" in index_text
        assert b"Beta,2" in index_text
        assert b"Gamma,5" in index_text

    def test_repeated_term_lists_every_distinct_page(self):
        data = _index_doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            index_text = _squashed(pdf.pages[-1])
        # Delta appears on page 1 and page 5: both pages listed, comma-joined.
        assert b"Delta,1,5" in index_text

    def test_same_page_repeat_is_not_duplicated(self):
        data = _index_doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            index_text = _squashed(pdf.pages[-1])
        # Beta occurs twice on page 2 but is listed once, not "Beta, 2, 2".
        assert b"Beta,2," not in index_text
        assert b"Beta,22" not in index_text

    def test_entries_are_alphabetized(self):
        data = _index_doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            page_text = _squashed(pdf.pages[-1])
        # Isolate the index section itself (its title text is unique on the
        # page); the body paragraphs above it are in authoring order, not
        # alphabetical, so they must be excluded from this check.
        index_text = page_text[page_text.rfind(b"Index") :]
        assert (
            index_text.find(b"Alpha")
            < index_text.find(b"Beta")
            < index_text.find(b"Delta")
            < index_text.find(b"Gamma")
        )

    def test_document_without_index_is_unaffected(self):
        doc = Document(title="Plain")
        doc.heading("Plain", level=1)
        doc.paragraph(
            [
                TextRun("No "),
                TextRun("marks", index_terms=("marks",)),
                TextRun(" here."),
            ]
        )
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            text = _all_text(pdf)
        assert b"Index" not in text
        assert b"marks" in text


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------


class TestGlossary:
    def _doc(self, body_text: str | None = None) -> Document:
        doc = Document(title="Gloss", page_numbers=False)
        doc.heading("Gloss", level=1)
        doc.glossary(
            [
                GlossaryEntry("Zebra", "A striped equine."),
                GlossaryEntry("Apple", "A pomaceous fruit."),
            ]
        )
        if body_text:
            doc.paragraph(body_text)
        return doc

    def test_entries_are_alphabetized_by_term(self):
        data = self._doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            text = _all_text(pdf)
        assert text.find(b"Apple") < text.find(b"Zebra")

    def test_term_renders_bold_definition_does_not(self):
        data = self._doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            fragments = _text_fonts(pdf.pages[0])
        # The term's font differs from the definition's font (bold vs regular).
        term_font = next(font for font, text in fragments if text == b"Apple")
        def_font = next(font for font, text in fragments if text == b"A")
        assert term_font != def_font

    def test_first_body_occurrence_is_linked_second_is_not(self):
        doc = self._doc(
            "This uses Apple in body text and later Apple appears again in text."
        )
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            gotos = _goto_annots(pdf)
        assert len(gotos) == 1

    def test_second_paragraph_occurrence_is_not_linked(self):
        doc = self._doc()
        doc.paragraph("Apple shows up here first.")
        doc.paragraph("Apple shows up again in a later paragraph.")
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            gotos = _goto_annots(pdf)
        assert len(gotos) == 1

    def test_document_without_glossary_is_unaffected(self):
        doc = Document(title="Plain")
        doc.heading("Plain", level=1)
        doc.paragraph("Apple appears with no glossary defined.")
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            gotos = _goto_annots(pdf)
        assert gotos == []


# ---------------------------------------------------------------------------
# Determinism and regression
# ---------------------------------------------------------------------------


def _combined_doc() -> Document:
    doc = Document(title="Combined", toc=True, page_numbers=False)
    doc.heading("Combined", level=1)
    doc.paragraph(
        [TextRun("Uses "), TextRun("Widget", index_terms=("Widget",)), TextRun(".")]
    )
    doc.add(PageBreak())
    doc.paragraph(
        [TextRun("Also "), TextRun("Gizmo", index_terms=("Gizmo",)), TextRun(".")]
    )
    doc.appendix("Extra Data", Heading("Table Notes", level=2))
    doc.add(Index())
    doc.glossary(
        [
            GlossaryEntry("Widget", "A small mechanical device."),
            GlossaryEntry("Gizmo", "A gadget of uncertain purpose."),
        ]
    )
    doc.paragraph("Both Widget and Gizmo are defined above.")
    return doc


def test_determinism_double_render():
    doc = _combined_doc()
    assert doc.render() == doc.render()


def test_combined_document_renders_all_three_features():
    data = _combined_doc().render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        text = _all_text(pdf)
        titles = _outline_titles(pdf)
    assert b"AppendixA:ExtraData" in text
    assert b"Widget,1" in text
    assert b"Gizmo,2" in text
    assert b"Glossary" in text
    assert "Appendix A: Extra Data" in titles


def test_plain_document_regression_unaffected():
    """A document using none of these features renders exactly as before."""
    doc = Document(title="Plain Report", style="finance")
    doc.heading("Plain Report", level=1)
    doc.paragraph("Ordinary body text with nothing special going on.")
    doc.bullets(["First point", "Second point"])
    data = doc.render()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert len(pdf.pages) == 1
        text = _all_text(pdf)
    assert b"Ordinarybodytext" in text
    assert b"Firstpoint" in text
    assert doc.render() == data


def test_plain_paragraph_default_has_no_index_terms():
    para = Paragraph("hello")
    assert para.runs[0].index_terms == ()
