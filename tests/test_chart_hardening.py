"""Tests for chart hardening: honest axes, no truncation, patterns, facts."""

from __future__ import annotations

import math

import pytest

from emboss import Series
from emboss.chart_facts import compute_facts, fact_sentence, verify_caption
from emboss.charts import (
    ChartData,
    ChartSpec,
    format_value,
    render_chart,
    series_summary,
    validate_chart,
)
from emboss.pdf.objects import fmt_number
from emboss.pdf.streams import ContentStream
from emboss.spec import Chart

X, Y, W, H, FONT = 72.0, 700.0, 400.0, 250.0, 10.0
PLOT_X = X + 50.0
PLOT_Y = Y - H + FONT + 14.0
PLOT_W = W - 60.0
PLOT_H = H - (FONT + 14.0) - 10.0


def _render(data, chart_type="bar", mode="rgb", **kw):
    stream = ContentStream(color_mode=mode)
    spec = ChartSpec(chart_type=chart_type, data=data, **kw)
    render_chart(stream, spec, X, Y, "F1", FONT)
    return stream.to_bytes()


def _rects(ops):
    out = []
    for line in ops.split(b"\n"):
        parts = line.split()
        if len(parts) == 5 and parts[-1] == b"re":
            out.append(tuple(float(p) for p in parts[:4]))
    return out


class TestZeroBaseline:
    def test_all_positive_bars_start_at_zero_tick(self):
        data = ChartData(labels=["Q1", "Q2", "Q3"], values=[1200.0, 2400.0, 4000.0])
        ops = _render(data)
        assert b"(0)" in ops  # first tick is zero: bars are never truncated
        for _bx, by, _bw, bh in _rects(ops):
            assert by == pytest.approx(PLOT_Y, abs=0.01)
            assert bh > 0

    def test_negative_bars_extend_below_zero_axis(self):
        data = ChartData(labels=["A", "B"], values=[10.0, -5.0])
        ops = _render(data)
        min_v = -5.0 * 1.1
        rng = 10.0 * 1.1 - min_v
        zero_y = PLOT_Y + (0.0 - min_v) / rng * PLOT_H
        rects = _rects(ops)
        assert len(rects) == 2
        pos = [r for r in rects if r[1] == pytest.approx(zero_y, abs=0.01)]
        neg = [r for r in rects if r[1] < zero_y - 1.0]
        assert len(pos) == 1 and len(neg) == 1
        assert neg[0][1] + neg[0][3] == pytest.approx(zero_y, abs=0.01)
        # x-axis is drawn at the zero line, not at the plot bottom
        axis_m = b" ".join([fmt_number(PLOT_X), fmt_number(zero_y), b"m"])
        assert axis_m in ops

    def test_tick_labels_use_thousands_separators(self):
        data = ChartData(labels=["Q1", "Q2"], values=[1200.0, 4000.0])
        ops = _render(data)
        assert b"(1,100)" in ops
        assert b"(4,400)" in ops

    def test_tick_labels_use_m_suffix_for_millions(self):
        data = ChartData(labels=["a"], values=[2_000_000.0])
        ops = _render(data)
        assert b"(2.2M)" in ops
        assert b"(550,000)" in ops

    def test_line_chart_min_tick_labeled(self):
        data = ChartData(labels=["a", "b"], values=[-10.0, 30.0])
        ops = _render(data, "line")
        assert b"(-10)" in ops

    def test_format_value_unified(self):
        assert format_value(999) == "999"
        assert format_value(1200) == "1,200"
        assert format_value(1234.5) == "1,234.5"
        assert format_value(1_200_000) == "1.2M"
        assert format_value(12.5) == "12.5"
        assert format_value(-4500) == "-4,500"


class TestLabelFitting:
    def test_long_category_label_wraps_to_two_lines(self):
        labels = [f"c{i}" for i in range(7)] + ["Northern Region"]
        data = ChartData(labels=labels, values=[float(i + 1) for i in range(8)])
        ops = _render(data)
        assert b"(Northern Region)" not in ops
        assert b"(Northern)" in ops
        assert b"(Region)" in ops

    def test_unbreakable_label_rotates_30_degrees(self):
        word = "Antidisestablishmentarianism"
        labels = [f"c{i}" for i in range(7)] + [word]
        data = ChartData(labels=labels, values=[float(i + 1) for i in range(8)])
        ops = _render(data)
        assert f"({word})".encode() in ops  # full text, never chopped
        cos = fmt_number(math.cos(math.radians(-30.0)))
        sin = fmt_number(math.sin(math.radians(-30.0)))
        prefix = b" ".join([cos, sin, fmt_number(0.5), cos]) + b" "
        rotated = [op for op in ops.split(b"\n") if op.endswith(b"Tm")]
        assert any(op.startswith(prefix) for op in rotated)

    def test_rotated_label_shrinks_to_min_6pt(self):
        word = "Antidisestablishmentarianism"
        labels = [f"c{i}" for i in range(15)] + [word]
        data = ChartData(labels=labels, values=[1.0] * 16)
        ops = _render(data)
        assert f"({word})".encode() in ops
        assert b"/F1 6 Tf" in ops

    def test_legend_grows_for_long_labels(self):
        long_name = "An Extremely Long Series Name For The Legend"
        series = [Series("A", [1.0, 2.0]), Series(long_name, [2.0, 1.0])]
        short = [Series("A", [1.0, 2.0]), Series("B", [2.0, 1.0])]
        ops = _render(ChartData(labels=["x", "y"], values=[], series=series), "line")
        ops_short = _render(
            ChartData(labels=["x", "y"], values=[], series=short), "line"
        )
        assert f"({long_name})".encode() in ops  # complete, not truncated
        long_lx = min(r[0] for r in _rects(ops))
        short_lx = min(r[0] for r in _rects(ops_short))
        assert long_lx < short_lx  # legend box grew leftward to fit

    def test_legend_wraps_when_wider_than_chart(self):
        long_name = (
            "An Extraordinarily Long Series Name That Cannot Fit On One Legend Row"
        )
        series = [Series(long_name, [1.0, 2.0])]
        data = ChartData(labels=["x", "y"], values=[], series=series)
        ops = _render(data, "line", width=200.0)
        assert f"({long_name})".encode() not in ops  # wrapped over rows
        texts = [op for op in ops.split(b"\n") if op.endswith(b"Tj")]
        assert any(b"An Extraordinarily" in op for op in texts)
        assert any(b"Legend Row)" in op for op in texts)
        assert len(_rects(ops)) == 1  # still exactly one swatch

    def test_pie_labels_not_truncated(self):
        data = ChartData(
            labels=["Infrastructure Modernization", "Ops"], values=[60.0, 40.0]
        )
        ops = _render(data, "pie")
        assert b"(Infrastructure Modernization \\(60%\\))" in ops


class TestValueLabelThinning:
    def _data(self, count):
        return ChartData(
            labels=[f"c{i}" for i in range(count)],
            values=[12300.0 + 10.0 * i for i in range(count)],
        )

    def test_overlapping_labels_thinned_every_other(self):
        ops = _render(self._data(20))
        assert ops.count(b"(12,3") + ops.count(b"(12,4") == 10  # every other kept

    def test_wide_slots_keep_every_label(self):
        ops = _render(self._data(20), width=1200.0)
        assert ops.count(b"(12,3") + ops.count(b"(12,4") == 20

    def test_thinning_deterministic(self):
        assert _render(self._data(20)) == _render(self._data(20))


class TestPatterns:
    def _ops(self, mode="rgb"):
        data = ChartData(labels=["a", "b", "c", "d"], values=[10.0] * 4, patterns=True)
        return _render(data, mode=mode)

    def test_each_bar_gets_clipped_pattern(self):
        ops = self._ops()
        clips = [op for op in ops.split(b"\n") if op.endswith(b"re W n")]
        assert len(clips) == 4

    def test_pattern_types_differ_per_series(self):
        ops = self._ops()
        lines = ops.split(b"\n")
        shapes = []
        for i, op in enumerate(lines):
            if op.endswith(b"re W n"):
                block = b"\n".join(lines[i : i + 6])
                shapes.append((block.count(b" l "), b"1 J" in block))
        assert len(shapes) == 4
        assert len(set(shapes)) == 4  # hatch, dots, crosshatch, horizontal

    def test_dots_use_round_caps(self):
        assert b"1 J" in self._ops()

    def test_patterns_off_by_default(self):
        data = ChartData(labels=["a", "b"], values=[1.0, 2.0])
        assert b"W n" not in _render(data)

    def test_cmyk_patterns_use_k_operators(self):
        ops = self._ops(mode="cmyk")
        assert b"0 0 0 0 K" in ops  # white pattern strokes through the funnel
        assert b"RG" not in ops
        assert b"rg" not in ops

    def test_pie_wedge_patterns_clip_to_wedge(self):
        data = ChartData(labels=["a", "b"], values=[60.0, 40.0], patterns=True)
        ops = _render(data, "pie")
        assert ops.count(b"W n") == 2
        assert b"1 J" in ops  # second wedge gets the dots pattern


class TestRefusals:
    def test_pie_negative_value_rejected(self):
        data = ChartData(labels=["a", "b"], values=[5.0, -3.0])
        with pytest.raises(ValueError, match="negative.*'b'.*-3"):
            _render(data, "pie")

    def test_pie_zero_sum_rejected(self):
        data = ChartData(labels=["a", "b"], values=[0.0, 0.0])
        with pytest.raises(ValueError, match="sum to zero"):
            _render(data, "pie")

    def test_single_point_line_rejected(self):
        data = ChartData(labels=["A"], values=[10.0])
        with pytest.raises(ValueError, match="line chart.*at least 2.*got 1"):
            _render(data, "line")

    def test_single_point_scatter_rejected(self):
        data = ChartData(labels=["A"], values=[10.0])
        with pytest.raises(ValueError, match="scatter chart.*at least 2"):
            _render(data, "scatter")

    def test_series_length_mismatch_rejected(self):
        series = [Series("A", [1.0, 2.0]), Series("B", [1.0])]
        data = ChartData(labels=["x", "y"], values=[], series=series)
        with pytest.raises(ValueError, match="mismatched lengths"):
            _render(data, "bar")

    def test_empty_chart_still_renders_silently(self):
        data = ChartData(labels=[], values=[])
        validate_chart(ChartSpec(chart_type="bar", data=data))
        _render(data, "bar")

    def test_validate_chart_direct(self):
        data = ChartData(labels=["a", "b"], values=[1.0, 2.0])
        validate_chart(ChartSpec(chart_type="line", data=data))  # no raise


REVENUE = Chart(
    chart_type="line",
    labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
    series=[Series("Revenue", [100.0, 120.0, 90.0, 140.0, 160.0, 112.0])],
)


class TestComputeFacts:
    def test_known_series_exact_values(self):
        facts = compute_facts(REVENUE)
        s = facts["series"]["Revenue"]
        assert s["min"] == 90.0
        assert s["max"] == 160.0
        assert s["first"] == 100.0
        assert s["last"] == 112.0
        assert s["mean"] == 120.3333
        assert s["total"] == 722.0
        assert s["pct_change"] == 12.0
        assert s["direction"] == "rising"
        assert s["max_category"] == "May"
        assert s["min_category"] == "Mar"
        assert facts["direction"] == "rising"
        assert facts["largest_category"] == "May"
        assert facts["smallest_category"] == "Mar"
        assert facts["series_count"] == 1
        assert facts["category_count"] == 6
        assert facts["total"] == 722.0

    def test_pie_shares(self):
        chart = Chart(chart_type="pie", labels=["a", "b"], values=[30.0, 70.0])
        facts = compute_facts(chart)
        assert facts["shares"] == {"a": 30.0, "b": 70.0}

    def test_flat_direction_within_one_percent(self):
        chart = Chart(chart_type="line", labels=["a", "b"], values=[1000.0, 1005.0])
        assert compute_facts(chart)["direction"] == "flat"

    def test_deterministic(self):
        assert compute_facts(REVENUE) == compute_facts(REVENUE)


class TestVerifyCaption:
    def test_caption_using_only_facts_passes(self):
        facts = compute_facts(REVENUE)
        caption = "Revenue rose 12.0% from Jan to Jun, peaking at 160 in May."
        assert verify_caption(caption, facts) == []

    def test_fabricated_number_flagged(self):
        facts = compute_facts(REVENUE)
        violations = verify_caption("Revenue hit 500 in May.", facts)
        assert len(violations) == 1
        assert "'500'" in violations[0]

    def test_one_percent_rounding_tolerated(self):
        facts = compute_facts(REVENUE)
        assert verify_caption("Revenue peaked near 159.", facts) == []

    def test_small_integers_exempt(self):
        facts = compute_facts(REVENUE)
        assert verify_caption("Across 6 months the top 3 held.", facts) == []

    def test_suffixes_and_separators_parsed(self):
        chart = Chart(
            chart_type="line",
            labels=["Jan", "Jun"],
            series=[Series("Sales", [1200.0, 4_200_000.0])],
        )
        facts = compute_facts(chart)
        assert verify_caption("Sales grew from 1,200 to $4.2M.", facts) == []
        violations = verify_caption("Sales grew to $9.9M.", facts)
        assert len(violations) == 1


class TestFactSentence:
    def test_deterministic_and_self_verifying(self):
        sentence = fact_sentence(REVENUE)
        assert sentence == fact_sentence(REVENUE)
        assert "rose" in sentence
        assert "Revenue" in sentence
        assert verify_caption(sentence, compute_facts(REVENUE)) == []

    def test_bar_sentence_self_verifying(self):
        chart = Chart(
            chart_type="bar", labels=["North", "South"], values=[4200.0, 1100.0]
        )
        sentence = fact_sentence(chart)
        assert "North" in sentence and "South" in sentence
        assert verify_caption(sentence, compute_facts(chart)) == []

    def test_pie_sentence_self_verifying(self):
        chart = Chart(chart_type="pie", labels=["a", "b"], values=[30.0, 70.0])
        sentence = fact_sentence(chart)
        assert "70.0%" in sentence
        assert verify_caption(sentence, compute_facts(chart)) == []

    def test_falling_and_flat_phrasing(self):
        falling = Chart(
            chart_type="line",
            labels=["Jan", "Feb"],
            series=[Series("Churn", [10.0, 5.0])],
        )
        assert "fell" in fact_sentence(falling)
        flat = Chart(
            chart_type="line",
            labels=["Jan", "Feb"],
            series=[Series("Churn", [10.0, 10.0])],
        )
        assert "held flat" in fact_sentence(flat)

    def test_empty_chart_gives_empty_sentence(self):
        assert fact_sentence(Chart(chart_type="bar", labels=[], values=[])) == ""


class TestAltText:
    def test_series_summary_includes_direction_and_range(self):
        text = series_summary(REVENUE)
        assert "rising" in text
        assert "range 90 to 160" in text
        assert text == series_summary(REVENUE)

    def test_values_only_summary_unchanged(self):
        chart = Chart(chart_type="pie", labels=["a", "b"], values=[1.0, 2.0])
        assert series_summary(chart) == "pie chart; 2 categories"


class TestDeterminism:
    def test_hardened_features_double_render_identical(self):
        data = ChartData(
            labels=["Northern Region", "S", "A Very Long Unbreakable-Label-Here"],
            values=[10.0, -5.0, 7.0],
            patterns=True,
        )
        assert _render(data) == _render(data)
        series = [Series("Alpha", [1.0, -2.0]), Series("Beta", [2.0, 3.0])]
        multi = ChartData(labels=["x", "y"], values=[], series=series, patterns=True)
        for kind in ("bar", "line", "scatter"):
            assert _render(multi, kind) == _render(multi, kind)
        pie = ChartData(labels=["a", "b"], values=[60.0, 40.0], patterns=True)
        assert _render(pie, "pie") == _render(pie, "pie")
