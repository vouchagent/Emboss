"""Tests for alt-text emission, Tz removal, mixed-size lines, bibliography wrap."""

from __future__ import annotations

import binascii
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, Paragraph, Style, TextRun  # noqa: E402
from emboss.layout.engine import LayoutEngine  # noqa: E402
from emboss.spec import BibliographyBlock  # noqa: E402
from emboss.styles import resolve_preset  # noqa: E402
from emboss.typography.font_metrics import FontRegistry  # noqa: E402


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


_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<rect x="0" y="0" width="100" height="100" fill="red"/>'
    "</svg>"
)


def _page_content(document: Document, page: int = 0) -> bytes:
    import io

    import pikepdf

    with pikepdf.open(io.BytesIO(document.render())) as pdf:
        return bytes(pdf.pages[page].Contents.read_bytes())


class TestAltText:
    def test_image_alt_text_emitted(self, tmp_path):
        png = tmp_path / "fig.png"
        png.write_bytes(_make_png())
        doc = Document(title="Alt Image")
        doc.image(str(png), alt_text="a red square")
        data = doc.render()
        assert b"/Alt" in data
        assert b"/Alt (a red square)" in data

    def test_svg_alt_text_emitted(self):
        doc = Document(title="Alt SVG")
        doc.svg(_SVG, alt_text="red rectangle diagram")
        data = doc.render()
        assert b"/Alt (red rectangle diagram)" in data

    def test_chart_explicit_alt_text(self):
        doc = Document(title="Alt Chart")
        doc.chart("bar", ["a", "b"], [1, 2], alt_text="two-bar comparison")
        data = doc.render()
        assert b"/Alt (two-bar comparison)" in data

    def test_chart_default_alt_text(self):
        doc = Document(title="Alt Chart Default")
        doc.chart("bar", ["a", "b"], [1, 2], title="Revenue")
        data = doc.render()
        assert b"/Alt (bar chart: Revenue)" in data

    def test_chart_default_alt_text_without_title(self):
        doc = Document(title="Alt Chart Bare")
        doc.chart("pie", ["a", "b"], [1, 2])
        data = doc.render()
        assert b"/Alt (pie chart; 2 categories)" in data


class TestNoFakeFontExpansion:
    def test_justified_paragraph_has_no_tz_operator(self):
        doc = Document(title="Justified")
        doc.paragraph(
            "The quick brown fox jumps over the lazy dog and keeps "
            "running until every line of this paragraph is justified "
            "against both margins of the measure. " * 3,
            style=Style(align="justify"),
        )
        content = _page_content(doc)
        assert b"Tz" not in content


class TestMixedSizeLineHeight:
    def _engine(self):
        return LayoutEngine(FontRegistry(), resolve_preset("corporate"))

    def test_larger_inline_run_raises_line_height(self):
        engine = self._engine()
        sheet = resolve_preset("corporate")
        style = sheet.resolved(sheet.body)
        base_size = style.require("font_size")
        big_size = base_size * 2.0
        multiplier = style.require("line_height")
        metrics = FontRegistry().resolve(style.require("font_family"))

        para = Paragraph(
            [
                TextRun("lead-in words before the "),
                TextRun("BIG", font_size=big_size),
                TextRun(" and after."),
            ]
        )
        block = engine.measure(para, 468.0)

        big_line = next(
            line
            for line in block.lines
            if any(run.font_size == big_size for _t, run, _x in line.fragments)
        )
        assert big_line.height >= metrics.line_height(big_size, multiplier)
        assert big_line.ascent >= metrics.ascent(big_size)

    def test_uniform_paragraph_keeps_base_line_height(self):
        engine = self._engine()
        sheet = resolve_preset("corporate")
        style = sheet.resolved(sheet.body)
        metrics = FontRegistry().resolve(style.require("font_family"))
        base_height = metrics.line_height(
            style.require("font_size"), style.require("line_height")
        )
        para = Paragraph("plain words repeated for several lines " * 6)
        block = engine.measure(para, 200.0)
        assert len(block.lines) > 1
        assert all(line.height == base_height for line in block.lines)

    def test_mixed_size_render_is_deterministic(self):
        def make() -> bytes:
            doc = Document(title="Mixed")
            doc.paragraph(
                [
                    TextRun("normal then "),
                    TextRun("LARGE", font_size=22.0),
                    TextRun(" then normal again."),
                ]
            )
            return doc.render()

        assert make() == make()


class TestBibliographyWrapping:
    _LONG_ENTRY = {
        "key": "wrap2020",
        "authors": ["Alice Wonder", "Bob Builder", "Carol Danvers"],
        "title": (
            "An exhaustive and thoroughly comprehensive investigation "
            "into the wrapping behavior of extremely long bibliography "
            "entries in automated typesetting systems, with particular "
            "attention to hanging indentation, measure overflow, and "
            "the preservation of readable reference lists across pages"
        ),
        "year": 2020,
        "journal": (
            "Transactions on Reproducible Document Engineering "
            "and Automated Layout Quality"
        ),
        "volume": "42",
        "pages": "100-142",
    }

    def _measure(self, width: float = 468.0, title=None):
        engine = LayoutEngine(FontRegistry(), resolve_preset("corporate"))
        block = engine.measure(
            BibliographyBlock(citations=[self._LONG_ENTRY], title=title),
            width,
        )
        return block

    def test_long_entry_wraps_to_multiple_lines(self):
        block = self._measure()
        assert len(block.lines) >= 3

    def test_wrapped_lines_stay_within_measure(self):
        width = 468.0
        block = self._measure(width)
        for index, line in enumerate(block.lines):
            x0 = line.fragments[0][2] if line.fragments else 0.0
            assert x0 + line.width <= width + 0.5, f"line {index} overflows"

    def test_continuation_lines_hang_by_18pt(self):
        block = self._measure()
        first, *rest = block.lines
        assert first.fragments[0][2] == 0.0
        assert rest, "expected continuation lines"
        for line in rest:
            assert line.fragments[0][2] == pytest.approx(first.fragments[0][2] + 18.0)

    def test_title_group_precedes_entry_groups(self):
        block = self._measure(title="References")
        assert block.line_groups[0][0] == "title"
        assert all(kind == "entry" for kind, _n in block.line_groups[1:])

    def test_rendered_bibliography_contains_wrapped_text(self):
        doc = Document(title="Bib Render")
        doc.bibliography([self._LONG_ENTRY])
        data = doc.render()
        assert b"%%EOF" in data

        from emboss.pdf.verify import verify_pdf

        report = verify_pdf(data)
        assert report.ok, report.problems

    def test_bibliography_render_is_deterministic(self):
        def make() -> bytes:
            doc = Document(title="Bib Det")
            doc.bibliography([self._LONG_ENTRY])
            return doc.render()

        assert make() == make()
