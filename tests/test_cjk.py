"""Tests for CJK (Chinese/Japanese/Korean) text support.

Covers the CJK-aware line-breaking rule in isolation (no font required),
CID glyph subsetting at scale using a synthetic large-glyph-count font (no
font required), and full render/extract/wrap/determinism behavior with a
real CJK-capable font, gated on availability.

Out of scope, by design: RTL scripts (Arabic, Hebrew), complex script
shaping (Indic reordering/ligatures), full kinsoku shori (Japanese
line-break punctuation restrictions), and vertical writing mode. These are
not attempted here and are not silently assumed to work.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from emboss import Document, Paragraph, Style, TableCell, TextRun
from emboss.pdf.fonts import (
    _build_cid_set,
    _build_cid_widths,
    _program_advances,
    _subset_font,
)
from emboss.spec import Table
from emboss.typography.font_metrics import FontMetrics
from emboss.typography.line_breaking import (
    Box,
    Glue,
    LineBreaker,
    Penalty,
    build_items,
    is_cjk_codepoint,
    split_cjk_runs,
)
from emboss.writer import render_document

# ===========================================================================
# Real CJK font discovery
# ===========================================================================

_SYSTEM_FONT_CANDIDATES = (
    # macOS
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux (common Noto CJK install paths)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
)


def _find_cjk_font() -> str | None:
    """`EMBOSS_CJK_FONT_PATH` first, else a probe of common system paths."""
    env_path = os.environ.get("EMBOSS_CJK_FONT_PATH")
    if env_path and Path(env_path).is_file():
        return env_path
    for candidate in _SYSTEM_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


_CJK_FONT_PATH = _find_cjk_font()

requires_cjk_font = pytest.mark.skipif(
    _CJK_FONT_PATH is None,
    reason=(
        "no CJK-capable font found: set EMBOSS_CJK_FONT_PATH to a TTF/OTF "
        "with CJK glyph coverage (e.g. Noto Sans CJK); no bundled system "
        "font was found either at the common macOS/Linux locations checked"
    ),
)

# Text samples verified (see module docstring context) to lie within the
# glyph coverage of every font this probe currently resolves to on macOS
# (AppleSDGothicNeo, Hiragino Sans GB, STHeiti). A caller-supplied
# EMBOSS_CJK_FONT_PATH is checked for coverage before use; tests skip with
# a clear reason rather than fail on missing glyphs in an unknown font.
JAPANESE_TEXT = "日本語のテスト"
CHINESE_TEXT = "中文世界"
KOREAN_TEXT = "안녕하세요"
ALL_CJK_CHARS = JAPANESE_TEXT + CHINESE_TEXT + KOREAN_TEXT


def _register_cjk_family(doc: Document, family: str = "cjk") -> None:
    """Register the discovered font for every bold/italic combination.

    A `Heading`'s runs are always bold, so a family used for headings must
    be registered for `bold=True` too or it silently falls back to the
    base-14 font (a caller-usage detail, not a library defect).
    """
    for bold in (False, True):
        for italic in (False, True):
            doc.fonts.register(family, _CJK_FONT_PATH, bold=bold, italic=italic)


def _font_covers(path: str, text: str) -> bool:
    metrics = FontMetrics.from_file(path)
    return all(metrics.supports(ch) for ch in text if not ch.isspace())


def _skip_unless_covered() -> None:
    if _CJK_FONT_PATH is not None and not _font_covers(_CJK_FONT_PATH, ALL_CJK_CHARS):
        pytest.skip(
            f"discovered font {_CJK_FONT_PATH!r} does not cover the test "
            "CJK sample text; set EMBOSS_CJK_FONT_PATH to a font with "
            "broader CJK coverage (e.g. Noto Sans CJK)"
        )


# ===========================================================================
# Codepoint-range and tokenizer logic (no font required)
# ===========================================================================


class TestIsCjkCodepoint:
    def test_cjk_unified_ideographs_range(self):
        assert is_cjk_codepoint(0x4E00) is True
        assert is_cjk_codepoint(0x9FFF) is True
        assert is_cjk_codepoint(0x4E2D) is True  # 中
        assert is_cjk_codepoint(0x2FFF) is False
        assert is_cjk_codepoint(0xA000) is False

    def test_extension_a_range(self):
        assert is_cjk_codepoint(0x3400) is True
        assert is_cjk_codepoint(0x4DBF) is True
        assert is_cjk_codepoint(0x33FF) is False
        assert is_cjk_codepoint(0x4DC0) is False

    def test_hiragana_range(self):
        assert is_cjk_codepoint(0x3040) is True
        assert is_cjk_codepoint(0x309F) is True
        assert is_cjk_codepoint(0x306E) is True  # の
        assert is_cjk_codepoint(0x303F) is False
        assert is_cjk_codepoint(0x30A0) is True  # katakana starts here, not hiragana

    def test_katakana_range(self):
        assert is_cjk_codepoint(0x30A0) is True
        assert is_cjk_codepoint(0x30FF) is True
        assert is_cjk_codepoint(0x30C6) is True  # テ
        assert is_cjk_codepoint(0x3100) is False

    def test_hangul_syllables_range(self):
        assert is_cjk_codepoint(0xAC00) is True
        assert is_cjk_codepoint(0xD7A3) is True
        assert is_cjk_codepoint(0xC548) is True  # 안
        assert is_cjk_codepoint(0xABFF) is False
        assert is_cjk_codepoint(0xD7A4) is False

    def test_latin_and_ascii_are_not_cjk(self):
        for ch in "Hello, World! 123":
            assert is_cjk_codepoint(ord(ch)) is False

    def test_arabic_is_not_cjk(self):
        # Arabic/Hebrew shaping is explicitly out of scope; confirm this
        # rule does not accidentally treat them as breakable-anywhere CJK.
        assert is_cjk_codepoint(ord("م")) is False


class TestSplitCjkRuns:
    def test_empty_string(self):
        assert split_cjk_runs("") == []

    def test_pure_latin_is_one_piece(self):
        assert split_cjk_runs("hello") == ["hello"]

    def test_pure_cjk_isolates_every_character(self):
        assert split_cjk_runs(JAPANESE_TEXT) == list(JAPANESE_TEXT)

    def test_mixed_latin_and_cjk(self):
        assert split_cjk_runs("abc日def語ghi") == [
            "abc",
            "日",
            "def",
            "語",
            "ghi",
        ]

    def test_cjk_adjacent_to_cjk_from_different_ranges(self):
        # Hangul next to a Hiragana character: both isolated independently.
        assert split_cjk_runs("안녕のあ") == ["안", "녕", "の", "あ"]

    def test_rejoining_pieces_recovers_original_text(self):
        for text in ("plain latin", "日本語のテスト", "mix日ed текст"):
            assert "".join(split_cjk_runs(text)) == text


class _FlatMetrics:
    """Fixed-advance fake metrics: every character is 10 units wide."""

    def text_width(self, text: str, size: float) -> float:
        return 10.0 * len(text) * (size / 10.0)

    def kern_pairs(self, text: str) -> list:
        return []


class _Run:
    """Minimal stand-in for a styled text run."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.font_family = None


def _build(text: str, size: float = 10.0, **kw) -> list:
    metrics = _FlatMetrics()
    run = _Run(text)
    return build_items(
        [run], metrics_for=lambda r: metrics, size_for=lambda r: size, **kw
    )


class TestBuildItemsCjkBreaks:
    def test_pure_latin_token_is_a_single_box_unaffected(self):
        """A plain word with no CJK characters must produce exactly the
        same item shape as before: one Box, no `soft` Penalty at all."""
        items = _build("hello")
        boxes = [it for it in items if isinstance(it, Box)]
        soft_penalties = [it for it in items if isinstance(it, Penalty) and it.soft]
        assert [b.text for b in boxes] == ["hello"]
        assert soft_penalties == []

    def test_cjk_token_produces_one_box_per_character(self):
        items = _build(JAPANESE_TEXT)
        boxes = [it for it in items if isinstance(it, Box)]
        assert [b.text for b in boxes] == list(JAPANESE_TEXT)

    def test_cjk_characters_joined_by_soft_zero_cost_penalties(self):
        items = _build("日本")
        # Box('日'), Penalty(soft), Box('本'), <terminator glue>, <terminator penalty>
        assert isinstance(items[0], Box) and items[0].text == "日"
        assert isinstance(items[1], Penalty)
        assert items[1].soft is True
        assert items[1].penalty == 0.0
        assert items[1].width == 0.0
        assert items[1].flagged is False
        assert isinstance(items[2], Box) and items[2].text == "本"

    def test_soft_penalty_is_a_legal_break_point(self):
        items = _build(JAPANESE_TEXT)
        soft = next(it for it in items if isinstance(it, Penalty) and it.soft)
        from emboss.typography.line_breaking import INFINITE_PENALTY

        assert soft.penalty < INFINITE_PENALTY

    def test_mixed_token_breaks_only_around_cjk_characters(self):
        items = _build("ABC日本DEF")
        boxes = [it.text for it in items if isinstance(it, Box)]
        assert boxes == ["ABC", "日", "本", "DEF"]

    def test_two_tokens_still_joined_by_real_glue(self):
        """CJK text separated by an actual space still gets a real Glue,
        not a soft Penalty, between the two tokens."""
        items = _build(f"{JAPANESE_TEXT} {CHINESE_TEXT}")
        # Find the boundary between the last char of JAPANESE_TEXT's boxes
        # and the first of CHINESE_TEXT's: it must be a Glue with nonzero
        # (space) width, not a soft Penalty.
        glues = [it for it in items if isinstance(it, Glue) and it.width > 0]
        assert len(glues) == 1


class TestLineBreakerCjkWrapping:
    """Line-wrapping behavior using fake fixed-width metrics, so this needs
    no real font: proves the Knuth-Plass breaker actually uses the new
    soft-Penalty break points to wrap CJK text instead of overflowing."""

    def test_long_cjk_text_wraps_into_multiple_lines(self):
        text = JAPANESE_TEXT * 20  # 140 characters, no spaces at all
        items = _build(text)
        # Each character is 10pt wide at size 10; a 60pt line width fits 6.
        lines = LineBreaker().break_paragraph(items, 60.0)
        assert len(lines) > 1
        for line in lines:
            assert line.width <= 60.0 + 1e-6

    def test_wrapped_lines_reconstruct_the_original_text(self):
        text = JAPANESE_TEXT * 10
        items = _build(text)
        lines = LineBreaker().break_paragraph(items, 60.0)
        assert len(lines) > 1
        reconstructed = "".join(line.text for line in lines)
        assert reconstructed == text

    def test_single_short_cjk_token_stays_one_line(self):
        items = _build(JAPANESE_TEXT)
        lines = LineBreaker().break_paragraph(items, 1000.0)
        assert len(lines) == 1
        assert lines[0].text == JAPANESE_TEXT


class TestLatinRegressionUnaffected:
    """Pins line-breaking output for a fixed Latin fixture so the CJK
    addition is provably a no-op for text with no CJK characters."""

    FIXTURE_TEXT = (
        "The quick brown fox jumps over the lazy dog while the "
        "committee reviewed every clause of the contract before "
        "the filing deadline passed quietly into the archive."
    )

    def test_fixed_paragraph_line_count_unchanged(self):
        metrics = FontMetrics.base14("Helvetica")
        run = _Run(self.FIXTURE_TEXT)
        items = build_items(
            [run], metrics_for=lambda r: metrics, size_for=lambda r: 12.0
        )
        lines = LineBreaker().break_paragraph(items, 200.0)
        assert len(lines) == 5
        assert [line.text for line in lines] == [
            "The quick brown fox jumps over the",
            "lazy dog while the committee",
            "reviewed every clause of the contract",
            "before the filing deadline passed",
            "quietly into the archive.",
        ]

    def test_no_soft_penalties_appear_for_latin_only_text(self):
        metrics = FontMetrics.base14("Helvetica")
        run = _Run(self.FIXTURE_TEXT)
        items = build_items(
            [run], metrics_for=lambda r: metrics, size_for=lambda r: 12.0
        )
        assert not any(isinstance(it, Penalty) and it.soft for it in items)


# ===========================================================================
# CID glyph embedding at scale (synthetic large-glyph-count font, no real
# CJK font required)
# ===========================================================================


def _build_large_synthetic_font(path: Path, glyph_count: int, base_cp: int) -> None:
    """Build a valid TrueType font with `glyph_count` CJK-mapped glyphs.

    Outlines are simple rectangles, not real character shapes: this proves
    the subsetting/CID-embedding *mechanics* scale to thousands of glyphs
    without depending on a real CJK font being installed.
    """
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    glyph_chars = {base_cp + i: f"g{i}" for i in range(glyph_count)}
    glyph_names = [".notdef"] + list(glyph_chars.values())

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(glyph_names)
    fb.setupCharacterMap(glyph_chars)

    glyphs = {}
    metrics = {}

    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 700))
    pen.lineTo((0, 700))
    pen.closePath()
    glyphs[".notdef"] = pen.glyph()
    metrics[".notdef"] = (500, 0)

    for cp, name in glyph_chars.items():
        pen = TTGlyphPen(None)
        width = 500 + (cp % 200)
        pen.moveTo((0, 0))
        pen.lineTo((width, 0))
        pen.lineTo((width, 700))
        pen.lineTo((0, 700))
        pen.closePath()
        glyphs[name] = pen.glyph()
        metrics[name] = (width, 0)

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "BigCjkTest", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sCapHeight=700)
    fb.setupPost()
    fb.font.save(str(path))


class TestCidEmbeddingAtScale:
    """Verifies the CIDFontType2 subsetting path with a large glyph count.

    Uses a synthetic 2000-glyph font (codepoints from the CJK Unified
    Ideographs block) rather than a real CJK font, so this always runs
    regardless of environment: it is testing the subsetting *mechanics*
    (does /W cover exactly the retained glyphs, is CIDSet sized correctly)
    at CJK scale, not glyph shape fidelity.
    """

    GLYPH_COUNT = 2000
    BASE_CODEPOINT = 0x4E00  # start of CJK Unified Ideographs

    @pytest.fixture
    def big_font_path(self, tmp_path) -> Path:
        path = tmp_path / "big_cjk_test.ttf"
        _build_large_synthetic_font(path, self.GLYPH_COUNT, self.BASE_CODEPOINT)
        return path

    def test_subsetting_reduces_glyph_count_for_sparse_usage(self, big_font_path):
        """Using only the first 30 of 2000 glyphs must shrink the subset
        dramatically, proving real subsetting occurred (not just
        repackaging the entire original font)."""
        metrics = FontMetrics.from_file(big_font_path)
        used_text = "".join(chr(self.BASE_CODEPOINT + i) for i in range(30))
        metrics.note_usage(used_text)

        data, codepoints = _subset_font(metrics)
        assert len(codepoints) == 30
        assert len(data) > 0

        _upm, advances = _program_advances(data)
        # 30 used glyphs + .notdef; retain_gids truncates trailing unused
        # glyphs, so the subset must be far smaller than the original
        # 2001-glyph font, not merely repackaged whole.
        assert len(advances) == 31
        assert len(advances) < (self.GLYPH_COUNT + 1) * 0.1

    def test_cid_set_size_matches_glyph_count(self, big_font_path):
        metrics = FontMetrics.from_file(big_font_path)
        metrics.note_usage(chr(self.BASE_CODEPOINT))
        data, _codepoints = _subset_font(metrics)
        upm, advances = _program_advances(data)

        cid_set = _build_cid_set(len(advances))
        assert len(cid_set) == math.ceil(len(advances) / 8)
        # Every bit up to num_glyphs-1 is set (all bytes 0xFF except a
        # possibly partial final byte), per PDF/A clause 6.2.11.4.2.
        full_bytes, remainder = divmod(len(advances), 8)
        assert cid_set[:full_bytes] == b"\xff" * full_bytes
        if remainder:
            assert cid_set[full_bytes] == (0xFF << (8 - remainder)) & 0xFF

    def test_cid_widths_cover_every_retained_glyph(self, big_font_path):
        metrics = FontMetrics.from_file(big_font_path)
        used_text = "".join(chr(self.BASE_CODEPOINT + i) for i in range(50))
        metrics.note_usage(used_text)
        data, _codepoints = _subset_font(metrics)
        program_advances = _program_advances(data)
        _upm, advances = program_advances

        w_array = _build_cid_widths(program_advances)
        # Decode the [startGID [w1 w2 ...] ...] structure and confirm every
        # glyph 0..numGlyphs-1 has exactly one width entry.
        covered = set()
        items = w_array.items
        i = 0
        while i < len(items):
            start_gid = items[i]
            widths = items[i + 1]
            for offset in range(len(widths.items)):
                covered.add(start_gid + offset)
            i += 2
        assert covered == set(range(len(advances)))

    def test_large_glyph_count_font_renders_without_error(self, big_font_path):
        """End-to-end: a document using this large synthetic font renders
        successfully and the glyphs are not substituted away."""
        doc = Document(title="Scale test")
        doc.fonts.register("big-cjk", big_font_path)
        text = "".join(chr(self.BASE_CODEPOINT + i) for i in range(20))
        doc.paragraph(TextRun(text, font_family="big-cjk"))
        result = render_document(doc, return_result=True)
        assert result.issues == []
        assert result.page_count == 1


# ===========================================================================
# Full pipeline with a real CJK font (gated on availability)
# ===========================================================================


@requires_cjk_font
class TestCjkFontResolution:
    def setup_method(self):
        _skip_unless_covered()

    def test_registered_family_resolves_no_substitution(self):
        doc = Document(title="CJK resolution test")
        _register_cjk_family(doc)
        doc.paragraph(TextRun(ALL_CJK_CHARS, font_family="cjk"))
        result = render_document(doc, return_result=True)
        assert result.issues == []

    def test_unregistered_family_falls_back_and_substitutes(self):
        """Confirms the baseline failure this whole feature fixes: without
        a registered CJK font, base-14 Helvetica cannot render CJK glyphs
        and the substitution-with-warning path engages."""
        doc = Document(title="No CJK font")
        doc.paragraph(TextRun(JAPANESE_TEXT))
        result = render_document(doc, return_result=True)
        assert len(result.issues) > 0
        assert any("is not renderable" in issue for issue in result.issues)


@requires_cjk_font
class TestCjkTextExtraction:
    """THE KEY PROOF TEST: the exact CJK characters, not substitutes or
    dropped text, come back out of the rendered document's text index."""

    def setup_method(self):
        _skip_unless_covered()

    def test_extracted_text_contains_exact_cjk_characters(self):
        doc = Document(title="CJK extraction test")
        _register_cjk_family(doc)
        source_text = f"{JAPANESE_TEXT} {CHINESE_TEXT} {KOREAN_TEXT}"
        doc.paragraph(TextRun(source_text, font_family="cjk"), id="p1")

        idx = doc.text_index()
        extracted = idx.node_text("p1")

        assert JAPANESE_TEXT in extracted
        assert CHINESE_TEXT in extracted
        assert KOREAN_TEXT in extracted
        assert extracted == source_text

    def test_extraction_survives_line_wrapping(self):
        """The proof test above fits on one line; this variant forces a
        wrap and confirms the CJK characters are not corrupted by phantom
        separators inserted at the wrap boundary (a real bug this fix
        also had to correct in the text-index span recording)."""
        doc = Document(title="CJK wrap extraction test")
        _register_cjk_family(doc)
        long_text = JAPANESE_TEXT * 40
        doc.paragraph(TextRun(long_text, font_family="cjk"), id="p1")

        idx = doc.text_index()
        extracted = idx.node_text("p1")
        assert extracted == long_text


@requires_cjk_font
class TestCjkLineWrapping:
    def setup_method(self):
        _skip_unless_covered()

    def test_long_cjk_paragraph_wraps_across_multiple_lines(self):
        doc = Document(title="CJK wrap test")
        _register_cjk_family(doc)
        long_text = JAPANESE_TEXT * 40
        doc.paragraph(TextRun(long_text, font_family="cjk"), id="p1")

        result = render_document(doc, return_result=True)
        assert result.issues == []

        spans = result.text_index["p1"]
        distinct_lines = {round(s["y0"], 3) for s in spans}
        assert len(distinct_lines) > 1

        content_right = doc.page.width - doc.page.margin_right
        assert max(s["x1"] for s in spans) <= content_right + 1e-6

    def test_short_cjk_paragraph_stays_on_one_line(self):
        doc = Document(title="CJK short test")
        _register_cjk_family(doc)
        doc.paragraph(TextRun(JAPANESE_TEXT, font_family="cjk"), id="p1")

        result = render_document(doc, return_result=True)
        spans = result.text_index["p1"]
        distinct_lines = {round(s["y0"], 3) for s in spans}
        assert len(distinct_lines) == 1


@requires_cjk_font
class TestMixedLatinCjkRun:
    def setup_method(self):
        _skip_unless_covered()

    def test_mixed_latin_and_cjk_in_one_run(self):
        doc = Document(title="Mixed run test")
        _register_cjk_family(doc)
        text = f"Report notes: {JAPANESE_TEXT} summary {CHINESE_TEXT} end"
        doc.paragraph(TextRun(text, font_family="cjk"), id="p1")

        result = render_document(doc, return_result=True)
        assert result.issues == []

        idx = doc.text_index()
        assert idx.node_text("p1") == text

    def test_table_cell_cjk_text_no_substitution(self):
        """Table cells share the same tokenizer/font-resolution path."""
        doc = Document(title="CJK table test")
        _register_cjk_family(doc)
        doc.add(
            Table(
                headers=["Column"],
                rows=[[TableCell(TextRun(CHINESE_TEXT * 8, font_family="cjk"))]],
            )
        )
        result = render_document(doc, return_result=True)
        assert result.issues == []

    def test_heading_cjk_text_no_substitution(self):
        """Headings share the same tokenizer/font-resolution path. A
        Heading's runs are always bold, so the family must be registered
        for bold=True as well (handled by `_register_cjk_family`)."""
        doc = Document(title="CJK heading test")
        _register_cjk_family(doc)
        doc.heading(JAPANESE_TEXT * 6, level=1, style=Style(font_family="cjk"))
        result = render_document(doc, return_result=True)
        assert result.issues == []

    def test_paragraph_helper_with_cjk_text_run(self):
        """Document.paragraph(...) -> Paragraph -> TextRun path, the most
        common call site, carries a registered font_family through."""
        doc = Document(title="CJK paragraph helper test")
        _register_cjk_family(doc)
        doc.paragraph(TextRun(KOREAN_TEXT, font_family="cjk"), id="p1")
        assert isinstance(doc.content[-1], Paragraph)
        result = render_document(doc, return_result=True)
        assert result.issues == []


@requires_cjk_font
class TestCjkDeterminism:
    def setup_method(self):
        _skip_unless_covered()

    def test_double_render_is_byte_identical(self):
        def _build_doc() -> Document:
            doc = Document(title="Determinism test")
            _register_cjk_family(doc)
            doc.paragraph(
                TextRun(
                    f"{JAPANESE_TEXT} {CHINESE_TEXT} {KOREAN_TEXT}",
                    font_family="cjk",
                )
            )
            doc.paragraph(TextRun(JAPANESE_TEXT * 30, font_family="cjk"))
            return doc

        first = render_document(_build_doc())
        second = render_document(_build_doc())
        assert first == second
