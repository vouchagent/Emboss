"""Tests for advanced GPOS kerning: Extension lookups, Value2, lazy Format 2.

Covers three upgrades to _extract_gpos_kerning:
  1. Extension lookups (LookupType 9) are unwrapped to inner PairPos
  2. Value2.XAdvance is summed with Value1.XAdvance
  3. Format 2 class kerning is stored lazily and memoized on demand
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.typography.font_metrics import (  # noqa: E402
    FontMetrics,
    _ClassKernTable,
    _extract_gpos_kerning,
    _gpos_format1,
    _pair_adjustment,
)

# -----------------------------------------------------------------------
# Helpers -- synthetic GPOS object graphs (mimic the fontTools API)
# -----------------------------------------------------------------------


def _value(x_advance):
    return SimpleNamespace(XAdvance=x_advance)


def _make_format1(glyph_pairs, coverage_glyphs):
    """Build a fake PairPos Format 1 subtable from (first, seconds) pairs."""
    subtable = SimpleNamespace(Format=1)
    pairsets = []
    for _first, seconds in glyph_pairs:
        pvrs = [
            SimpleNamespace(SecondGlyph=g, Value1=_value(adv), Value2=None)
            for g, adv in seconds
        ]
        pairsets.append(SimpleNamespace(PairValueRecord=pvrs))
    subtable.PairSet = pairsets
    subtable.Coverage = SimpleNamespace(glyphs=coverage_glyphs)
    return subtable


def _make_format2(class1_defs, class2_defs, records, coverage_glyphs):
    """Build a fake PairPos Format 2 subtable from a class value matrix."""
    subtable = SimpleNamespace(Format=2)
    subtable.ClassDef1 = SimpleNamespace(classDefs=class1_defs)
    subtable.ClassDef2 = SimpleNamespace(classDefs=class2_defs)
    subtable.Coverage = SimpleNamespace(glyphs=coverage_glyphs)
    subtable.Class1Record = [
        SimpleNamespace(
            Class2Record=[
                SimpleNamespace(Value1=_value(adv) if adv else None, Value2=None)
                for adv in row
            ]
        )
        for row in records
    ]
    return subtable


def _gpos_font(lookups):
    """Wrap lookups in a fake font exposing only a GPOS table."""
    feature = SimpleNamespace(
        FeatureTag="kern",
        Feature=SimpleNamespace(LookupListIndex=list(range(len(lookups)))),
    )
    table = SimpleNamespace(
        FeatureList=SimpleNamespace(FeatureRecord=[feature]),
        LookupList=SimpleNamespace(Lookup=lookups),
    )
    return {"GPOS": SimpleNamespace(table=table)}


def _ext_lookup(subtables, ext_type=2):
    """Wrap PairPos subtables in a fake Extension (type 9) lookup."""
    wrapped = [
        SimpleNamespace(Format=1, ExtensionLookupType=ext_type, ExtSubTable=st)
        for st in subtables
    ]
    return SimpleNamespace(LookupType=9, SubTable=wrapped)


def _metrics_with(pairs, tables, codepoints=()):
    """Build embedded FontMetrics carrying the given kerning state."""
    return FontMetrics(
        name="Fake",
        ascender=800.0,
        descender=-200.0,
        cap_height=700.0,
        flags=32,
        is_embedded=True,
        _widths={cp: 600.0 for cp in codepoints},
        _kerning=pairs,
        _class_kerning=tables,
    )


class _CountingTable:
    """Wraps a _ClassKernTable and counts lookup() calls."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def lookup(self, left, right):
        self.calls += 1
        return self.inner.lookup(left, right)


# -----------------------------------------------------------------------
# Helpers -- real fonts built with fontTools fontBuilder + feaLib
# -----------------------------------------------------------------------

_CMAP = {65: "A", 84: "T", 86: "V", 87: "W", 111: "o"}


def _build_font(tmp_path, fea):
    """Build a minimal real TTF with the given feature code."""
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    order = [".notdef"] + sorted(set(_CMAP.values()))
    fb = FontBuilder(unitsPerEm=1000)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(_CMAP)
    fb.setupGlyf({g: TTGlyphPen(None).glyph() for g in order})
    fb.setupHorizontalMetrics({g: (600, 0) for g in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable(
        {
            "familyName": "KernTest",
            "styleName": "Regular",
            "psName": "KernTest-Regular",
        }
    )
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sCapHeight=700)
    fb.setupPost()
    addOpenTypeFeaturesFromString(fb.font, fea)
    path = tmp_path / "kerntest.ttf"
    fb.save(str(path))
    return path


_FEA_EXTENSION = """
languagesystem DFLT dflt;
lookup kx useExtension {
    pos A V -80;
} kx;
feature kern {
    lookup kx;
} kern;
"""

_FEA_VALUE2 = """
languagesystem DFLT dflt;
feature kern {
    pos T <0 0 -60 0> o <0 0 -20 0>;
} kern;
"""

_FEA_CLASS = """
languagesystem DFLT dflt;
feature kern {
    pos [A T] [V W] -70;
} kern;
"""


# -----------------------------------------------------------------------
# Value1 + Value2 summing
# -----------------------------------------------------------------------


class TestPairAdjustment:
    def test_sums_value1_and_value2(self):
        rec = SimpleNamespace(Value1=_value(-60), Value2=_value(-20))
        assert _pair_adjustment(rec, 1.0) == -80.0

    def test_value2_only(self):
        rec = SimpleNamespace(Value1=None, Value2=_value(-20))
        assert _pair_adjustment(rec, 1.0) == -20.0

    def test_missing_xadvance_attributes(self):
        rec = SimpleNamespace(Value1=SimpleNamespace(), Value2=None)
        assert _pair_adjustment(rec, 1.0) == 0.0

    def test_scale_applied(self):
        rec = SimpleNamespace(Value1=_value(-100), Value2=_value(-100))
        assert _pair_adjustment(rec, 0.5) == -100.0

    def test_format1_sums_both_values(self):
        subtable = _make_format1([("A", [("V", -60)])], ["A"])
        subtable.PairSet[0].PairValueRecord[0].Value2 = _value(-20)
        pairs: dict = {}
        _gpos_format1(subtable, {"A": 65, "V": 86}, 1.0, pairs)
        assert pairs[(65, 86)] == -80.0

    def test_value2_real_font(self, tmp_path):
        metrics = FontMetrics.from_file(_build_font(tmp_path, _FEA_VALUE2))
        assert metrics.kern(84, 111) == -80.0  # T/o: -60 + -20
        assert metrics._kerning[(84, 111)] == -80.0


# -----------------------------------------------------------------------
# Extension lookup (LookupType 9) unwrapping
# -----------------------------------------------------------------------


class TestExtensionUnwrap:
    def test_extension_wrapped_format1(self):
        subtable = _make_format1([("A", [("V", -80)])], ["A"])
        font = _gpos_font([_ext_lookup([subtable])])
        pairs: dict = {}
        _extract_gpos_kerning(font, 1.0, {"A": 65, "V": 86}, pairs)
        assert pairs[(65, 86)] == -80.0

    def test_extension_wrapped_format2_is_lazy(self):
        subtable = _make_format2({"T": 1}, {"o": 1}, [[0, 0], [0, -90]], ["T"])
        font = _gpos_font([_ext_lookup([subtable])])
        pairs: dict = {}
        tables = _extract_gpos_kerning(font, 1.0, {"T": 84, "o": 111}, pairs)
        assert pairs == {}
        assert len(tables) == 1
        assert tables[0].lookup(84, 111) == -90.0

    def test_non_pair_extension_skipped(self):
        subtable = _make_format1([("A", [("V", -80)])], ["A"])
        font = _gpos_font([_ext_lookup([subtable], ext_type=4)])
        pairs: dict = {}
        tables = _extract_gpos_kerning(font, 1.0, {"A": 65, "V": 86}, pairs)
        assert pairs == {}
        assert tables == []

    def test_non_pair_direct_lookup_skipped(self):
        lookup = SimpleNamespace(LookupType=4, SubTable=[SimpleNamespace(Format=1)])
        pairs: dict = {}
        tables = _extract_gpos_kerning(_gpos_font([lookup]), 1.0, {}, pairs)
        assert pairs == {}
        assert tables == []

    def test_extension_real_font(self, tmp_path):
        from fontTools.ttLib import TTFont

        path = _build_font(tmp_path, _FEA_EXTENSION)
        font = TTFont(str(path))
        try:
            lookup_types = [
                lk.LookupType for lk in font["GPOS"].table.LookupList.Lookup
            ]
        finally:
            font.close()
        assert 9 in lookup_types  # fixture really uses an Extension lookup
        metrics = FontMetrics.from_file(path)
        assert metrics.kern(65, 86) == -80.0  # A/V through the wrapper
        assert metrics._kerning[(65, 86)] == -80.0


# -----------------------------------------------------------------------
# Lazy Format 2 class kerning
# -----------------------------------------------------------------------


def _big_format2(num_glyphs=500, num_classes=50, value=-55):
    """Fake Format 2 spanning num_glyphs glyphs and a full class matrix."""
    glyphs = [f"g{i}" for i in range(num_glyphs)]
    reverse_cmap = {g: 0x4E00 + i for i, g in enumerate(glyphs)}
    class_defs = {g: (i % num_classes) for i, g in enumerate(glyphs)}
    records = [
        [(value if (c1 or c2) else 0) for c2 in range(num_classes)]
        for c1 in range(num_classes)
    ]
    subtable = _make_format2(class_defs, dict(class_defs), records, glyphs)
    return subtable, reverse_cmap


class TestLazyFormat2:
    def test_extraction_does_not_expand_pairs(self):
        """500 glyphs x 50x50 classes must not become ~glyphs^2 pairs."""
        subtable, reverse_cmap = _big_format2()
        lookup = SimpleNamespace(LookupType=2, SubTable=[subtable])
        pairs: dict = {}
        tables = _extract_gpos_kerning(_gpos_font([lookup]), 1.0, reverse_cmap, pairs)
        assert len(tables) == 1
        assert len(pairs) < 100  # eager expansion would produce ~250,000
        assert pairs == {}

    def test_lazy_resolution_and_memoization_bounds(self):
        subtable, reverse_cmap = _big_format2()
        lookup = SimpleNamespace(LookupType=2, SubTable=[subtable])
        pairs: dict = {}
        tables = _extract_gpos_kerning(_gpos_font([lookup]), 1.0, reverse_cmap, pairs)
        metrics = _metrics_with(pairs, tables, reverse_cmap.values())
        assert len(metrics._class_kern_memo) == 0  # nothing resolved yet
        assert metrics.kern(0x4E01, 0x4E02) == -55.0  # class 1 x class 2
        assert metrics.kern(0x4E00, 0x4E00) == 0.0  # class 0 x class 0
        assert len(metrics._class_kern_memo) == 2  # only what was asked

    def test_memoization_hits_table_once(self):
        subtable = _make_format2({"T": 1}, {"o": 1}, [[0, 0], [0, -90]], ["T"])
        table = _ClassKernTable.from_subtable(subtable, {"T": 84, "o": 111}, 1.0)
        counting = _CountingTable(table)
        metrics = _metrics_with({}, [counting], (84, 111))
        assert metrics.kern(84, 111) == -90.0
        assert metrics.kern(84, 111) == -90.0
        assert counting.calls == 1  # second call served from the memo

    def test_uncovered_left_glyph_returns_zero(self):
        subtable = _make_format2({"T": 1}, {"o": 1}, [[0, 0], [0, -90]], ["T"])
        table = _ClassKernTable.from_subtable(
            subtable, {"T": 84, "o": 111, "x": 120}, 1.0
        )
        metrics = _metrics_with({}, [table], (84, 111, 120))
        assert table.lookup(120, 111) is None  # "x" not in coverage
        assert metrics.kern(120, 111) == 0.0
        assert metrics.kern_pairs("xo") == []

    def test_class_kerning_real_font(self, tmp_path):
        metrics = FontMetrics.from_file(_build_font(tmp_path, _FEA_CLASS))
        assert metrics._kerning == {}  # nothing eagerly expanded
        assert len(metrics._class_kerning) == 1
        assert metrics.kern(65, 86) == -70.0  # A/V
        assert metrics.kern(84, 87) == -70.0  # T/W
        assert metrics.kern(84, 111) == 0.0  # T/o not in right class
        assert (65, 86) in metrics._class_kern_memo  # memoized

    def test_kern_pairs_resolves_class_kerning(self, tmp_path):
        metrics = FontMetrics.from_file(_build_font(tmp_path, _FEA_CLASS))
        assert metrics.kern_pairs("AV") == [(1, -70.0)]
        assert metrics.kern_pairs("Ao") == []

    def test_text_width_includes_class_kerning(self, tmp_path):
        metrics = FontMetrics.from_file(_build_font(tmp_path, _FEA_CLASS))
        base = metrics.width_of(65) + metrics.width_of(86)
        expected = (base - 70.0) * 12.0 / 1000.0
        assert metrics.text_width("AV", 12.0) == pytest.approx(expected)
        # Cached second call must agree with the first.
        assert metrics.text_width("AV", 12.0) == pytest.approx(expected)
        unkerned = base * 12.0 / 1000.0
        assert metrics.text_width("AV", 12.0, kerning=False) == pytest.approx(unkerned)

    def test_explicit_pairs_beat_class_fallback(self):
        subtable = _make_format2({"T": 1}, {"o": 1}, [[0, 0], [0, -90]], ["T"])
        table = _ClassKernTable.from_subtable(subtable, {"T": 84, "o": 111}, 1.0)
        metrics = _metrics_with({(84, 111): -40.0}, [table], (84, 111))
        assert metrics.kern(84, 111) == -40.0

    def test_deterministic_across_loads(self, tmp_path):
        m1 = FontMetrics.from_file(_build_font(tmp_path, _FEA_CLASS))
        m2 = FontMetrics.from_file(_build_font(tmp_path, _FEA_CLASS))
        samples = [(a, b) for a in _CMAP for b in _CMAP]
        assert [m1.kern(a, b) for a, b in samples] == [
            m2.kern(a, b) for a, b in samples
        ]
        assert m1._kerning == m2._kerning
