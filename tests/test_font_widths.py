"""Tests for base-14 width coverage beyond ASCII (WinAnsi punctuation, accents)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.typography.font_metrics import FontMetrics  # noqa: E402

EN_DASH = "–"
EM_DASH = "—"
LSQUO = "‘"
RSQUO = "’"
LDQUO = "“"
RDQUO = "”"
ELLIPSIS = "…"
BULLET = "•"
NBSP = " "
SOFT_HYPHEN = "­"

WINANSI_EXTRAS = [
    0x00A2,
    0x00A3,
    0x00A5,
    0x00A7,
    0x00A9,
    0x00AB,
    0x00AE,
    0x00B0,
    0x00B1,
    0x00B5,
    0x00B7,
    0x00BB,
    0x00D7,
    0x00F7,
    0x2013,
    0x2014,
    0x2018,
    0x2019,
    0x201A,
    0x201C,
    0x201D,
    0x201E,
    0x2020,
    0x2021,
    0x2022,
    0x2026,
    0x2030,
    0x2039,
    0x203A,
    0x20AC,
    0x2122,
]

TEXT_FAMILIES = [
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
]


class TestPunctuationWidths:
    """Typographic punctuation must carry exact AFM advances."""

    @pytest.mark.parametrize(
        ("name", "endash", "emdash", "ldquo", "lsquo"),
        [
            ("Helvetica", 556, 1000, 333, 222),
            ("Helvetica-Bold", 556, 1000, 500, 278),
            ("Helvetica-Oblique", 556, 1000, 333, 222),
            ("Helvetica-BoldOblique", 556, 1000, 500, 278),
            ("Times-Roman", 500, 1000, 444, 333),
            ("Times-Bold", 500, 1000, 500, 333),
            ("Times-Italic", 500, 1000, 444, 333),
            ("Times-BoldItalic", 500, 1000, 500, 333),
            ("Courier", 600, 600, 600, 600),
        ],
    )
    def test_dashes_and_quotes(self, name, endash, emdash, ldquo, lsquo):
        metrics = FontMetrics.base14(name)
        assert metrics.width_of(ord(EN_DASH)) == endash
        assert metrics.width_of(ord(EM_DASH)) == emdash
        assert metrics.width_of(ord(LDQUO)) == ldquo
        assert metrics.width_of(ord(RDQUO)) == ldquo
        assert metrics.width_of(ord(LSQUO)) == lsquo
        assert metrics.width_of(ord(RSQUO)) == lsquo

    @pytest.mark.parametrize(
        ("name", "ellipsis", "bullet"),
        [
            ("Helvetica", 1000, 350),
            ("Times-Roman", 1000, 350),
            ("Courier", 600, 600),
        ],
    )
    def test_ellipsis_and_bullet(self, name, ellipsis, bullet):
        metrics = FontMetrics.base14(name)
        assert metrics.width_of(ord(ELLIPSIS)) == ellipsis
        assert metrics.width_of(ord(BULLET)) == bullet

    @pytest.mark.parametrize("name", TEXT_FAMILIES)
    def test_nbsp_matches_space(self, name):
        metrics = FontMetrics.base14(name)
        assert metrics.width_of(ord(NBSP)) == metrics.width_of(ord(" "))

    @pytest.mark.parametrize("name", TEXT_FAMILIES)
    def test_soft_hyphen_matches_hyphen(self, name):
        metrics = FontMetrics.base14(name)
        assert metrics.width_of(ord(SOFT_HYPHEN)) == metrics.width_of(ord("-"))

    def test_courier_uniform_600(self):
        metrics = FontMetrics.base14("Courier")
        for codepoint in WINANSI_EXTRAS:
            assert metrics.width_of(codepoint) == 600

    def test_no_default_width_for_winansi_extras(self):
        for name in TEXT_FAMILIES:
            metrics = FontMetrics.base14(name)
            for codepoint in WINANSI_EXTRAS:
                assert codepoint in metrics._widths, (name, hex(codepoint))

    def test_symbol_math_operators(self):
        metrics = FontMetrics.base14("Symbol")
        assert metrics.width_of(0x2022) == 460
        assert metrics.width_of(0x00B1) == 549
        assert metrics.width_of(0x00D7) == 549
        assert metrics.width_of(0x00F7) == 549


class TestAccentedLatin:
    """Accented Latin letters take the base letter's advance via NFD."""

    @pytest.mark.parametrize(
        "name", ["Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold"]
    )
    def test_eacute_equals_e(self, name):
        metrics = FontMetrics.base14(name)
        assert metrics.width_of(ord("é")) == metrics.width_of(ord("e"))

    def test_cafe_exact_width_helvetica(self):
        metrics = FontMetrics.base14("Helvetica")
        # c=500, a=556, f=278, e-acute = e = 556 (Helvetica AFM).
        expected = 500 + 556 + 278 + 556
        assert metrics.text_width("café", 1000.0) == pytest.approx(expected)

    def test_cafe_exact_width_times(self):
        metrics = FontMetrics.base14("Times-Roman")
        # c=444, a=444, f=333, e-acute = e = 444 (Times-Roman AFM).
        expected = 444 + 444 + 333 + 444
        assert metrics.text_width("café", 1000.0) == pytest.approx(expected)

    def test_decomposition_is_cached_in_width_table(self):
        metrics = FontMetrics.base14("Helvetica")
        assert 0x00FC not in metrics._widths
        metrics.width_of(0x00FC)  # u-dieresis
        assert metrics._widths[0x00FC] == metrics.width_of(ord("u"))

    def test_unmapped_char_still_uses_missing_width(self):
        metrics = FontMetrics.base14("Helvetica")
        assert metrics.width_of(0x6C49) == 500  # CJK: no decomposition
        assert not metrics.supports("汉")


class TestJustificationAdvances:
    """text_width sums must be exact so justification stays correct."""

    def test_em_dash_run_helvetica(self):
        metrics = FontMetrics.base14("Helvetica")
        a = metrics.width_of(ord("a"))
        b = metrics.width_of(ord("b"))
        assert metrics.text_width("a—b", 1000.0) == pytest.approx(a + 1000 + b)

    def test_quoted_phrase_times(self):
        metrics = FontMetrics.base14("Times-Roman")
        inner = metrics.text_width("ok", 1000.0)
        total = metrics.text_width("“ok”", 1000.0)
        assert total == pytest.approx(inner + 444 + 444)

    def test_scaling_convention(self):
        metrics = FontMetrics.base14("Helvetica")
        at_12 = metrics.text_width("—", 12.0)
        assert at_12 == pytest.approx(1000 * 12.0 / 1000.0)
