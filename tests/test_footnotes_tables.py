"""Tests for bottom-anchored footnotes, table colspan/decimal, and wiring."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.layout.engine import LayoutEngine  # noqa: E402
from emboss.spec import (  # noqa: E402
    Footnote,
    PageSpec,
    Paragraph,
    Table,
    TableCell,
)
from emboss.styles import resolve_preset  # noqa: E402
from emboss.typography.font_metrics import FontRegistry  # noqa: E402
from emboss.writer import render_document  # noqa: E402


def _engine() -> LayoutEngine:
    return LayoutEngine(FontRegistry(), resolve_preset("corporate"))


def _page_content(document: Document, page: int = 0) -> str:
    import pikepdf

    with pikepdf.open(io.BytesIO(document.render())) as pdf:
        return pdf.pages[page].Contents.read_bytes().decode("latin-1")


def _td_before(content: str, literal: str) -> tuple:
    """(x, y) of the Td op preceding the given literal string."""
    pattern = re.compile(r"(-?[\d.]+) (-?[\d.]+) Td\n\(" + re.escape(literal) + r"\)")
    match = pattern.search(content)
    assert match is not None, f"no Td found before ({literal})"
    return float(match.group(1)), float(match.group(2))


def _tf_before(content: str, literal: str) -> float:
    """Font size of the Tf op preceding the given literal string."""
    pattern = re.compile(
        r"/F\d+ (-?[\d.]+) Tf\n-?[\d.]+ -?[\d.]+ Td\n\(" + re.escape(literal) + r"\)"
    )
    match = pattern.search(content)
    assert match is not None, f"no Tf found before ({literal})"
    return float(match.group(1))


def _stroked_segments(content: str) -> list:
    """All (x1, y1, x2, y2) m/l pairs in the content stream."""
    pattern = re.compile(r"(-?[\d.]+) (-?[\d.]+) m\n(-?[\d.]+) (-?[\d.]+) l")
    return [tuple(float(v) for v in m.groups()) for m in pattern.finditer(content)]


# ===========================================================================
# FOOTNOTES
# ===========================================================================


class TestFootnoteRendering:
    def _doc(self) -> Document:
        doc = Document(title="Notes")
        doc.paragraph("Body text[1] continues here.")
        doc.add(Footnote(content="The footnote body."))
        return doc

    def test_footnote_renders_at_page_bottom(self):
        content = _page_content(self._doc())
        _, body_y = _td_before(content, "Body")
        _, note_y = _td_before(content, "footnote")
        _, footer_y = _td_before(content, "1 of 1")
        assert note_y < body_y - 300
        assert footer_y < note_y < 120

    def test_separator_rule_spans_third_of_measure(self):
        content = _page_content(self._doc())
        _, note_y = _td_before(content, "footnote")
        spec = PageSpec()
        rules = [
            seg
            for seg in _stroked_segments(content)
            if seg[1] == seg[3] and note_y < seg[1] < note_y + 30
        ]
        assert rules, "no separator rule above the footnote"
        x1, _, x2, _ = rules[0]
        assert x2 - x1 == pytest.approx(spec.content_width * 0.3, abs=0.1)

    def test_reference_mark_superscript(self):
        content = _page_content(self._doc())
        sheet = resolve_preset("corporate")
        body_size = sheet.resolved(sheet.body).require("font_size")
        _, text_y = _td_before(content, "Body")
        _, mark_y = _td_before(content, "[1]")
        mark_size = _tf_before(content, "[1]")
        assert mark_size == pytest.approx(body_size * 0.65, abs=0.01)
        assert mark_y - text_y == pytest.approx(body_size * 0.33, abs=0.01)

    def test_note_struct_elem_tagged(self):
        data = self._doc().render()
        assert b"/S /Note" in data

    def test_auto_numbering_is_sequential(self):
        doc = Document(title="Notes")
        doc.paragraph("First[1] and second[2].")
        doc.add(Footnote(content="Alpha."))
        doc.add(Footnote(content="Beta."))
        content = _page_content(doc)
        _, first_y = _td_before(content, "Alpha.")
        _, second_y = _td_before(content, "Beta.")
        assert first_y > second_y


class TestFootnoteReservation:
    def _blocks(self, engine, width: float) -> list:
        elements = [
            Paragraph("Filler text for the page. " * 40),
            Paragraph("Reference[1] paragraph."),
            Footnote(content="The attached note.", marker="1"),
        ]
        return [engine.measure(el, width) for el in elements]

    def _spec_for(self, content_height: float, **kw) -> PageSpec:
        return PageSpec(height=content_height + 144.0, **kw)

    def test_reservation_moves_block_and_note_together(self):
        probe = self._blocks(_engine(), PageSpec().content_width)
        filler, ref, note = probe
        # Room for the paragraphs but not the footnote reservation.
        content_height = (
            filler.height
            + filler.space_after
            + ref.space_before
            + ref.height
            + note.height
        )
        engine = _engine()
        spec = self._spec_for(content_height)
        pages = engine.paginate(self._blocks(engine, spec.content_width), spec)
        assert len(pages) == 2
        assert pages[0].footnotes == []
        assert len(pages[0].blocks) == 1
        assert len(pages[1].blocks) == 1
        assert len(pages[1].footnotes) == 1
        assert pages[1].footnotes[0].block.element.marker == "1"

    def test_block_and_note_share_page_when_room(self):
        probe = self._blocks(_engine(), PageSpec().content_width)
        filler, ref, note = probe
        content_height = (
            filler.height
            + filler.space_after
            + ref.space_before
            + ref.height
            + note.height
            + LayoutEngine.FOOTNOTE_SEPARATION
            + 1.0
        )
        engine = _engine()
        spec = self._spec_for(content_height)
        pages = engine.paginate(self._blocks(engine, spec.content_width), spec)
        assert len(pages) == 1
        assert len(pages[0].footnotes) == 1
        placed = pages[0].footnotes[0]
        assert placed.y == pytest.approx(spec.content_bottom + placed.block.height)

    def test_two_notes_on_one_page_ordered(self):
        engine = _engine()
        spec = PageSpec()
        elements = [
            Paragraph("Uses both[1] marks[2]."),
            Footnote(content="First note.", marker="1"),
            Footnote(content="Second note.", marker="2"),
        ]
        blocks = [engine.measure(el, spec.content_width) for el in elements]
        pages = engine.paginate(blocks, spec)
        assert len(pages) == 1
        notes = pages[0].footnotes
        assert [n.block.element.marker for n in notes] == ["1", "2"]
        assert notes[0].y > notes[1].y
        assert notes[0].separator is True
        assert notes[1].separator is False

    def test_multicolumn_footnote_reserved_in_column(self):
        engine = _engine()
        spec = PageSpec(columns=2)
        elements = [
            Paragraph("Column text[1] here."),
            Footnote(content="Column note.", marker="1"),
        ]
        blocks = [engine.measure(el, 200.0) for el in elements]
        pages = engine.paginate(blocks, spec)
        assert len(pages[0].footnotes) == 1
        placed = pages[0].footnotes[0]
        col_w = (spec.content_width - spec.column_gap) / 2
        assert placed.x == spec.margin_left
        assert placed.width == pytest.approx(col_w)
        assert placed.width < spec.content_width


# ===========================================================================
# TABLES: COLSPAN + DECIMAL ALIGNMENT + CAPTION HEIGHT
# ===========================================================================


def _span_table(**kw) -> Table:
    return Table(
        headers=[TableCell("Combined results", colspan=3, align="center")],
        rows=[["a", "b", "c"], ["d", "e", "f"], ["g", "h", "i"]],
        **kw,
    )


class TestColspan:
    def test_span_geometry_covers_three_columns(self):
        engine = _engine()
        block = engine.measure(_span_table(), 468.0)
        layout = block.table
        assert layout.header_spans == [3, 0, 0]
        assert len(layout.column_widths) == 3
        # The centered header sits beyond the first column: only possible
        # when its measure is the sum of all three columns.
        offset = layout.header_lines[0][0].fragments[0][2]
        assert offset > layout.column_widths[0]
        assert layout.header_lines[1] == []
        assert layout.header_lines[2] == []

    def test_span_constrains_sum_of_columns(self):
        wide = "An extremely long spanning header cell " * 3
        table = Table(headers=[TableCell(wide.strip(), colspan=3)], rows=[["a"] * 3])
        block = _engine().measure(table, 468.0)
        assert sum(block.table.column_widths) == pytest.approx(468.0, abs=1.0)

    def test_colspan_attribute_in_structure(self):
        doc = Document(title="Span")
        doc.add(_span_table())
        data = doc.render()
        assert b"/ColSpan 3" in data
        assert b"/O /Table" in data

    def test_covered_cells_not_drawn(self):
        doc = Document(title="Span")
        doc.add(_span_table())
        content = _page_content(doc)
        assert content.count("/TH <</MCID") == 1
        assert content.count("/TD <</MCID") == 9


class TestDecimalAlignment:
    def _layout(self):
        engine = _engine()
        table = Table(
            headers=[TableCell("Amount", align="decimal")],
            rows=[["1,234.5"], ["12"], ["0.25"]],
        )
        block = engine.measure(table, 468.0)
        sheet = resolve_preset("corporate")
        style = sheet.resolved(sheet.table_cell)
        metrics = engine._metrics(style)
        size = engine._size(style)
        return block.table, metrics, size, sheet

    def test_decimal_points_share_one_x(self):
        layout, metrics, size, _sheet = self._layout()
        anchors = []
        for row, int_part in zip(layout.row_lines, ["1,234", "12", "0"]):
            text, _run, offset = row[0][0].fragments[0]
            anchors.append(offset + metrics.text_width(int_part, size))
        assert anchors[0] == pytest.approx(anchors[1], abs=0.01)
        assert anchors[0] == pytest.approx(anchors[2], abs=0.01)

    def test_header_keeps_right_alignment(self):
        layout, _metrics, _size, sheet = self._layout()
        header_style = sheet.resolved(sheet.table_header)
        engine = _engine()
        h_metrics = engine._metrics(header_style)
        h_size = engine._size(header_style)
        available = layout.column_widths[0] - 2 * sheet.table_cell_padding_x
        offset = layout.header_lines[0][0].fragments[0][2]
        expected = available - h_metrics.text_width("Amount", h_size)
        assert offset == pytest.approx(expected, abs=0.01)

    def test_render_matches_measurement(self):
        doc = Document(title="Decimal")
        doc.table(
            headers=[TableCell("Amount", align="decimal")],
            rows=[["1,234.5"], ["12"], ["0.25"]],
        )
        content = _page_content(doc)
        engine = _engine()
        sheet = resolve_preset("corporate")
        style = sheet.resolved(sheet.table_cell)
        metrics = engine._metrics(style)
        size = engine._size(style)
        anchors = []
        for literal, int_part in [
            ("1,234.5", "1,234"),
            ("12", "12"),
            ("0.25", "0"),
        ]:
            x, _y = _td_before(content, literal)
            anchors.append(x + metrics.text_width(int_part, size))
        assert anchors[0] == pytest.approx(anchors[1], abs=0.01)
        assert anchors[0] == pytest.approx(anchors[2], abs=0.01)


class TestTableCaptionHeight:
    def _table(self, caption=None) -> Table:
        return Table(headers=["A"], rows=[["1"], ["2"]], caption=caption)

    def test_caption_height_reserved_in_measurement(self):
        engine = _engine()
        plain = engine.measure(self._table(), 468.0)
        titled = engine.measure(self._table("Totals"), 468.0)
        allowance = engine._caption_allowance(titled.style)
        assert titled.height - plain.height == pytest.approx(allowance)

    def test_caption_overflows_to_next_page(self):
        engine = _engine()
        width = PageSpec().content_width
        para = engine.measure(Paragraph("Intro."), width)
        plain = engine.measure(self._table(), width)
        needed = para.height + para.space_after + plain.space_before + plain.height
        spec = PageSpec(height=needed + 144.0 + 0.5)

        fresh = _engine()
        without = fresh.paginate(
            [
                fresh.measure(Paragraph("Intro."), width),
                fresh.measure(self._table(), width),
            ],
            spec,
        )
        assert len(without) == 1

        fresh = _engine()
        with_caption = fresh.paginate(
            [
                fresh.measure(Paragraph("Intro."), width),
                fresh.measure(self._table("Totals"), width),
            ],
            spec,
        )
        assert len(with_caption) == 2


# ===========================================================================
# SVG RESOURCE WIRING
# ===========================================================================


_SVG_OPACITY = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<rect x="10" y="10" width="80" height="80" fill="#ff0000" '
    'fill-opacity="0.5"/></svg>'
)

_SVG_TEXT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<text x="10" y="40" font-family="sans-serif" font-size="12">Hi</text></svg>'
)


class TestSvgResourceWiring:
    def test_opacity_gstate_registered_and_resolves(self):
        import pikepdf

        doc = Document(title="Opacity")
        doc.svg(_SVG_OPACITY)
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            page = pdf.pages[0]
            assert "/GSsvg1 gs" in page.Contents.read_bytes().decode("latin-1")
            gstates = page.Resources.ExtGState
            entry = gstates["/GSsvg1"]
            assert float(entry["/ca"]) == pytest.approx(0.5)
            assert float(entry["/CA"]) == pytest.approx(1.0)

    def test_svg_text_font_in_page_resources(self):
        import pikepdf

        doc = Document(title="SvgText")
        doc.svg(_SVG_TEXT)
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            page = pdf.pages[0]
            assert "/FsvgSSR" in page.Contents.read_bytes().decode("latin-1")
            font = page.Resources.Font["/FsvgSSR"]
            assert "SourceSans3" in str(font["/BaseFont"])


# ===========================================================================
# WARNINGS + DETERMINISM + REGRESSION
# ===========================================================================


class TestWarningsSurfacing:
    def test_engine_warning_reaches_render_result(self):
        doc = Document(title="Warn")
        doc.paragraph("Latency fell 10 ms → 5 ms")
        result = render_document(doc, return_result=True)
        assert any("U+2192" in str(issue) for issue in result.issues)

    def test_clean_document_adds_no_warnings(self):
        doc = Document(title="Clean")
        doc.paragraph("Plain text only.")
        result = render_document(doc, return_result=True)
        assert not any("substituted" in str(issue) for issue in result.issues)


def _full_feature_doc() -> Document:
    doc = Document(title="Full")
    doc.paragraph("Reference[1] text.")
    doc.add(Footnote(content="A note."))
    doc.add(_span_table())
    doc.table(
        headers=[TableCell("Amount", align="decimal")],
        rows=[["1,234.5"], ["0.25"]],
        caption="Amounts",
    )
    doc.svg(_SVG_OPACITY)
    doc.svg(_SVG_TEXT)
    return doc


class TestDeterminismAndRegression:
    def test_double_render_is_byte_identical(self):
        assert _full_feature_doc().render() == _full_feature_doc().render()

    def test_footnote_free_doc_has_no_note_artifacts(self):
        doc = Document(title="Plain")
        doc.paragraph("Just a paragraph with brackets [1] but no notes.")
        data = doc.render()
        assert b"/S /Note" not in data
        assert doc.render() == data

    def test_plain_table_has_no_colspan_attribute(self):
        doc = Document(title="PlainTable")
        doc.table(headers=["A", "B"], rows=[["1", "2"], ["3", "4"]])
        data = doc.render()
        assert b"/ColSpan" not in data
        assert doc.render() == data
