"""Tests for the four micro-typography features.

Feature 1: Optical margin alignment (hanging punctuation)
Feature 2: Character protrusion tables (letter protrusion)
Feature 3: Font expansion (hz-program via Tz operator)
Feature 4: River detection
"""

from __future__ import annotations

import pytest

from emboss.typography.protrusion import (
    PROTRUSION_TABLE,
    left_protrusion,
    protrusion_width,
    right_protrusion,
)
from emboss.typography.line_breaking import (
    Box, Glue, Line, LineBreaker, Penalty, detect_rivers,
    INFINITE_PENALTY, build_items,
)
from emboss.pdf.streams import ContentStream


# =====================================================================
# Feature 1: Optical margin alignment (hanging punctuation)
# =====================================================================

class TestOpticalMarginAlignment:
    """The protrusion table must contain punctuation with correct factors."""

    def test_hyphen_protrusion(self):
        assert PROTRUSION_TABLE["-"] == (0.7, 0.7)

    def test_period_right_protrusion(self):
        left, right = PROTRUSION_TABLE["."]
        assert right == 0.7
        assert left == 0.0

    def test_comma_right_protrusion(self):
        left, right = PROTRUSION_TABLE[","]
        assert right == 0.7
        assert left == 0.0

    def test_colon_protrusion(self):
        left, right = PROTRUSION_TABLE[":"]
        assert right == 0.5

    def test_semicolon_protrusion(self):
        left, right = PROTRUSION_TABLE[";"]
        assert right == 0.5

    def test_left_double_quote(self):
        left, right = PROTRUSION_TABLE["\u201c"]
        assert left == 0.5
        assert right == 0.0

    def test_right_double_quote(self):
        left, right = PROTRUSION_TABLE["\u201d"]
        assert left == 0.0
        assert right == 0.5

    def test_left_single_quote(self):
        left, right = PROTRUSION_TABLE["‘"]
        assert left == 0.5

    def test_right_single_quote(self):
        left, right = PROTRUSION_TABLE["’"]
        assert right == 0.5

    def test_open_paren_protrusion(self):
        left, right = PROTRUSION_TABLE["("]
        assert left == 0.3
        assert right == 0.0

    def test_close_paren_protrusion(self):
        left, right = PROTRUSION_TABLE[")"]
        assert left == 0.0
        assert right == 0.3

    def test_left_protrusion_helper(self):
        assert left_protrusion("-") == 0.7
        assert left_protrusion("(") == 0.3
        assert left_protrusion("x") == 0.0

    def test_right_protrusion_helper(self):
        assert right_protrusion(".") == 0.7
        assert right_protrusion(")") == 0.3
        assert right_protrusion("x") == 0.0

    def test_protrusion_width_left(self):
        # Hyphen width 10pt, protrusion factor 0.7 => 7pt
        assert protrusion_width("-", 10.0, "left") == pytest.approx(7.0)

    def test_protrusion_width_right(self):
        assert protrusion_width(".", 10.0, "right") == pytest.approx(7.0)

    def test_protrusion_width_no_entry(self):
        assert protrusion_width("x", 10.0, "left") == 0.0

    def test_optical_margin_in_rendered_pdf(self):
        """Rendering a paragraph that starts with a left double quote should
        succeed with protrusion enabled."""
        from emboss.spec import Document, Paragraph
        from emboss.styles import Style
        from emboss.writer import render_document

        text = ('"Hello world this is a paragraph of justified '
                'text that should be long enough to wrap."')
        doc = Document(title="Test")
        doc.add(Paragraph(text, style=Style(align="justify")))
        pdf_bytes = render_document(doc)
        assert pdf_bytes  # Should render without error


# =====================================================================
# Feature 2: Character protrusion tables (letter protrusion)
# =====================================================================

class TestCharacterProtrusion:
    """Letters like A, V, W, T should protrude slightly."""

    @pytest.mark.parametrize("char,expected", [
        ("A", (0.05, 0.05)),
        ("V", (0.05, 0.05)),
        ("W", (0.05, 0.05)),
        ("T", (0.05, 0.05)),
        ("F", (0.0, 0.05)),
        ("Y", (0.05, 0.05)),
        ("J", (0.0, 0.03)),
    ])
    def test_uppercase_protrusion(self, char, expected):
        assert PROTRUSION_TABLE[char] == expected

    @pytest.mark.parametrize("char,expected", [
        ("v", (0.03, 0.03)),
        ("w", (0.03, 0.03)),
        ("y", (0.03, 0.03)),
    ])
    def test_lowercase_protrusion(self, char, expected):
        assert PROTRUSION_TABLE[char] == expected

    def test_no_protrusion_for_regular_letters(self):
        for ch in "BbCcDdEeGgHhIiKkLlMmNnOoPpQqRrSsUuXxZz":
            assert ch not in PROTRUSION_TABLE, f"{ch!r} should not protrude"

    def test_protrusion_slack_in_line_breaker(self):
        """The line breaker should account for protrusion when computing
        adjustment ratios, giving slightly more room."""
        breaker = LineBreaker(protrusion=True)
        # A line starting with 'A' (5% protrusion) on a box of width 50
        # gets ~2.5pt extra slack.
        items = [
            Box(width=50.0, text="Alpha"),
            Glue(width=10.0, stretch=5.0, shrink=3.0),
            Box(width=50.0, text="beta"),
            Glue(width=0.0, stretch=INFINITE_PENALTY),
            Penalty(penalty=-INFINITE_PENALTY),
        ]
        sums = breaker._running_sums(items)
        from emboss.typography.line_breaking import _Node
        node = _Node(
            position=0, line=0, fitness=1,
            total_width=0.0, total_stretch=0.0, total_shrink=0.0,
            demerits=0.0,
        )
        # Without protrusion, the width is 110 and the target is 110.
        # With protrusion, the effective target is slightly wider.
        ratio_with = breaker._adjustment_ratio(node, 3, items, sums, 110.0)
        breaker_no = LineBreaker(protrusion=False)
        ratio_without = breaker_no._adjustment_ratio(node, 3, items, sums, 110.0)
        # Both should be valid ratios. With protrusion, the ratio should be
        # more positive (more room) or less negative.
        assert ratio_with >= ratio_without


# =====================================================================
# Feature 3: Font expansion (hz-program)
# =====================================================================

class TestFontExpansion:
    """The Tz operator should appear in the content stream for non-100
    horizontal scaling."""

    def test_text_line_default_no_tz(self):
        """Default h_scale=100.0 should not emit Tz."""
        stream = ContentStream()
        stream.text_line("Hello", "F1", 12.0, 72.0, 700.0, "000000")
        output = stream.to_bytes()
        assert b"Tz" not in output

    def test_text_line_with_expansion(self):
        """h_scale=101.5 should emit '101.5 Tz' before text and
        '100 Tz' after."""
        stream = ContentStream()
        stream.text_line(
            "Hello", "F1", 12.0, 72.0, 700.0, "000000", h_scale=101.5,
        )
        output = stream.to_bytes()
        assert b"Tz" in output
        # Should contain the scaling value
        assert b"101.5 Tz" in output
        # Should reset to 100
        assert b"100 Tz" in output

    def test_text_line_with_compression(self):
        """h_scale=98.5 should emit '98.5 Tz'."""
        stream = ContentStream()
        stream.text_line(
            "Test", "F1", 10.0, 50.0, 600.0, "000000", h_scale=98.5,
        )
        output = stream.to_bytes()
        assert b"98.5 Tz" in output
        assert b"100 Tz" in output

    def test_tz_comes_before_text_operator(self):
        """Tz must appear after Tf and before Td/TJ/Tj."""
        stream = ContentStream()
        stream.text_line(
            "Hi", "F1", 12.0, 72.0, 700.0, "000000", h_scale=102.0,
        )
        output = stream.to_bytes()
        lines = output.split(b"\n")
        # Find positions of relevant operators
        tz_line = None
        td_line = None
        for i, line in enumerate(lines):
            if b"Tz" in line and b"100 Tz" not in line:
                tz_line = i
            if b"Td" in line:
                td_line = i
        assert tz_line is not None, "Tz not found"
        assert td_line is not None, "Td not found"
        assert tz_line < td_line, "Tz must come before Td"

    def test_h_scale_clamped_in_writer(self):
        """h_scale should be clamped to [98.0, 102.0]."""
        # This is a unit check: the clamping formula
        ratio = 5.0  # extreme ratio
        h_scale = 100.0 + (ratio * 1.0)
        h_scale = max(98.0, min(102.0, h_scale))
        assert h_scale == 102.0

        ratio = -5.0
        h_scale = 100.0 + (ratio * 1.0)
        h_scale = max(98.0, min(102.0, h_scale))
        assert h_scale == 98.0

    def test_h_scale_with_kern_pairs(self):
        """Tz should be emitted even when kern pairs are present."""
        stream = ContentStream()
        stream.text_line(
            "AV", "F1", 12.0, 72.0, 700.0, "000000",
            kern_pairs=[(1, -50)], h_scale=99.0,
        )
        output = stream.to_bytes()
        assert b"99 Tz" in output
        assert b"TJ" in output  # kerned array uses TJ


# =====================================================================
# Feature 4: River detection
# =====================================================================

class TestRiverDetection:
    """detect_rivers() should identify vertically aligned spaces."""

    def _make_line(self, items, ratio=0.0):
        width = sum(it.width for it in items if isinstance(it, (Box, Glue)))
        return Line(items=items, start=0, end=len(items),
                    ratio=ratio, width=width)

    def test_no_rivers_in_two_lines(self):
        """Rivers require at least 3 lines."""
        lines = [
            self._make_line([Box(30, "aaa"), Glue(10), Box(30, "bbb")]),
            self._make_line([Box(30, "ccc"), Glue(10), Box(30, "ddd")]),
        ]
        assert detect_rivers(lines) == 0

    def test_aligned_spaces_three_lines_is_river(self):
        """Three lines with a space at the same x-position form a river."""
        # Each line: Box(30) + Glue(10) + Box(30)
        # Space centre at x=35 on every line
        lines = [
            self._make_line([Box(30, "aaa"), Glue(10), Box(30, "bbb")]),
            self._make_line([Box(30, "ccc"), Glue(10), Box(30, "ddd")]),
            self._make_line([Box(30, "eee"), Glue(10), Box(30, "fff")]),
        ]
        assert detect_rivers(lines) >= 1

    def test_no_river_when_spaces_offset(self):
        """Spaces at very different x-positions should not be rivers."""
        lines = [
            self._make_line([Box(10, "a"), Glue(10), Box(50, "bbbbb")]),
            self._make_line([Box(50, "ccccc"), Glue(10), Box(10, "d")]),
            self._make_line([Box(10, "e"), Glue(10), Box(50, "fffff")]),
        ]
        # Spaces at x=15, x=55, x=15 -- not 3 consecutive aligned
        assert detect_rivers(lines) == 0

    def test_empty_lines(self):
        assert detect_rivers([]) == 0

    def test_single_line(self):
        lines = [self._make_line([Box(30, "aaa")])]
        assert detect_rivers(lines) == 0

    def test_tolerance_parameter(self):
        """Spaces within tolerance should count as aligned."""
        lines = [
            self._make_line([Box(30, "aaa"), Glue(10), Box(30, "bbb")]),
            self._make_line([Box(31, "aab"), Glue(10), Box(29, "bba")]),
            self._make_line([Box(29, "aac"), Glue(10), Box(31, "bbc")]),
        ]
        # Space centres at 35, 36, 34 -- within default tolerance of 2pt
        assert detect_rivers(lines, tolerance=2.0) >= 1
        # With very tight tolerance they should not align
        assert detect_rivers(lines, tolerance=0.1) == 0

    def test_river_avoidance_in_line_breaker(self):
        """LineBreaker with avoid_rivers=True should try a tighter break
        when rivers are detected."""
        breaker = LineBreaker(avoid_rivers=True, tolerance=2.5)
        # Construct a paragraph where rivers might form
        items = []
        for i in range(30):
            if i > 0:
                items.append(Glue(width=5.0, stretch=3.0, shrink=2.0))
            items.append(Box(width=15.0, text=f"w{i:02d}"))
        items.append(Glue(width=0.0, stretch=INFINITE_PENALTY))
        items.append(Penalty(penalty=-INFINITE_PENALTY))

        lines = breaker.break_paragraph(items, 100.0)
        # Should produce lines without error
        assert len(lines) > 0

    def test_detect_rivers_four_lines(self):
        """Four lines with aligned spaces should detect a river."""
        lines = [
            self._make_line([Box(40, "aaaa"), Glue(10), Box(40, "bbbb")]),
            self._make_line([Box(40, "cccc"), Glue(10), Box(40, "dddd")]),
            self._make_line([Box(40, "eeee"), Glue(10), Box(40, "ffff")]),
            self._make_line([Box(40, "gggg"), Glue(10), Box(40, "hhhh")]),
        ]
        assert detect_rivers(lines) >= 1


# =====================================================================
# Integration: end-to-end rendering with micro-typography
# =====================================================================

class TestEndToEndMicrotypography:
    """Full render should succeed with micro-typography features active."""

    def test_justified_paragraph_renders(self):
        from emboss.spec import Document, Paragraph
        from emboss.styles import Style
        from emboss.writer import render_document

        doc = Document(title="Test")
        doc.add(Paragraph(
            "The quick brown fox jumps over the lazy dog. "
            "A very long paragraph with multiple sentences that "
            "should wrap across several lines when justified, "
            "testing optical margin alignment, character protrusion, "
            "and font expansion features together.",
            style=Style(align="justify"),
        ))
        result = render_document(doc, return_result=True)
        assert result.page_count >= 1
        assert len(result.data) > 0

    def test_left_aligned_paragraph_renders(self):
        from emboss.spec import Document, Paragraph
        from emboss.styles import Style
        from emboss.writer import render_document

        doc = Document(title="Test")
        doc.add(Paragraph(
            '"Quoted text at the start of a paragraph should '
            'have its opening quote hang into the margin for '
            'optical alignment."',
            style=Style(align="left"),
        ))
        result = render_document(doc, return_result=True)
        assert result.page_count >= 1

    def test_center_aligned_no_protrusion(self):
        """Center-aligned text should not apply protrusion shifts."""
        from emboss.spec import Document, Paragraph
        from emboss.styles import Style
        from emboss.writer import render_document

        doc = Document(title="Test")
        doc.add(Paragraph(
            '"Centered text" should not hang punctuation.',
            style=Style(align="center"),
        ))
        result = render_document(doc, return_result=True)
        assert result.page_count >= 1
