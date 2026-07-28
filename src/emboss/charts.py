"""Chart rendering directly to PDF content streams.

Draws bar, line, pie, and scatter charts using primitive PDF operators —
no external charting library required. Charts are vector graphics and
render at any zoom level. Data is either a single unnamed series
(``labels`` + ``values``) or a list of named series for grouped bars,
multi-line, and scatter charts. Pie charts use the first series only.

Hardening guarantees: bar charts always include zero in the y-range and
draw negative bars below a zero baseline; category and legend labels are
measured (wrap, rotate, shrink — never silently truncated); value labels
thin deterministically instead of overprinting; optional per-series
patterns keep series distinguishable in grayscale print.

All color output goes through the mode-aware ``set_fill``/``set_stroke``
funnel on ContentStream so CMYK documents emit k/K operators.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .pdf.streams import ContentStream
from .typography.font_metrics import FontMetrics

__all__ = [
    "ChartData",
    "ChartSpec",
    "direction_of",
    "format_value",
    "render_chart",
    "series_summary",
    "validate_chart",
]

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
_MIN_LABEL_SIZE = 6.0
_COS30 = math.cos(math.radians(30.0))

PATTERN_KINDS = ("diagonal", "dots", "crosshatch", "horizontal")
_PATTERN_COLOR = "ffffff"
_PATTERN_SPACING = 4.0
_PATTERN_LINE_WIDTH = 0.6

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
    ``patterns`` overlays per-series vector patterns for print/grayscale.
    """

    labels: list[str]
    values: list[float]
    colors: list[str] | None = None
    title: str | None = None
    series: list | None = None
    x_title: str | None = None
    y_title: str | None = None
    legend: bool = True
    patterns: bool = False


@dataclass
class ChartSpec:
    """Complete chart specification."""

    chart_type: str  # "bar", "line", "pie", "scatter"
    data: ChartData
    width: float = 400.0
    height: float = 250.0


def direction_of(first: float, last: float) -> str:
    """Classify first-vs-last movement with a 1% relative tolerance."""
    if abs(last - first) <= 0.01 * max(abs(first), abs(last)):
        return "flat"
    return "rising" if last > first else "falling"


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
    if series:
        all_values = [float(v) for s in series for v in getattr(s, "values", [])]
        first_vals = [float(v) for v in getattr(series[0], "values", [])]
        if all_values and first_vals:
            low = format_value(min(all_values))
            high = format_value(max(all_values))
            trend = direction_of(first_vals[0], first_vals[-1])
            parts.append(f"range {low} to {high}; {trend}")
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


def validate_chart(chart: ChartSpec) -> None:
    """Validate chart data at render time, raising correctable ValueErrors."""
    data = chart.data
    kind = chart.chart_type
    series = _normalized_series(data)
    if data.series:
        lengths = [len(values) for _label, values in series]
        if len(set(lengths)) > 1:
            raise ValueError(
                f"chart series have mismatched lengths {lengths}; give every "
                "series the same number of values (one per category)"
            )
    all_values = [v for _label, values in series for v in values]
    if not all_values:
        return
    if kind == "pie":
        values = series[0][1]
        for i, value in enumerate(values):
            if value < 0:
                label = str(data.labels[i]) if i < len(data.labels) else str(i + 1)
                raise ValueError(
                    f"pie chart cannot contain negative values: category "
                    f"{label!r} has {value}; use a bar chart for negative data"
                )
        if sum(values) == 0:
            raise ValueError(
                "pie chart values sum to zero, so shares are undefined; "
                "provide at least one positive value"
            )
    if kind in ("line", "scatter"):
        count = max(len(values) for _label, values in series)
        if count < 2:
            raise ValueError(
                f"{kind} chart shows a trend and needs at least 2 data "
                f"points, got {count}; add more points or use a bar chart"
            )


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
    validate_chart(chart)
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
# Label fitting (measure, wrap, rotate, shrink — never truncate)
# ---------------------------------------------------------------------------


def _wrap_lines(text: str, size: float, max_w: float) -> list[str]:
    """Greedily wrap text into lines fitting max_w; overlong words stand alone."""
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if _measure_label(candidate, size) <= max_w:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _wrap_two_lines(text: str, size: float, max_w: float) -> list[str] | None:
    """Wrap text onto exactly two fitting lines, or None if impossible."""
    lines = _wrap_lines(text, size, max_w)
    if len(lines) != 2:
        return None
    if any(_measure_label(line, size) > max_w for line in lines):
        return None
    return lines


def _draw_x_label(
    stream: ContentStream,
    text: str,
    font_key: str,
    size: float,
    cx: float,
    base_y: float,
    slot_w: float,
    color: str,
) -> None:
    """Draw a category label: fit, two-line wrap, then rotate and shrink."""
    width = _measure_label(text, size)
    if width <= slot_w:
        stream.text_line(text, font_key, size, cx - width / 2, base_y, color)
        return
    lines = _wrap_two_lines(text, size, slot_w)
    if lines:
        for row, line in enumerate(lines):
            line_w = _measure_label(line, size)
            row_y = base_y - row * (size + 1.0)
            stream.text_line(line, font_key, size, cx - line_w / 2, row_y, color)
        return
    rot_size = size
    while (
        rot_size - 0.5 >= _MIN_LABEL_SIZE
        and _measure_label(text, rot_size) * _COS30 > slot_w * 2.0
    ):
        rot_size -= 0.5
    anchor_x = cx - rot_size * 0.3
    stream.rotated_text(
        text, font_key, rot_size, anchor_x, base_y + size * 0.5, color, -30.0
    )


def _label_step(texts: list[str], size: float, slot_w: float) -> int:
    """Return the deterministic keep-every-nth step for value labels."""
    if not texts or slot_w <= 0:
        return 1
    max_w = max(_measure_label(text, size) for text in texts) + 2.0
    if max_w <= slot_w:
        return 1
    return max(2, math.ceil(max_w / slot_w))


# ---------------------------------------------------------------------------
# Pattern fills (print / grayscale accessibility)
# ---------------------------------------------------------------------------


def _pattern_overlay(
    stream: ContentStream,
    kind: str,
    x: float,
    y: float,
    w: float,
    h: float,
    clip_ops: list[bytes] | None = None,
) -> None:
    """Overlay a distinguishing vector pattern clipped to a shape."""
    if w <= 0 or h <= 0:
        return
    n = stream._num
    stream.save()
    if clip_ops is None:
        stream.raw(b" ".join([n(x), n(y), n(w), n(h), b"re", b"W", b"n"]))
    else:
        stream.raw(b" ".join(clip_ops + [b"W", b"n"]))
    stream.set_stroke(_PATTERN_COLOR)
    if kind == "dots":
        stream.set_line_width(1.1)
        stream.raw(b"1 J")
    else:
        stream.set_line_width(_PATTERN_LINE_WIDTH)
    step = _PATTERN_SPACING
    ops: list[bytes] = []
    if kind in ("diagonal", "crosshatch"):
        for i in range(int((w + h) / step) + 1):
            t = x - h + i * step
            ops.extend([n(t), n(y), b"m", n(t + h), n(y + h), b"l"])
    if kind == "crosshatch":
        for i in range(int((w + h) / step) + 1):
            t = x - h + i * step
            ops.extend([n(t), n(y + h), b"m", n(t + h), n(y), b"l"])
    if kind == "horizontal":
        for i in range(1, int(h / step) + 1):
            gy = y + i * step
            ops.extend([n(x), n(gy), b"m", n(x + w), n(gy), b"l"])
    if kind == "dots":
        for row in range(int(h / step) + 1):
            gy = y + step / 2 + row * step
            offset = step / 2 if row % 2 else 0.0
            for col in range(int(w / step) + 1):
                gx = x + step / 2 + offset + col * step
                ops.extend([n(gx), n(gy), b"m", n(gx + 0.01), n(gy), b"l"])
    if ops:
        ops.append(b"S")
        stream.raw(b" ".join(ops))
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
    """Draw swatch+label legend rows, growing or wrapping to fit each label."""
    palette = _palette(data)
    entries = [
        (j, label, palette[j % len(palette)])
        for j, (label, _values) in enumerate(series)
        if label
    ]
    if not entries:
        return

    size = font_size * 0.75
    swatch = 6.0
    pad = 4.0
    row_h = size + 4.0
    avail = max(width - (pad + swatch + 4.0 + pad) - 12.0, swatch)

    rows: list[tuple[int | None, str, str]] = []
    for j, label, color in entries:
        lines = (
            [label]
            if _measure_label(label, size) <= avail
            else _wrap_lines(label, size, avail)
        )
        for row, line in enumerate(lines):
            rows.append((j if row == 0 else None, line, color))

    text_w = max(_measure_label(line, size) for _j, line, _color in rows)
    box_w = pad + swatch + 4.0 + text_w + pad

    lx = max(x + width - box_w - 6.0, x + 2.0)
    ly = y - 6.0
    for k, (row_j, line, color) in enumerate(rows):
        row_top = ly - k * row_h
        if row_j is not None:
            stream.rect(lx + pad, row_top - swatch, swatch, swatch, fill=color)
            if data.patterns:
                kind = PATTERN_KINDS[row_j % len(PATTERN_KINDS)]
                _pattern_overlay(
                    stream, kind, lx + pad, row_top - swatch, swatch, swatch
                )
        stream.text_line(
            line,
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

    # Honest axes: the y-range always includes zero, never truncating bars.
    min_val = min(0.0, min(all_values))
    max_val = max(0.0, max(all_values))
    if max_val > 0:
        max_val *= 1.1
    if min_val < 0:
        min_val *= 1.1
    val_range = (max_val - min_val) or 1.0

    def val_to_y(v: float) -> float:
        return plot_y + (v - min_val) / val_range * plot_h

    zero_y = val_to_y(0.0)

    # Y-axis gridlines with labeled ticks (min tick always labeled)
    for i in range(5):
        gy = plot_y + plot_h * i / 4
        val = round(min_val + val_range * i / 4, 4)
        stream.line(plot_x, gy, plot_x + plot_w, gy, color=_GRID_COLOR, width=0.3)
        stream.text_line(
            format_value(val),
            font_key,
            font_size * 0.8,
            x + 4,
            gy - font_size * 0.3,
            _LABEL_COLOR,
        )

    # Y axis
    stream.line(plot_x, plot_y, plot_x, plot_y + plot_h, color=_AXIS_COLOR, width=0.8)

    # Bars: one group per label, series side by side within the group
    palette = _palette(data)
    single = len(series) == 1
    zone = plot_w / count
    group_w = zone * 0.65
    gap = zone * 0.175
    bar_w = group_w / len(series)

    lbl_size = font_size * 0.75
    vstep = 1
    if single:
        value_texts = [format_value(v) for v in series[0][1]]
        vstep = _label_step(value_texts, lbl_size, zone)

    for i in range(count):
        for j, (_label, values) in enumerate(series):
            if i >= len(values):
                continue
            value = values[i]
            top = val_to_y(value)
            if value >= 0:
                by, bh = zero_y, top - zero_y
            else:
                by, bh = top, zero_y - top
            bx = plot_x + i * zone + gap + j * bar_w
            color = palette[i % len(palette)] if single else palette[j % len(palette)]
            stream.rect(bx, by, bar_w, bh, fill=color)
            if data.patterns:
                kind = PATTERN_KINDS[(i if single else j) % len(PATTERN_KINDS)]
                _pattern_overlay(stream, kind, bx, by, bar_w, bh)

            if single and i % vstep == 0:
                val_text = format_value(value)
                val_w = _measure_label(val_text, lbl_size)
                val_y = by + bh + 3 if value >= 0 else by - lbl_size - 2
                stream.text_line(
                    val_text,
                    font_key,
                    lbl_size,
                    bx + (bar_w - val_w) / 2,
                    val_y,
                    _AXIS_COLOR,
                )

        if i < len(labels):
            _draw_x_label(
                stream,
                labels[i],
                font_key,
                font_size * 0.75,
                plot_x + i * zone + zone / 2,
                plot_y - font_size - 2,
                zone * 0.9,
                _LABEL_COLOR,
            )

    # X axis drawn at the zero baseline, over the bars, so it stays visible
    stream.line(plot_x, zero_y, plot_x + plot_w, zero_y, color=_AXIS_COLOR, width=0.8)


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

    max_val = max(all_values)
    min_val = min(all_values)
    if min_val >= 0:
        min_val = 0
    val_range = (max_val - min_val) * 1.1 or 1

    def val_to_y(v: float) -> float:
        return plot_y + (v - min_val) / val_range * plot_h

    # Gridlines with labeled ticks; the y-min tick is always labeled so the
    # visible range is explicit even when it does not start at zero.
    for i in range(5):
        gy = plot_y + plot_h * i / 4
        val = round(min_val + val_range * i / 4, 4)
        stream.line(plot_x, gy, plot_x + plot_w, gy, color=_GRID_COLOR, width=0.3)
        stream.text_line(
            format_value(val),
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
        _draw_x_label(
            stream,
            labels[i],
            font_key,
            font_size * 0.7,
            px,
            plot_y - font_size - 2,
            spacing * 0.95,
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
            lbl = font_size * 0.7
            vstep = _label_step([format_value(v) for v in values], lbl, spacing)
            for i, ((px, py), value) in enumerate(zip(points, values)):
                if i % vstep:
                    continue
                val_text = format_value(value)
                val_w = _measure_label(val_text, lbl)
                stream.text_line(
                    val_text,
                    font_key,
                    lbl,
                    px - val_w / 2,
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
        wedge = _wedge_path(stream, cx, cy, radius, angle, angle + sweep)
        stream.set_fill(colors[i % len(colors)])
        stream.raw(b" ".join(wedge + [b"f"]))
        if data.patterns:
            kind = PATTERN_KINDS[i % len(PATTERN_KINDS)]
            _pattern_overlay(
                stream,
                kind,
                cx - radius,
                cy - radius,
                radius * 2,
                radius * 2,
                clip_ops=_wedge_path(stream, cx, cy, radius, angle, angle + sweep),
            )

        # Label (full text, centered on its anchor — never truncated)
        mid_angle = math.radians(angle + sweep / 2)
        label_r = radius + 14
        lx = cx + label_r * math.cos(mid_angle)
        ly = cy + label_r * math.sin(mid_angle)
        pct = abs(value) / total * 100
        text = f"{label} ({pct:.0f}%)"
        text_w = _measure_label(text, font_size * 0.75)
        stream.text_line(
            text,
            font_key,
            font_size * 0.75,
            lx - text_w / 2,
            ly - font_size * 0.3,
            _AXIS_COLOR,
        )

        angle += sweep


def _wedge_path(
    stream: ContentStream,
    cx: float,
    cy: float,
    r: float,
    start_deg: float,
    end_deg: float,
) -> list[bytes]:
    """Build path ops for a pie wedge using cubic Bezier arc approximation."""
    n = stream._num
    start_rad = math.radians(start_deg)
    sx = cx + r * math.cos(start_rad)
    sy = cy + r * math.sin(start_rad)
    ops = [n(cx), n(cy), b"m", n(sx), n(sy), b"l"]

    remaining = end_deg - start_deg
    current = start_deg
    while remaining > 0.01:
        seg = min(remaining, 90.0)
        _arc_bezier(ops, stream, cx, cy, r, current, current + seg)
        current += seg
        remaining -= seg
    return ops


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


def format_value(v: float) -> str:
    """Format a number for chart labels: 1,200 below 1M, 1.2M above."""
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        if v == int(v):
            return f"{int(v):,}"
        return f"{v:,.1f}"
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}"


_format_value = format_value
