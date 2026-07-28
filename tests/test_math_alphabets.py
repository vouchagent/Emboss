"""Tests for real math alphabet glyphs (blackboard, script, fraktur)."""

import re
import zlib
from io import BytesIO
from pathlib import Path

from emboss import Document
from emboss.math_render import (
    MATH_ALPHABETS,
    GroupNode,
    MathLayoutEngine,
    TextNode,
    math_alphabet_node,
    math_font_metrics,
    parse_math,
)

FONT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "emboss"
    / "fonts"
    / "EmbossMath-Regular.ttf"
)


def _decompressed_streams(pdf: bytes) -> list:
    """All flate stream payloads in a PDF, decompressed."""
    out = []
    for match in re.finditer(rb"stream\n(.*?)\nendstream", pdf, re.DOTALL):
        try:
            out.append(zlib.decompress(match.group(1)))
        except zlib.error:
            out.append(match.group(1))
    return out


def _embedded_font_cmaps(pdf: bytes) -> list:
    """Best cmaps of every embedded TrueType font file in a PDF."""
    from fontTools.ttLib import TTFont

    cmaps = []
    for data in _decompressed_streams(pdf):
        if data[:4] == b"\x00\x01\x00\x00":
            font = TTFont(BytesIO(data), lazy=True)
            try:
                cmaps.append(dict(font.getBestCmap()))
            finally:
                font.close()
    return cmaps


class TestMappingTables:
    def test_double_struck_reserved_letterlike(self):
        table = MATH_ALPHABETS["double-struck"]
        assert table["C"] == "ℂ"
        assert table["H"] == "ℍ"
        assert table["N"] == "ℕ"
        assert table["P"] == "ℙ"
        assert table["Q"] == "ℚ"
        assert table["R"] == "ℝ"
        assert table["Z"] == "ℤ"
        assert table["R"] != "\U0001d549"  # the reserved gap is never used

    def test_double_struck_regulars_and_digits(self):
        table = MATH_ALPHABETS["double-struck"]
        assert table["A"] == "\U0001d538"
        assert table["B"] == "\U0001d539"
        assert table["a"] == "\U0001d552"
        assert table["z"] == "\U0001d56b"
        assert table["0"] == "\U0001d7d8"
        assert table["9"] == "\U0001d7e1"
        assert len(table) == 62

    def test_script_reserved_letterlike(self):
        table = MATH_ALPHABETS["script"]
        assert table["B"] == "ℬ"
        assert table["E"] == "ℰ"
        assert table["F"] == "ℱ"
        assert table["H"] == "ℋ"
        assert table["I"] == "ℐ"
        assert table["L"] == "ℒ"
        assert table["M"] == "ℳ"
        assert table["R"] == "ℛ"
        assert table["e"] == "ℯ"
        assert table["g"] == "ℊ"
        assert table["o"] == "ℴ"
        assert table["H"] != "\U0001d4a3"

    def test_script_regulars_no_digits(self):
        table = MATH_ALPHABETS["script"]
        assert table["A"] == "\U0001d49c"
        assert table["a"] == "\U0001d4b6"
        assert "0" not in table
        assert len(table) == 52

    def test_fraktur_reserved_letterlike(self):
        table = MATH_ALPHABETS["fraktur"]
        assert table["C"] == "ℭ"
        assert table["H"] == "ℌ"
        assert table["I"] == "ℑ"
        assert table["R"] == "ℜ"
        assert table["Z"] == "ℨ"

    def test_fraktur_regulars_no_digits(self):
        table = MATH_ALPHABETS["fraktur"]
        assert table["A"] == "\U0001d504"
        assert table["a"] == "\U0001d51e"
        assert table["g"] == "\U0001d524"
        assert "0" not in table
        assert len(table) == 52

    def test_all_mapped_codepoints_have_bundled_glyphs(self):
        metrics = math_font_metrics()
        for table in MATH_ALPHABETS.values():
            for char in table.values():
                assert metrics.supports(char), hex(ord(char))


class TestParsing:
    def test_mathbb_maps_to_real_codepoint(self):
        node = parse_math(r"\mathbb{R}")
        assert isinstance(node, TextNode)
        assert node.text == "ℝ"
        assert node.alpha is True
        assert node.italic is False

    def test_mathcal_and_mathscr_alias(self):
        cal = parse_math(r"\mathcal{L}")
        scr = parse_math(r"\mathscr{L}")
        assert isinstance(cal, TextNode) and cal.text == "ℒ"
        assert cal.alpha is True
        assert scr == cal

    def test_mathfrak_supported(self):
        node = parse_math(r"\mathfrak{g}")
        assert isinstance(node, TextNode)
        assert node.text == "\U0001d524"
        assert node.alpha is True

    def test_multi_char_argument(self):
        node = parse_math(r"\mathbb{NZ}")
        assert isinstance(node, TextNode)
        assert node.text == "ℕℤ"

    def test_unmapped_chars_split_out(self):
        node = math_alphabet_node("H2", "script")
        assert isinstance(node, GroupNode)
        alpha, plain = node.children
        assert alpha.text == "ℋ" and alpha.alpha is True
        assert plain.text == "2" and plain.alpha is False


class TestLayout:
    def test_box_carries_alpha_font_flag_and_real_width(self):
        engine = MathLayoutEngine(base_size=10.0)
        layout = engine.layout(parse_math(r"\mathbb{R}"))
        assert len(layout.boxes) == 1
        box = layout.boxes[0]
        assert box.alpha is True
        assert box.symbol is False
        assert box.text == "ℝ"
        expected = math_font_metrics().text_width("ℝ", 10.0)
        assert abs(layout.width - expected) < 1e-9
        assert abs(layout.width - 0.55 * 10.0) > 0.05  # not the old fake width
        assert abs(layout.width - 0.5 * 10.0) > 0.05  # not a fallback width

    def test_metrics_are_from_bundled_font_file(self):
        metrics = math_font_metrics()
        assert metrics.is_embedded
        assert metrics.name == "EmbossMath-Regular"
        assert metrics.font_path == FONT_PATH

    def test_script_and_fraktur_widths_differ_from_roman(self):
        engine = MathLayoutEngine(base_size=12.0)
        cal = engine.layout(parse_math(r"\mathcal{L}"))
        frak = engine.layout(parse_math(r"\mathfrak{g}"))
        assert cal.boxes[0].alpha and frak.boxes[0].alpha
        assert abs(cal.width - 0.55 * 12.0) > 0.05
        assert abs(frak.width - 0.55 * 12.0) > 0.05


class TestMathML:
    def test_mi_mathvariant_double_struck(self):
        node = parse_math(
            '<math xmlns="http://www.w3.org/1998/Math/MathML">'
            '<mi mathvariant="double-struck">R</mi></math>'
        )
        assert isinstance(node, TextNode)
        assert node.text == "ℝ"
        assert node.alpha is True

    def test_mi_mathvariant_script_and_fraktur(self):
        script = parse_math('<math><mi mathvariant="script">H</mi></math>')
        fraktur = parse_math('<math><mi mathvariant="fraktur">Z</mi></math>')
        assert script.text == "ℋ" and script.alpha is True
        assert fraktur.text == "ℨ" and fraktur.alpha is True

    def test_mtext_mathvariant(self):
        node = parse_math('<math><mtext mathvariant="double-struck">NQ</mtext></math>')
        assert isinstance(node, TextNode)
        assert node.text == "ℕℚ"
        assert node.alpha is True

    def test_plain_mi_unchanged(self):
        node = parse_math("<math><mi>x</mi></math>")
        assert isinstance(node, TextNode)
        assert node.text == "x"
        assert node.alpha is False
        assert node.italic is True

    def test_mathml_document_renders(self):
        doc = Document(title="MathML Alphabets")
        doc.math(
            "<math><mi>x</mi><mo>&isin;</mo>"
            '<mi mathvariant="double-struck">R</mi></math>',
            display=True,
        )
        pdf = doc.render()
        assert pdf.startswith(b"%PDF")
        assert b"EmbossMath" in pdf
        assert any(0x211D in cmap for cmap in _embedded_font_cmaps(pdf))


class TestRendering:
    def _render(self, source: str) -> bytes:
        doc = Document(title="Math Alphabets")
        doc.math(source, display=True)
        return doc.render()

    def test_mathbb_r_embeds_math_font(self):
        pdf = self._render(r"x \in \mathbb{R}")
        assert pdf.startswith(b"%PDF")
        assert b"EmbossMath" in pdf
        assert b"/FontFile2" in pdf or b"/FontFile3" in pdf
        assert b"/Subtype /CIDFontType2" in pdf

    def test_subset_contains_used_glyph_only(self):
        pdf = self._render(r"\mathbb{R}")
        cmaps = _embedded_font_cmaps(pdf)
        assert any(0x211D in cmap for cmap in cmaps)
        # Unused alphabet glyphs are subset away.
        assert not any(0x1D538 in cmap for cmap in cmaps)

    def test_tounicode_maps_glyph_back_to_codepoint(self):
        pdf = self._render(r"\mathbb{R}")
        streams = _decompressed_streams(pdf)
        assert any(b"beginbfchar" in s and b"<211D>" in s for s in streams)

    def test_mathcal_l(self):
        pdf = self._render(r"\mathcal{L}(f)")
        assert pdf.startswith(b"%PDF")
        assert b"EmbossMath" in pdf
        assert any(0x2112 in cmap for cmap in _embedded_font_cmaps(pdf))

    def test_mathfrak_g(self):
        pdf = self._render(r"\mathfrak{g} = \mathfrak{h}")
        assert pdf.startswith(b"%PDF")
        assert b"EmbossMath" in pdf
        cmaps = _embedded_font_cmaps(pdf)
        assert any(0x1D524 in cmap for cmap in cmaps)
        assert any(0x1D525 in cmap for cmap in cmaps)

    def test_deterministic_double_render(self):
        source = r"\mathbb{R}^n \to \mathcal{H}, \mathfrak{sl}_2"
        assert self._render(source) == self._render(source)

    def test_math_without_alphabets_does_not_embed_math_font(self):
        source = r"\frac{a}{b} + \sum_{i=1}^{n} \alpha_i x^2"
        first = self._render(source)
        second = self._render(source)
        assert first == second  # byte-identical rerender
        assert b"EmbossMath" not in first
        assert b"/FontFile2" not in first  # base-14 fonts only

    def test_mixed_math_keeps_other_fonts(self):
        pdf = self._render(r"f(x) = \mathcal{F}[g](x) + \pi")
        assert b"EmbossMath" in pdf
        assert b"/Symbol" in pdf
        assert b"Italic" in pdf or b"Oblique" in pdf


class TestBundle:
    def test_bundle_size_under_budget(self):
        assert FONT_PATH.is_file()
        assert FONT_PATH.stat().st_size < 400 * 1024

    def test_license_file_present(self):
        license_path = FONT_PATH.parent / "LICENSE-EmbossMath.txt"
        text = license_path.read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in text.upper()
        assert "Emboss Math" in text

    def test_family_registered_as_bundled(self):
        from emboss.bundled_fonts import BUNDLED_FAMILIES, bundled_font_path

        assert "Emboss Math" in BUNDLED_FAMILIES
        assert bundled_font_path("Emboss Math") == FONT_PATH
