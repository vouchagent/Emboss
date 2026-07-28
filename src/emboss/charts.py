"""Chart rendering directly to PDF content streams.

Draws bar, line, pie, and scatter charts using primitive PDF operators —
no external charting library required. Charts are vector graphics and
render at any zoom level. Data is either a single unnamed series
(``labels`` + ``values``) or a list of named series for grouped bars,
multi-line, and scatter charts. Pie charts use the first series only.

All color output goes through the mode-aware ``set_fill``/``set_stroke``
funnel on ContentStream so CMYK documents emit k/K operators.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .pdf.streams import ContentStream
from .typography.font_metrics import FontMetrics

__all__ = ["ChartData", "ChartSpec", "render_chart", "series_summary"]

DEFAULT_COLORS = [
    "3b82f6",
    "ef4444",
    "22c55e",
    "f59e0b",
    "8b5cf6",
    "ec4899",
    "06b6d4",
    "f97316",
]

_AXIS_COLOR = "44403c"
_GRID_COLOR = "e5e5e5"
_LABEL_COLOR = "57534e"
_MARKER_RADIUS = 2.0

_label_metrics: FontMetrics | None = None


def _measure_label(text: str, size: float) -> float:
    """Measure a chart label in points using Helvetica base-14 metrics."""
    global _label_metrics
    if _label_metrics is None:
        _label_metrics = FontMetrics.base14("Helvetica")
    return _label_metrics.text_width(text, size)


@dataclass
class ChartData:
    """Data for a chart.

    ``series`` holds objects exposing ``label``/``values`` (emboss.Series);
    when omitted, ``labels`` + ``values`` form one unnamed series.
    """

    labels: list[str]
    values: list[float]
    colors: list[str] | None = None
    title: str | None = None
    series: list | None = None
    x_title: str | None = None
    y_title: str | None = None
    legend: bool = True


@dataclass
class ChartSpec:
    """Complete chart specification."""

    chart_type: str  # "bar", "line", "pie", "scatter"
    data: ChartData
    width: float = 400.0
    height: float = 250.0


def series_summary(chart) -> str:
    """Return a deterministic alt-text summary naming each chart series."""
    kind = getattr(chart, "chart_type", "chart")
    title = getattr(chart, "title", None)
    series = list(getattr(chart, "series", None) or [])
    head = f"{kind} chart"
    if title:
        head += f": {title}"
    parts = [head]
    if series:
        names = ", ".join(
            getattr(s, "label", "") or f"series {i + 1}" for i, s in enumerate(series)
        )
        parts.append(f"{len(series)} series ({names})")
    categories = list(getattr(chart, "labels", None) or [])
    if categories:
        parts.append(f"{len(categories)} categories")
    return "; ".join(parts)


def _normalized_series(data: ChartData) -> list[tuple[str, list[float]]]:
    """Return chart data as (label, values) pairs; labels+values = one series."""
    if data.series:
        return [
            (getattr(s, "label", "") or "", [float(v) for v in s.values])
            for s in data.series
        ]
    return [("", [float(v) for v in data.values])]


def _palette(data: ChartData) -> list[str]:
    """Return the color cycle: explicit colors or the deterministic default."""
    return list(data.colors) if data.colors else list(DEFAULT_COLORS)


def render_chart(
    stream: ContentStream,
    chart: ChartSpec,
    x: float,
    y: float,
    font_key: str,
    font_size: float,
) -> None:
    """Draw a chart into a content stream.

    The chart occupies the rectangle from (x, y - height) to (x + width, y).
    """
    data = chart.data
    series = _normalized_series(data)
    width = chart.width
    height = chart.height

    stream.save()

    if data.title:
        title_size = font_size + 2
        stream.text_line(
            data.title,
            font_key,
            title_size,
            x + (chart.width - len(data.title) * title_size * 0.5) / 2,
            y - title_size - 2,
            _AXIS_COLOR,
        )
        y -= title_size + 10
        height -= title_size + 10

    if chart.chart_type != "pie":
        x, y, width, height = _draw_axis_titles(
            stream, data, x, y, width, height, font_key, font_size
        )

    if chart.chart_type == "bar":
        _draw_bar_chart(stream, data, series, x, y, width, height, font_key, font_size)
    elif chart.chart_type in ("line", "scatter"):
        _draw_point_chart(
            stream,
            data,
            series,
            x,
            y,
            width,
            height,
            font_key,
            font_size,
            connect=chart.chart_type == "line",
        )
    elif chart.chart_type == "pie":
        _draw_pie_chart(stream, data, series, x, y, width, height, font_key, font_size)

    if data.legend and any(label for label, _ in series):
        _draw_legend(stream, data, series, x, y, width, font_key, font_size)

    stream.restore()


# ---------------------------------------------------------------------------
# Axis titles and legend
# ---------------------------------------------------------------------------


def _draw_axis_titles(
    stream: ContentStream,
    data: ChartData,
    x: float,
    y: float,
    width: float,
    height: float,
    font_key: str,
    font_size: float,
) -> tuple[float, float, float, float]:
    """Draw x/y axis titles and return the reduced chart rectangle."""
    size = font_size * 0.85
    strip = size + 6.0
    if data.y_title:
        ty = y - height / 2 - _measure_label(data.y_title, size) / 2
        stream.rotated_text(data.y_title, font_key, size, x + size, ty, _AXIS_COLOR, 90)
        x += strip
        width -= strip
    if data.x_title:
        tx = x + (width - _measure_label(data.x_title, size)) / 2
        stream.text_line(data.x_title, font_key, size, tx, y - height + 2, _AXIS_COLOR)
        height -= strip
    return x, y, width, height


def _draw_legend(
    stream: ContentStream,
    data: ChartData,
    series: list[tuple[str, list[float]]],
    x: float,
    y: float,
    width: float,
    font_key: str,
    font_size: float,
) -> None:
    """Draw swatch+label legend rows in the top-right of the chart area."""
    palette = _palette(data)
    entries = [
        (label, palette[j % len(palette)])
        for j, (label, _values) in enumerate(series)
        if label
    ]
    if not entries:
        return

    size = font_size * 0.75
    swatch = 6.0
    pad = 4.0
    row_h = size + 4.0
    text_w = max(_measure_label(label, size) for label, _color in entries)
    box_w = pad + swatch + 4.0 + text_w + pad

    lx = x + width - box_w - 6.0
    ly = y - 6.0
    for k, (label, color) in enumerate(entries):
        row_top = ly - k * row_h
        stream.rect(lx + pad, row_top - swatch, swatch, swatch, fill=color)
        stream.text_line(
            label,
            font_key,
            size,
            lx + pad + swatch + 4.0,
            row_top - swatch + 1.0,
            _AXIS_COLOR,
        )


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------


def _draw_bar_chart(
    stream: ContentStream,
    data: ChartData,
    series: list[tuple[str, list[float]]],
    x: float,
    y: float,
    width: float,
    height: float,
    font_key: str,
    font_size: float,
) -> None:
    labels = [str(label) for label in data.labels]
    count = max([len(values) for _label, values in series] + [len(labels)])
    all_values = [v for _label, values in series for v in values]
    if count == 0 or not all_values:
        return

    margin_left = 50.0
    margin_bottom = font_size + 14
    margin_right = 10.0
    margin_top = 10.0

    plot_x = x + margin_left
    plot_y = y - height + margin_bottom
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_bottom - margin_top

    max_val = max(abs(v) for v in all_values) or 1
    max_val *= 1.1

    # Y-axis gridlines
    for i in range(5):
        gy = plot_y + plot_h * i / 4
        val = max_val * i / 4
        stream.line(plot_x, gy, plot_x + plot_w, gy, color=_GRID_COLOR, width=0.3)
        label = _format_value(val)
        stream.text_line(
            label, font_key, font_size * 0.8, x + 4, gy - font_size * 0.3, _LABEL_COLOR
        )

    # Axes
    stream.line(plot_x, plot_y, plot_x + plot_w, plot_y, color=_AXIS_COLOR, width=0.8)
    stream.line(plot_x, plot_y, plot_x, plot_y + plot_h, color=_AXIS_COLOR, width=0.8)

    # Bars: one group per label, series side by side within the group
    palette = _palette(data)
    single = len(series) == 1
    zone = plot_w / count
    group_w = zone * 0.65
    gap = zone * 0.175
    bar_w = group_w / len(series)

    for i in range(count):
        for j, (_label, values) in enumerate(series):
            if i >= len(values):
                continue
            value = values[i]
            bar_h = abs(value) / max_val * plot_h
            bx = plot_x + i * zone + gap + j * bar_w
            color = palette[i % len(palette)] if single else palette[j % len(palette)]
            stream.rect(bx, plot_y, bar_w, bar_h, fill=color)

            if single:
                val_text = _format_value(value)
                stream.text_line(
                    val_text,
                    font_key,
                    font_size * 0.75,
                    bx + bar_w * 0.15,
                    plot_y + bar_h + 3,
                    _AXIS_COLOR,
                )

        if i < len(labels):
            lx = plot_x + i * zone + gap + group_w * 0.1
            ly = plot_y - font_size - 2
            stream.text_line(
                labels[i][:10], font_key, font_size * 0.75, lx, ly, _LABEL_COLOR
            )


# ---------------------------------------------------------------------------
# Line and scatter charts
# ---------------------------------------------------------------------------


def _draw_point_chart(
    stream: ContentStream,
    data: ChartData,
    series: list[tuple[str, list[float]]],
    x: float,
    y: float,
    width: float,
    height: float,
    font_key: str,
    font_size: float,
    connect: bool,
) -> None:
    """Draw a line chart (connect=True) or scatter chart (markers only)."""
    labels = [str(label) for label in data.labels]
    count = max([len(values) for _label, values in series] + [0])
    all_values = [v for _label, values in series for v in values]
    if count == 0 or not all_values:
        return

    margin_left = 50.0
    margin_bottom = font_size + 14
    margin_right = 10.0
    margin_top = 10.0

    plot_x = x + margin_left
    plot_y = y - height + margin_bottom
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_bottom - margin_top

    max_val = max(abs(v) for v in all_values) or 1
    min_val = min(all_values)
    if min_val >= 0:
        min_val = 0
    val_range = (max_val - min_val) * 1.1 or 1

    def val_to_y(v: float) -> float:
        return plot_y + (v - min_val) / val_range * plot_h

    # Gridlines
    for i in range(5):
        gy = plot_y + plot_h * i / 4
        val = min_val + val_range * i / 4
        stream.line(plot_x, gy, plot_x + plot_w, gy, color=_GRID_COLOR, width=0.3)
        stream.text_line(
            _format_value(val),
            font_key,
            font_size * 0.8,
            x + 4,
            gy - font_size * 0.3,
            _LABEL_COLOR,
        )

    # Axes
    stream.line(plot_x, plot_y, plot_x + plot_w, plot_y, color=_AXIS_COLOR, width=0.8)
    stream.line(plot_x, plot_y, plot_x, plot_y + plot_h, color=_AXIS_COLOR, width=0.8)

    # X-axis labels
    spacing = plot_w / max(count - 1, 1)
    for i in range(min(count, len(labels))):
        px = plot_x + i * spacing
        stream.text_line(
            labels[i][:8],
            font_key,
            font_size * 0.7,
            px - font_size * 0.5,
            plot_y - font_size - 2,
            _LABEL_COLOR,
        )

    palette = _palette(data)
    single = len(series) == 1

    for j, (_label, values) in enumerate(series):
        color = palette[j % len(palette)]
        points = [
            (plot_x + i * spacing, val_to_y(value)) for i, value in enumerate(values)
        ]

        if connect and len(points) > 1:
            stream.set_stroke(color)
            stream.set_line_width(1.5)
            ops = [stream._num(points[0][0]), stream._num(points[0][1]), b"m"]
            for px, py in points[1:]:
                ops.extend([stream._num(px), stream._num(py), b"l"])
            ops.append(b"S")
            stream.raw(b" ".join(ops))

        for px, py in points:
            _draw_marker(stream, px, py, _MARKER_RADIUS, color)

        if single and connect:
            for (px, py), value in zip(points, values):
                stream.text_line(
                    _format_value(value),
                    font_key,
                    font_size * 0.7,
                    px - font_size,
                    py + _MARKER_RADIUS + 3,
                    _AXIS_COLOR,
                )


def _draw_marker(
    stream: ContentStream, cx: float, cy: float, r: float, color: str
) -> None:
    """Draw a filled circle marker from four cubic Bezier arc segments."""
    stream.set_fill(color)
    n = stream._num
    ops = [n(cx + r), n(cy), b"m"]
    for quadrant in range(4):
        _arc_bezier(ops, stream, cx, cy, r, quadrant * 90.0, quadrant * 90.0 + 90.0)
    ops.append(b"f")
    stream.raw(b" ".join(ops))


# ---------------------------------------------------------------------------
# Pie chart
# ---------------------------------------------------------------------------


def _draw_pie_chart(
    stream: ContentStream,
    data: ChartData,
    series: list[tuple[str, list[float]]],
    x: float,
    y: float,
    width: float,
    height: float,
    font_key: str,
    font_size: float,
) -> None:
    """Draw a pie chart from the first series only."""
    values = series[0][1] if series else []
    if not values:
        return

    total = sum(abs(v) for v in values) or 1
    colors = _palette(data)

    radius = min(width * 0.35, height * 0.4)
    cx = x + width * 0.4
    cy = y - height * 0.5

    angle = 0.0
    for i, (label, value) in enumerate(zip(data.labels, values)):
        sweep = abs(value) / total * 360.0
        _draw_pie_wedge(
            stream, cx, cy, radius, angle, angle + sweep, colors[i % len(colors)]
        )

        # Label
        mid_angle = math.radians(angle + sweep / 2)
        label_r = radius + 14
        lx = cx + label_r * math.cos(mid_angle)
        ly = cy + label_r * math.sin(mid_angle)
        pct = abs(value) / total * 100
        text = f"{str(label)[:12]} ({pct:.0f}%)"
        stream.text_line(
            text,
            font_key,
            font_size * 0.75,
            lx - font_size * 2,
            ly - font_size * 0.3,
            _AXIS_COLOR,
        )

        angle += sweep


def _draw_pie_wedge(
    stream: ContentStream,
    cx: float,
    cy: float,
    r: float,
    start_deg: float,
    end_deg: float,
    color: str,
) -> None:
    """Draw a filled pie wedge using cubic Bezier approximation of arcs."""
    stream.set_fill(color)

    n = stream._num
    ops = [n(cx), n(cy), b"m"]

    # Move to start point on circumference
    start_rad = math.radians(start_deg)
    sx = cx + r * math.cos(start_rad)
    sy = cy + r * math.sin(start_rad)
    ops = [n(cx), n(cy), b"m", n(sx), n(sy), b"l"]

    # Approximate arc with cubic Bezier segments (max 90 degrees each)
    remaining = end_deg - start_deg
    current = start_deg
    while remaining > 0.01:
        seg = min(remaining, 90.0)
        _arc_bezier(ops, stream, cx, cy, r, current, current + seg)
        current += seg
        remaining -= seg

    ops.extend([b"f"])
    stream.raw(b" ".join(ops))


def _arc_bezier(
    ops: list,
    stream: ContentStream,
    cx: float,
    cy: float,
    r: float,
    start_deg: float,
    end_deg: float,
) -> None:
    """Append a cubic Bezier approximation of a circular arc."""
    a1 = math.radians(start_deg)
    a2 = math.radians(end_deg)
    da = a2 - a1

    # Handle factor for Bezier approximation of circular arc
    alpha = 4.0 / 3.0 * math.tan(da / 4.0)

    cos1, sin1 = math.cos(a1), math.sin(a1)
    cos2, sin2 = math.cos(a2), math.sin(a2)

    # Control points
    cp1x = cx + r * (cos1 - alpha * sin1)
    cp1y = cy + r * (sin1 + alpha * cos1)
    cp2x = cx + r * (cos2 + alpha * sin2)
    cp2y = cy + r * (sin2 - alpha * cos2)
    ex = cx + r * cos2
    ey = cy + r * sin2

    n = stream._num
    ops.extend(
        [
            n(cp1x),
            n(cp1y),
            n(cp2x),
            n(cp2y),
            n(ex),
            n(ey),
            b"c",
        ]
    )


def _format_value(v: float) -> str:
    """Format a number for chart labels."""
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f}K"
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}"
