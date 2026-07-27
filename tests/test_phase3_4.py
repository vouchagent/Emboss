"""Tests for Phase 3 (images, charts, TOC, multi-column) and Phase 4 (PDF/A, redaction, signatures)."""

import struct
import zlib

import pytest

from emboss import Document, Image, Chart, PageSpec
from emboss.charts import ChartData, ChartSpec, render_chart
from emboss.images import load_image, image_xobject
from emboss.toc import TOCEntry, _nest
from emboss.pdfa import build_xmp_metadata
from emboss.redaction import RedactionMark, apply_redactions
from emboss.signing import SignatureField, build_signature_appearance, can_sign
from emboss.pdf.assembler import PDFAssembler
from emboss.pdf.streams import ContentStream


# ---------------------------------------------------------------------------
# Helper: create a minimal valid JPEG
# ---------------------------------------------------------------------------


def _make_jpeg(width: int = 8, height: int = 8) -> bytes:
    """Build the smallest valid JPEG: SOI + SOF0 + EOI."""
    buf = bytearray()
    buf += b"\xff\xd8"  # SOI
    # SOF0 marker
    buf += b"\xff\xc0"
    length = 11  # 2 + 1 + 2 + 2 + 1 + 3*components
    buf += struct.pack(">H", length)
    buf += struct.pack("B", 8)  # precision
    buf += struct.pack(">H", height)
    buf += struct.pack(">H", width)
    buf += struct.pack("B", 3)  # components (RGB)
    for i in range(1, 4):
        buf += struct.pack("BBB", i, 0x11, 0)
    buf += b"\xff\xd9"  # EOI
    return bytes(buf)


# ---------------------------------------------------------------------------
# Helper: create a minimal valid PNG
# ---------------------------------------------------------------------------


def _make_png(width: int = 4, height: int = 4) -> bytes:
    """Build a minimal valid 8-bit RGB PNG."""
    buf = bytearray()
    buf += b"\x89PNG\r\n\x1a\n"

    # IHDR
    ihdr_data = struct.pack(">IIBB", width, height, 8, 2)  # 8-bit RGB
    ihdr_data += b"\x00\x00\x00"  # compression, filter, interlace
    _write_chunk(buf, b"IHDR", ihdr_data)

    # IDAT — raw pixel rows (filter_type=0, then RGB pixels)
    raw = bytearray()
    for _ in range(height):
        raw += b"\x00"  # no filter
        raw += b"\xff\x00\x00" * width  # red pixels
    compressed = zlib.compress(bytes(raw), 6)
    _write_chunk(buf, b"IDAT", compressed)

    # IEND
    _write_chunk(buf, b"IEND", b"")
    return bytes(buf)


def _write_chunk(buf: bytearray, chunk_type: bytes, data: bytes) -> None:
    import binascii

    buf += struct.pack(">I", len(data))
    buf += chunk_type
    buf += data
    crc = binascii.crc32(chunk_type + data) & 0xFFFFFFFF
    buf += struct.pack(">I", crc)


# ===========================================================================
# IMAGE TESTS
# ===========================================================================


class TestImageParsing:
    def test_jpeg_dimensions(self):
        data = _make_jpeg(320, 240)
        img = load_image(data)
        assert img.width == 320
        assert img.height == 240
        assert img.filter == "DCTDecode"
        assert img.color_space == "DeviceRGB"

    def test_png_dimensions(self):
        data = _make_png(16, 12)
        img = load_image(data)
        assert img.width == 16
        assert img.height == 12
        assert img.filter == "FlateDecode"
        assert img.color_space == "DeviceRGB"

    def test_unsupported_format(self):
        with pytest.raises(ValueError, match="unsupported"):
            load_image(b"GIF89a...")

    def test_image_xobject(self):
        data = _make_jpeg(8, 8)
        img = load_image(data)
        asm = PDFAssembler()
        ref = image_xobject(asm, img)
        assert ref.obj_id >= 1


class TestImageInDocument:
    def test_image_renders(self, tmp_path):
        jpeg_path = tmp_path / "test.jpg"
        jpeg_path.write_bytes(_make_jpeg(100, 80))

        doc = Document(title="Image Test")
        doc.image(str(jpeg_path), alt_text="Test image")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Subtype /Image" in pdf

    def test_image_with_caption(self, tmp_path):
        jpeg_path = tmp_path / "test.jpg"
        jpeg_path.write_bytes(_make_jpeg(50, 50))

        doc = Document(title="Caption Test")
        doc.image(str(jpeg_path), caption="Figure 1: Test", alt_text="test")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_image_alignment(self, tmp_path):
        jpeg_path = tmp_path / "test.jpg"
        jpeg_path.write_bytes(_make_jpeg(50, 50))

        for align in ("left", "center", "right"):
            doc = Document(title="Align Test")
            doc.image(str(jpeg_path), align=align)
            pdf = doc.render()
            assert b"%PDF-1.7" in pdf

    def test_png_image(self, tmp_path):
        png_path = tmp_path / "test.png"
        png_path.write_bytes(_make_png(10, 10))

        doc = Document(title="PNG Test")
        doc.image(str(png_path), alt_text="PNG image")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/XObject" in pdf


# ===========================================================================
# CHART TESTS
# ===========================================================================


class TestChartRendering:
    def test_bar_chart(self):
        stream = ContentStream()
        data = ChartData(
            labels=["A", "B", "C"],
            values=[10, 20, 15],
            title="Test Bar",
        )
        spec = ChartSpec(chart_type="bar", data=data, width=300, height=200)
        render_chart(stream, spec, 72, 700, "F1", 10)
        output = stream.to_bytes()
        assert len(output) > 100

    def test_line_chart(self):
        stream = ContentStream()
        data = ChartData(
            labels=["Jan", "Feb", "Mar"],
            values=[100, 150, 130],
        )
        spec = ChartSpec(chart_type="line", data=data)
        render_chart(stream, spec, 72, 700, "F1", 10)
        output = stream.to_bytes()
        assert len(output) > 100

    def test_pie_chart(self):
        stream = ContentStream()
        data = ChartData(
            labels=["Red", "Blue", "Green"],
            values=[50, 30, 20],
        )
        spec = ChartSpec(chart_type="pie", data=data)
        render_chart(stream, spec, 72, 500, "F1", 10)
        output = stream.to_bytes()
        assert len(output) > 100

    def test_empty_values(self):
        stream = ContentStream()
        data = ChartData(labels=[], values=[])
        spec = ChartSpec(chart_type="bar", data=data)
        render_chart(stream, spec, 72, 700, "F1", 10)

    def test_custom_colors(self):
        stream = ContentStream()
        data = ChartData(
            labels=["X", "Y"],
            values=[5, 10],
            colors=["ff0000", "00ff00"],
        )
        spec = ChartSpec(chart_type="bar", data=data)
        render_chart(stream, spec, 72, 700, "F1", 10)
        output = stream.to_bytes()
        assert len(output) > 0


class TestChartInDocument:
    def test_bar_chart_renders(self):
        doc = Document(title="Chart Test")
        doc.chart("bar", ["Q1", "Q2", "Q3"], [100, 150, 130], title="Revenue")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Figure" in pdf

    def test_line_chart_renders(self):
        doc = Document(title="Line Chart")
        doc.chart("line", ["Jan", "Feb"], [10, 20])
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_pie_chart_renders(self):
        doc = Document(title="Pie Chart")
        doc.chart("pie", ["A", "B", "C"], [40, 35, 25])
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf


# ===========================================================================
# TOC TESTS
# ===========================================================================


class TestTOC:
    def test_nest_flat_headings(self):
        flat = [
            TOCEntry("Chapter 1", level=1, page_index=0, y_position=700),
            TOCEntry("Section 1.1", level=2, page_index=0, y_position=600),
            TOCEntry("Section 1.2", level=2, page_index=1, y_position=700),
            TOCEntry("Chapter 2", level=1, page_index=1, y_position=400),
        ]
        nested = _nest(flat)
        assert len(nested) == 2
        assert nested[0].text == "Chapter 1"
        assert len(nested[0].children) == 2
        assert nested[1].text == "Chapter 2"

    def test_empty_toc(self):
        assert _nest([]) == []

    def test_toc_in_document(self):
        doc = Document(title="TOC Test", toc=True)
        doc.heading("Introduction", level=1)
        doc.paragraph("Some text here.")
        doc.heading("Methods", level=1)
        doc.paragraph("More text.")
        doc.heading("Sub-section", level=2)
        doc.paragraph("Details.")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Outlines" in pdf

    def test_toc_hierarchy(self):
        doc = Document(title="Deep TOC", toc=True)
        doc.heading("Level 1", level=1)
        doc.heading("Level 2", level=2)
        doc.heading("Level 3", level=3)
        doc.heading("Back to 1", level=1)
        pdf = doc.render()
        assert b"/Outlines" in pdf


# ===========================================================================
# MULTI-COLUMN TESTS
# ===========================================================================


class TestMultiColumn:
    def test_two_column_layout(self):
        page = PageSpec(columns=2)
        doc = Document(title="Two Columns", page=page)
        for i in range(6):
            doc.paragraph(f"Paragraph {i + 1} with enough text to test column layout.")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_three_column_layout(self):
        page = PageSpec(columns=3, column_gap=12.0)
        doc = Document(title="Three Columns", page=page)
        for i in range(9):
            doc.paragraph(f"Item {i + 1}.")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_single_column_default(self):
        doc = Document(title="Single")
        doc.paragraph("Normal text.")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf


# ===========================================================================
# PDF/A TESTS
# ===========================================================================


class TestPDFA:
    def test_xmp_metadata(self):
        xmp = build_xmp_metadata(
            title="Test",
            author="Author",
            subject="Subject",
            keywords="key1, key2",
            creator="Emboss",
            producer="Emboss",
            language="en-US",
        )
        text = xmp.decode("utf-8")
        assert "pdfaid:part" in text
        assert "pdfaid:conformance" in text
        assert "<dc:title>" in text

    def test_pdfa_document(self):
        doc = Document(title="PDF/A Test", pdfa=True)
        doc.paragraph("This is a PDF/A document.")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/OutputIntents" in pdf
        assert b"/Metadata" in pdf

    def test_pdfa_with_content(self):
        doc = Document(title="PDF/A Full", pdfa=True, author="Test Author")
        doc.heading("Section 1")
        doc.paragraph("Content here.")
        doc.table(["A", "B"], [["1", "2"]])
        pdf = doc.render()
        assert b"/OutputIntents" in pdf


# ===========================================================================
# REDACTION TESTS
# ===========================================================================


class TestRedaction:
    def test_redaction_mark(self):
        mark = RedactionMark(
            page_index=0,
            x=100,
            y=700,
            width=200,
            height=20,
            replacement_text="[REDACTED]",
        )
        assert mark.color == "000000"
        assert mark.replacement_text == "[REDACTED]"

    def test_apply_redactions_stream(self):
        stream = ContentStream()
        marks = [
            RedactionMark(page_index=0, x=72, y=700, width=100, height=15),
            RedactionMark(page_index=1, x=72, y=600, width=100, height=15),
        ]
        apply_redactions(stream, marks, 0, "F1", 10)
        output = stream.to_bytes()
        assert b"Artifact" in output

    def test_redaction_in_document(self):
        doc = Document(title="Redaction Test")
        doc.paragraph("This text has sensitive information.")
        doc.redactions = [
            RedactionMark(page_index=0, x=72, y=700, width=200, height=14)
        ]
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_redaction_with_replacement(self):
        doc = Document(title="Redaction Replace")
        doc.paragraph("Confidential data here.")
        doc.redactions = [
            RedactionMark(
                page_index=0,
                x=72,
                y=700,
                width=200,
                height=14,
                replacement_text="[CLASSIFIED]",
            )
        ]
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf


# ===========================================================================
# SIGNATURE TESTS
# ===========================================================================


class TestSignature:
    def test_signature_field(self):
        sig = SignatureField(
            page_index=0,
            x=350,
            y=72,
            signer_name="John Doe",
            reason="Approval",
            location="New York",
        )
        assert sig.field_name == "Signature1"

    def test_signature_appearance(self):
        stream = ContentStream()
        sig = SignatureField(
            page_index=0,
            x=100,
            y=100,
            signer_name="Test Signer",
            reason="Testing",
        )
        build_signature_appearance(stream, sig, "F1", 10)
        output = stream.to_bytes()
        assert b"Artifact" in output

    def test_can_sign_function(self):
        result = can_sign()
        assert isinstance(result, bool)

    def test_signature_in_document(self):
        doc = Document(title="Signature Test")
        doc.paragraph("This document is signed.")
        doc.signatures = [
            SignatureField(
                page_index=0,
                x=350,
                y=72,
                signer_name="Jane Smith",
                reason="Approval",
            )
        ]
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Sig" in pdf


# ===========================================================================
# PYDANTIC ADAPTER TESTS
# ===========================================================================


class TestPydanticNewTypes:
    def test_chart_spec_roundtrip(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        data = {
            "title": "Chart Doc",
            "content": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "labels": ["A", "B"],
                    "values": [10, 20],
                    "title": "Test Chart",
                },
            ],
        }
        spec = DocumentSpec.model_validate(data)
        doc = spec.to_document()
        assert len(doc.content) == 1
        assert isinstance(doc.content[0], Chart)

    def test_image_spec_roundtrip(self, tmp_path):
        from emboss.adapters.pydantic_schema import DocumentSpec

        jpeg = tmp_path / "test.jpg"
        jpeg.write_bytes(_make_jpeg(50, 50))

        data = {
            "title": "Image Doc",
            "content": [
                {
                    "type": "image",
                    "source": str(jpeg),
                    "alt_text": "Test",
                },
            ],
        }
        spec = DocumentSpec.model_validate(data)
        doc = spec.to_document()
        assert len(doc.content) == 1
        assert isinstance(doc.content[0], Image)


# ===========================================================================
# EXPORT ADAPTER TESTS
# ===========================================================================


class TestExportAdapters:
    def test_html_image_export(self, tmp_path):
        from emboss.adapters.html_export import to_html

        jpeg = tmp_path / "test.jpg"
        jpeg.write_bytes(_make_jpeg(50, 50))

        doc = Document(title="HTML Image")
        doc.image(str(jpeg), alt_text="Test", caption="Figure 1")
        html = to_html(doc)
        assert "<figure" in html
        assert "Figure 1" in html
        assert "<img" in html

    def test_html_chart_export(self):
        from emboss.adapters.html_export import to_html

        doc = Document(title="HTML Chart")
        doc.chart("bar", ["X", "Y"], [5, 10], title="Test")
        html = to_html(doc)
        assert 'data-type="bar"' in html
        assert "Test" in html

    def test_markdown_image_export(self, tmp_path):
        from emboss.adapters.markdown_export import to_markdown

        jpeg = tmp_path / "test.jpg"
        jpeg.write_bytes(_make_jpeg(50, 50))

        doc = Document(title="MD Image")
        doc.image(str(jpeg), alt_text="Photo", caption="Caption here")
        md = to_markdown(doc)
        assert "![Photo]" in md
        assert "*Caption here*" in md

    def test_markdown_chart_export(self):
        from emboss.adapters.markdown_export import to_markdown

        doc = Document(title="MD Chart")
        doc.chart("pie", ["A", "B"], [60, 40], title="Split")
        md = to_markdown(doc)
        assert "**Split**" in md
        assert "| A" in md

    def test_office_image_export(self, tmp_path):
        from emboss.adapters.docx_export import to_office_dict

        jpeg = tmp_path / "test.jpg"
        jpeg.write_bytes(_make_jpeg(50, 50))

        doc = Document(title="Office Image")
        doc.image(str(jpeg), alt_text="test")
        data = to_office_dict(doc)
        assert data["content"][0]["type"] == "image"

    def test_office_chart_export(self):
        from emboss.adapters.docx_export import to_office_dict

        doc = Document(title="Office Chart")
        doc.chart("line", ["A"], [10])
        data = to_office_dict(doc)
        assert data["content"][0]["type"] == "chart"


# ===========================================================================
# INTEGRATION: FULL DOCUMENT WITH ALL FEATURES
# ===========================================================================


class TestFullIntegration:
    def test_all_features_together(self, tmp_path):
        jpeg = tmp_path / "logo.jpg"
        jpeg.write_bytes(_make_jpeg(200, 100))

        doc = Document(
            title="Complete Feature Test",
            author="Test Author",
            subject="Integration test",
            style="corporate",
            toc=True,
            pdfa=True,
        )
        doc.heading("Executive Summary", level=1)
        doc.paragraph("This document tests all features.")
        doc.image(str(jpeg), alt_text="Company logo", caption="Logo")
        doc.heading("Data Analysis", level=2)
        doc.chart(
            "bar", ["Q1", "Q2", "Q3", "Q4"], [100, 150, 130, 180], title="Revenue"
        )
        doc.table(["Metric", "Value"], [["Revenue", "$4.5M"], ["Growth", "12%"]])
        doc.rule()
        doc.heading("Conclusion", level=2)
        doc.paragraph("All features work correctly.")

        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Outlines" in pdf
        assert b"/OutputIntents" in pdf
        assert b"/Subtype /Image" in pdf
        assert b"/Figure" in pdf

    def test_deterministic_output(self, tmp_path):
        jpeg = tmp_path / "test.jpg"
        jpeg.write_bytes(_make_jpeg(50, 50))

        def make_doc():
            doc = Document(title="Determinism", pdfa=True, toc=True)
            doc.heading("Test")
            doc.paragraph("Content.")
            doc.chart("bar", ["A", "B"], [10, 20])
            doc.image(str(jpeg))
            return doc.render()

        assert make_doc() == make_doc()

    def test_redaction_and_signature(self):
        doc = Document(title="Secure Doc")
        doc.paragraph("Sensitive information follows.")
        doc.paragraph("More content.")
        doc.redactions = [
            RedactionMark(
                page_index=0,
                x=72,
                y=700,
                width=200,
                height=14,
                replacement_text="[REDACTED]",
            ),
        ]
        doc.signatures = [
            SignatureField(
                page_index=0, x=350, y=72, signer_name="Approver", reason="Final review"
            ),
        ]
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"/Sig" in pdf
