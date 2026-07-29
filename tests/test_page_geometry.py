"""Tests for landscape/mixed page geometry and numeric formatting helpers."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import format_number  # noqa: E402
from emboss.spec import Document, PageBreak, PageSpec  # noqa: E402

_TEXT_OP = re.compile(rb"([0-9.+-]+) ([0-9.+-]+) Td\n(.*?)\nET", re.DOTALL)

LONG_TEXT = (
    "The quick brown fox jumps over the lazy dog while pondering the wide "
    "expanse of the meadow beyond the old stone wall. "
) * 4


def _page_contents(data: bytes) -> list:
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return [bytes(page.Contents.read_bytes()) for page in pdf.pages]


def _page_media_boxes(data: bytes) -> list:
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return [tuple(float(v) for v in page.MediaBox) for page in pdf.pages]


def _line_count(content: bytes) -> int:
    """Distinct baseline y-positions in a content stream: a line-count proxy."""
    ys = {round(float(match.group(2)), 2) for match in _TEXT_OP.finditer(content)}
    return len(ys)


class TestPageSpecLandscape:
    def test_a4_landscape_swaps_dimensions(self):
        portrait = PageSpec.a4()
        wide = PageSpec.a4(landscape=True)
        assert wide.width == portrait.height
        assert wide.height == portrait.width
        assert wide.width > wide.height

    def test_content_area_correct_after_swap(self):
        wide = PageSpec.a4(landscape=True)
        assert wide.content_width == wide.width - wide.margin_left - wide.margin_right
        assert wide.content_height == wide.height - wide.margin_top - wide.margin_bottom
        # Content area is wider than it is tall, matching the physical page.
        assert wide.content_width > wide.content_height

    def test_letter_landscape(self):
        portrait = PageSpec.letter()
        wide = PageSpec.letter(landscape=True)
        assert wide.width == portrait.height
        assert wide.height == portrait.width

    def test_already_wide_dimensions_unaffected(self):
        # width already >= height: no swap needed, no-op.
        spec = PageSpec(width=800.0, height=600.0, landscape=True)
        assert spec.width == 800.0
        assert spec.height == 600.0

    def test_portrait_default_unaffected(self):
        assert PageSpec.a4().width < PageSpec.a4().height
        assert PageSpec.compact().width < PageSpec.compact().height


class TestMixedPageGeometry:
    def _build(self) -> Document:
        wide = PageSpec.a4(landscape=True)
        doc = Document(title="Mixed Geometry", page_styles={"wide": wide})
        doc.paragraph(LONG_TEXT)
        doc.page_break(page_style="wide")
        doc.paragraph(LONG_TEXT)
        doc.page_break()
        doc.paragraph(LONG_TEXT)
        return doc

    def test_mediabox_per_page_matches_geometry(self):
        doc = self._build()
        wide = doc.page_styles["wide"]
        default = doc.page
        data = doc.render()
        boxes = _page_media_boxes(data)
        assert len(boxes) == 3
        assert boxes[0] == (0.0, 0.0, default.width, default.height)
        assert boxes[1] == (0.0, 0.0, wide.width, wide.height)
        assert boxes[1][2] > boxes[1][3]  # landscape: width > height
        assert boxes[2] == (0.0, 0.0, default.width, default.height)

    def test_wide_section_remeasures_at_wider_width(self):
        doc = self._build()
        data = doc.render()
        contents = _page_contents(data)
        assert len(contents) == 3
        # Page 0 also carries the prepended title heading, so compare the
        # wide section against page 2 (same paragraph, no extra heading).
        wide_lines = _line_count(contents[1])
        narrow_after = _line_count(contents[2])
        assert wide_lines < narrow_after

    def test_unknown_page_style_raises(self):
        doc = Document(
            title="Bad Style", page_styles={"wide": PageSpec.a4(landscape=True)}
        )
        doc.paragraph("First page.")
        doc.add(PageBreak(page_style="nonexistent"))
        doc.paragraph("Never reached.")
        with pytest.raises(ValueError, match="unknown page_style"):
            doc.render()

    def test_multicolumn_page_style_switch(self):
        """A named style with columns=2 paginates via the multicolumn path."""
        two_col = PageSpec(columns=2)
        doc = Document(title="Columns", page_styles={"cols": two_col})
        doc.paragraph("Portrait single column intro.")
        doc.page_break(page_style="cols")
        for i in range(20):
            doc.paragraph(f"Column paragraph number {i}. " + LONG_TEXT)
        data = doc.render()
        boxes = _page_media_boxes(data)
        assert len(boxes) >= 2


class TestRegressionNoPageStyles:
    def test_plain_document_page_count_and_geometry(self):
        doc = Document(title="Plain")
        doc.paragraph("Page one.")
        doc.page_break()
        doc.paragraph("Page two.")
        doc.page_break()
        doc.paragraph("Page three.")
        data = doc.render()
        boxes = _page_media_boxes(data)
        assert len(boxes) == 3
        default = doc.page
        assert all(box == (0.0, 0.0, default.width, default.height) for box in boxes)

    def test_double_render_is_byte_identical(self):
        doc = Document(title="Determinism Check")
        doc.heading("Report", level=1)
        doc.paragraph(LONG_TEXT)
        doc.page_break()
        doc.paragraph("Second page text.")
        assert doc.render() == doc.render()

    def test_plain_page_break_inside_styled_section_reverts_to_default(self):
        """A page_style-less PageBreak always falls back to the document
        default, matching pre-existing PageBreak semantics."""
        wide = PageSpec.a4(landscape=True)
        doc = Document(title="Revert Test", page_styles={"wide": wide})
        doc.paragraph("Portrait.")
        doc.page_break(page_style="wide")
        doc.paragraph("Wide.")
        doc.page_break()  # no page_style: reverts to default, not "wide"
        doc.paragraph("Portrait again.")
        boxes = _page_media_boxes(doc.render())
        default = doc.page
        assert boxes[0] == (0.0, 0.0, default.width, default.height)
        assert boxes[1] == (0.0, 0.0, wide.width, wide.height)
        assert boxes[2] == (0.0, 0.0, default.width, default.height)


class TestFormatNumber:
    def test_plain(self):
        assert format_number(1234567) == "1234567"

    def test_thousands(self):
        assert format_number(1234567, style="thousands") == "1,234,567"

    def test_thousands_small_number_no_grouping_needed(self):
        assert format_number(42, style="thousands") == "42"

    def test_currency(self):
        assert format_number(1234.5, style="currency") == "$1,234.50"

    def test_currency_custom_symbol(self):
        assert format_number(9.5, style="currency", currency_symbol="€") == ("€9.50")

    def test_percent(self):
        assert format_number(0.123, style="percent") == "12.3%"

    def test_decimals_override(self):
        assert format_number(1234.5, style="thousands", decimals=2) == "1,234.50"
        assert format_number(1234.567, style="plain", decimals=1) == "1234.6"

    def test_negative_numbers(self):
        assert format_number(-1234.5, style="currency") == "-$1,234.50"
        assert format_number(-0.05, style="percent") == "-5.0%"
        assert format_number(-1234567, style="thousands") == "-1,234,567"

    def test_zero(self):
        assert format_number(0, style="currency") == "$0.00"
        assert format_number(0, style="percent") == "0.0%"
        assert format_number(0, style="thousands") == "0"

    def test_unknown_style_raises(self):
        with pytest.raises(ValueError):
            format_number(1, style="bogus")

    def test_negative_decimals_raises(self):
        with pytest.raises(ValueError):
            format_number(1, decimals=-1)

    def test_deterministic(self):
        assert format_number(1234567.891, style="currency") == format_number(
            1234567.891, style="currency"
        )
