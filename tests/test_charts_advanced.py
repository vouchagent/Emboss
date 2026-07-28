"""Tests for multi-series charts: grouped bars, scatter, legends, axis titles."""

import json

import pytest

from emboss import Document, Series
from emboss.charts import (
    DEFAULT_COLORS,
    ChartData,
    ChartSpec,
    render_chart,
    series_summary,
)
from emboss.pdf.objects import fmt_number
from emboss.pdf.streams import ContentStream, hex_color
from emboss.spec import Chart


def _render(data, chart_type="bar", mode="rgb", **kw):
    stream = ContentStream(color_mode=mode)
    spec = ChartSpec(chart_type=chart_type, data=data, **kw)
    render_chart(stream, spec, 72.0, 700.0, "F1", 10.0)
    return stream.to_bytes()


def _color_op(hex_str, op):
    channels = b" ".join(fmt_number(c) for c in hex_color(hex_str))
    return channels + b" " + op


class TestBackCompat:
    def test_labels_values_identical_to_one_unnamed_series(self):
        labels = ["Q1", "Q2", "Q3"]
        values = [10.0, 25.0, 15.0]
        for kind in ("bar", "line", "pie", "scatter"):
            legacy = _render(ChartData(labels=labels, values=values), kind)
            modern = _render(
                ChartData(labels=labels, values=[], series=[Series("", values)]),
                kind,
            )
            assert legacy == modern

    def test_entry_point_signature_positional(self):
        stream = ContentStream()
        spec = ChartSpec("bar", ChartData(["A"], [1.0]), 300.0, 200.0)
        render_chart(stream, spec, 72.0, 700.0, "F1", 10.0)
        assert b"re" in stream.to_bytes()


class TestGroupedBars:
    def test_n_series_m_labels_filled_rects(self):
        series = [
            Series("Alpha", [1.0, 2.0, 3.0, 4.0]),
            Series("Beta", [2.0, 3.0, 4.0, 5.0]),
            Series("Gamma", [3.0, 4.0, 5.0, 6.0]),
        ]
        data = ChartData(
            labels=["W", "X", "Y", "Z"], values=[], series=series, legend=False
        )
        ops = _render(data, "bar")
        assert ops.count(b" re") == 3 * 4

    def test_series_colors_follow_default_palette(self):
        series = [Series("A", [1.0, 2.0]), Series("B", [2.0, 1.0])]
        data = ChartData(labels=["x", "y"], values=[], series=series, legend=False)
        ops = _render(data, "bar")
        assert _color_op(DEFAULT_COLORS[0], b"rg") in ops
        assert _color_op(DEFAULT_COLORS[1], b"rg") in ops


class TestMultiLine:
    def test_two_polylines_distinct_colors(self):
        series = [Series("A", [1.0, 3.0, 2.0]), Series("B", [2.0, 1.0, 4.0])]
        data = ChartData(labels=["x", "y", "z"], values=[], series=series)
        ops = _render(data, "line")
        first = _color_op(DEFAULT_COLORS[0], b"RG")
        second = _color_op(DEFAULT_COLORS[1], b"RG")
        assert first != second
        assert ops.count(first) == 1
        assert ops.count(second) == 1

    def test_markers_are_bezier_circles(self):
        data = ChartData(labels=["x", "y"], values=[1.0, 2.0])
        ops = _render(data, "line")
        assert b" c" in ops


class TestScatter:
    def test_markers_but_no_connecting_polyline(self):
        series = [Series("A", [1.0, 3.0]), Series("B", [2.0, 1.0])]
        data = ChartData(labels=["x", "y"], values=[], series=series)
        ops = _render(data, "scatter")
        for color in (DEFAULT_COLORS[0], DEFAULT_COLORS[1]):
            assert _color_op(color, b"rg") in ops  # marker fills
            assert _color_op(color, b"RG") not in ops  # no series strokes
        assert b" c" in ops


class TestLegend:
    def _series(self):
        return [
            Series("North", [1.0, 2.0]),
            Series("South", [2.0, 3.0]),
            Series("West", [3.0, 1.0]),
        ]

    def test_swatch_count_equals_series_count(self):
        data = ChartData(labels=["a", "b"], values=[], series=self._series())
        ops = _render(data, "line")
        assert ops.count(b" re") == 3  # only legend swatches draw rects
        for name in (b"(North)", b"(South)", b"(West)"):
            assert name in ops

    def test_absent_when_legend_false(self):
        data = ChartData(
            labels=["a", "b"], values=[], series=self._series(), legend=False
        )
        ops = _render(data, "line")
        assert ops.count(b" re") == 0

    def test_absent_for_unnamed_series(self):
        data = ChartData(labels=["a", "b"], values=[1.0, 2.0])
        ops = _render(data, "line")
        assert ops.count(b" re") == 0


class TestAxisTitles:
    def test_titles_present(self):
        data = ChartData(
            labels=["a", "b"], values=[1.0, 2.0], x_title="Quarter", y_title="Units"
        )
        ops = _render(data, "bar")
        assert b"(Quarter)" in ops
        assert b"(Units)" in ops

    def test_y_title_uses_90_degree_rotation_matrix(self):
        data = ChartData(labels=["a"], values=[1.0], y_title="Units")
        ops = _render(data, "bar")
        rotated = [op for op in ops.split(b"\n") if op.endswith(b"Tm")]
        assert any(op.startswith(b"0 1 -1 0 ") for op in rotated)

    def test_x_title_not_rotated(self):
        data = ChartData(labels=["a"], values=[1.0], x_title="Quarter")
        ops = _render(data, "bar")
        assert b"(Quarter)" in ops
        assert not any(
            op.startswith(b"0 1 -1 0 ") for op in ops.split(b"\n") if op.endswith(b"Tm")
        )


class TestPie:
    def test_pie_uses_first_series_only(self):
        first = Series("A", [60.0, 40.0])
        both = ChartData(
            labels=["x", "y"],
            values=[],
            series=[first, Series("B", [1.0, 2.0])],
            legend=False,
        )
        only = ChartData(labels=["x", "y"], values=[], series=[first], legend=False)
        assert _render(both, "pie") == _render(only, "pie")


class TestSeriesSummary:
    def test_mentions_series_labels(self):
        chart = Chart(
            chart_type="bar",
            labels=["Q1", "Q2"],
            series=[Series("North", [1.0, 2.0]), Series("South", [2.0, 3.0])],
            title="Revenue",
        )
        text = series_summary(chart)
        assert "North" in text
        assert "South" in text
        assert "bar chart" in text
        assert "Revenue" in text
        assert text == series_summary(chart)

    def test_single_series_chart(self):
        chart = Chart(chart_type="pie", labels=["a", "b"], values=[1.0, 2.0])
        text = series_summary(chart)
        assert text == "pie chart; 2 categories"


class TestSpecJson:
    SPEC = {
        "title": "Charts",
        "content": [
            {
                "type": "chart",
                "chart_type": "scatter",
                "labels": ["Q1", "Q2"],
                "series": [
                    {"label": "North", "values": [100, 150]},
                    {"label": "South", "values": [90, 120]},
                ],
                "x_title": "Quarter",
                "y_title": "Units",
            },
        ],
    }

    def test_multiseries_chart_parses_and_renders(self):
        pytest.importorskip("pydantic")
        from emboss import parse_spec_json

        doc = parse_spec_json(json.dumps(self.SPEC), strict=True)
        chart = doc.content[0]
        assert isinstance(chart, Chart)
        assert chart.chart_type == "scatter"
        assert [s.label for s in chart.series] == ["North", "South"]
        assert chart.x_title == "Quarter"
        assert chart.y_title == "Units"
        assert chart.legend is True
        pdf = doc.render()
        assert pdf.startswith(b"%PDF")

    def test_caption_normalizes_to_title(self):
        pytest.importorskip("pydantic")
        from emboss import parse_spec_json

        data = {
            "title": "T",
            "content": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "labels": ["a"],
                    "values": [1],
                    "caption": "Revenue",
                },
            ],
        }
        doc = parse_spec_json(json.dumps(data), strict=True)
        assert doc.content[0].title == "Revenue"

    def test_chart_without_values_or_series_rejected(self):
        pydantic = pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import ChartSpec as PChartSpec

        with pytest.raises(pydantic.ValidationError):
            PChartSpec(type="chart", chart_type="bar", labels=["a"])


class TestCmyk:
    def test_cmyk_chart_emits_k_not_rg(self):
        series = [Series("A", [1.0, 2.0]), Series("B", [2.0, 1.0])]
        for kind in ("bar", "line", "pie", "scatter"):
            data = ChartData(
                labels=["x", "y"],
                values=[],
                series=series,
                title="T",
                x_title="X",
                y_title="Y",
            )
            ops = _render(data, kind, mode="cmyk")
            assert b" k" in ops
            if kind != "pie":  # pie is fill-only, no stroked axes
                assert b" K" in ops
            assert b"rg" not in ops
            assert b"RG" not in ops


class TestDeterminism:
    def test_double_render_identical_ops(self):
        series = [Series("North", [1.0, 2.0, 3.0]), Series("South", [3.0, 2.0, 1.0])]
        for kind in ("bar", "line", "pie", "scatter"):
            data = ChartData(
                labels=["a", "b", "c"],
                values=[],
                series=series,
                title="T",
                x_title="X",
                y_title="Y",
            )
            assert _render(data, kind) == _render(data, kind)

    def test_double_document_build_identical_bytes(self):
        def build():
            doc = Document(title="Charts")
            doc.add(
                Chart(
                    chart_type="line",
                    labels=["Q1", "Q2"],
                    series=[
                        Series("North", [10.0, 20.0]),
                        Series("South", [15.0, 5.0]),
                    ],
                    x_title="Quarter",
                    y_title="Units",
                )
            )
            return doc.render()

        assert build() == build()
