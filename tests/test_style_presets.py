"""Tests for the differentiated built-in style presets."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, StyleSheet  # noqa: E402
from emboss.styles import PRESETS, resolve_preset  # noqa: E402

ALL_PRESETS = sorted(PRESETS)

#: Snapshot of the tokens that carry each preset's visual identity.
SNAPSHOTS = {
    "legal": {
        "body_font": "Times",
        "heading_font": "Times",
        "body_size": 11.5,
        "align": "justify",
        "line_height": 1.5,
        "h1_color": "1a2744",
        "table_header_rule_color": "4a4237",
        "table_rule_color": "d6d0c4",
        "table_stripe_color": "f7f5f0",
        "table_rule_width": 0.5,
    },
    "finance": {
        "body_font": "Helvetica",
        "heading_font": "Helvetica",
        "body_size": 10.0,
        "align": "left",
        "line_height": 1.4,
        "h1_color": "26303b",
        "table_header_rule_color": "1f4e79",
        "table_rule_color": "c9d2da",
        "table_stripe_color": "f4f6f8",
        "table_rule_width": 0.5,
    },
    "academic": {
        "body_font": "Times",
        "heading_font": "Helvetica",
        "body_size": 11.5,
        "align": "justify",
        "line_height": 1.48,
        "h1_color": "6b1f2a",
        "table_header_rule_color": "3d3a36",
        "table_rule_color": "d5d0c9",
        "table_stripe_color": "f4f2ef",
        "table_rule_width": 0.5,
    },
    "corporate": {
        "body_font": "Helvetica",
        "heading_font": "Helvetica",
        "body_size": 10.5,
        "align": "left",
        "line_height": 1.5,
        "h1_color": "0f3d5c",
        "table_header_rule_color": "1f8a70",
        "table_rule_color": "cfdbd6",
        "table_stripe_color": "eef6f2",
        "table_rule_width": 0.5,
    },
    "minimal": {
        "body_font": "Helvetica",
        "heading_font": "Helvetica",
        "body_size": 9.5,
        "align": "left",
        "line_height": 1.55,
        "h1_color": "1a1a1a",
        "table_header_rule_color": "1a1a1a",
        "table_rule_color": "e5e5e5",
        "table_stripe_color": "fafafa",
        "table_rule_width": 0.3,
    },
    "journal": {
        "body_font": "Times",
        "heading_font": "Times",
        "body_size": 10.5,
        "align": "justify",
        "line_height": 1.46,
        "h1_color": "2d4a3a",
        "table_header_rule_color": "2d4a3a",
        "table_rule_color": "d8ddd9",
        "table_stripe_color": "f3f6f4",
        "table_rule_width": 0.5,
    },
    "brief": {
        "body_font": "Helvetica",
        "heading_font": "Helvetica",
        "body_size": 10.5,
        "align": "left",
        "line_height": 1.42,
        "h1_color": "b7452c",
        "table_header_rule_color": "b7452c",
        "table_rule_color": "d8d3d0",
        "table_stripe_color": "faf0ec",
        "table_rule_width": 0.5,
    },
}


def small_document(style: str) -> Document:
    """Build a small document exercising the preset-driven tokens."""
    doc = Document(title="Preset Smoke", style=style)
    doc.heading("Overview", level=1)
    doc.heading("Detail", level=2)
    doc.paragraph("A short paragraph of body text for the smoke render.")
    doc.bullets(["first item", "second item"])
    doc.table(
        headers=["Metric", "Value"],
        rows=[["Revenue", "100"], ["Cost", "40"], ["Margin", "60"]],
        stripe=True,
    )
    doc.rule()
    return doc


class TestPresetRegistry:
    def test_registry_contains_all_seven_presets(self):
        expected = {
            "legal",
            "finance",
            "academic",
            "corporate",
            "minimal",
            "journal",
            "brief",
        }
        assert set(PRESETS) == expected

    @pytest.mark.parametrize("name", ALL_PRESETS)
    def test_every_preset_resolves(self, name):
        sheet = resolve_preset(name)
        assert isinstance(sheet, StyleSheet)
        assert sheet.name == name

    def test_unknown_preset_lists_new_names(self):
        with pytest.raises(KeyError) as exc:
            resolve_preset("nope")
        message = str(exc.value)
        assert "journal" in message
        assert "brief" in message


class TestPresetSnapshots:
    @pytest.mark.parametrize("name", sorted(SNAPSHOTS))
    def test_key_tokens_match_snapshot(self, name):
        sheet = resolve_preset(name)
        expected = SNAPSHOTS[name]
        body = sheet.resolved(sheet.body)
        h1 = sheet.resolved(sheet.h1)
        assert body.font_family == expected["body_font"]
        assert body.font_size == expected["body_size"]
        assert body.align == expected["align"]
        assert body.line_height == expected["line_height"]
        assert h1.font_family == expected["heading_font"]
        assert h1.color == expected["h1_color"]
        assert h1.bold is True
        assert sheet.table_header_rule_color == expected["table_header_rule_color"]
        assert sheet.table_rule_color == expected["table_rule_color"]
        assert sheet.table_stripe_color == expected["table_stripe_color"]
        assert sheet.table_rule_width == expected["table_rule_width"]

    def test_snapshot_covers_every_registered_preset(self):
        assert set(SNAPSHOTS) == set(PRESETS)

    def test_no_two_presets_share_identity_tuple(self):
        seen = {}
        for name in ALL_PRESETS:
            sheet = resolve_preset(name)
            body = sheet.resolved(sheet.body)
            h1 = sheet.resolved(sheet.h1)
            key = (
                body.font_family,
                body.font_size,
                h1.color,
                sheet.table_stripe_color,
            )
            assert key not in seen, f"{name} duplicates {seen.get(key)}: {key}"
            seen[key] = name

    def test_minimal_is_monochrome_and_hairline(self):
        sheet = resolve_preset("minimal")
        body = sheet.resolved(sheet.body)
        h1 = sheet.resolved(sheet.h1)
        assert h1.color == body.color
        assert sheet.table_rule_width < 0.5
        assert sheet.table_header_rule_width < 1.0

    def test_brief_h1_is_largest_relative_scale(self):
        for name in ALL_PRESETS:
            if name == "brief":
                continue
            sheet = resolve_preset(name)
            ratio = sheet.h1.font_size / sheet.resolved(sheet.body).font_size
            brief = resolve_preset("brief")
            brief_ratio = brief.h1.font_size / brief.resolved(brief.body).font_size
            assert brief_ratio > ratio


class TestPresetRendering:
    @pytest.mark.parametrize("name", ALL_PRESETS)
    def test_small_document_renders_to_pdf_bytes(self, name):
        data = small_document(name).render()
        assert data.startswith(b"%PDF")
        assert b"%%EOF" in data

    @pytest.mark.parametrize("name", ["journal", "brief"])
    def test_render_is_deterministic(self, name):
        first = small_document(name).render()
        second = small_document(name).render()
        assert first == second
