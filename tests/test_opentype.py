"""Tests for GPOS kerning extraction, small caps, and tighter spacing.

Covers the three new features:
  1. GPOS PairPos Format 1 / Format 2 kerning extraction
  2. Small caps measurement and TextRun.small_caps flag
  3. Tighter interword stretch/shrink and tracking parameter
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.spec import TextRun  # noqa: E402
from emboss.typography.font_metrics import (  # noqa: E402
    FontMetrics,
    _extract_gpos_kerning,
    _extract_kerning,
    _gpos_format1,
    _gpos_format2,
)
from emboss.typography.line_breaking import (  # noqa: E402
    Box,
    Glue,
    Penalty,
    build_items,
)


# -----------------------------------------------------------------------
# Helpers -- synthetic GPOS structures
# -----------------------------------------------------------------------


def _make_value1(x_advance: int):
    """Create a mock Value1 with an XAdvance attribute."""
    v = SimpleNamespace(XAdvance=x_advance)
    return v


def _make_pairpos_format1(glyph_pairs, coverage_glyphs):
    """Build a synthetic PairPos Format 1 subtable.

    glyph_pairs: list of (first_glyph_name, [(second_glyph_name, x_advance), ...])
    coverage_glyphs: list of glyph names in coverage order
    """
    subtable = SimpleNamespace(Format=1)
    pairsets = []
    for _first, seconds in glyph_pairs:
        pvrs = []
        for second_glyph, x_adv in seconds:
            pvr = SimpleNamespace(
                SecondGlyph=second_glyph,
                Value1=_make_value1(x_adv),
            )
            pvrs.append(pvr)
        pairsets.append(SimpleNamespace(PairValueRecord=pvrs))
    subtable.PairSet = pairsets
    subtable.Coverage = SimpleNamespace(glyphs=coverage_glyphs)
    return subtable


def _make_pairpos_format2(class1_defs, class2_defs, records, coverage_glyphs):
    """Build a synthetic PairPos Format 2 subtable.

    class1_defs: dict glyph_name -> class_index
    class2_defs: dict glyph_name -> class_index
    records: 2d list of x_advance values, indexed [cls1][cls2]
    coverage_glyphs: list of glyph names in coverage
    """
    subtable = SimpleNamespace(Format=2)
    subtable.ClassDef1 = SimpleNamespace(classDefs=class1_defs)
    subtable.ClassDef2 = SimpleNamespace(classDefs=class2_defs)
    subtable.Coverage = SimpleNamespace(glyphs=coverage_glyphs)

    class1_records = []
    for row in records:
        class2_records = []
        for xadv in row:
            class2_records.append(
                SimpleNamespace(Value1=_make_value1(xadv) if xadv else None)
            )
        class1_records.append(
            SimpleNamespace(Class2Record=class2_records)
        )
    subtable.Class1Record = class1_records
    return subtable


def _wrap_gpos(subtables):
    """Wrap subtable(s) in a minimal GPOS table structure."""
    lookup = SimpleNamespace(SubTable=subtables)
    feature = SimpleNamespace(
        FeatureTag="kern",
        Feature=SimpleNamespace(LookupListIndex=[0]),
    )
    gpos_table = SimpleNamespace(
        FeatureList=SimpleNamespace(FeatureRecord=[feature]),
        LookupList=SimpleNamespace(Lookup=[lookup]),
    )
    return gpos_table


# -----------------------------------------------------------------------
# Feature 1: GPOS PairPos kerning
# -----------------------------------------------------------------------


class TestGPOSFormat1:
    """PairPos Format 1 -- explicit individual pairs."""

    def test_extracts_individual_pairs(self):
        reverse_cmap = {"A": 65, "V": 86}
        subtable = _make_pairpos_format1(
            [("A", [("V", -80)])],
            coverage_glyphs=["A"],
        )
        pairs: dict = {}
        _gpos_format1(subtable, reverse_cmap, 1.0, pairs)
        assert (65, 86) in pairs
        assert pairs[(65, 86)] == -80.0

    def test_applies_scale_factor(self):
        reverse_cmap = {"T": 84, "o": 111}
        subtable = _make_pairpos_format1(
            [("T", [("o", -100)])],
            coverage_glyphs=["T"],
        )
        pairs: dict = {}
        _gpos_format1(subtable, reverse_cmap, 0.5, pairs)
        assert pairs[(84, 111)] == -50.0

    def test_skips_glyphs_not_in_cmap(self):
        reverse_cmap = {"A": 65}  # "V" missing
        subtable = _make_pairpos_format1(
            [("A", [("V", -80)])],
            coverage_glyphs=["A"],
        )
        pairs: dict = {}
        _gpos_format1(subtable, reverse_cmap, 1.0, pairs)
        assert len(pairs) == 0

    def test_skips_zero_adjustment(self):
        reverse_cmap = {"A": 65, "B": 66}
        subtable = _make_pairpos_format1(
            [("A", [("B", 0)])],
            coverage_glyphs=["A"],
        )
        pairs: dict = {}
        _gpos_format1(subtable, reverse_cmap, 1.0, pairs)
        assert len(pairs) == 0

    def test_setdefault_does_not_overwrite(self):
        reverse_cmap = {"A": 65, "V": 86}
        subtable = _make_pairpos_format1(
            [("A", [("V", -80)])],
            coverage_glyphs=["A"],
        )
        pairs = {(65, 86): -50.0}  # pre-existing kern pair
        _gpos_format1(subtable, reverse_cmap, 1.0, pairs)
        assert pairs[(65, 86)] == -50.0  # not overwritten


class TestGPOSFormat2:
    """PairPos Format 2 -- class-based kerning."""

    def test_extracts_class_pairs(self):
        reverse_cmap = {"T": 84, "o": 111}
        class1 = {"T": 1}
        class2 = {"o": 1}
        records = [
            [0, 0],      # class 0 x class 0, class 0 x class 1
            [0, -90],    # class 1 x class 0, class 1 x class 1
        ]
        subtable = _make_pairpos_format2(
            class1, class2, records, coverage_glyphs=["T"]
        )
        pairs: dict = {}
        _gpos_format2(subtable, reverse_cmap, 1.0, pairs)
        assert (84, 111) in pairs
        assert pairs[(84, 111)] == -90.0

    def test_class0_includes_uncovered_coverage_glyphs(self):
        """Glyphs in Coverage but not in ClassDef1 belong to class 0."""
        reverse_cmap = {"A": 65, "V": 86, "W": 87}
        class1 = {"V": 1}  # "A" not listed -> class 0
        class2 = {"W": 1}
        records = [
            [0, -40],    # class 0 x class 1  -> A/W pair
            [0, 0],
        ]
        subtable = _make_pairpos_format2(
            class1, class2, records, coverage_glyphs=["A", "V"]
        )
        pairs: dict = {}
        _gpos_format2(subtable, reverse_cmap, 1.0, pairs)
        assert (65, 87) in pairs
        assert pairs[(65, 87)] == -40.0

    def test_setdefault_preserves_kern_table_values(self):
        reverse_cmap = {"T": 84, "o": 111}
        class1 = {"T": 1}
        class2 = {"o": 1}
        records = [
            [0, 0],
            [0, -90],
        ]
        subtable = _make_pairpos_format2(
            class1, class2, records, coverage_glyphs=["T"]
        )
        pairs = {(84, 111): -70.0}
        _gpos_format2(subtable, reverse_cmap, 1.0, pairs)
        assert pairs[(84, 111)] == -70.0


class TestExtractGPOSKerning:
    """Integration: _extract_gpos_kerning walks the GPOS table."""

    def test_no_gpos_table_is_noop(self):
        font = {}
        pairs: dict = {}
        _extract_gpos_kerning(font, 1.0, {}, pairs)
        assert pairs == {}

    def test_non_kern_features_ignored(self):
        """Only 'kern' features are read, not 'mark' or others."""
        lookup = SimpleNamespace(SubTable=[])
        feature = SimpleNamespace(
            FeatureTag="mark",
            Feature=SimpleNamespace(LookupListIndex=[0]),
        )
        gpos_table = SimpleNamespace(
            FeatureList=SimpleNamespace(FeatureRecord=[feature]),
            LookupList=SimpleNamespace(Lookup=[lookup]),
        )
        font = {"GPOS": SimpleNamespace(table=gpos_table)}
        pairs: dict = {}
        _extract_gpos_kerning(font, 1.0, {}, pairs)
        assert pairs == {}

    def test_malformed_gpos_does_not_raise(self):
        """A broken GPOS table should be caught, not crash."""
        font = {"GPOS": SimpleNamespace(table=None)}
        pairs: dict = {}
        _extract_gpos_kerning(font, 1.0, {}, pairs)
        assert pairs == {}

    def test_format1_through_full_path(self):
        reverse_cmap = {"A": 65, "V": 86}
        subtable = _make_pairpos_format1(
            [("A", [("V", -80)])],
            coverage_glyphs=["A"],
        )
        gpos_table = _wrap_gpos([subtable])
        font = {"GPOS": SimpleNamespace(table=gpos_table)}
        pairs: dict = {}
        _extract_gpos_kerning(font, 1.0, reverse_cmap, pairs)
        assert pairs[(65, 86)] == -80.0


class TestExtractKerningIntegration:
    """_extract_kerning: legacy kern + GPOS fallback."""

    def test_kern_table_values_take_precedence(self):
        """When both kern and GPOS define the same pair, kern wins."""
        reverse_cmap = {"A": 65, "V": 86}
        subtable = _make_pairpos_format1(
            [("A", [("V", -80)])],
            coverage_glyphs=["A"],
        )
        gpos_table = _wrap_gpos([subtable])

        # Build a minimal mock font with both kern and GPOS
        kern_subtable = SimpleNamespace(
            kernTable={("A", "V"): -50}
        )
        kern_table = SimpleNamespace(kernTables=[kern_subtable])

        cmap = {65: "A", 86: "V"}
        font = {
            "GPOS": SimpleNamespace(table=gpos_table),
            "kern": kern_table,
        }
        font_mock = MagicMock()
        font_mock.__contains__ = lambda self, key: key in font
        font_mock.__getitem__ = lambda self, key: font[key]
        font_mock.getBestCmap.return_value = cmap

        pairs = _extract_kerning(font_mock, 1.0)
        # Legacy kern pair was -50 (not GPOS -80)
        assert pairs[(65, 86)] == -50.0


# -----------------------------------------------------------------------
# Feature 2: Small Caps
# -----------------------------------------------------------------------


class TestSmallCaps:
    """TextRun.small_caps flag and FontMetrics.small_caps_width."""

    def test_textrun_small_caps_default_false(self):
        run = TextRun("hello")
        assert run.small_caps is False

    def test_textrun_small_caps_true(self):
        run = TextRun("hello", small_caps=True)
        assert run.small_caps is True

    def test_small_caps_width_all_lowercase(self):
        m = FontMetrics.base14("Helvetica")
        text = "abc"
        size = 12.0
        sc_size = size * 0.8

        # Manually compute expected width
        expected = 0.0
        for ch in text:
            expected += m.width_of(ord(ch.upper())) * sc_size / 1000.0

        assert m.small_caps_width(text, size) == pytest.approx(expected)

    def test_small_caps_width_all_uppercase(self):
        m = FontMetrics.base14("Helvetica")
        text = "ABC"
        size = 12.0

        # Uppercase stays at full size
        expected = 0.0
        for ch in text:
            expected += m.width_of(ord(ch)) * size / 1000.0

        assert m.small_caps_width(text, size) == pytest.approx(expected)

    def test_small_caps_width_mixed(self):
        m = FontMetrics.base14("Helvetica")
        text = "AbC"
        size = 10.0
        sc_size = size * 0.8

        expected = (
            m.width_of(ord("A")) * size / 1000.0      # uppercase
            + m.width_of(ord("B")) * sc_size / 1000.0  # 'b' -> 'B' at sc_size
            + m.width_of(ord("C")) * size / 1000.0      # uppercase
        )
        assert m.small_caps_width(text, size) == pytest.approx(expected)

    def test_small_caps_width_empty_string(self):
        m = FontMetrics.base14("Helvetica")
        assert m.small_caps_width("", 12.0) == 0.0

    def test_small_caps_width_non_alpha(self):
        """Non-alphabetic characters use full size."""
        m = FontMetrics.base14("Helvetica")
        text = "1.2"
        size = 12.0
        expected = sum(
            m.width_of(ord(ch)) * size / 1000.0 for ch in text
        )
        assert m.small_caps_width(text, size) == pytest.approx(expected)

    def test_small_caps_narrower_than_uppercase(self):
        """Small caps text should be narrower than the same text in full uppercase."""
        m = FontMetrics.base14("Helvetica")
        text = "hello"
        size = 12.0
        sc_width = m.small_caps_width(text, size)
        full_width = m.text_width(text.upper(), size)
        assert sc_width < full_width


# -----------------------------------------------------------------------
# Feature 3: Tighter Interword Spacing and Tracking
# -----------------------------------------------------------------------


@dataclass
class _MockRun:
    """Minimal stand-in for TextRun in build_items tests."""
    text: str


class TestTighterSpacing:
    """Stretch/shrink ratios and the tracking parameter."""

    def _metrics(self):
        return FontMetrics.base14("Helvetica")

    def _metrics_for(self, _run):
        return self._metrics()

    def _size_for(self, _run):
        return 12.0

    def test_justified_stretch_shrink_ratios(self):
        """Justified spacing now uses 0.45 stretch, 0.30 shrink."""
        run = _MockRun(text="hello world")
        items = build_items(
            [run], self._metrics_for, self._size_for, justified=True
        )
        glues = [it for it in items if isinstance(it, Glue) and it.stretch > 0
                 and it.stretch < 1000]
        assert len(glues) >= 1
        g = glues[0]
        m = self._metrics()
        space = m.text_width(" ", 12.0)
        assert g.stretch == pytest.approx(space * 0.45, abs=0.01)
        assert g.shrink == pytest.approx(space * 0.30, abs=0.01)

    def test_ragged_has_no_stretch_shrink(self):
        run = _MockRun(text="hello world")
        items = build_items(
            [run], self._metrics_for, self._size_for, justified=False
        )
        glues = [it for it in items if isinstance(it, Glue) and it.stretch < 1000]
        for g in glues:
            assert g.stretch == 0.0
            assert g.shrink == 0.0

    def test_tracking_increases_box_width(self):
        run = _MockRun(text="Hello")
        items_normal = build_items(
            [run], self._metrics_for, self._size_for, tracking=0.0
        )
        items_tracked = build_items(
            [run], self._metrics_for, self._size_for, tracking=0.5
        )
        boxes_normal = [it for it in items_normal if isinstance(it, Box)]
        boxes_tracked = [it for it in items_tracked if isinstance(it, Box)]
        assert len(boxes_tracked) == len(boxes_normal)
        for bn, bt in zip(boxes_normal, boxes_tracked):
            expected_extra = len(bn.text) * 0.5
            assert bt.width == pytest.approx(bn.width + expected_extra, abs=0.01)

    def test_tracking_zero_matches_no_tracking(self):
        run = _MockRun(text="The quick fox")
        items_none = build_items(
            [run], self._metrics_for, self._size_for
        )
        items_zero = build_items(
            [run], self._metrics_for, self._size_for, tracking=0.0
        )
        widths_none = [it.width for it in items_none if isinstance(it, Box)]
        widths_zero = [it.width for it in items_zero if isinstance(it, Box)]
        assert widths_none == widths_zero

    def test_tracking_negative_shrinks_boxes(self):
        run = _MockRun(text="Hello")
        items_normal = build_items(
            [run], self._metrics_for, self._size_for, tracking=0.0
        )
        items_tight = build_items(
            [run], self._metrics_for, self._size_for, tracking=-0.3
        )
        bn = [it for it in items_normal if isinstance(it, Box)][0]
        bt = [it for it in items_tight if isinstance(it, Box)][0]
        assert bt.width < bn.width

    def test_tracking_with_hyphenation(self):
        """Tracking applies to hyphenated fragments too."""
        run = _MockRun(text="extraordinary")
        # Use a mock hyphenator that always breaks at position 5
        hyph = SimpleNamespace(break_points=lambda w: [5])
        items = build_items(
            [run], self._metrics_for, self._size_for,
            hyphenator=hyph, hyphenate=True, tracking=1.0,
        )
        boxes = [it for it in items if isinstance(it, Box)]
        # "extra" (5 chars) and "ordinary" (8 chars)
        assert len(boxes) == 2
        m = self._metrics()
        for box in boxes:
            base = m.text_width(box.text, 12.0)
            expected = base + len(box.text) * 1.0
            assert box.width == pytest.approx(expected, abs=0.01)
