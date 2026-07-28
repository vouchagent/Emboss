"""Tests for presentation MathML input parsing."""

import pytest

from emboss.math_render import (
    AlignedNode,
    DelimiterNode,
    FractionNode,
    MathLayoutEngine,
    MatrixNode,
    SqrtNode,
    SymbolNode,
    parse_math,
)
from emboss.mathml import parse_mathml

SIZE = 10.0

MATRIX_LATEX = "\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}"
MATRIX_TABLE = (
    "<mtable>"
    "<mtr><mtd><mi>a</mi></mtd><mtd><mi>b</mi></mtd></mtr>"
    "<mtr><mtd><mi>c</mi></mtd><mtd><mi>d</mi></mtd></mtr>"
    "</mtable>"
)
SUM_LATEX = "\\sum_{i=1}^{n}"
SUM_MATHML = (
    "<math><munderover><mo>&sum;</mo>"
    "<mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow>"
    "<mi>n</mi></munderover></math>"
)


def _assert_same_layout(a, b):
    assert len(a.boxes) == len(b.boxes)
    for box_a, box_b in zip(a.boxes, b.boxes):
        assert box_a.text == box_b.text
        assert box_a.italic == box_b.italic
        assert box_a.bold == box_b.bold
        assert box_a.symbol == box_b.symbol
        assert box_a.x == pytest.approx(box_b.x)
        assert box_a.y == pytest.approx(box_b.y)
        assert box_a.size == pytest.approx(box_b.size)
    assert len(a.lines) == len(b.lines)
    for line_a, line_b in zip(a.lines, b.lines):
        assert line_a.x == pytest.approx(line_b.x)
        assert line_a.y == pytest.approx(line_b.y)
        assert line_a.width == pytest.approx(line_b.width)
        assert line_a.thickness == pytest.approx(line_b.thickness)
    assert a.width == pytest.approx(b.width)
    assert a.height == pytest.approx(b.height)
    assert a.depth == pytest.approx(b.depth)


def _assert_equivalent(mathml_src, latex_src, display=False):
    engine = MathLayoutEngine(base_size=SIZE, display=display)
    _assert_same_layout(
        engine.layout(parse_math(mathml_src)),
        engine.layout(parse_math(latex_src)),
    )


class TestLayoutEquivalence:
    def test_mfrac_matches_frac(self):
        _assert_equivalent(
            "<math><mfrac><mi>a</mi><mi>b</mi></mfrac></math>",
            "\\frac{a}{b}",
        )

    def test_msup_matches_caret(self):
        _assert_equivalent(
            "<math><msup><mi>x</mi><mn>2</mn></msup></math>",
            "x^2",
        )

    def test_msub_matches_underscore(self):
        _assert_equivalent(
            "<math><msub><mi>a</mi><mi>n</mi></msub></math>",
            "a_n",
        )

    def test_msqrt_matches_sqrt(self):
        _assert_equivalent(
            "<math><msqrt><mi>x</mi></msqrt></math>",
            "\\sqrt{x}",
        )

    def test_msubsup_matches_latex(self):
        _assert_equivalent(
            "<math><msubsup><mi>x</mi><mi>i</mi><mn>2</mn></msubsup></math>",
            "x_i^2",
        )

    def test_greek_entity_matches_alpha(self):
        _assert_equivalent("<math><mi>&alpha;</mi></math>", "\\alpha")

    def test_greek_unicode_matches_alpha(self):
        _assert_equivalent("<math><mi>α</mi></math>", "\\alpha")

    def test_greek_parses_to_symbol_node(self):
        node = parse_mathml("<math><mi>&alpha;</mi></math>")
        assert node == SymbolNode(symbol="alpha", display="α")

    def test_operator_spacing_matches(self):
        _assert_equivalent(
            "<math><mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow></math>",
            "x+y",
        )

    def test_relation_spacing_matches(self):
        _assert_equivalent(
            "<math><mi>E</mi><mo>=</mo><mi>m</mi>"
            "<msup><mi>c</mi><mn>2</mn></msup></math>",
            "E=mc^2",
        )


class TestFences:
    def test_mfenced_defaults_to_parens_with_separators(self):
        node = parse_mathml("<math><mfenced><mi>a</mi><mi>b</mi></mfenced></math>")
        assert isinstance(node, DelimiterNode)
        assert node.left == "("
        assert node.right == ")"
        layout = MathLayoutEngine(base_size=SIZE).layout(node)
        assert any(box.text == "," for box in layout.boxes)

    def test_matched_mo_pair_matches_left_right(self):
        _assert_equivalent(
            "<math><mrow><mo>(</mo><mi>a</mi><mo>)</mo></mrow></math>",
            "\\left( a \\right)",
        )

    def test_mfenced_matrix_matches_pmatrix(self):
        mathml = f"<math><mfenced open='(' close=')'>{MATRIX_TABLE}</mfenced></math>"
        node = parse_math(mathml)
        assert isinstance(node, MatrixNode)
        assert node.left_delim == "("
        assert node.right_delim == ")"
        _assert_equivalent(mathml, MATRIX_LATEX)

    def test_mo_pair_matrix_matches_pmatrix(self):
        mathml = f"<math><mrow><mo>(</mo>{MATRIX_TABLE}<mo>)</mo></mrow></math>"
        _assert_equivalent(mathml, MATRIX_LATEX)


class TestTables:
    def test_bare_mtable_matches_plain_matrix(self):
        _assert_equivalent(
            f"<math>{MATRIX_TABLE}</math>",
            "\\begin{matrix} a & b \\\\ c & d \\end{matrix}",
        )

    def test_columnalign_right_left_gives_aligned(self):
        mathml = (
            "<math><mtable columnalign='right left'>"
            "<mtr><mtd><mi>a</mi></mtd>"
            "<mtd><mrow><mo>=</mo><mi>b</mi></mrow></mtd></mtr>"
            "<mtr><mtd><mi>x</mi></mtd>"
            "<mtd><mrow><mo>=</mo><mi>y</mi></mrow></mtd></mtr>"
            "</mtable></math>"
        )
        node = parse_math(mathml)
        assert isinstance(node, AlignedNode)
        assert node.col_align == "rl"
        _assert_equivalent(mathml, "\\begin{aligned} a &= b \\\\ x &= y \\end{aligned}")


class TestLimits:
    def test_munderover_sum_display_matches_latex(self):
        _assert_equivalent(SUM_MATHML, SUM_LATEX, display=True)

    def test_munderover_sum_inline_matches_latex(self):
        _assert_equivalent(SUM_MATHML, SUM_LATEX, display=False)

    def test_display_limits_sit_above_and_below(self):
        engine = MathLayoutEngine(base_size=SIZE, display=True)
        layout = engine.layout(parse_math(SUM_MATHML))
        op = next(b for b in layout.boxes if b.symbol and b.text == "∑")
        n = next(b for b in layout.boxes if b.text == "n")
        i = next(b for b in layout.boxes if b.text == "i")
        assert n.y > op.y
        assert i.y < op.y

    def test_mover_places_script_above_even_inline(self):
        engine = MathLayoutEngine(base_size=SIZE)
        layout = engine.layout(
            parse_mathml("<math><mover><mi>x</mi><mo>^</mo></mover></math>")
        )
        base = next(b for b in layout.boxes if b.text == "x")
        hat = next(b for b in layout.boxes if b.text == "^")
        assert hat.y > base.y
        assert hat.size < base.size

    def test_munder_places_script_below_even_inline(self):
        engine = MathLayoutEngine(base_size=SIZE)
        layout = engine.layout(
            parse_mathml("<math><munder><mo>max</mo><mi>k</mi></munder></math>")
        )
        base = next(b for b in layout.boxes if b.text == "max")
        k = next(b for b in layout.boxes if b.text == "k")
        assert k.y < base.y


class TestTokensAndSpacing:
    def test_mtext_is_upright(self):
        node = parse_mathml("<math><mtext>if</mtext></math>")
        layout = MathLayoutEngine(base_size=SIZE).layout(node)
        assert layout.boxes[0].text == "if"
        assert not layout.boxes[0].italic
        _assert_equivalent("<math><mtext>if</mtext></math>", "\\text{if}")

    def test_multichar_mi_is_upright_operator_name(self):
        _assert_equivalent("<math><mi>sin</mi><mi>x</mi></math>", "\\sin x")

    def test_mspace_width_em_matches_quad(self):
        _assert_equivalent(
            "<math><mi>a</mi><mspace width='1em'/><mi>b</mi></math>",
            "a\\quad b",
        )

    def test_mroot_matches_latex_nth_root(self):
        node = parse_mathml("<math><mroot><mi>x</mi><mn>3</mn></mroot></math>")
        assert isinstance(node, SqrtNode)
        assert node.index is not None
        _assert_equivalent(
            "<math><mroot><mi>x</mi><mn>3</mn></mroot></math>", "\\sqrt[3]{x}"
        )

    def test_mroot_index_raised_above_left_of_radical(self):
        engine = MathLayoutEngine(base_size=SIZE)
        layout = engine.layout(
            parse_mathml("<math><mroot><mi>x</mi><mn>3</mn></mroot></math>")
        )
        radical = next(b for b in layout.boxes if b.text == "√")
        index = next(b for b in layout.boxes if b.text == "3")
        radicand = next(b for b in layout.boxes if b.text == "x")
        assert index.size == pytest.approx(SIZE * 0.6)
        assert index.x < radical.x + radical.size * 0.5
        assert index.y > radical.y
        assert index.y > radicand.y
        plain = engine.layout(parse_mathml("<math><msqrt><mi>x</mi></msqrt></math>"))
        assert layout.width > plain.width

    def test_plain_sqrt_layout_unchanged_by_index_support(self):
        _assert_equivalent("<math><msqrt><mi>x</mi></msqrt></math>", "\\sqrt{x}")
        engine = MathLayoutEngine(base_size=SIZE)
        layout = engine.layout(parse_math("\\sqrt{x}"))
        assert not any(b.text == "3" for b in layout.boxes)
        assert len(layout.lines) == 1

    def test_minus_sign_normalized(self):
        _assert_equivalent(
            "<math><mo>−</mo><mi>x</mi></math>",
            "-x",
        )


class TestStructuralPassthrough:
    def test_mstyle_is_transparent(self):
        _assert_equivalent("<math><mstyle><mi>x</mi></mstyle></math>", "x")

    def test_semantics_takes_presentation_child(self):
        mathml = (
            "<math><semantics><mrow><mi>x</mi></mrow>"
            "<annotation encoding='application/x-tex'>y+z</annotation>"
            "</semantics></math>"
        )
        _assert_equivalent(mathml, "x")

    def test_xmlns_namespace_stripped(self):
        _assert_equivalent(
            "<math xmlns='http://www.w3.org/1998/Math/MathML'><mi>x</mi></math>",
            "x",
        )


class TestErrors:
    def test_malformed_xml_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid MathML"):
            parse_mathml("<math><mi>x</mi>")

    def test_wrong_root_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid MathML"):
            parse_mathml("<mathx><mi>x</mi></mathx>")

    def test_missing_frac_child_raises_value_error(self):
        with pytest.raises(ValueError, match="mfrac"):
            parse_math("<math><mfrac><mi>a</mi></mfrac></math>")


class TestIntegration:
    MIXED = (
        "<math xmlns='http://www.w3.org/1998/Math/MathML'><mrow>"
        "<mi>x</mi><mo>=</mo><mfrac>"
        "<mrow><mo>-</mo><mi>b</mi><mo>&PlusMinus;</mo>"
        "<msqrt><mrow><msup><mi>b</mi><mn>2</mn></msup>"
        "<mo>-</mo><mn>4</mn><mi>a</mi><mi>c</mi></mrow></msqrt></mrow>"
        "<mrow><mn>2</mn><mi>a</mi></mrow>"
        "</mfrac></mrow></math>"
    )

    def test_document_mathml_renders_pdf(self):
        from emboss import Document

        doc = Document(title="MathML Doc")
        doc.math(self.MIXED, display=True)
        doc.math(
            "<math><msup><mi>e</mi><mrow><mi>i</mi><mi>&pi;</mi></mrow></msup></math>"
        )
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_document_render_deterministic(self):
        from emboss import Document

        def make():
            doc = Document(title="MathML Determinism")
            doc.math(self.MIXED, display=True)
            return doc.render()

        assert make() == make()

    def test_layout_deterministic(self):
        def run():
            engine = MathLayoutEngine(base_size=SIZE, display=True)
            return engine.layout(parse_math(self.MIXED))

        first, second = run(), run()
        assert first.boxes == second.boxes
        assert first.lines == second.lines
        assert first.width == second.width
        assert first.height == second.height
        assert first.depth == second.depth

    def test_latex_sources_unaffected(self):
        node = parse_math("\\frac{a}{b}")
        assert isinstance(node, FractionNode)

    def test_parse_math_routes_mathml(self):
        node = parse_math("  <math><mfrac><mi>a</mi><mi>b</mi></mfrac></math>")
        assert isinstance(node, FractionNode)
