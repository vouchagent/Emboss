"""Tests for CMYK color support, spot colors, and color mode conversion.

Covers the CmykColor and SpotColor dataclasses, RGB-to-CMYK conversion,
CMYK string parsing, content stream operators, and the Document color_mode
field that auto-converts RGB to CMYK.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.colors import (  # noqa: E402
    CmykColor, SpotColor, rgb_to_cmyk, hex_to_cmyk, parse_cmyk,
    build_spot_color_resource,
)
from emboss.pdf.streams import ContentStream  # noqa: E402
from emboss import Document  # noqa: E402


# ---------------------------------------------------------------------------
# CmykColor dataclass
# ---------------------------------------------------------------------------

class TestCmykColor:
    def test_create_valid(self):
        c = CmykColor(0.0, 1.0, 0.5, 0.2)
        assert c.c == 0.0
        assert c.m == 1.0
        assert c.y == 0.5
        assert c.k == 0.2

    def test_components_property(self):
        c = CmykColor(0.1, 0.2, 0.3, 0.4)
        assert c.components == (0.1, 0.2, 0.3, 0.4)

    def test_frozen(self):
        c = CmykColor(0.0, 0.0, 0.0, 1.0)
        with pytest.raises(AttributeError):
            c.c = 0.5  # type: ignore

    def test_validation_rejects_negative(self):
        with pytest.raises(ValueError, match="CMYK component c"):
            CmykColor(-0.1, 0.0, 0.0, 0.0)

    def test_validation_rejects_over_one(self):
        with pytest.raises(ValueError, match="CMYK component m"):
            CmykColor(0.0, 1.1, 0.0, 0.0)

    def test_pure_black(self):
        c = CmykColor(0.0, 0.0, 0.0, 1.0)
        assert c.k == 1.0

    def test_slots(self):
        assert hasattr(CmykColor, "__slots__")


# ---------------------------------------------------------------------------
# SpotColor dataclass
# ---------------------------------------------------------------------------

class TestSpotColor:
    def test_create(self):
        s = SpotColor("PANTONE 485 C", 0.0, 1.0, 0.95, 0.0)
        assert s.name == "PANTONE 485 C"
        assert s.c == 0.0

    def test_fallback_cmyk(self):
        s = SpotColor("PANTONE 485 C", 0.0, 1.0, 0.95, 0.0)
        fb = s.fallback_cmyk
        assert isinstance(fb, CmykColor)
        assert fb.m == 1.0

    def test_frozen(self):
        s = SpotColor("Test", 0.0, 0.0, 0.0, 0.0)
        with pytest.raises(AttributeError):
            s.name = "Other"  # type: ignore


# ---------------------------------------------------------------------------
# RGB to CMYK conversion
# ---------------------------------------------------------------------------

class TestRgbToCmyk:
    def test_pure_red(self):
        c = rgb_to_cmyk(1.0, 0.0, 0.0)
        assert c.c == pytest.approx(0.0)
        assert c.m == pytest.approx(1.0)
        assert c.y == pytest.approx(1.0)
        assert c.k == pytest.approx(0.0)

    def test_pure_green(self):
        c = rgb_to_cmyk(0.0, 1.0, 0.0)
        assert c.c == pytest.approx(1.0)
        assert c.m == pytest.approx(0.0)
        assert c.y == pytest.approx(1.0)
        assert c.k == pytest.approx(0.0)

    def test_pure_blue(self):
        c = rgb_to_cmyk(0.0, 0.0, 1.0)
        assert c.c == pytest.approx(1.0)
        assert c.m == pytest.approx(1.0)
        assert c.y == pytest.approx(0.0)
        assert c.k == pytest.approx(0.0)

    def test_pure_black(self):
        c = rgb_to_cmyk(0.0, 0.0, 0.0)
        assert c == CmykColor(0.0, 0.0, 0.0, 1.0)

    def test_pure_white(self):
        c = rgb_to_cmyk(1.0, 1.0, 1.0)
        assert c.c == pytest.approx(0.0)
        assert c.m == pytest.approx(0.0)
        assert c.y == pytest.approx(0.0)
        assert c.k == pytest.approx(0.0)

    def test_gray(self):
        c = rgb_to_cmyk(0.5, 0.5, 0.5)
        assert c.c == pytest.approx(0.0)
        assert c.m == pytest.approx(0.0)
        assert c.y == pytest.approx(0.0)
        assert c.k == pytest.approx(0.5)


class TestHexToCmyk:
    def test_red(self):
        c = hex_to_cmyk("ff0000")
        assert c.m == pytest.approx(1.0)
        assert c.k == pytest.approx(0.0)

    def test_with_hash(self):
        c = hex_to_cmyk("#00ff00")
        assert c.c == pytest.approx(1.0)
        assert c.m == pytest.approx(0.0)

    def test_invalid_hex(self):
        with pytest.raises(ValueError):
            hex_to_cmyk("xyz")


# ---------------------------------------------------------------------------
# CMYK string parsing
# ---------------------------------------------------------------------------

class TestParseCmyk:
    def test_percentage_format(self):
        c = parse_cmyk("cmyk(0,100,100,0)")
        assert c is not None
        assert c.c == pytest.approx(0.0)
        assert c.m == pytest.approx(1.0)
        assert c.y == pytest.approx(1.0)
        assert c.k == pytest.approx(0.0)

    def test_fraction_format(self):
        c = parse_cmyk("cmyk(0.5,0.3,0.1,0.0)")
        assert c is not None
        assert c.c == pytest.approx(0.5)
        assert c.m == pytest.approx(0.3)

    def test_with_spaces(self):
        c = parse_cmyk("cmyk( 10, 20, 30, 40 )")
        assert c is not None
        assert c.c == pytest.approx(0.1)

    def test_non_cmyk_returns_none(self):
        assert parse_cmyk("ff0000") is None
        assert parse_cmyk("blue-600") is None

    def test_pure_black_percentage(self):
        c = parse_cmyk("cmyk(0,0,0,100)")
        assert c is not None
        assert c == CmykColor(0.0, 0.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Content stream CMYK operators
# ---------------------------------------------------------------------------

class TestContentStreamCmyk:
    def test_set_fill_cmyk(self):
        stream = ContentStream()
        stream.set_fill_cmyk(0.1, 0.2, 0.3, 0.4)
        output = stream.to_bytes()
        assert b"k" in output
        assert b"0.1" in output
        assert b"0.4" in output

    def test_set_stroke_cmyk(self):
        stream = ContentStream()
        stream.set_stroke_cmyk(0.5, 0.6, 0.7, 0.8)
        output = stream.to_bytes()
        assert b"K" in output
        assert b"0.5" in output

    def test_set_fill_spot(self):
        stream = ContentStream()
        stream.set_fill_spot("CSMySpot", 0.75)
        output = stream.to_bytes()
        assert b"/CSMySpot cs" in output
        assert b"0.75 scn" in output

    def test_set_stroke_spot(self):
        stream = ContentStream()
        stream.set_stroke_spot("CSTest", 1.0)
        output = stream.to_bytes()
        assert b"/CSTest CS" in output
        assert b"1 SCN" in output


# ---------------------------------------------------------------------------
# Document color_mode field
# ---------------------------------------------------------------------------

class TestDocumentColorMode:
    def test_default_is_rgb(self):
        doc = Document(title="Test")
        assert doc.color_mode == "rgb"

    def test_can_set_cmyk(self):
        doc = Document(title="Test", color_mode="cmyk")
        assert doc.color_mode == "cmyk"

    def test_rgb_document_renders(self):
        doc = Document(title="RGB Test", color_mode="rgb")
        doc.paragraph("Hello, world!")
        pdf = doc.render()
        assert len(pdf) > 0

    def test_cmyk_document_renders(self):
        doc = Document(title="CMYK Test", color_mode="cmyk")
        doc.paragraph("Hello, world!")
        pdf = doc.render()
        assert len(pdf) > 0


# ---------------------------------------------------------------------------
# Spot color resource building
# ---------------------------------------------------------------------------

class TestSpotColorResource:
    def test_build_spot_color_resource(self):
        from emboss.pdf.assembler import PDFAssembler
        assembler = PDFAssembler()
        name, ref = build_spot_color_resource(
            assembler, "PANTONE 485 C", 0.0, 1.0, 0.95, 0.0
        )
        assert "PANTONE" in name or name.startswith("CS")
        assert ref is not None

    def test_resource_name_sanitized(self):
        from emboss.pdf.assembler import PDFAssembler
        assembler = PDFAssembler()
        name, _ = build_spot_color_resource(
            assembler, "My Spot!", 0.5, 0.5, 0.5, 0.0
        )
        # Should not contain special characters
        assert all(c.isalnum() for c in name)
