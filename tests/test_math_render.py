"""Tests for mathematical notation rendering."""

import pytest

from precisionpdf import Document
from precisionpdf.math_render import (
    MathExpression,
    MathLayoutEngine,
    parse_math,
    render_math,
    GREEK_LETTERS,
    MATH_SYMBOLS,
    GroupNode,
    TextNode,
    SuperscriptNode,
    SubscriptNode,
    FractionNode,
    SqrtNode,
    SymbolNode,
    SpaceNode,
    AccentNode,
    DelimiterNode,
    SuperSubNode,
)


class TestParseMath:
    def test_simple_text(self):
        node = parse_math("abc")
        assert isinstance(node, TextNode)
        assert node.text == "abc"

    def test_single_char(self):
        node = parse_math("x")
        assert isinstance(node, TextNode)
        assert node.text == "x"

    def test_superscript(self):
        node = parse_math("x^{2}")
        assert isinstance(node, SuperscriptNode)
        assert isinstance(node.base, TextNode)
        assert node.base.text == "x"

    def test_subscript(self):
        node = parse_math("a_{n}")
        assert isinstance(node, SubscriptNode)
        assert isinstance(node.base, TextNode)

    def test_super_and_sub(self):
        node = parse_math("x^{2}_{i}")
        assert isinstance(node, SuperSubNode)

    def test_fraction(self):
        node = parse_math("\\frac{a}{b}")
        assert isinstance(node, FractionNode)

    def test_sqrt(self):
        node = parse_math("\\sqrt{x}")
        assert isinstance(node, SqrtNode)

    def test_greek_letter(self):
        node = parse_math("\\alpha")
        assert isinstance(node, SymbolNode)
        assert node.display == "α"

    def test_math_symbol(self):
        node = parse_math("\\infty")
        assert isinstance(node, SymbolNode)
        assert node.display == "∞"

    def test_spacing_quad(self):
        node = parse_math("a\\quad b")
        assert isinstance(node, GroupNode)
        has_space = any(isinstance(c, SpaceNode) for c in node.children)
        assert has_space

    def test_accent_hat(self):
        node = parse_math("\\hat{x}")
        assert isinstance(node, AccentNode)
        assert node.accent_type == "hat"

    def test_delimiter(self):
        node = parse_math("\\left(x\\right)")
        assert isinstance(node, DelimiterNode)

    def test_text_command(self):
        node = parse_math("\\text{hello}")
        assert isinstance(node, TextNode)
        assert node.italic is False

    def test_nested_fraction(self):
        node = parse_math("\\frac{\\frac{a}{b}}{c}")
        assert isinstance(node, FractionNode)
        assert isinstance(node.numerator, FractionNode)

    def test_complex_expression(self):
        node = parse_math("E = mc^{2}")
        assert isinstance(node, GroupNode)


class TestGreekLetters:
    def test_all_lowercase(self):
        lower = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta",
                 "eta", "theta", "iota", "kappa", "lambda", "mu",
                 "nu", "xi", "pi", "rho", "sigma", "tau",
                 "upsilon", "phi", "chi", "psi", "omega"]
        for name in lower:
            assert name in GREEK_LETTERS
            assert len(GREEK_LETTERS[name]) == 1

    def test_uppercase_variants(self):
        assert "Gamma" in GREEK_LETTERS
        assert "Delta" in GREEK_LETTERS
        assert "Sigma" in GREEK_LETTERS
        assert "Omega" in GREEK_LETTERS


class TestMathSymbols:
    def test_operators(self):
        assert "sum" in MATH_SYMBOLS
        assert "prod" in MATH_SYMBOLS
        assert "int" in MATH_SYMBOLS

    def test_relations(self):
        assert "leq" in MATH_SYMBOLS
        assert "geq" in MATH_SYMBOLS
        assert "neq" in MATH_SYMBOLS
        assert "approx" in MATH_SYMBOLS

    def test_arrows(self):
        assert "to" in MATH_SYMBOLS
        assert "leftarrow" in MATH_SYMBOLS
        assert "Rightarrow" in MATH_SYMBOLS

    def test_sets(self):
        assert "in" in MATH_SYMBOLS
        assert "subset" in MATH_SYMBOLS
        assert "cup" in MATH_SYMBOLS
        assert "emptyset" in MATH_SYMBOLS


class TestMathLayout:
    def test_basic_layout(self):
        engine = MathLayoutEngine(base_size=12.0)
        node = parse_math("x")
        layout = engine.layout(node)
        assert layout.width > 0
        assert layout.height > 0

    def test_superscript_height(self):
        engine = MathLayoutEngine(base_size=12.0)
        base = engine.layout(parse_math("x"))
        sup = engine.layout(parse_math("x^{2}"))
        assert sup.height >= base.height

    def test_fraction_has_line(self):
        engine = MathLayoutEngine(base_size=12.0)
        layout = engine.layout(parse_math("\\frac{a}{b}"))
        assert len(layout.lines) > 0

    def test_sqrt_has_lines(self):
        engine = MathLayoutEngine(base_size=12.0)
        layout = engine.layout(parse_math("\\sqrt{x}"))
        assert len(layout.lines) >= 1

    def test_empty_expression(self):
        engine = MathLayoutEngine(base_size=12.0)
        layout = engine.layout(parse_math(""))
        assert layout is not None

    def test_space_node_width(self):
        engine = MathLayoutEngine(base_size=12.0)
        layout = engine.layout(parse_math("a\\quad b"))
        assert layout.width > 0


class TestMathExpression:
    def test_structure_tag(self):
        expr = MathExpression(source="x^2")
        assert expr.structure_tag == "Formula"

    def test_display_default(self):
        expr = MathExpression(source="x^2")
        assert expr.display is False


class TestMathRendering:
    def test_inline_math(self):
        doc = Document(title="Math Test")
        doc.math("x^{2} + y^{2} = z^{2}")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
        assert b"%%EOF" in pdf

    def test_display_math(self):
        doc = Document(title="Display Math")
        doc.math("E = mc^{2}", display=True)
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_fraction_rendering(self):
        doc = Document(title="Fraction")
        doc.math("\\frac{a+b}{c-d}", display=True)
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_greek_letters_rendering(self):
        doc = Document(title="Greek")
        doc.math("\\alpha + \\beta = \\gamma")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_complex_expression(self):
        doc = Document(title="Complex")
        doc.math("\\sum_{i=1}^{n} x_{i}^{2}", display=True)
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_math_with_caption(self):
        doc = Document(title="Captioned")
        doc.math("e^{i\\pi} + 1 = 0", display=True, caption="Euler's Identity")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf

    def test_deterministic_output(self):
        def make():
            doc = Document(title="Deterministic Math")
            doc.math("\\frac{1}{2}")
            return doc.render()
        assert make() == make()

    def test_verification_passes(self):
        from precisionpdf.pdf.verify import verify_pdf

        doc = Document(title="Verified Math")
        doc.math("x^{2}", display=True)
        pdf = doc.render()
        report = verify_pdf(pdf)
        assert report.ok, f"Verification failed: {report.problems}"

    def test_multiple_math_blocks(self):
        doc = Document(title="Multi Math")
        doc.math("a^{2} + b^{2} = c^{2}")
        doc.paragraph("The quadratic formula:")
        doc.math("x = \\frac{-b \\pm \\sqrt{b^{2} - 4ac}}{2a}", display=True)
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf


class TestMathHTML:
    def test_html_export(self):
        from precisionpdf.adapters.html_export import to_html

        doc = Document(title="HTML Math")
        doc.math("x^{2}", display=True)
        html = to_html(doc)
        assert "x^{2}" in html
        assert "math" in html


class TestMathMarkdown:
    def test_markdown_export(self):
        from precisionpdf.adapters.markdown_export import to_markdown

        doc = Document(title="MD Math")
        doc.math("x^{2}", display=True)
        md = to_markdown(doc)
        assert "$$x^{2}$$" in md
