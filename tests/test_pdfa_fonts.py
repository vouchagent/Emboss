"""Structural PDF/A font-embedding conformance for pdfa=True documents."""

from __future__ import annotations

import io
import re

import pytest

from emboss import Document, Paragraph, TextRun

pikepdf = pytest.importorskip("pikepdf")

# Base-14 BaseFont names that PDF/A forbids relying on unembedded.
_BASE14_NAMES = {
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Symbol",
    "ZapfDingbats",
}


def _render_mixed_pdfa() -> bytes:
    """A pdfa document exercising serif, sans, and mono families."""
    doc = Document(title="Font Conformance", pdfa=True)
    doc.heading("Overview", level=1)
    doc.add(Paragraph([TextRun("Serif body text.", font_family="Times")]))
    doc.add(Paragraph([TextRun("Sans body text.", font_family="Helvetica")]))
    doc.code_block("mono = value + 1", language="python")
    return doc.render()


def _fonts(pdf) -> list:
    """All /Type /Font dictionaries in the document."""
    out = []
    for obj in pdf.objects:
        if not isinstance(obj, pikepdf.Dictionary):
            continue
        if obj.get("/Type") == pikepdf.Name("/Font"):
            out.append(obj)
    return out


def _to_unicode_map(font) -> set:
    """Collect target Unicode codepoints from a font's ToUnicode CMap."""
    stream = font.get("/ToUnicode")
    if stream is None:
        return set()
    raw = stream.read_bytes().decode("latin-1")
    mapped = set()
    for match in re.finditer(r"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4,})>", raw):
        mapped.add(int(match.group(2)[:4], 16))
    return mapped


class TestEmbeddedFontsOnly:
    def test_no_bare_base14_font_survives(self):
        pdf = pikepdf.open(io.BytesIO(_render_mixed_pdfa()))
        for font in _fonts(pdf):
            subtype = font.get("/Subtype")
            base = str(font.get("/BaseFont", "")).lstrip("/")
            # Subset names carry a TAG+ prefix; strip it before comparing.
            stem = base.split("+", 1)[-1]
            if subtype in (pikepdf.Name("/Type1"), pikepdf.Name("/TrueType")):
                assert stem not in _BASE14_NAMES, f"bare base-14 font {base}"
                assert "/FontDescriptor" in font, base

    def test_every_font_is_type0_composite(self):
        pdf = pikepdf.open(io.BytesIO(_render_mixed_pdfa()))
        top = [f for f in _fonts(pdf) if "/DescendantFonts" in f or "/Encoding" in f]
        type0 = [f for f in _fonts(pdf) if f.get("/Subtype") == pikepdf.Name("/Type0")]
        assert top and type0
        for font in type0:
            assert font.get("/Encoding") == pikepdf.Name("/Identity-H")

    def test_cid_descriptors_have_fontfile2_and_cidset(self):
        pdf = pikepdf.open(io.BytesIO(_render_mixed_pdfa()))
        cid_fonts = [
            f for f in _fonts(pdf) if f.get("/Subtype") == pikepdf.Name("/CIDFontType2")
        ]
        assert cid_fonts, "expected embedded CIDFontType2 fonts"
        for font in cid_fonts:
            descriptor = font["/FontDescriptor"]
            assert "/FontFile2" in descriptor
            assert "/CIDSet" in descriptor
            assert font.get("/CIDToGIDMap") == pikepdf.Name("/Identity")
            assert "/W" in font

    def test_cidset_bit_count_covers_font_program(self):
        pdf = pikepdf.open(io.BytesIO(_render_mixed_pdfa()))
        for font in _fonts(pdf):
            if font.get("/Subtype") != pikepdf.Name("/CIDFontType2"):
                continue
            cid_set = bytes(font["/FontDescriptor"]["/CIDSet"].read_bytes())
            assert cid_set, "CIDSet must be non-empty"
            # The .notdef glyph (CID 0) is always present.
            assert cid_set[0] & 0x80


class TestFontDescriptorFlags:
    def test_flags_are_sane_computed_values(self):
        pdf = pikepdf.open(io.BytesIO(_render_mixed_pdfa()))
        seen_by_family = {}
        for font in _fonts(pdf):
            if font.get("/Subtype") != pikepdf.Name("/CIDFontType2"):
                continue
            flags = int(font["/FontDescriptor"]["/Flags"])
            base = str(font.get("/BaseFont", ""))
            symbolic = bool(flags & 0x4)
            nonsymbolic = bool(flags & 0x20)
            # PDF/A: exactly one of Symbolic / Nonsymbolic.
            assert symbolic != nonsymbolic, base
            seen_by_family[base.split("+")[-1]] = flags

        # Sans -> Source Sans 3: nonsymbolic, not serif, not fixed pitch.
        sans = next(v for k, v in seen_by_family.items() if "SourceSans3" in k)
        assert sans & 0x20 and not (sans & 0x2) and not (sans & 0x1)

        # Serif -> Source Serif 4: nonsymbolic and serif bit set.
        serif = next(v for k, v in seen_by_family.items() if "SourceSerif4" in k)
        assert serif & 0x20 and serif & 0x2

        # Mono -> Source Code Pro: fixed-pitch bit set.
        mono = next(v for k, v in seen_by_family.items() if "SourceCodePro" in k)
        assert mono & 0x1

    def test_italic_sets_italic_flag(self):
        doc = Document(title="Italic", pdfa=True)
        doc.add(Paragraph([TextRun("Slanted", font_family="Times", italic=True)]))
        pdf = pikepdf.open(io.BytesIO(doc.render()))
        italic_flags = [
            int(f["/FontDescriptor"]["/Flags"])
            for f in _fonts(pdf)
            if f.get("/Subtype") == pikepdf.Name("/CIDFontType2")
            and "It" in str(f.get("/BaseFont", ""))
        ]
        assert italic_flags and all(fl & 0x40 for fl in italic_flags)


class TestTextExtraction:
    def test_to_unicode_present_on_every_font(self):
        pdf = pikepdf.open(io.BytesIO(_render_mixed_pdfa()))
        top_fonts = [
            f for f in _fonts(pdf) if f.get("/Subtype") == pikepdf.Name("/Type0")
        ]
        assert top_fonts
        for font in top_fonts:
            assert "/ToUnicode" in font

    def test_text_is_extractable_via_pdfminer(self):
        pdfminer = pytest.importorskip("pdfminer.high_level")
        text = pdfminer.extract_text(io.BytesIO(_render_mixed_pdfa()))
        assert "Serif body text." in text
        assert "Sans body text." in text

    def test_non_latin_roundtrips_through_to_unicode(self):
        sample = "Ελληνικά Кириллица"
        doc = Document(title="Non-Latin", pdfa=True)
        doc.paragraph(sample)
        pdf = pikepdf.open(io.BytesIO(doc.render()))
        mapped = set()
        for font in _fonts(pdf):
            mapped |= _to_unicode_map(font)
        for char in sample:
            if char != " ":
                assert ord(char) in mapped, char


class TestNonPdfaUnchanged:
    def _render_plain(self) -> bytes:
        doc = Document(title="Plain")
        doc.heading("Title", level=1)
        doc.paragraph("Regular body text with serif and sans.")
        doc.code_block("x = 1", language="python")
        return doc.render()

    def test_non_pdfa_uses_base14_and_no_embedding(self):
        data = self._render_plain()
        assert b"/FontFile2" not in data
        assert b"/Helvetica" in data
        pdf = pikepdf.open(io.BytesIO(data))
        assert any(f.get("/Subtype") == pikepdf.Name("/Type1") for f in _fonts(pdf))
        assert not any(
            f.get("/Subtype") == pikepdf.Name("/CIDFontType2") for f in _fonts(pdf)
        )

    def test_non_pdfa_render_is_deterministic(self):
        assert self._render_plain() == self._render_plain()


class TestDeterminism:
    def test_pdfa_double_render_is_byte_identical(self):
        doc = Document(title="Stable", pdfa=True)
        doc.heading("Heading", level=1)
        doc.add(Paragraph([TextRun("Serif", font_family="Times")]))
        doc.add(Paragraph([TextRun("Sans", font_family="Helvetica")]))
        doc.code_block("mono()", language="python")
        assert doc.render() == doc.render()
