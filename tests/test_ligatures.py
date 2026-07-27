"""Tests for ligature substitution gated on embedded font glyph coverage."""

from __future__ import annotations

import pytest

from emboss.typography.font_metrics import FontMetrics
from emboss.typography.ligatures import (
    LIGATURE_MAP,
    apply_ligatures,
    available_ligatures,
    ligate,
    supports_ligatures,
)
from emboss.typography.line_breaking import (
    Box,
    Glue,
    INFINITE_PENALTY,
    Penalty,
    build_items,
)

FI = "ﬁ"
FL = "ﬂ"
FF = "ﬀ"
FFI = "ﬃ"
FFL = "ﬄ"

_LIG_ADVANCES = {FI: 780, FL: 790, FF: 760, FFI: 1100, FFL: 1120}


class _Run:
    """Minimal stand-in for a styled text run."""

    def __init__(self, text: str) -> None:
        self.text = text


class _MapHyphenator:
    """Hyphenator returning canned break points per word."""

    def __init__(self, points: dict) -> None:
        self.points = points

    def break_points(self, word: str) -> list:
        return self.points.get(word, [])


def _build_font(path, ligatures: tuple[str, ...]) -> None:
    """Write a minimal deterministic TTF with the requested ligature glyphs."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    letters = "abcdefghijklmnopqrstuvwxyz"
    cmap = {0x20: "space"}
    advances = {".notdef": 500, "space": 250}
    order = [".notdef", "space"]
    for char in letters:
        cmap[ord(char)] = char
        advances[char] = 500
        order.append(char)
    for lig in ligatures:
        name = f"uni{ord(lig):04X}"
        cmap[ord(lig)] = name
        advances[name] = _LIG_ADVANCES[lig]
        order.append(name)

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    pen = TTGlyphPen(None)
    empty = pen.glyph()
    fb.setupGlyf({name: empty for name in order})
    fb.setupHorizontalMetrics({name: (advances[name], 0) for name in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "LigFixture", "styleName": "Regular"})
    fb.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
        sCapHeight=700,
    )
    fb.setupPost()
    fb.save(str(path))


@pytest.fixture(scope="module")
def full_metrics(tmp_path_factory) -> FontMetrics:
    path = tmp_path_factory.mktemp("fonts") / "lig_full.ttf"
    _build_font(path, (FI, FL, FF, FFI, FFL))
    return FontMetrics.from_file(path)


@pytest.fixture(scope="module")
def fi_only_metrics(tmp_path_factory) -> FontMetrics:
    path = tmp_path_factory.mktemp("fonts") / "lig_fi_only.ttf"
    _build_font(path, (FI,))
    return FontMetrics.from_file(path)


@pytest.fixture(scope="module")
def bare_metrics(tmp_path_factory) -> FontMetrics:
    path = tmp_path_factory.mktemp("fonts") / "lig_none.ttf"
    _build_font(path, ())
    return FontMetrics.from_file(path)


class TestApplyLigatures:
    def test_fi(self):
        assert apply_ligatures("find") == f"{FI}nd"

    def test_fl(self):
        assert apply_ligatures("flow") == f"{FL}ow"

    def test_ffi(self):
        assert apply_ligatures("office") == f"o{FFI}ce"

    def test_ffl(self):
        assert apply_ligatures("waffle") == f"wa{FFL}e"

    def test_ff(self):
        assert apply_ligatures("offset") == f"o{FF}set"

    def test_ffi_beats_ff_and_fi(self):
        result = apply_ligatures("office")
        assert FF not in result and FI not in result
        assert FFI in result

    def test_ffl_beats_ff_and_fl(self):
        result = apply_ligatures("waffle")
        assert FF not in result and FL not in result
        assert FFL in result

    def test_no_ligation_across_hyphen(self):
        assert apply_ligatures("f-i") == "f-i"
        assert apply_ligatures("f-l") == "f-l"

    def test_no_ligation_across_underscore(self):
        assert apply_ligatures("f_i") == "f_i"
        assert apply_ligatures("f_lag") == "f_lag"

    def test_ligation_within_hyphenated_segments(self):
        assert apply_ligatures("off-fire") == f"o{FF}-{FI}re"

    def test_idempotent(self):
        once = apply_ligatures("final office waffle offset flow")
        assert apply_ligatures(once) == once

    def test_no_change_without_sequences(self):
        assert apply_ligatures("hello world") == "hello world"

    def test_font_supports_filter(self):
        result = apply_ligatures("find flow", font_supports=lambda g: g == FI)
        assert result == f"{FI}nd flow"

    def test_map_contents(self):
        assert LIGATURE_MAP == {
            "ffi": FFI,
            "ffl": FFL,
            "ff": FF,
            "fi": FI,
            "fl": FL,
        }

    def test_ligate_with_no_pairs_is_identity(self):
        assert ligate("final", ()) == "final"


class TestSupportGate:
    def test_base14_has_no_ligatures(self):
        metrics = FontMetrics.base14("Times-Roman")
        assert supports_ligatures(metrics) is False
        assert available_ligatures(metrics) == ()

    def test_all_base14_faces_unsupported(self):
        for name in ("Helvetica", "Times-Bold", "Courier", "Symbol"):
            assert supports_ligatures(FontMetrics.base14(name)) is False

    def test_embedded_with_glyphs_supported(self, full_metrics):
        assert supports_ligatures(full_metrics) is True
        sequences = [seq for seq, _ in available_ligatures(full_metrics)]
        assert sequences == ["ffi", "ffl", "ff", "fi", "fl"]

    def test_embedded_without_glyphs_unsupported(self, bare_metrics):
        assert supports_ligatures(bare_metrics) is False
        assert available_ligatures(bare_metrics) == ()

    def test_partial_support_exposes_only_fi(self, fi_only_metrics):
        assert supports_ligatures(fi_only_metrics) is False
        assert available_ligatures(fi_only_metrics) == (("fi", FI),)

    def test_available_ligatures_cached(self, full_metrics):
        assert available_ligatures(full_metrics) is available_ligatures(full_metrics)


def _expected_plain_items(text: str, metrics, size: float) -> list:
    """Manually built item list for a single unhyphenated, unligated run."""
    items: list = []
    space_width = metrics.text_width(" ", size)
    for i, word in enumerate(text.split(" ")):
        if i:
            items.append(Glue(width=space_width))
        items.append(
            Box(
                width=metrics.text_width(word, size),
                text=word,
                char_widths=tuple(metrics.text_width(char, size) for char in word),
            )
        )
    items.append(Glue(width=0.0, stretch=INFINITE_PENALTY, shrink=0.0))
    items.append(Penalty(penalty=-INFINITE_PENALTY))
    return items


class TestBuildItems:
    def test_base14_items_unchanged(self):
        metrics = FontMetrics.base14("Times-Roman")
        text = "find the final offset waffle flows"
        items = build_items(
            [_Run(text)], lambda r: metrics, lambda r: 11.0, justified=False
        )
        assert items == _expected_plain_items(text, metrics, 11.0)
        for item in items:
            if isinstance(item, Box):
                assert FI not in item.text and FL not in item.text

    def test_embedded_boxes_are_ligated(self, full_metrics):
        items = build_items(
            [_Run("final flow office waffle")],
            lambda r: full_metrics,
            lambda r: 10.0,
        )
        boxes = [it for it in items if isinstance(it, Box)]
        assert [b.text for b in boxes] == [
            f"{FI}nal",
            f"{FL}ow",
            f"o{FFI}ce",
            f"wa{FFL}e",
        ]

    def test_ligated_widths_use_ligature_advances(self, full_metrics):
        size = 10.0
        items = build_items([_Run("final")], lambda r: full_metrics, lambda r: size)
        box = next(it for it in items if isinstance(it, Box))
        assert box.width == pytest.approx((780 + 3 * 500) * size / 1000.0)
        assert box.char_widths == tuple(
            full_metrics.text_width(char, size) for char in f"{FI}nal"
        )
        assert len(box.char_widths) == 4

    def test_partial_support_ligates_only_fi(self, fi_only_metrics):
        items = build_items(
            [_Run("final flow office")],
            lambda r: fi_only_metrics,
            lambda r: 10.0,
        )
        boxes = [b.text for b in items if isinstance(b, Box)]
        assert boxes == [f"{FI}nal", "flow", f"of{FI}ce"]

    def test_embedded_without_glyphs_unchanged(self, bare_metrics):
        text = "final flow office"
        items = build_items([_Run(text)], lambda r: bare_metrics, lambda r: 10.0)
        assert items == _expected_plain_items(text, bare_metrics, 10.0)

    def test_ligation_applies_per_hyphenation_fragment(self, full_metrics):
        hyphenator = _MapHyphenator({"offices": [3]})
        items = build_items(
            [_Run("offices")],
            lambda r: full_metrics,
            lambda r: 10.0,
            hyphenator=hyphenator,
            hyphenate=True,
        )
        boxes = [b.text for b in items if isinstance(b, Box)]
        assert boxes == [f"o{FF}", "ices"]

    def test_break_inside_ligature_stays_unligated(self, full_metrics):
        hyphenator = _MapHyphenator({"fluffy": [1]})
        items = build_items(
            [_Run("fluffy")],
            lambda r: full_metrics,
            lambda r: 10.0,
            hyphenator=hyphenator,
            hyphenate=True,
        )
        boxes = [b.text for b in items if isinstance(b, Box)]
        assert boxes == ["f", f"lu{FF}y"]

    def test_deterministic(self, full_metrics):
        args = (
            [_Run("final flow office waffle offset")],
            lambda r: full_metrics,
            lambda r: 12.0,
        )
        assert build_items(*args) == build_items(*args)
