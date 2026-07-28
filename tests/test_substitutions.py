"""Tests for missing-glyph handling: substitution, fallbacks, engine wiring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, Paragraph, TextRun  # noqa: E402
from emboss.layout.engine import LayoutEngine  # noqa: E402
from emboss.styles import resolve_preset  # noqa: E402
from emboss.typography.font_metrics import FontMetrics, FontRegistry  # noqa: E402
from emboss.typography.substitutions import (  # noqa: E402
    SUBSTITUTIONS,
    substitute_unsupported,
)


def _ascii_only(char: str) -> bool:
    return 32 <= ord(char) < 127


def _make_font(path, chars=None, family="FallbackTest"):
    """Build a minimal TrueType font whose cmap covers `chars`."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    if chars is None:
        chars = {32: "space", 0x0416: "Zhe"}

    glyph_names = [".notdef"] + list(chars.values())
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(glyph_names)
    fb.setupCharacterMap(chars)

    glyphs, metrics = {}, {}
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 700))
    pen.lineTo((0, 700))
    pen.closePath()
    glyphs[".notdef"] = pen.glyph()
    metrics[".notdef"] = (500, 0)

    for codepoint, name in chars.items():
        pen = TTGlyphPen(None)
        if name == "space":
            pen.moveTo((0, 0))
            pen.endPath()
            metrics[name] = (250, 0)
        else:
            width = 500 + (codepoint % 200)
            pen.moveTo((0, 0))
            pen.lineTo((width, 0))
            pen.lineTo((width, 700))
            pen.lineTo((0, 700))
            pen.closePath()
            metrics[name] = (width, 0)
        glyphs[name] = pen.glyph()

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sCapHeight=700)
    fb.setupPost()
    fb.font.save(str(path))
    return path


# ===========================================================================
# SUBSTITUTION UNITS
# ===========================================================================


class TestSubstitutionUnits:
    def test_arrows(self):
        text, replaced = substitute_unsupported("A → B ⇒ C ← D", _ascii_only)
        assert text == "A -> B => C <- D"
        assert replaced == ("→", "⇒", "←")

    def test_comparisons(self):
        text, _ = substitute_unsupported("x ≤ y ≥ z ≠ w", _ascii_only)
        assert text == "x <= y >= z != w"

    def test_typographic_spaces_collapse(self):
        text, replaced = substitute_unsupported("a b c d　e", _ascii_only)
        assert text == "a b c d e"
        assert len(replaced) == 4

    def test_zero_width_characters_vanish(self):
        text, replaced = substitute_unsupported("a​b‍c﻿d⁠", _ascii_only)
        assert text == "abcd"
        assert len(replaced) == 4

    def test_superscript_and_subscript_digits(self):
        assert substitute_unsupported("E = mc²", _ascii_only)[0] == "E = mc2"
        assert substitute_unsupported("H₂O x⁵", _ascii_only)[0] == "H2O x5"

    def test_vulgar_fractions(self):
        assert substitute_unsupported("½ ⅓ ¾ ⅞", _ascii_only)[0] == "1/2 1/3 3/4 7/8"

    def test_box_drawing(self):
        assert substitute_unsupported("─│┌┼", _ascii_only)[0] == "-|++"

    def test_checkmarks_and_ballots(self):
        assert substitute_unsupported("✓✔✗✘", _ascii_only)[0] == "**xx"
        assert substitute_unsupported("☐☑☒", _ascii_only)[0] == "[ ][*][x]"

    def test_nfkd_accent_stripping(self):
        text, replaced = substitute_unsupported("café naïve", _ascii_only)
        assert text == "cafe naive"
        assert replaced == ("é", "ï")

    def test_last_resort_question_mark(self):
        text, replaced = substitute_unsupported("a\U0001f984b", _ascii_only)
        assert text == "a?b"
        assert replaced == ("\U0001f984",)

    def test_structural_whitespace_passes_through(self):
        text, replaced = substitute_unsupported("a\tb\nc", _ascii_only)
        assert text == "a\tb\nc"
        assert replaced == ()

    def test_map_keys_single_char_values_ascii(self):
        assert all(len(key) == 1 for key in SUBSTITUTIONS)
        assert all(
            all(32 <= ord(c) < 127 for c in value) for value in SUBSTITUTIONS.values()
        )


class TestNoOpAndDeterminism:
    def test_supported_text_returned_unchanged(self):
        metrics = FontMetrics.base14("Helvetica")
        text = "Hello — “quotes” … café ½ Š"
        result, replaced = substitute_unsupported(text, metrics.supports)
        assert result is text
        assert replaced == ()

    def test_nbsp_untouched_for_base14(self):
        metrics = FontMetrics.base14("Times-Roman")
        text = "10 kg"
        result, replaced = substitute_unsupported(text, metrics.supports)
        assert result is text
        assert replaced == ()

    def test_plain_ascii_identity(self):
        text = "Just plain ASCII text."
        result, replaced = substitute_unsupported(text, _ascii_only)
        assert result is text
        assert replaced == ()

    def test_deterministic_across_calls(self):
        metrics = FontMetrics.base14("Helvetica")
        text = "→ ✓ ½ ⅓ café ​ ▪ ─ \U0001f984"
        first = substitute_unsupported(text, metrics.supports)
        second = substitute_unsupported(text, metrics.supports)
        assert first == second

    def test_arrow_unsupported_by_base14(self):
        metrics = FontMetrics.base14("Helvetica")
        text, replaced = substitute_unsupported("A → B", metrics.supports)
        assert text == "A -> B"
        assert replaced == ("→",)


# ===========================================================================
# REGISTRY FALLBACK CHAIN
# ===========================================================================


class TestRegistryFallback:
    def test_no_fallbacks_no_behavior_change(self):
        registry = FontRegistry()
        primary = registry.resolve("helvetica")
        assert primary.name == "Helvetica"
        assert registry.fallbacks == []
        assert registry.segment_runs("aЖb", primary) == [("aЖb", primary)]

    def test_fallback_font_picks_up_char(self, tmp_path):
        path = _make_font(tmp_path / "fallback.ttf")
        registry = FontRegistry()
        registry.register_fallback(path)
        primary = registry.resolve("helvetica")

        segments = registry.segment_runs("abЖcd", primary)
        assert [text for text, _m in segments] == ["ab", "Ж", "cd"]
        assert segments[0][1] is primary
        assert segments[2][1] is primary
        fallback = segments[1][1]
        assert fallback is registry.fallbacks[0]
        assert fallback.is_embedded
        assert fallback.supports("Ж")
        assert not primary.supports("Ж")

    def test_first_supporting_fallback_wins(self, tmp_path):
        first = _make_font(tmp_path / "first.ttf", family="FirstFallback")
        second = _make_font(tmp_path / "second.ttf", family="SecondFallback")
        registry = FontRegistry()
        registry.register_fallback(first)
        registry.register_fallback(second)
        primary = registry.resolve("helvetica")

        segments = registry.segment_runs("Ж", primary)
        assert segments == [("Ж", registry.fallbacks[0])]
        assert registry.fallbacks[0].font_path == first

    def test_char_no_font_supports_stays_with_primary(self, tmp_path):
        path = _make_font(tmp_path / "fallback.ttf")
        registry = FontRegistry()
        registry.register_fallback(path)
        primary = registry.resolve("helvetica")
        segments = registry.segment_runs("a\U0001f984b", primary)
        assert segments == [("a\U0001f984b", primary)]

    def test_resolve_unaffected_by_fallbacks(self, tmp_path):
        registry = FontRegistry()
        registry.register_fallback(_make_font(tmp_path / "fallback.ttf"))
        assert registry.resolve("times", bold=True).name == "Times-Bold"

    def test_empty_text(self):
        registry = FontRegistry()
        assert registry.segment_runs("", registry.resolve("helvetica")) == []


# ===========================================================================
# ENGINE WIRING
# ===========================================================================


def _engine() -> LayoutEngine:
    return LayoutEngine(FontRegistry(), resolve_preset("corporate"))


class TestEngineSubstitution:
    def test_arrow_paragraph_measures_as_ascii(self):
        arrow = _engine().measure(Paragraph("Latency fell 10 ms → 5 ms"), 400.0)
        ascii_ = _engine().measure(Paragraph("Latency fell 10 ms -> 5 ms"), 400.0)
        assert [line.width for line in arrow.lines] == pytest.approx(
            [line.width for line in ascii_.lines]
        )
        rendered = "".join(
            text for line in arrow.lines for text, _r, _x in line.fragments
        )
        assert "->" in rendered
        assert "→" not in rendered

    def test_warnings_populated_and_deduplicated(self):
        engine = _engine()
        engine.measure(Paragraph("A → B ✓"), 400.0)
        assert any("U+2192" in warning for warning in engine.warnings)
        assert any("U+2713" in warning for warning in engine.warnings)
        count = len(engine.warnings)
        engine.measure(Paragraph("C → D ✓"), 400.0)
        assert len(engine.warnings) == count

    def test_no_warnings_for_supported_text(self):
        engine = _engine()
        engine.measure(Paragraph("Plain text — with “WinAnsi” café ½."), 400.0)
        assert engine.warnings == []

    def test_run_styling_survives_substitution(self):
        engine = _engine()
        para = Paragraph([TextRun("bold →", bold=True, link="https://e.com")])
        measured = engine.measure(para, 400.0)
        runs = [run for line in measured.lines for _t, run, _x in line.fragments]
        assert runs
        assert all(run.bold and run.link == "https://e.com" for run in runs)

    def test_ascii_runs_not_copied(self):
        engine = _engine()
        para = Paragraph("No substitution needed here.")
        measured = engine.measure(para, 400.0)
        for line in measured.lines:
            for _text, run, _x in line.fragments:
                assert run is para.runs[0]

    def test_segment_run_exposed_for_writer_wiring(self, tmp_path):
        registry = FontRegistry()
        registry.register_fallback(_make_font(tmp_path / "fallback.ttf"))
        engine = LayoutEngine(registry, resolve_preset("corporate"))
        style = engine.sheet.resolved(engine.sheet.body)
        segments = engine.segment_run(style, TextRun("aЖb"))
        assert "".join(text for text, _m in segments) == "aЖb"
        assert len(segments) == 3
        assert segments[1][1].supports("Ж")

    def test_renders_pdf_without_error(self):
        doc = Document(title="Substitutions")
        doc.paragraph("Throughput 2 GB/s → 4 GB/s ✓ (≈ 2×, ⅓ the cost)")
        doc.bullets(["☑ shipped", "☐ pending"])
        data = doc.render()
        assert data.startswith(b"%PDF")

    def test_render_deterministic_with_substitutions(self):
        def build() -> bytes:
            doc = Document(title="Det")
            doc.paragraph("A → B ✓ ½ ​zero")
            return doc.render()

        assert build() == build()

    def test_plain_ascii_render_regression(self):
        def build() -> bytes:
            doc = Document(title="Plain")
            doc.paragraph("Plain ASCII paragraph, nothing to substitute.")
            doc.paragraph("Second paragraph for good measure.")
            return doc.render()

        first, second = build(), build()
        assert first == second
        assert first.startswith(b"%PDF")
