"""Tests for PDF/X-4 (ISO 15930-7) print/prepress conformance output."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, PDFX_VERSION  # noqa: E402
from emboss.pdfa import build_xmp_metadata  # noqa: E402
from emboss.pdfx import (  # noqa: E402
    build_pdfx_output_intent,
    pdfx_output_intent_profile,
)


def _doc(**overrides) -> Document:
    kwargs = dict(
        title="Print Job",
        author="Studio",
        color_mode="cmyk",
        pdfx=True,
        pdfx_condition="FOGRA39",
    )
    kwargs.update(overrides)
    doc = Document(**kwargs)
    doc.heading("Poster", level=1)
    doc.paragraph("Camera-ready body copy for offset printing.")
    return doc


class TestPdfxOutputIntent:
    def test_output_intent_is_gts_pdfx(self):
        pdf = _doc().render()
        assert b"/S /GTS_PDFX" in pdf
        assert b"/Type /OutputIntent" in pdf

    def test_dest_output_profile_present(self):
        pdf = _doc().render()
        assert b"/DestOutputProfile" in pdf

    def test_condition_identifier_recorded(self):
        pdf = _doc().render()
        assert b"/OutputConditionIdentifier" in pdf
        assert b"FOGRA39" in pdf

    def test_version_string_in_xmp_and_info(self):
        pdf = _doc().render()
        assert b"PDF/X-4" in pdf
        assert b"/GTS_PDFXVersion" in pdf
        assert b"pdfxid:GTS_PDFXVersion" in pdf
        assert b"http://www.npes.org/pdfx/ns/id/" in pdf

    def test_fonts_embedded(self):
        pdf = _doc().render()
        assert b"/FontFile" in pdf

    def test_deterministic(self):
        assert _doc().render() == _doc().render()


class TestPdfxProfile:
    def test_default_profile_is_bundled_cmyk(self):
        doc = Document(pdfx=True)
        icc, condition = pdfx_output_intent_profile(doc)
        assert icc[36:40] == b"acsp"  # valid ICC signature
        assert icc[16:20] == b"CMYK"
        assert condition  # non-empty identifier

    def test_caller_supplied_profile_is_used(self):
        supplied = b"acsp" * 64
        doc = Document(pdfx=True, pdfx_output_profile=supplied, pdfx_condition="X")
        icc, condition = pdfx_output_intent_profile(doc)
        assert icc == supplied
        assert condition == "X"

    def test_supplied_profile_must_be_bytes(self):
        doc = Document(pdfx=True, pdfx_output_profile="not-bytes")  # type: ignore
        with pytest.raises(TypeError):
            pdfx_output_intent_profile(doc)


class TestPdfxXmp:
    def test_xmp_declares_pdfx_version(self):
        packet = build_xmp_metadata(
            title="T",
            author="A",
            subject="S",
            keywords="",
            creator="Emboss",
            producer="Emboss",
            language="en-US",
            pdfa=False,
            pdfx=PDFX_VERSION,
        ).decode("utf-8")
        assert "<pdfxid:GTS_PDFXVersion>PDF/X-4</pdfxid:GTS_PDFXVersion>" in packet
        assert "PDF/X identification schema" in packet


class TestPdfxIntentBuilder:
    def test_builder_returns_reference(self):
        from emboss.pdf.assembler import PDFAssembler

        assembler = PDFAssembler()
        doc = Document(pdfx=True, pdfx_condition="GRACoL")
        ref = build_pdfx_output_intent(assembler, doc)
        assert ref is not None


@pytest.mark.skipif(shutil.which("verapdf") is None, reason="veraPDF not installed")
def test_pdfx_carrier_is_valid_pdfa_2b():
    """A PDF/X-4 file that is also PDF/A-2b validates under veraPDF.

    veraPDF ships no dedicated PDF/X profile, so this asserts the PDF/X
    output intent and GTS_PDFXVersion XMP do not break the PDF/A carrier.
    """
    from emboss.pdf.verify import verify_conformance

    doc = _doc(pdfa=True)
    report = verify_conformance(doc.render(), "2b")
    assert report.compliant, str(report)
