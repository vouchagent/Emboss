"""Tests for BrandKit: serialization, palettes, style layering, rendering."""

import re
import zlib

import pytest

from emboss import BrandKit, Document, StyleSheet, apply_brand, resolve_preset
from emboss.brandkit import contrast_ratio, darken_to_contrast
from emboss.pdf.objects import fmt_number
from emboss.pdf.streams import hex_color


def _rg_op(color: str) -> bytes:
    """The exact 'r g b rg' fill operator bytes for a hex color."""
    r, g, b = hex_color(color)
    return b" ".join([fmt_number(r), fmt_number(g), fmt_number(b), b"rg"])


def _content_soup(pdf: bytes) -> bytes:
    """Concatenate every decompressed content stream, space-normalized."""
    parts = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        data = match.group(1)
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
        parts.append(data)
    return b" ".join(b" ".join(p.split()) for p in parts)


# -- serialization --


def test_to_dict_from_dict_round_trip_with_logo_bytes():
    logo = b"\x89PNG\r\n\x1a\n fake-logo-bytes \x00\xff"
    brand = BrandKit(
        name="Acme",
        version="2.3",
        primary="1f4e79",
        accent="e0653a",
        palette=("112233", "445566"),
        heading_font="Emboss Serif",
        footer_text="© Acme",
        logo=logo,
    )
    data = brand.to_dict()
    assert "logo_b64" in data and "logo" not in data
    assert BrandKit.from_dict(data) == brand


def test_to_dict_keeps_logo_path_as_is():
    brand = BrandKit(name="Acme", primary="1f4e79", accent="e0653a", logo="brand.png")
    data = brand.to_dict()
    assert data["logo"] == "brand.png" and "logo_b64" not in data
    assert BrandKit.from_dict(data).logo == "brand.png"


def test_to_dict_is_deterministic():
    brand = BrandKit(name="Acme", primary="1f4e79", accent="e0653a", logo=b"\x01\x02")
    assert brand.to_dict() == brand.to_dict()


# -- derived palette --


def test_derived_palette_length_and_distinct():
    brand = BrandKit(name="Acme", primary="1f4e79", accent="e0653a")
    palette = brand.derived_palette(5)
    assert len(palette) == 5
    assert len(set(palette)) == 5
    assert all(re.fullmatch(r"[0-9a-f]{6}", c) for c in palette)


def test_derived_palette_is_deterministic():
    brand = BrandKit(name="Acme", primary="1f4e79", accent="e0653a")
    assert brand.derived_palette(6) == brand.derived_palette(6)


def test_derived_palette_starts_with_primary_and_accent():
    brand = BrandKit(name="Acme", primary="1f4e79", accent="e0653a")
    palette = brand.derived_palette(4)
    assert palette[0] == "1f4e79"
    assert palette[1] == "e0653a"


def test_series_palette_prefers_explicit_palette():
    brand = BrandKit(
        name="Acme", primary="1f4e79", accent="e0653a", palette=("aaaaaa", "bbbbbb")
    )
    assert brand.series_palette(2) == ["aaaaaa", "bbbbbb"]


# -- apply_brand layering --


def test_apply_brand_layers_colors_without_mutating_input():
    sheet = resolve_preset("corporate")
    original_h1 = sheet.h1.color
    original_body = sheet.body.color
    brand = BrandKit(name="Acme", primary="1f4e79", accent="1f8a70", ink="222222")
    new = apply_brand(sheet, brand)

    assert isinstance(new, StyleSheet)
    assert new.h1.color == darken_to_contrast("1f4e79")
    assert new.body.color == darken_to_contrast("222222")
    assert new.table_header_rule_color == "1f8a70"
    # Input sheet is untouched.
    assert sheet.h1.color == original_h1
    assert sheet.body.color == original_body


def test_apply_brand_applies_bundled_fonts():
    sheet = resolve_preset("corporate")
    brand = BrandKit(
        name="Acme",
        primary="1f4e79",
        accent="1f8a70",
        heading_font="Emboss Serif",
        body_font="Emboss Sans",
    )
    new = apply_brand(sheet, brand)
    assert new.h1.font_family == "Times"
    assert new.body.font_family == "Helvetica"


def test_contrast_guard_darkens_text_but_keeps_fill():
    sheet = resolve_preset("corporate")
    # A near-white brand fails 4.5:1 for text on white.
    brand = BrandKit(name="Glow", primary="ffe600", accent="ffe600")
    new = apply_brand(sheet, brand)

    # Heading (text role) is darkened to a text-safe variant.
    assert new.h1.color != "ffe600"
    assert contrast_ratio(new.h1.color, "ffffff") >= 4.5
    # Table header rule (fill role) keeps the raw brand color.
    assert new.table_header_rule_color == "ffe600"


# -- rendering integration --


def _branded_doc(brand: BrandKit | None) -> Document:
    doc = Document(title="Report", style="corporate", brand=brand)
    doc.heading("Revenue", level=1)
    doc.paragraph("Revenue increased 12% year over year.")
    return doc


def test_document_with_brand_renders_and_headings_use_brand_color():
    # A dark primary passes contrast, so the heading fill is the raw primary.
    primary = "1f4e79"
    brand = BrandKit(name="Acme", primary=primary, accent="1f8a70")
    pdf = _branded_doc(brand).render()
    assert pdf.startswith(b"%PDF")
    assert _rg_op(primary) in _content_soup(pdf)


def test_brand_none_is_byte_identical_to_no_brand():
    plain = _branded_doc(None).render()
    default = Document(title="Report", style="corporate")
    default.heading("Revenue", level=1)
    default.paragraph("Revenue increased 12% year over year.")
    assert plain == default.render()


def test_two_documents_sharing_brand_are_consistent():
    brand = BrandKit(name="Acme", primary="1f4e79", accent="1f8a70")
    first = _branded_doc(brand).render()
    second = _branded_doc(brand).render()
    op = _rg_op("1f4e79")
    assert op in _content_soup(first)
    assert op in _content_soup(second)


def test_brand_render_is_deterministic():
    brand = BrandKit(name="Acme", primary="1f4e79", accent="1f8a70")
    assert _branded_doc(brand).render() == _branded_doc(brand).render()


# -- pydantic path --


def test_pydantic_spec_builds_a_brand():
    pytest.importorskip("pydantic")
    from emboss.adapters.pydantic_schema import DocumentSpec

    spec = DocumentSpec.model_validate(
        {
            "title": "Report",
            "style": "corporate",
            "brand": {
                "name": "Acme",
                "primary": "1f4e79",
                "accent": "1f8a70",
                "heading_font": "Emboss Serif",
            },
            "content": [{"type": "heading", "text": "Revenue", "level": 1}],
        }
    )
    doc = spec.to_document()
    assert isinstance(doc.brand, BrandKit)
    assert doc.brand.name == "Acme"
    assert doc.stylesheet.h1.font_family == "Times"
    assert doc.render().startswith(b"%PDF")
