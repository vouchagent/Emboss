"""Tests for cross-reference wiring: caption numbering, @key links, sections."""

from __future__ import annotations

import binascii
import io
import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.writer import Renderer  # noqa: E402

pikepdf = pytest.importorskip("pikepdf")


def _make_png() -> bytes:
    buf = bytearray(b"\x89PNG\r\n\x1a\n")
    ihdr = struct.pack(">IIBB", 4, 4, 8, 2) + b"\x00\x00\x00"
    buf += struct.pack(">I", len(ihdr))
    buf += b"IHDR" + ihdr
    buf += struct.pack(">I", binascii.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    raw = b""
    for _ in range(4):
        raw += b"\x00" + b"\xff\x00\x00" * 4
    compressed = zlib.compress(bytes(raw), 6)
    buf += struct.pack(">I", len(compressed))
    buf += b"IDAT" + compressed
    buf += struct.pack(">I", binascii.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
    buf += struct.pack(">I", 0) + b"IEND"
    buf += struct.pack(">I", binascii.crc32(b"IEND") & 0xFFFFFFFF)
    return bytes(buf)


_LITERAL = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _page_text(data: bytes, page: int) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        stream = bytes(pdf.pages[page].Contents.read_bytes())
    return b"".join(m.group(1) for m in _LITERAL.finditer(stream))


def _pdf_text(data: bytes) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        streams = [bytes(p.Contents.read_bytes()) for p in pdf.pages]
    return b"".join(m.group(1) for stream in streams for m in _LITERAL.finditer(stream))


def _squashed(data: bytes) -> bytes:
    """Extracted text with spaces removed (words are positioned separately)."""
    return _pdf_text(data).replace(b" ", b"")


def _goto_annots(pdf) -> list:
    found = []
    for page_index, page in enumerate(pdf.pages):
        for annot in page.get("/Annots", []):
            if annot.get("/Subtype") == pikepdf.Name("/Link") and "/Dest" in annot:
                found.append((page_index, annot))
    return found


class TestCaptionNumbering:
    def _doc(self, tmp_path) -> Document:
        png = tmp_path / "fig.png"
        png.write_bytes(_make_png())
        doc = Document(title="Report")
        doc.paragraph("Introductory text.")
        doc.image(str(png), caption="Revenue over time", alt_text="revenue")
        doc.image(str(png), caption="Cost breakdown", alt_text="costs")
        doc.table(["Q", "Value"], [["Q1", "10"]], caption="Quarterly data")
        doc.code_block("x = 1", language="python", caption="Setup code")
        return doc

    def test_captions_get_numbered_prefixes(self, tmp_path):
        text = _pdf_text(self._doc(tmp_path).render())
        assert b"Figure 1: Revenue over time" in text
        assert b"Figure 2: Cost breakdown" in text
        assert b"Table 1: Quarterly data" in text
        assert b"Listing 1: Setup code" in text

    def test_auto_number_opt_out(self, tmp_path):
        doc = self._doc(tmp_path)
        doc.auto_number = False
        text = _pdf_text(doc.render())
        assert b"Figure 1:" not in text
        assert b"Table 1:" not in text
        assert b"Revenue over time" in text
        assert b"Quarterly data" in text

    def test_determinism_double_render(self, tmp_path):
        first = self._doc(tmp_path).render()
        second = self._doc(tmp_path).render()
        assert first == second


class TestAtReferences:
    def _doc(self, tmp_path) -> Document:
        png = tmp_path / "fig.png"
        png.write_bytes(_make_png())
        doc = Document(title="Refs")
        doc.paragraph("See @fig:cost for details.")
        doc.image(str(png), caption="Revenue chart", label="fig:rev")
        doc.image(str(png), caption="Cost detail", label="fig:cost")
        return doc

    def test_reference_text_is_resolved(self, tmp_path):
        text = _squashed(self._doc(tmp_path).render())
        assert b"SeeFigure2fordetails." in text
        assert b"@fig:cost" not in text

    def test_reference_produces_goto_annot(self, tmp_path):
        data = self._doc(tmp_path).render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            annots = _goto_annots(pdf)
            assert len(annots) == 1
            page_index, annot = annots[0]
            assert page_index == 0
            assert "/A" not in annot
            # Both figures are on page 1; the destination must point there.
            assert annot.Dest[0].objgen == pdf.pages[0].obj.objgen

    def test_unknown_reference_left_verbatim(self, tmp_path):
        doc = Document(title="Unknown")
        doc.paragraph("Contact gaurav@nuaav.com about @nowhere:ref today.")
        text = _pdf_text(doc.render())
        assert b"@nowhere:ref" in text

    def test_anchor_across_pages(self, tmp_path):
        png = tmp_path / "fig.png"
        png.write_bytes(_make_png())
        doc = Document(title="Paged")
        doc.paragraph("The results appear in @fig:far below.")
        doc.page_break()
        doc.paragraph("Interlude page.")
        doc.page_break()
        doc.paragraph("Results follow.")
        doc.image(str(png), caption="Far away figure", label="fig:far")
        data = doc.render()
        assert b"Figure1" in _page_text(data, 0).replace(b" ", b"")
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert len(pdf.pages) == 3
            annots = _goto_annots(pdf)
            assert len(annots) == 1
            page_index, annot = annots[0]
            assert page_index == 0
            assert annot.Dest[0].objgen == pdf.pages[2].obj.objgen


class TestSectionNumbering:
    def _doc(self) -> Document:
        doc = Document(title="Sections", toc=True)
        doc.number_sections = True
        doc.heading("Intro", level=1, anchor="sec:intro")
        doc.heading("Background", level=2, anchor="sec:bg")
        doc.heading("Methods", level=1)
        doc.heading("Sampling", level=2)
        doc.paragraph("As shown in @sec:bg, context matters.")
        return doc

    def test_headings_get_hierarchical_prefixes(self):
        text = _squashed(self._doc().render())
        assert b"1Intro" in text
        assert b"1.1Background" in text
        assert b"2Methods" in text
        assert b"2.1Sampling" in text

    def test_default_off_leaves_headings_alone(self):
        doc = Document(title="Plain Sections")
        doc.heading("Intro", level=1)
        doc.paragraph("Body.")
        text = _squashed(doc.render())
        assert b"Intro" in text
        assert b"1Intro" not in text

    def test_section_reference_resolves_hierarchically(self):
        data = self._doc().render()
        text = _squashed(data)
        assert b"Section1.1" in text
        with pikepdf.open(io.BytesIO(data)) as pdf:
            annots = _goto_annots(pdf)
            assert len(annots) == 1
            _, annot = annots[0]
            assert annot.Dest[0].objgen == pdf.pages[0].obj.objgen

    def test_bookmarks_pick_up_prefixed_titles(self):
        data = self._doc().render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            with pdf.open_outline() as outline:
                titles = [item.title for item in outline.root]
        assert "1 Intro" in titles
        assert "2 Methods" in titles


class TestRegression:
    def _plain_doc(self) -> Document:
        doc = Document(title="Plain")
        doc.heading("A heading", level=1)
        doc.paragraph("A paragraph with an email gaurav@nuaav.com in it.")
        doc.table(["A", "B"], [["1", "2"]])
        doc.bullets(["one", "two"])
        return doc

    def test_no_captions_byte_identical_to_skipped_pass(self, monkeypatch):
        doc = self._plain_doc()
        with_pass = doc.render()
        monkeypatch.setattr(
            Renderer, "_resolve_references", lambda self, document, content: content
        )
        without_pass = doc.render()
        assert with_pass == without_pass

    def test_plain_document_double_render(self):
        assert self._plain_doc().render() == self._plain_doc().render()
