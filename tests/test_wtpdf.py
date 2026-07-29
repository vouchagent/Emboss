"""Tests for WTPDF 1.0 (Well-Tagged PDF, Reuse) declaration and self-check."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, Image, WTPDF_REUSE_ID, verify_wtpdf  # noqa: E402
from emboss.pdfa import build_xmp_metadata  # noqa: E402

# Minimal valid 1x1 white PNG.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGP4z8BQDwAEgAF/pooBPQAAAABJRU5ErkJggg=="
)


def _doc(alt: str = "a labelled bar chart", language: str = "en-US") -> Document:
    doc = Document(title="Reusable Report", author="A", wtpdf=True, language=language)
    doc.heading("Overview", level=1)
    doc.paragraph("A paragraph of reusable body text.")
    doc.bullets(["first", "second"])
    doc.table(headers=["Region", "Q3"], rows=[["North", "10"]])
    doc.add(Image(source=_PNG, alt_text=alt, width=50.0, height=50.0))
    return doc


class TestWtpdfDeclaration:
    def test_xmp_carries_reuse_declaration(self):
        pdf = _doc().render()
        assert WTPDF_REUSE_ID.encode("ascii") in pdf
        assert b"pdfd:conformsTo" in pdf
        assert b"http://pdfa.org/declarations/" in pdf

    def test_extension_schema_describes_declarations(self):
        pdf = _doc().render()
        assert b"PDF Declarations schema" in pdf

    def test_declaration_absent_without_flag(self):
        doc = Document(title="Plain", author="A", language="en-US")
        doc.heading("H", level=1)
        doc.paragraph("body")
        assert WTPDF_REUSE_ID.encode("ascii") not in doc.render()

    def test_build_xmp_metadata_reuse_block(self):
        packet = build_xmp_metadata(
            title="T",
            author="A",
            subject="S",
            keywords="",
            creator="Emboss",
            producer="Emboss",
            language="en-US",
            pdfa=False,
            wtpdf=True,
        ).decode("utf-8")
        assert WTPDF_REUSE_ID in packet
        assert 'xmlns:pdfd="http://pdfa.org/declarations/"' in packet

    def test_deterministic(self):
        assert _doc().render() == _doc().render()


class TestVerifyWtpdf:
    def test_well_formed_document_passes(self):
        report = verify_wtpdf(_doc().render())
        assert report.ok, report.problems
        assert report.has_struct_tree
        assert report.has_lang
        assert report.wtpdf_declared
        assert report.figure_count == 1
        assert report.figures_with_alt == 1
        assert "Figure" in report.structure_types
        assert "Table" in report.structure_types
        assert {"H1", "P", "L"} <= report.structure_types

    def test_figure_without_alt_is_flagged(self):
        report = verify_wtpdf(_doc(alt="").render())
        assert not report.ok
        assert any("Alt" in p for p in report.problems)
        assert report.figures_with_alt == 0

    def test_missing_language_is_flagged(self):
        # Strip the /Lang entry to simulate a document with no language.
        pdf = _doc().render().replace(b"/Lang", b"/Xang")
        report = verify_wtpdf(pdf)
        assert not report.ok
        assert not report.has_lang
        assert any("language" in p.lower() for p in report.problems)

    def test_missing_declaration_is_flagged(self):
        # A tagged document without the wtpdf flag lacks the declaration.
        doc = Document(title="Plain", author="A", language="en-US")
        doc.heading("H", level=1)
        doc.paragraph("body")
        report = verify_wtpdf(doc.render())
        assert not report.wtpdf_declared
        assert any("WTPDF" in p for p in report.problems)

    def test_str_render_is_readable(self):
        text = str(verify_wtpdf(_doc().render()))
        assert "WTPDF 1.0" in text
