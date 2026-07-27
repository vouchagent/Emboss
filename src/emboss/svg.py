"""Lightweight SVG-to-PDF embedding using only the standard library.

Parses a subset of SVG (paths, basic shapes, text) and converts them
to PDF drawing operations. No external dependencies are required.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

__all__ = ["SvgImage", "parse_svg", "render_svg"]

_NS = "{http://www.w3.org/2000/svg}"


@dataclass
class SvgImage:
    """Parsed SVG ready for PDF rendering."""

    width: float
    height: float
    view_box: tuple[float, float, float, float] | None = None
    elements: list = field(default_factory=list)

    @property
    def aspect_width(self) -> float:
        if self.view_box:
            return self.view_box[2]
        return self.width

    @property
    def aspect_height(self) -> float:
        if self.view_box:
            return self.view_box[3]
        return self.height


@dataclass
class SvgElement:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    text: str = ""


def parse_svg(source: str | bytes) -> SvgImage:
    if isinstance(source, bytes):
        source = source.decode("utf-8")
    root = ET.fromstring(source)
    tag = root.tag.replace(_NS, "")
    if tag != "svg":
        raise ValueError(f"expected <svg> root, got <{tag}>")

    width = _parse_length(root.get("width", "300"))
    height = _parse_length(root.get("height", "150"))

    vb = root.get("viewBox")
    view_box = None
    if vb:
        parts = re.split(r"[\s,]+", vb.strip())
        if len(parts) == 4:
            view_box = tuple(float(p) for p in parts)

    elements = []
    _collect(root, elements)
    return SvgImage(width=width, height=height, view_box=view_box, elements=elements)


def _parse_length(value: str) -> float:
    value = value.strip()
    for suffix in ("px", "pt", "mm", "cm", "in", "em", "%"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    try:
        return float(value)
    except ValueError:
        return 0.0


def _collect(node, out: list) -> None:
    for child in node:
        tag = child.tag.replace(_NS, "")
        if tag == "g":
            _collect(child, out)
            continue
        attrs = dict(child.attrib)
        el = SvgElement(tag=tag, attrs=attrs, text=child.text or "")
        _collect(child, el.children)
        out.append(el)


def _hex_color(value: str | None) -> str | None:
    if not value or value == "none":
        return None
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = h[0] * 2 + h[1] * 2 + h[2] * 2
        return h.lower()
    named = {
        "black": "000000",
        "white": "ffffff",
        "red": "ff0000",
        "green": "008000",
        "blue": "0000ff",
        "yellow": "ffff00",
        "gray": "808080",
        "grey": "808080",
        "orange": "ffa500",
        "purple": "800080",
        "navy": "000080",
        "teal": "008080",
    }
    return named.get(value.lower())


def _style_attrs(el: SvgElement) -> dict:
    result = dict(el.attrs)
    style = el.attrs.get("style", "")
    for part in style.split(";"):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def render_svg(
    stream,
    svg: SvgImage,
    x: float,
    y: float,
    display_width: float,
    display_height: float,
) -> None:
    sx = display_width / svg.aspect_width if svg.aspect_width else 1.0
    sy = display_height / svg.aspect_height if svg.aspect_height else 1.0

    ox = svg.view_box[0] if svg.view_box else 0.0
    oy = svg.view_box[1] if svg.view_box else 0.0

    stream.save()

    for el in svg.elements:
        attrs = _style_attrs(el)
        fill = _hex_color(attrs.get("fill"))
        stroke = _hex_color(attrs.get("stroke"))
        stroke_w = float(attrs.get("stroke-width", "1"))

        if el.tag == "rect":
            rx = (float(attrs.get("x", "0")) - ox) * sx + x
            ry = y - (float(attrs.get("y", "0")) - oy) * sy
            rw = float(attrs.get("width", "0")) * sx
            rh = float(attrs.get("height", "0")) * sy
            ry -= rh
            if fill:
                stream.rect(rx, ry, rw, rh, fill=fill)
            if stroke:
                stream.rect(rx, ry, rw, rh, fill=None)

        elif el.tag == "circle":
            cx = (float(attrs.get("cx", "0")) - ox) * sx + x
            cy = y - (float(attrs.get("cy", "0")) - oy) * sy
            r = float(attrs.get("r", "0")) * min(sx, sy)
            _draw_circle(stream, cx, cy, r, fill, stroke, stroke_w)

        elif el.tag == "ellipse":
            cx = (float(attrs.get("cx", "0")) - ox) * sx + x
            cy = y - (float(attrs.get("cy", "0")) - oy) * sy
            erx = float(attrs.get("rx", "0")) * sx
            ery = float(attrs.get("ry", "0")) * sy
            _draw_ellipse(stream, cx, cy, erx, ery, fill, stroke, stroke_w)

        elif el.tag == "line":
            x1 = (float(attrs.get("x1", "0")) - ox) * sx + x
            y1 = y - (float(attrs.get("y1", "0")) - oy) * sy
            x2 = (float(attrs.get("x2", "0")) - ox) * sx + x
            y2 = y - (float(attrs.get("y2", "0")) - oy) * sy
            c = stroke or "000000"
            stream.line(x1, y1, x2, y2, color=c, width=stroke_w * min(sx, sy))

        elif el.tag == "path":
            d = attrs.get("d", "")
            if d:
                _draw_path(stream, d, x, y, ox, oy, sx, sy, fill, stroke, stroke_w)

        elif el.tag == "polygon" or el.tag == "polyline":
            points_str = attrs.get("points", "")
            if points_str:
                points = _parse_points(points_str, x, y, ox, oy, sx, sy)
                if points:
                    _draw_polygon(
                        stream,
                        points,
                        fill if el.tag == "polygon" else None,
                        stroke,
                        stroke_w,
                    )

    stream.restore()


def _parse_points(s: str, x, y, ox, oy, sx, sy):
    nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", s)
    points = []
    for i in range(0, len(nums) - 1, 2):
        px = (float(nums[i]) - ox) * sx + x
        py = y - (float(nums[i + 1]) - oy) * sy
        points.append((px, py))
    return points


def _draw_circle(stream, cx, cy, r, fill, stroke, stroke_w):
    k = 0.5522847498
    ops = []
    ops.append(f"{cx + r:.4f} {cy:.4f} m")
    ops.append(
        f"{cx + r:.4f} {cy + r * k:.4f} {cx + r * k:.4f} {cy + r:.4f} {cx:.4f} {cy + r:.4f} c"
    )
    ops.append(
        f"{cx - r * k:.4f} {cy + r:.4f} {cx - r:.4f} {cy + r * k:.4f} {cx - r:.4f} {cy:.4f} c"
    )
    ops.append(
        f"{cx - r:.4f} {cy - r * k:.4f} {cx - r * k:.4f} {cy - r:.4f} {cx:.4f} {cy - r:.4f} c"
    )
    ops.append(
        f"{cx + r * k:.4f} {cy - r:.4f} {cx + r:.4f} {cy - r * k:.4f} {cx + r:.4f} {cy:.4f} c"
    )
    _fill_stroke(stream, ops, fill, stroke, stroke_w)


def _draw_ellipse(stream, cx, cy, rx, ry, fill, stroke, stroke_w):
    kx = 0.5522847498 * rx
    ky = 0.5522847498 * ry
    ops = []
    ops.append(f"{cx + rx:.4f} {cy:.4f} m")
    ops.append(
        f"{cx + rx:.4f} {cy + ky:.4f} {cx + kx:.4f} {cy + ry:.4f} {cx:.4f} {cy + ry:.4f} c"
    )
    ops.append(
        f"{cx - kx:.4f} {cy + ry:.4f} {cx - rx:.4f} {cy + ky:.4f} {cx - rx:.4f} {cy:.4f} c"
    )
    ops.append(
        f"{cx - rx:.4f} {cy - ky:.4f} {cx - kx:.4f} {cy - ry:.4f} {cx:.4f} {cy - ry:.4f} c"
    )
    ops.append(
        f"{cx + kx:.4f} {cy - ry:.4f} {cx + rx:.4f} {cy - ky:.4f} {cx + rx:.4f} {cy:.4f} c"
    )
    _fill_stroke(stream, ops, fill, stroke, stroke_w)


def _fill_stroke(stream, ops, fill, stroke, stroke_w):
    raw_lines = []
    if fill:
        r, g, b = (
            int(fill[0:2], 16) / 255,
            int(fill[2:4], 16) / 255,
            int(fill[4:6], 16) / 255,
        )
        raw_lines.append(f"{r:.4f} {g:.4f} {b:.4f} rg")
    if stroke:
        r, g, b = (
            int(stroke[0:2], 16) / 255,
            int(stroke[2:4], 16) / 255,
            int(stroke[4:6], 16) / 255,
        )
        raw_lines.append(f"{r:.4f} {g:.4f} {b:.4f} RG")
        raw_lines.append(f"{stroke_w:.4f} w")
    raw_lines.extend(ops)
    if fill and stroke:
        raw_lines.append("B")
    elif fill:
        raw_lines.append("f")
    elif stroke:
        raw_lines.append("S")
    stream.raw("\n".join(raw_lines).encode("ascii"))


def _draw_polygon(stream, points, fill, stroke, stroke_w):
    if not points:
        return
    ops = [f"{points[0][0]:.4f} {points[0][1]:.4f} m"]
    for px, py in points[1:]:
        ops.append(f"{px:.4f} {py:.4f} l")
    if fill:
        ops.append("h")
    _fill_stroke(stream, ops, fill, stroke, stroke_w)


def _draw_path(stream, d, x, y, ox, oy, sx, sy, fill, stroke, stroke_w):
    tokens = re.findall(
        r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", d
    )
    ops = []
    i = 0
    cx_cur, cy_cur = 0.0, 0.0

    def tx(v):
        return (v - ox) * sx + x

    def ty(v):
        return y - (v - oy) * sy

    while i < len(tokens):
        cmd = tokens[i]
        if not cmd[0].isalpha():
            i += 1
            continue
        i += 1

        if cmd == "M":
            cx_cur, cy_cur = float(tokens[i]), float(tokens[i + 1])
            ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} m")
            i += 2
        elif cmd == "m":
            cx_cur += float(tokens[i])
            cy_cur += float(tokens[i + 1])
            ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} m")
            i += 2
        elif cmd == "L":
            while i < len(tokens) and tokens[i][0] not in "MmLlHhVvCcSsQqTtAaZz":
                cx_cur, cy_cur = float(tokens[i]), float(tokens[i + 1])
                ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} l")
                i += 2
        elif cmd == "l":
            while i < len(tokens) and tokens[i][0] not in "MmLlHhVvCcSsQqTtAaZz":
                cx_cur += float(tokens[i])
                cy_cur += float(tokens[i + 1])
                ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} l")
                i += 2
        elif cmd == "H":
            cx_cur = float(tokens[i])
            ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} l")
            i += 1
        elif cmd == "h":
            cx_cur += float(tokens[i])
            ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} l")
            i += 1
        elif cmd == "V":
            cy_cur = float(tokens[i])
            ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} l")
            i += 1
        elif cmd == "v":
            cy_cur += float(tokens[i])
            ops.append(f"{tx(cx_cur):.4f} {ty(cy_cur):.4f} l")
            i += 1
        elif cmd == "C":
            while i + 5 < len(tokens) and tokens[i][0] not in "MmLlHhVvCcSsQqTtAaZz":
                x1, y1 = float(tokens[i]), float(tokens[i + 1])
                x2, y2 = float(tokens[i + 2]), float(tokens[i + 3])
                cx_cur, cy_cur = float(tokens[i + 4]), float(tokens[i + 5])
                ops.append(
                    f"{tx(x1):.4f} {ty(y1):.4f} {tx(x2):.4f} {ty(y2):.4f} {tx(cx_cur):.4f} {ty(cy_cur):.4f} c"
                )
                i += 6
        elif cmd == "c":
            while i + 5 < len(tokens) and tokens[i][0] not in "MmLlHhVvCcSsQqTtAaZz":
                x1 = cx_cur + float(tokens[i])
                y1 = cy_cur + float(tokens[i + 1])
                x2 = cx_cur + float(tokens[i + 2])
                y2 = cy_cur + float(tokens[i + 3])
                cx_cur += float(tokens[i + 4])
                cy_cur += float(tokens[i + 5])
                ops.append(
                    f"{tx(x1):.4f} {ty(y1):.4f} {tx(x2):.4f} {ty(y2):.4f} {tx(cx_cur):.4f} {ty(cy_cur):.4f} c"
                )
                i += 6
        elif cmd in ("Z", "z"):
            ops.append("h")
        else:
            if i < len(tokens) and tokens[i][0] not in "MmLlHhVvCcSsQqTtAaZz":
                i += 1

    if ops:
        _fill_stroke(stream, ops, fill, stroke, stroke_w)
