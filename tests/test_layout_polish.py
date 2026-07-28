"""Tests for right-margin protrusion, baseline grid, and column balancing.

Covers plan items 4.2 (right protrusion handled inside the breaker with the
credit recorded on the Line), 4.5 (opt-in baseline grid snapping during
placement), and 4.6 (balanced columns on the final page of a multicolumn
document).
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.layout.engine import LayoutEngine
from emboss.spec import Document, Heading, PageSpec, Paragraph, TextRun
from emboss.styles import PRESETS, Style, resolve_preset
from emboss.typography.font_metrics import FontRegistry
from emboss.typography.line_breaking import (
    INFINITE_PENALTY,
    Box,
    Glue,
    LineBreaker,
    Penalty,
)
from emboss.typography.protrusion import right_protrusion
from emboss.writer import render_document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine(sheet=None):
    """Build a LayoutEngine on the corporate sheet (or an override)."""
    return LayoutEngine(FontRegistry(), sheet or resolve_preset("corporate"))


def _breaker_items():
    """Items where 'two,' fits on line one only with the comma credit."""
    return [
        Box(width=40.0, text="one", char_widths=(13.0, 13.0, 14.0)),
        Glue(width=10.0, stretch=4.5, shrink=3.0),
        Box(width=54.0, text="two,", char_widths=(15.0, 15.0, 14.0, 10.0)),
        Glue(width=10.0, stretch=4.5, shrink=3.0),
        Box(width=40.0, text="three", char_widths=(8.0,) * 5),
        Glue(width=0.0, stretch=INFINITE_PENALTY),
        Penalty(penalty=-INFINITE_PENALTY),
    ]


_COMMA_TEXT = (
    "alpha beta, gamma delta, epsilon zeta, eta theta, iota kappa, "
    "lambda mu, nu xi, omicron pi, rho sigma, tau upsilon, phi chi, "
    "psi omega, alpha beta, gamma delta, epsilon zeta, eta theta,"
)
_MEASURE = 160.0


def _justified_lines(engine, align="justify"):
    """Lay out the comma-heavy paragraph at a narrow measure."""
    sheet = engine.sheet
    style = sheet.resolved(sheet.body, Style(align=align, hyphenate=False))
    return engine._layout_runs([TextRun(_COMMA_TEXT)], style, _MEASURE), style


def _fragment_right_edge(engine, style, line):
    """X coordinate where a line's last fragment ends."""
    text, run, x = line.fragments[-1]
    return x + engine._metrics(style, run).text_width(text, engine._size(style, run))


def _grid_pages(grid=14.0, spanning_heading_every=7, count=40):
    """Paginate a mixed heading/paragraph document under a baseline grid."""
    sheet = replace(resolve_preset("corporate"), baseline_grid=grid)
    engine = _engine(sheet)
    spec = PageSpec()
    elements = []
    for i in range(count):
        if i % spanning_heading_every == 0:
            elements.append(Heading(f"Section {i}", level=2))
        elements.append(
            Paragraph("Filler text that wraps across a couple of lines. " * 3)
        )
    measured = [engine.measure(el, spec.content_width) for el in elements]
    return engine.paginate(measured, spec), spec


def _first_baseline(pb):
    return pb.y - pb.lines[0].ascent


def _grid_error(spec, baseline, grid=14.0):
    remainder = (spec.content_top - baseline) % grid
    return min(remainder, grid - remainder)


def _column_lefts(spec):
    col_w = (spec.content_width - spec.column_gap * (spec.columns - 1)) / spec.columns
    return [
        spec.margin_left + c * (col_w + spec.column_gap) for c in range(spec.columns)
    ]


def _balanced_pages(engine=None, count=60, columns=2):
    """Paginate identical paragraphs into a multicolumn page spec."""
    engine = engine or _engine()
    spec = PageSpec(columns=columns)
    col_w = (spec.content_width - spec.column_gap * (columns - 1)) / columns
    width = col_w if columns > 1 else spec.content_width
    elements = [
        Paragraph(f"Column filler paragraph number {i} with a bit of text. " * 2)
        for i in range(count)
    ]
    measured = [engine.measure(el, width) for el in elements]
    return engine.paginate(measured, spec), spec


def _placements(pages):
    """Comparable (page, x, y, height) tuples for every placed block."""
    return [
        (pg.number, round(pb.x, 6), round(pb.y, 6), round(pb.height, 6))
        for pg in pages
        for pb in pg.blocks
    ]


class _NoBalanceEngine(LayoutEngine):
    """Engine with last-page column balancing disabled."""

    def _balance_last_page(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# 4.2: right-margin protrusion in the breaker
# ---------------------------------------------------------------------------


class TestRightProtrusionInBreaker:
    def test_comma_line_gains_word_with_protrusion(self):
        """The comma credit lets 'two,' join line one; off it breaks early."""
        on = LineBreaker(protrusion=True).break_paragraph(_breaker_items(), 100.0)
        off = LineBreaker(protrusion=False).break_paragraph(_breaker_items(), 100.0)
        assert on[0].text == "one two,"
        assert off[0].text == "one"

    def test_credit_recorded_on_line(self):
        """The applied credit is the comma's char width times its factor."""
        on = LineBreaker(protrusion=True).break_paragraph(_breaker_items(), 100.0)
        assert on[0].protrusion_credit == 10.0 * right_protrusion(",")
        assert on[-1].protrusion_credit == 0.0

    def test_no_credit_when_protrusion_off(self):
        off = LineBreaker(protrusion=False).break_paragraph(_breaker_items(), 100.0)
        assert all(line.protrusion_credit == 0.0 for line in off)

    def test_comma_fragment_hangs_past_measure(self):
        """Justified comma-ended lines extend past the measure by the credit."""
        engine = _engine()
        lines, style = _justified_lines(engine)
        metrics = engine._metrics(style)
        credit = metrics.text_width(",", engine._size(style)) * right_protrusion(",")
        comma_lines = [
            line
            for line in lines
            if not line.is_last and line.fragments[-1][0].endswith(",")
        ]
        assert comma_lines, "construction must yield a comma-ended line"
        for line in comma_lines:
            overhang = _fragment_right_edge(engine, style, line) - _MEASURE
            assert abs(overhang - credit) < 1e-6

    def test_plain_justified_lines_end_at_measure(self):
        """Lines without protrudable endings still finish on the measure."""
        engine = _engine()
        lines, style = _justified_lines(engine)
        plain = [
            line
            for line in lines
            if not line.is_last and right_protrusion(line.fragments[-1][0][-1]) == 0.0
        ]
        assert plain
        for line in plain:
            edge = _fragment_right_edge(engine, style, line)
            assert abs(edge - _MEASURE) < 1e-6

    def test_ragged_right_unaffected(self):
        """Ragged-right lines never extend past the measure."""
        engine = _engine()
        lines, style = _justified_lines(engine, align="left")
        for line in lines:
            assert _fragment_right_edge(engine, style, line) <= _MEASURE + 1e-6

    def test_protrusion_determinism(self):
        """Two identical layouts produce identical fragment geometry."""
        first, _ = _justified_lines(_engine())
        second, _ = _justified_lines(_engine())
        assert [line.fragments for line in first] == [line.fragments for line in second]


# ---------------------------------------------------------------------------
# 4.5: baseline grid
# ---------------------------------------------------------------------------


class TestBaselineGrid:
    def test_presets_default_to_no_grid(self):
        assert all(sheet.baseline_grid is None for sheet in PRESETS.values())

    def test_first_baselines_on_grid_across_pages(self):
        """Every text block's first baseline lands on the 14pt grid."""
        pages, spec = _grid_pages()
        assert len(pages) >= 2
        checked = 0
        for page in pages:
            for pb in page.blocks:
                if not pb.lines:
                    continue
                if not isinstance(pb.block.element, (Paragraph, Heading)):
                    continue
                assert _grid_error(spec, _first_baseline(pb)) < 1e-6
                checked += 1
        assert checked > 10

    def test_grid_off_by_default_byte_identical(self):
        """An explicit baseline_grid=None sheet renders identical bytes."""

        def _doc(style):
            doc = Document(title="Grid", style=style)
            for i in range(20):
                doc.add(Paragraph(f"Paragraph {i} with some steady text. " * 3))
            return doc

        plain = render_document(_doc("corporate"))
        explicit = render_document(
            _doc(replace(resolve_preset("corporate"), baseline_grid=None))
        )
        assert plain == explicit

    def test_grid_changes_placement(self):
        """Turning the grid on actually moves baselines."""
        sheet = resolve_preset("corporate")
        specs = []
        for grid in (None, 14.0):
            engine = _engine(replace(sheet, baseline_grid=grid))
            spec = PageSpec()
            measured = [
                engine.measure(
                    Paragraph("Steady filler text. " * 6), spec.content_width
                )
                for _ in range(6)
            ]
            specs.append(_placements(engine.paginate(measured, spec)))
        assert specs[0] != specs[1]

    def test_heading_absorbs_delta_into_space_before(self):
        """Mid-page headings land on grid with a grown preceding gap."""
        pages, spec = _grid_pages()
        found = 0
        for page in pages:
            for i, pb in enumerate(page.blocks):
                if i == 0 or not isinstance(pb.block.element, Heading):
                    continue
                prev = page.blocks[i - 1]
                gap = (prev.y - prev.height) - pb.y
                nominal = prev.block.space_after + pb.block.space_before
                assert gap >= nominal - 1e-6
                assert _grid_error(spec, _first_baseline(pb)) < 1e-6
                found += 1
        assert found >= 1

    def test_non_text_blocks_not_snapped(self):
        """Rules keep their natural position; only text blocks snap."""
        from emboss.spec import HorizontalRule

        sheet = replace(resolve_preset("corporate"), baseline_grid=14.0)
        engine = _engine(sheet)
        spec = PageSpec()
        elements = [
            Paragraph("Lead paragraph before the rule. " * 3),
            HorizontalRule(),
            Paragraph("Trailing paragraph after the rule. " * 3),
        ]
        measured = [engine.measure(el, spec.content_width) for el in elements]
        page = engine.paginate(measured, spec)[0]
        first, rule = page.blocks[0], page.blocks[1]
        expected = first.y - first.height - first.block.space_after
        expected -= rule.block.space_before
        assert abs(rule.y - expected) < 1e-6

    def test_multicolumn_pages_share_grid(self):
        """Both columns snap first baselines to the same grid."""
        sheet = replace(resolve_preset("corporate"), baseline_grid=14.0)
        engine = _engine(sheet)
        pages, spec = _balanced_pages(engine=engine, count=30)
        checked = 0
        for page in pages:
            for pb in page.blocks:
                if pb.lines:
                    assert _grid_error(spec, _first_baseline(pb)) < 1e-6
                    checked += 1
        assert checked > 10

    def test_grid_determinism(self):
        assert _placements(_grid_pages()[0]) == _placements(_grid_pages()[0])


# ---------------------------------------------------------------------------
# 4.6: column balancing on the final page
# ---------------------------------------------------------------------------


class TestColumnBalancing:
    def test_last_page_delta_within_tallest_block(self):
        """Balanced column heights differ by at most one block's extent."""
        pages, spec = _balanced_pages()
        assert len(pages) >= 2
        last = pages[-1]
        used = []
        for left in _column_lefts(spec):
            col = [pb for pb in last.blocks if abs(pb.x - left) < 1e-6]
            assert col, "every column on the balanced page is populated"
            bottom = min(pb.y - pb.height for pb in col)
            used.append(spec.content_top - bottom)
        tallest = max(
            pb.height + pb.block.space_before + pb.block.space_after
            for pb in last.blocks
        )
        assert max(used) - min(used) <= tallest + 1e-6

    def test_full_pages_unchanged(self):
        """Balancing rewrites only the final page of the document."""
        balanced, _ = _balanced_pages(engine=_engine())
        greedy, _ = _balanced_pages(
            engine=_NoBalanceEngine(FontRegistry(), resolve_preset("corporate"))
        )
        assert len(balanced) == len(greedy)
        assert _placements(balanced[:-1]) == _placements(greedy[:-1])
        assert _placements([balanced[-1]]) != _placements([greedy[-1]])

    def test_single_column_unaffected(self):
        """Single-column pagination is identical with balancing available."""
        balanced, _ = _balanced_pages(engine=_engine(), columns=1)
        greedy, _ = _balanced_pages(
            engine=_NoBalanceEngine(FontRegistry(), resolve_preset("corporate")),
            columns=1,
        )
        assert _placements(balanced) == _placements(greedy)

    def test_balancing_determinism(self):
        first, _ = _balanced_pages()
        second, _ = _balanced_pages()
        assert _placements(first) == _placements(second)

    def test_two_column_document_renders_deterministically(self):
        """End-to-end two-column render is byte-stable across runs."""

        def _render():
            doc = Document(title="Columns", page=PageSpec(columns=2))
            for i in range(40):
                doc.add(Paragraph(f"Two column body text number {i}. " * 3))
            return render_document(doc)

        assert _render() == _render()
