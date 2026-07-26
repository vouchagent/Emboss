"""Chart rendering directly to PDF content streams.

Draws bar, line, and pie charts using primitive PDF operators — no
external charting library required. Charts are vector graphics and
render at any zoom level.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .pdf.streams import ContentStream, hex_color

__all__ = ["ChartData", "ChartSpec", "render_chart"]

DEFAULT_COLORS = [
    "3b82f6", "ef4444", "22c55e", "f59e0b",
    "8b5cf6", "ec4899", "06b6d4", "f97316",
]

_AXIS_COLOR = "44403c"
_GRID_COLOR = "e5e5e5"
_LABEL_COLOR = "57534e"


@dataclass
class ChartData:
    """Data for a chart."""

    labels: list[str]
    values: list[float]
    colors: list[str] | None = None
    title: str | None = None


@dataclass
class ChartSpec:
    """Complete chart specification."""

    chart_type: str  # "bar", "line", "pie"
    data: ChartData
    width: float = 400.0
    height: float = 250.0


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
    colors = chart.data.colors or DEFAULT_COLORS
    while len(colors) < len(chart.data.values):
        colors = colors + DEFAULT_COLORS

    stream.save()

    if chart.data.title:
        title_size = font_size + 2
        stream.text_line(
            chart.data.title, font_key, title_size,
            x + (chart.width - len(chart.data.title) * title_size * 0.5) / 2,
            y - title_size - 2,
            _AXIS_COLOR,
        )
        y -= title_size + 10
        effective_height = chart.height - title_size - 10
    else:
        effective_height = chart.height

    if chart.chart_type == "bar":
        _draw_bar_chart(stream, chart.data, colors, x, y, chart.width,
                        effective_height, font_key, font_size)
    elif chart.chart_type == "line":
        _draw_line_chart(stream, chart.data, colors, x, y, chart.width,
                         effective_height, font_key, font_size)
    elif chart.chart_type == "pie":
        _draw_pie_chart(stream, chart.data, colors, x, y, chart.width,
                        effective_height, font_key, font_size)

    stream.restore()


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------

def _draw_bar_chart(
    stream: ContentStream,
    data: ChartData,
    colors: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    font_key: str,
    font_size: float,
) -> None:
    n = len(data.values)
    if n == 0:
        return

    margin_left = 50.0
    margin_bottom = font_size + 14
    margin_right = 10.0
    margin_top = 10.0

    plot_x = x + margin_left
    plot_y = y - height + margin_bottom
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_bottom - margin_top

    max_val = max(abs(v) for v in data.values) or 1
    max_val *= 1.1

    # Y-axis gridlines
    for i in range(5):
        gy = plot_y + plot_h * i / 4
        val = max_val * i / 4
        stream.line(plot_x, gy, plot_x + plot_w, gy,
                    color=_GRID_COLOR, width=0.3)
        label = _format_value(val)
        stream.text_line(label, font_key, font_size * 0.8,
                         x + 4, gy - font_size * 0.3, _LABEL_COLOR)

    # Axes
    stream.line(plot_x, plot_y, plot_x + plot_w, plot_y,
                color=_AXIS_COLOR, width=0.8)
    stream.line(plot_x, plot_y, plot_x, plot_y + plot_h,
                color=_AXIS_COLOR, width=0.8)

    # Bars
    bar_zone = plot_w / n
    bar_width = bar_zone * 0.65
    gap = bar_zone * 0.175

    for i, (label, value) in enumerate(zip(data.labels, data.values)):
        bar_h = abs(value) / max_val * plot_h
        bx = plot_x + i * bar_zone + gap
        by = plot_y

        stream.rect(bx, by, bar_width, bar_h, fill=colors[i % len(colors)])

        # Value label above bar
        val_text = _format_value(value)
        stream.text_line(val_text, font_key, font_size * 0.75,
                         bx + bar_width * 0.15, by + bar_h + 3, _AXIS_COLOR)

        # X-axis label
        lx = bx + bar_width * 0.1
        ly = plot_y - font_size - 2
        stream.text_line(label[:10], font_key, font_size * 0.75,
                         lx, ly, _LABEL_COLOR)


# ---------------------------------------------------------------------------
# Line chart
# ---------------------------------------------------------------------------

def _draw_line_chart(
    stream: ContentStream,
    data: ChartData,
    colors: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    font_key: str,
    font_size: float,
) -> None:
    n = len(data.values)
    if n == 0:
        return

    margin_left = 50.0
    margin_bottom = font_size + 14
    margin_right = 10.0
    margin_top = 10.0

    plot_x = x + margin_left
    plot_y = y - height + margin_bottom
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_bottom - margin_top

    max_val = max(abs(v) for v in data.values) or 1
    min_val = min(data.values)
    if min_val >= 0:
        min_val = 0
    val_range = (max_val - min_val) * 1.1 or 1

    def val_to_y(v: float) -> float:
        return plot_y + (v - min_val) / val_range * plot_h

    # Gridlines
    for i in range(5):
        gy = plot_y + plot_h * i / 4
        val = min_val + val_range * i / 4
        stream.line(plot_x, gy, plot_x + plot_w, gy,
                    color=_GRID_COLOR, width=0.3)
        stream.text_line(_format_value(val), font_key, font_size * 0.8,
                         x + 4, gy - font_size * 0.3, _LABEL_COLOR)

    # Axes
    stream.line(plot_x, plot_y, plot_x + plot_w, plot_y,
                color=_AXIS_COLOR, width=0.8)
    stream.line(plot_x, plot_y, plot_x, plot_y + plot_h,
                color=_AXIS_COLOR, width=0.8)

    # Line segments and data points
    spacing = plot_w / max(n - 1, 1)
    color = colors[0]
    points = []

    for i, (label, value) in enumerate(zip(data.labels, data.values)):
        px = plot_x + i * spacing
        py = val_to_y(value)
        points.append((px, py))

        # X-axis label
        stream.text_line(label[:8], font_key, font_size * 0.7,
                         px - font_size * 0.5, plot_y - font_size - 2,
                         _LABEL_COLOR)

    # Draw line segments
    stream.set_stroke(color)
    stream.set_line_width(1.5)
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        stream.raw(b" ".join([
            stream._num(x1), stream._num(y1), b"m",
            stream._num(x2), stream._num(y2), b"l", b"S",
        ]))

    # Draw data points as filled circles (small rects as approximation)
    dot_r = 3.0
    for px, py in points:
        stream.rect(px - dot_r, py - dot_r, dot_r * 2, dot_r * 2,
                     fill=color)

    # Value labels
    for i, ((px, py), value) in enumerate(zip(points, data.values)):
        stream.text_line(_format_value(value), font_key, font_size * 0.7,
                         px - font_size, py + dot_r + 3, _AXIS_COLOR)


# ---------------------------------------------------------------------------
# Pie chart
# ---------------------------------------------------------------------------

def _draw_pie_chart(
    stream: ContentStream,
    data: ChartData,
    colors: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    font_key: str,
    font_size: float,
) -> None:
    n = len(data.values)
    if n == 0:
        return

    total = sum(abs(v) for v in data.values) or 1

    radius = min(width * 0.35, height * 0.4)
    cx = x + width * 0.4
    cy = y - height * 0.5

    angle = 0.0
    for i, (label, value) in enumerate(zip(data.labels, data.values)):
        sweep = abs(value) / total * 360.0
        _draw_pie_wedge(stream, cx, cy, radius, angle, angle + sweep,
                        colors[i % len(colors)])

        # Label
        mid_angle = math.radians(angle + sweep / 2)
        label_r = radius + 14
        lx = cx + label_r * math.cos(mid_angle)
        ly = cy + label_r * math.sin(mid_angle)
        pct = abs(value) / total * 100
        text = f"{label[:12]} ({pct:.0f}%)"
        stream.text_line(text, font_key, font_size * 0.75,
                         lx - font_size * 2, ly - font_size * 0.3,
                         _AXIS_COLOR)

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
    ops.extend([
        n(cp1x), n(cp1y), n(cp2x), n(cp2y), n(ex), n(ey), b"c",
    ])


def _format_value(v: float) -> str:
    """Format a number for chart labels."""
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f}K"
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}"
