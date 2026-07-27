"""Tests for math real-font metrics, TeX spacing, and environments."""

import pytest

from emboss.math_render import (
    AlignedNode,
    MathLayoutEngine,
    MatrixNode,
    parse_math,
)
from emboss.typography.font_metrics import FontMetrics

SIZE = 10.0
MED = 4.0 / 18.0 * SIZE
THICK = 5.0 / 18.0 * SIZE


@pytest.fixture
def engine():
    return MathLayoutEngine(base_size=SIZE)


@pytest.fixture
def display_engine():
    return MathLayoutEngine(base_size=SIZE, display=True)


@pytest.fixture
def times_italic():
    return FontMetrics.base14("Times-Italic")


@pytest.fixture
def times_roman():
    return FontMetrics.base14("Times-Roman")


def _boxes(layout, text):
    return [b for b in layout.boxes if b.text == text]


class TestWidthAccuracy:
    def test_single_variable_matches_afm(self, engine, times_italic):
        layout = engine.layout(parse_math("x"))
        assert layout.width == pytest.approx(times_italic.text_width("x", SIZE))

    def test_binary_expression_width(self, engine, times_italic, times_roman):
        layout = engine.layout(parse_math("x+y"))
        expected = (
            times_italic.text_width("x", SIZE)
            + times_roman.text_width("+", SIZE)
            + times_italic.text_width("y", SIZE)
            + 2 * MED
        )
        assert layout.width == pytest.approx(expected)

    def test_digits_use_roman_widths(self, engine, times_roman):
        layout = engine.layout(parse_math("123"))
        assert layout.width == pytest.approx(times_roman.text_width("123", SIZE))
        assert all(not b.italic for b in layout.boxes)

    def test_digits_upright_next_to_variable(self, engine):
        layout = engine.layout(parse_math("2x"))
        two = _boxes(layout, "2")[0]
        var = _boxes(layout, "x")[0]
        assert not two.italic
        assert var.italic

    def test_greek_symbol_uses_symbol_afm(self, engine):
        layout = engine.layout(parse_math("\\alpha"))
        assert layout.width == pytest.approx(0.631 * SIZE)

    def test_summation_symbol_width(self, engine):
        layout = engine.layout(parse_math("\\sum"))
        assert layout.width == pytest.approx(0.713 * SIZE)


class TestPmatrix:
    SOURCE = "\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}"

    def test_parses_to_matrix_node(self):
        node = parse_math(self.SOURCE)
        assert isinstance(node, MatrixNode)
        assert node.left_delim == "("
        assert node.right_delim == ")"
        assert len(node.rows) == 2
        assert len(node.rows[0]) == 2

    def test_columns_align(self, engine):
        layout = engine.layout(parse_math(self.SOURCE))
        a, b = _boxes(layout, "a")[0], _boxes(layout, "b")[0]
        c, d = _boxes(layout, "c")[0], _boxes(layout, "d")[0]
        assert a.x == pytest.approx(c.x)
        assert b.x == pytest.approx(d.x)
        assert b.x > a.x
        assert a.y > c.y  # first row sits above the second

    def test_parens_span_full_height(self, engine):
        layout = engine.layout(parse_math(self.SOURCE))
        left = _boxes(layout, "(")[0]
        right = _boxes(layout, ")")[0]
        total = layout.height + layout.depth
        assert left.size >= total
        assert right.size >= total
        assert left.x < _boxes(layout, "a")[0].x
        assert right.x > _boxes(layout, "b")[0].x


class TestDelimiterVariants:
    def test_bmatrix_uses_brackets(self, engine):
        layout = engine.layout(
            parse_math("\\begin{bmatrix} a & b \\\\ c & d \\end{bmatrix}")
        )
        assert _boxes(layout, "[")
        assert _boxes(layout, "]")
        assert not _boxes(layout, "(")

    def test_vmatrix_uses_bars(self, engine):
        layout = engine.layout(
            parse_math("\\begin{vmatrix} a & b \\\\ c & d \\end{vmatrix}")
        )
        assert len(_boxes(layout, "|")) == 2

    def test_Bmatrix_uses_braces(self, engine):
        layout = engine.layout(
            parse_math("\\begin{Bmatrix} a & b \\\\ c & d \\end{Bmatrix}")
        )
        assert _boxes(layout, "{")
        assert _boxes(layout, "}")

    def test_plain_matrix_has_no_delimiters(self, engine):
        layout = engine.layout(
            parse_math("\\begin{matrix} a & b \\\\ c & d \\end{matrix}")
        )
        for delim in "()[]|{}":
            assert not _boxes(layout, delim)


class TestCases:
    SOURCE = "\\begin{cases} a & b \\\\ cd & e \\end{cases}"

    def test_left_brace_only(self, engine):
        layout = engine.layout(parse_math(self.SOURCE))
        assert _boxes(layout, "{")
        assert not _boxes(layout, "}")

    def test_rows_left_aligned(self, engine):
        layout = engine.layout(parse_math(self.SOURCE))
        a = _boxes(layout, "a")[0]
        cd = _boxes(layout, "cd")[0]
        assert a.x == pytest.approx(cd.x)


class TestAligned:
    SOURCE = "\\begin{aligned} a &= b \\\\ ab &= cd \\\\ x &= y \\end{aligned}"

    def test_parses_to_aligned_node(self):
        node = parse_math(self.SOURCE)
        assert isinstance(node, AlignedNode)
        assert len(node.rows) == 3

    def test_equals_share_one_x(self, engine):
        layout = engine.layout(parse_math(self.SOURCE))
        equals = _boxes(layout, "=")
        assert len(equals) == 3
        assert equals[1].x == pytest.approx(equals[0].x)
        assert equals[2].x == pytest.approx(equals[0].x)

    def test_first_column_right_aligned(self, engine):
        layout = engine.layout(parse_math(self.SOURCE))
        a = _boxes(layout, "a")[0]
        ab = _boxes(layout, "ab")[0]
        # Right edges meet at the alignment point; "a" starts further right.
        assert a.x > ab.x


class TestDisplayLimits:
    SOURCE = "\\sum_{i=1}^{n}"

    def test_display_limits_centered(self, display_engine):
        layout = display_engine.layout(parse_math(self.SOURCE))
        op = next(b for b in layout.boxes if b.symbol and b.text == "∑")
        n = _boxes(layout, "n")[0]
        op_center = op.x + 0.713 * op.size / 2
        n_center = n.x + 0.5 * n.size / 2  # Times "n" is 500/1000 em
        assert n_center == pytest.approx(op_center, abs=1e-6)
        assert n.y > op.y  # superscript limit above
        sub_i = _boxes(layout, "i")[0]
        assert sub_i.y < op.y  # subscript limit below

    def test_inline_keeps_side_scripts(self, engine):
        layout = engine.layout(parse_math(self.SOURCE))
        op = next(b for b in layout.boxes if b.symbol and b.text == "∑")
        n = _boxes(layout, "n")[0]
        sub_i = _boxes(layout, "i")[0]
        assert n.x >= op.x + 0.713 * op.size - 1e-9
        assert sub_i.x >= op.x + 0.713 * op.size - 1e-9

    def test_lim_gets_under_limits_in_display(self, display_engine):
        layout = display_engine.layout(parse_math("\\lim_{n \\to \\infty}"))
        lim = _boxes(layout, "lim")[0]
        n = _boxes(layout, "n")[0]
        assert n.y < lim.y


class TestSpacingClasses:
    def test_relation_wider_than_binary(self, engine):
        w_rel = engine.layout(parse_math("a=b")).width
        w_bin = engine.layout(parse_math("a+b")).width
        w_ord = engine.layout(parse_math("ab")).width
        assert (w_rel - w_ord) > (w_bin - w_ord)

    def test_relation_spacing_is_thick(self, engine, times_italic, times_roman):
        w_rel = engine.layout(parse_math("a=b")).width
        glyphs = (
            times_italic.text_width("a", SIZE)
            + times_roman.text_width("=", SIZE)
            + times_italic.text_width("b", SIZE)
        )
        assert w_rel == pytest.approx(glyphs + 2 * THICK)

    def test_no_space_inside_parens(self, engine, times_italic, times_roman):
        layout = engine.layout(parse_math("(a)"))
        expected = (
            times_roman.text_width("(", SIZE)
            + times_italic.text_width("a", SIZE)
            + times_roman.text_width(")", SIZE)
        )
        assert layout.width == pytest.approx(expected)

    def test_unary_minus_is_tight(self, engine, times_italic, times_roman):
        layout = engine.layout(parse_math("-x"))
        expected = times_roman.text_width("-", SIZE) + times_italic.text_width(
            "x", SIZE
        )
        assert layout.width == pytest.approx(expected)

    def test_soft_spaces_ignored(self, engine):
        assert engine.layout(parse_math("a = b")).width == pytest.approx(
            engine.layout(parse_math("a=b")).width
        )


class TestFractionInMatrix:
    FRAC = "\\begin{pmatrix} \\frac{a}{b} & c \\\\ d & e \\end{pmatrix}"
    PLAIN = "\\begin{pmatrix} a & c \\\\ d & e \\end{pmatrix}"

    def test_row_height_grows(self, engine):
        frac = engine.layout(parse_math(self.FRAC))
        plain = engine.layout(parse_math(self.PLAIN))
        assert (frac.height + frac.depth) > (plain.height + plain.depth)

    def test_no_overlap_between_rows(self, engine):
        layout = engine.layout(parse_math(self.FRAC))
        den = _boxes(layout, "b")[0]  # fraction denominator, row 0 bottom
        d = _boxes(layout, "d")[0]  # row 1
        assert den.y > d.y + d.size * 0.7


class TestDeterminism:
    SOURCE = (
        "\\begin{pmatrix} \\frac{a}{b} & c \\\\ d & e \\end{pmatrix}"
        " + \\sum_{i=1}^{n} \\sqrt{x_{i}}"
    )

    def test_double_run_identical(self):
        first = MathLayoutEngine(base_size=SIZE, display=True).layout(
            parse_math(self.SOURCE)
        )
        second = MathLayoutEngine(base_size=SIZE, display=True).layout(
            parse_math(self.SOURCE)
        )
        assert first.boxes == second.boxes
        assert first.lines == second.lines
        assert first.width == second.width
        assert first.height == second.height
        assert first.depth == second.depth

    def test_document_render_deterministic(self):
        from emboss import Document

        def make():
            doc = Document(title="Env Math")
            doc.math(
                "\\begin{aligned} a &= b \\\\ x &= y \\end{aligned}",
                display=True,
            )
            return doc.render()

        assert make() == make()


class TestRegressions:
    def test_superscript_structure(self, engine):
        layout = engine.layout(parse_math("x^2"))
        base = _boxes(layout, "x")[0]
        sup = _boxes(layout, "2")[0]
        assert sup.x > base.x
        assert sup.y > base.y
        assert sup.size < base.size

    def test_fraction_structure(self, engine):
        layout = engine.layout(parse_math("\\frac{a}{b}"))
        assert len(layout.lines) == 1
        bar = layout.lines[0]
        num = _boxes(layout, "a")[0]
        den = _boxes(layout, "b")[0]
        assert num.y > bar.y
        assert den.y < bar.y

    def test_sqrt_structure(self, engine):
        layout = engine.layout(parse_math("\\sqrt{x}"))
        assert any(b.text == "√" and b.symbol for b in layout.boxes)
        assert len(layout.lines) == 1
        inner = _boxes(layout, "x")[0]
        assert inner.x > 0

    def test_environments_render_to_pdf(self):
        from emboss import Document

        doc = Document(title="Matrix Doc")
        doc.math("\\begin{pmatrix} 1 & 0 \\\\ 0 & 1 \\end{pmatrix}", display=True)
        doc.math("\\begin{cases} x & x > 0 \\\\ -x & x \\leq 0 \\end{cases}")
        pdf = doc.render()
        assert b"%PDF-1.7" in pdf
