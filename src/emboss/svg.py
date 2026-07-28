"""Static SVG subset to PDF content-stream operators using only the stdlib.

Supported: basic shapes, full path data (M/L/H/V/C/S/Q/T/A/Z with relative
and implicit-repeat forms), transform stacks with nested groups (emitted as
``cm`` inside ``q``/``Q``), defs/use with a reference-depth cap, clipPath
(``W n``), linear/radial gradients, opacity, and basic ``<text>``.

Integration notes (page resources are built in writer.py, not here):
- Gradients paint as clipped color bands so no page resources are needed;
  ``gradient_shading`` builds true type 2/3 /Shading dictionaries with
  stitching functions for page-resource wiring. Gradient stops are treated
  as fully opaque; ``stop-opacity`` is ignored rather than simulated.
- Opacity emits real ExtGState ``gs`` operators; requested states are
  recorded on the stream as ``used_svg_gstates`` (name -> {ca, CA}) and
  must be registered in page resources by the writer.
- ``<text>`` uses base-14 metrics; used fonts are recorded on the stream
  as ``used_svg_fonts`` (resource key -> base-14 name) for writer wiring.

Excluded: filters, animation, masks, patterns, CSS beyond the ``style``
presentation attribute.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace

from .colors import rgb_to_cmyk
from .typography.font_metrics import FontMetrics

__all__ = ["SvgImage", "parse_svg", "render_svg", "gradient_shading"]

_NS = "{http://www.w3.org/2000/svg}"
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_KAPPA = 0.5522847498
_GRADIENT_BANDS = 24
_MAX_REF_DEPTH = 8

_NUM_RE = re.compile(r"[-+]?(?:[0-9]*\.[0-9]+|[0-9]+\.?)(?:[eE][-+]?[0-9]+)?")
_PATH_TOKEN_RE = re.compile(
    r"[MmLlHhVvCcSsQqTtAaZz]"
    r"|[-+]?(?:[0-9]*\.[0-9]+|[0-9]+\.?)(?:[eE][-+]?[0-9]+)?"
)
_TRANSFORM_RE = re.compile(
    r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)"
)
_URL_RE = re.compile(r"url\(\s*#([^)\s]+)\s*\)")

_NON_RENDERED = {
    "defs",
    "linearGradient",
    "radialGradient",
    "clipPath",
    "symbol",
    "marker",
    "mask",
    "pattern",
    "filter",
    "style",
    "script",
    "title",
    "desc",
    "metadata",
}
_DRAWABLE = {"rect", "circle", "ellipse", "line", "path", "polygon", "polyline"}
_FAMILY_KEYS = {"Helvetica": "FsvgH", "Times-Roman": "FsvgT", "Courier": "FsvgC"}


@dataclass
class SvgImage:
    """Parsed SVG ready for PDF rendering."""

    width: float
    height: float
    view_box: tuple[float, float, float, float] | None = None
    elements: list = field(default_factory=list)
    defs: dict = field(default_factory=dict)

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
    tail: str = ""


def parse_svg(source: str | bytes) -> SvgImage:
    """Parse SVG markup into an SvgImage element tree with a defs index."""
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

    image = SvgImage(width=width, height=height, view_box=view_box)
    _collect(root, image.elements, image.defs)
    return image


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


def _collect(node, out: list, defs: dict) -> None:
    """Build the element tree, indexing ids and hiding non-rendered nodes."""
    for child in node:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag.replace(_NS, "")
        el = SvgElement(
            tag=tag,
            attrs=dict(child.attrib),
            text=child.text or "",
            tail=child.tail or "",
        )
        _collect(child, el.children, defs)
        ident = el.attrs.get("id")
        if ident and ident not in defs:
            defs[ident] = el
        if tag in _NON_RENDERED:
            continue
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
    if value.startswith("rgb"):
        return _rgb_func_color(value)
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


def _rgb_func_color(value: str) -> str | None:
    """Convert 'rgb(r, g, b)' with numbers or percentages to hex."""
    start, end = value.find("("), value.find(")")
    if start < 0 or end <= start:
        return None
    parts = [p.strip() for p in value[start + 1 : end].split(",")]
    if len(parts) < 3:
        return None
    channels = []
    for part in parts[:3]:
        try:
            if part.endswith("%"):
                num = float(part[:-1]) * 255.0 / 100.0
            else:
                num = float(part)
        except ValueError:
            return None
        channels.append(min(255, max(0, int(round(num)))))
    return "".join(f"{c:02x}" for c in channels)


def _style_attrs(el: SvgElement) -> dict:
    result = dict(el.attrs)
    style = el.attrs.get("style", "")
    for part in style.split(";"):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def _parse_float(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_num(value: str) -> float:
    nums = _NUM_RE.findall(value or "")
    return float(nums[0]) if nums else 0.0


def _url_id(value: str | None) -> str | None:
    if not value:
        return None
    match = _URL_RE.search(value)
    return match.group(1) if match else None


# -- matrices --


def _mat_mul(m1: tuple, m2: tuple) -> tuple:
    """Compose two affine matrices, applying m2 first and m1 second."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _mat_apply(m: tuple, px: float, py: float) -> tuple:
    return m[0] * px + m[2] * py + m[4], m[1] * px + m[3] * py + m[5]


def _parse_transform(text: str | None) -> tuple:
    """Parse an SVG transform list into a single affine matrix."""
    matrix = _IDENT
    if not text:
        return matrix
    for name, args in _TRANSFORM_RE.findall(text):
        nums = [float(v) for v in _NUM_RE.findall(args)]
        if name == "matrix" and len(nums) == 6:
            op = tuple(nums)
        elif name == "translate" and nums:
            op = (1.0, 0.0, 0.0, 1.0, nums[0], nums[1] if len(nums) > 1 else 0.0)
        elif name == "scale" and nums:
            sy = nums[1] if len(nums) > 1 else nums[0]
            op = (nums[0], 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate" and nums:
            rad = math.radians(nums[0])
            cos, sin = math.cos(rad), math.sin(rad)
            op = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                op = _mat_mul(
                    _mat_mul((1.0, 0.0, 0.0, 1.0, cx, cy), op),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
        elif name == "skewX" and nums:
            op = (1.0, 0.0, math.tan(math.radians(nums[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and nums:
            op = (1.0, math.tan(math.radians(nums[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        matrix = _mat_mul(matrix, op)
    return matrix


# -- path data --


def _quad_seg(cx, cy, qx, qy, x, y) -> tuple:
    """Convert one quadratic segment starting at (cx, cy) to a cubic."""
    return (
        "c",
        cx + 2.0 * (qx - cx) / 3.0,
        cy + 2.0 * (qy - cy) / 3.0,
        x + 2.0 * (qx - x) / 3.0,
        y + 2.0 * (qy - y) / 3.0,
        x,
        y,
    )


def _arc_point(cx, cy, rx, ry, cosp, sinp, th) -> tuple:
    return (
        cx + rx * cosp * math.cos(th) - ry * sinp * math.sin(th),
        cy + rx * sinp * math.cos(th) + ry * cosp * math.sin(th),
    )


def _arc_deriv(rx, ry, cosp, sinp, th) -> tuple:
    return (
        -rx * cosp * math.sin(th) - ry * sinp * math.cos(th),
        -rx * sinp * math.sin(th) + ry * cosp * math.cos(th),
    )


def _arc_segs(x1, y1, rx, ry, rot_deg, large, sweep, x2, y2) -> list:
    """Convert an endpoint-parameterized elliptical arc to cubic segments."""
    if x1 == x2 and y1 == y2:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0.0 or ry == 0.0:
        return [("l", x2, y2)]
    phi = math.radians(rot_deg % 360.0)
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cosp * dx + sinp * dy
    y1p = -sinp * dx + cosp * dy
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    rx2, ry2 = rx * rx, ry * ry
    num = rx2 * ry2 - rx2 * y1p * y1p - ry2 * x1p * x1p
    den = rx2 * y1p * y1p + ry2 * x1p * x1p
    factor = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        factor = -factor
    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx
    cx = cosp * cxp - sinp * cyp + (x1 + x2) / 2.0
    cy = sinp * cxp + cosp * cyp + (y1 + y2) / 2.0
    th1 = math.atan2((y1p - cyp) / ry, (x1p - cxp) / rx)
    th2 = math.atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx)
    dth = th2 - th1
    if sweep and dth < 0.0:
        dth += 2.0 * math.pi
    elif not sweep and dth > 0.0:
        dth -= 2.0 * math.pi
    count = max(1, int(math.ceil(abs(dth) / (math.pi / 2.0) - 1e-9)))
    delta = dth / count
    alpha = 4.0 / 3.0 * math.tan(delta / 4.0)
    segs = []
    th = th1
    for _ in range(count):
        p1 = _arc_point(cx, cy, rx, ry, cosp, sinp, th)
        d1 = _arc_deriv(rx, ry, cosp, sinp, th)
        th_next = th + delta
        p2 = _arc_point(cx, cy, rx, ry, cosp, sinp, th_next)
        d2 = _arc_deriv(rx, ry, cosp, sinp, th_next)
        segs.append(
            (
                "c",
                p1[0] + alpha * d1[0],
                p1[1] + alpha * d1[1],
                p2[0] - alpha * d2[0],
                p2[1] - alpha * d2[1],
                p2[0],
                p2[1],
            )
        )
        th = th_next
    last = segs[-1]
    segs[-1] = ("c", last[1], last[2], last[3], last[4], x2, y2)
    return segs


def _parse_path(d: str) -> list:
    """Parse SVG path data into absolute user-space segments."""
    tokens = _PATH_TOKEN_RE.findall(d)
    n = len(tokens)
    segs: list = []
    i = 0
    cmd = ""
    cx = cy = spx = spy = 0.0
    pc2 = pq = None

    def take(count):
        nonlocal i
        if i + count > n:
            return None
        try:
            vals = [float(tokens[i + k]) for k in range(count)]
        except ValueError:
            return None
        i += count
        return vals

    while i < n:
        tok = tokens[i]
        if len(tok) == 1 and tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                segs.append(("z",))
                cx, cy = spx, spy
                pc2 = pq = None
                cmd = ""
                continue
        if not cmd:
            break
        rel = cmd.islower()
        upper = cmd.upper()
        if upper == "M":
            vals = take(2)
            if vals is None:
                break
            px, py = vals
            if rel:
                px += cx
                py += cy
            cx, cy = px, py
            spx, spy = px, py
            segs.append(("m", cx, cy))
            cmd = "l" if rel else "L"
            pc2 = pq = None
        elif upper == "L":
            vals = take(2)
            if vals is None:
                break
            px, py = vals
            if rel:
                px += cx
                py += cy
            cx, cy = px, py
            segs.append(("l", cx, cy))
            pc2 = pq = None
        elif upper == "H":
            vals = take(1)
            if vals is None:
                break
            cx = cx + vals[0] if rel else vals[0]
            segs.append(("l", cx, cy))
            pc2 = pq = None
        elif upper == "V":
            vals = take(1)
            if vals is None:
                break
            cy = cy + vals[0] if rel else vals[0]
            segs.append(("l", cx, cy))
            pc2 = pq = None
        elif upper == "C":
            vals = take(6)
            if vals is None:
                break
            if rel:
                vals = [v + (cx if k % 2 == 0 else cy) for k, v in enumerate(vals)]
            x1, y1, x2, y2, px, py = vals
            segs.append(("c", x1, y1, x2, y2, px, py))
            cx, cy = px, py
            pc2 = (x2, y2)
            pq = None
        elif upper == "S":
            vals = take(4)
            if vals is None:
                break
            if rel:
                vals = [v + (cx if k % 2 == 0 else cy) for k, v in enumerate(vals)]
            x2, y2, px, py = vals
            x1, y1 = (2.0 * cx - pc2[0], 2.0 * cy - pc2[1]) if pc2 else (cx, cy)
            segs.append(("c", x1, y1, x2, y2, px, py))
            cx, cy = px, py
            pc2 = (x2, y2)
            pq = None
        elif upper == "Q":
            vals = take(4)
            if vals is None:
                break
            if rel:
                vals = [v + (cx if k % 2 == 0 else cy) for k, v in enumerate(vals)]
            qx, qy, px, py = vals
            segs.append(_quad_seg(cx, cy, qx, qy, px, py))
            cx, cy = px, py
            pq = (qx, qy)
            pc2 = None
        elif upper == "T":
            vals = take(2)
            if vals is None:
                break
            px, py = vals
            if rel:
                px += cx
                py += cy
            qx, qy = (2.0 * cx - pq[0], 2.0 * cy - pq[1]) if pq else (cx, cy)
            segs.append(_quad_seg(cx, cy, qx, qy, px, py))
            cx, cy = px, py
            pq = (qx, qy)
            pc2 = None
        elif upper == "A":
            vals = take(7)
            if vals is None:
                break
            arx, ary, rot, large, sweep, px, py = vals
            if rel:
                px += cx
                py += cy
            segs.extend(
                _arc_segs(cx, cy, arx, ary, rot, large != 0.0, sweep != 0.0, px, py)
            )
            cx, cy = px, py
            pc2 = pq = None
        else:
            break
    return segs


def _seg_ops(segs: list, pmap) -> list:
    """Format segments as PDF path operators through a point mapper."""
    ops = []
    for seg in segs:
        kind = seg[0]
        if kind == "m":
            px, py = pmap(seg[1], seg[2])
            ops.append(f"{px:.4f} {py:.4f} m")
        elif kind == "l":
            px, py = pmap(seg[1], seg[2])
            ops.append(f"{px:.4f} {py:.4f} l")
        elif kind == "c":
            x1, y1 = pmap(seg[1], seg[2])
            x2, y2 = pmap(seg[3], seg[4])
            x3, y3 = pmap(seg[5], seg[6])
            ops.append(f"{x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f} {x3:.4f} {y3:.4f} c")
        else:
            ops.append("h")
    return ops


def _segs_bbox(segs: list) -> tuple | None:
    xs, ys = [], []
    for seg in segs:
        coords = seg[1:]
        xs.extend(coords[0::2])
        ys.extend(coords[1::2])
    if not xs:
        return None
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _ellipse_segs(cx, cy, rx, ry) -> list:
    kx, ky = _KAPPA * rx, _KAPPA * ry
    return [
        ("m", cx + rx, cy),
        ("c", cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry),
        ("c", cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy),
        ("c", cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry),
        ("c", cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy),
        ("z",),
    ]


def _rect_segs(x, y, w, h) -> list:
    return [
        ("m", x, y),
        ("l", x + w, y),
        ("l", x + w, y + h),
        ("l", x, y + h),
        ("z",),
    ]


# -- colors and paint helpers --


def _color_op(hex_val, color_mode, stroke):
    """Build a color operator line for a hex color in the given mode."""
    r, g, b = (
        int(hex_val[0:2], 16) / 255,
        int(hex_val[2:4], 16) / 255,
        int(hex_val[4:6], 16) / 255,
    )
    if color_mode == "cmyk":
        cmyk = rgb_to_cmyk(r, g, b)
        op = "K" if stroke else "k"
        return f"{cmyk.c:.4f} {cmyk.m:.4f} {cmyk.y:.4f} {cmyk.k:.4f} {op}"
    op = "RG" if stroke else "rg"
    return f"{r:.4f} {g:.4f} {b:.4f} {op}"


def _fill_stroke(stream, ops, fill, stroke, stroke_w, color_mode="rgb"):
    raw_lines = []
    if fill:
        raw_lines.append(_color_op(fill, color_mode, stroke=False))
    if stroke:
        raw_lines.append(_color_op(stroke, color_mode, stroke=True))
        raw_lines.append(f"{stroke_w:.4f} w")
    raw_lines.extend(ops)
    if fill and stroke:
        raw_lines.append("B")
    elif fill:
        raw_lines.append("f")
    elif stroke:
        raw_lines.append("S")
    stream.raw("\n".join(raw_lines).encode("ascii"))


def _lerp_hex(c0: str, c1: str, t: float) -> str:
    out = []
    for k in (0, 2, 4):
        v0 = int(c0[k : k + 2], 16)
        v1 = int(c1[k : k + 2], 16)
        out.append(min(255, max(0, int(round(v0 + (v1 - v0) * t)))))
    return "".join(f"{v:02x}" for v in out)


def _stop_color(stops: list, t: float) -> str:
    t = min(1.0, max(0.0, t))
    if t <= stops[0][0]:
        return stops[0][1]
    for (o0, c0), (o1, c1) in zip(stops, stops[1:]):
        if t <= o1:
            if o1 <= o0:
                return c1
            return _lerp_hex(c0, c1, (t - o0) / (o1 - o0))
    return stops[-1][1]


# -- gradients --


def _frac(value: str) -> float:
    value = (value or "").strip()
    if value.endswith("%"):
        return _parse_float(value[:-1], 0.0) / 100.0
    return _parse_float(value, 0.0)


def _gradient_stops(el: SvgElement, defs: dict, depth: int) -> list:
    """Collect (offset, hex) stops, following href inheritance if empty."""
    stops = []
    for child in el.children:
        if child.tag != "stop":
            continue
        sattrs = _style_attrs(child)
        offset = min(1.0, max(0.0, _frac(sattrs.get("offset", "0"))))
        if stops and offset < stops[-1][0]:
            offset = stops[-1][0]
        color = _hex_color(sattrs.get("stop-color", "#000000")) or "000000"
        stops.append((offset, color))
    if not stops and depth < _MAX_REF_DEPTH:
        href = el.attrs.get("href") or el.attrs.get(_XLINK_HREF) or ""
        parent = defs.get(href[1:]) if href.startswith("#") else None
        if parent is not None and parent.tag in ("linearGradient", "radialGradient"):
            return _gradient_stops(parent, defs, depth + 1)
    return stops


def _parse_gradient(el: SvgElement, defs: dict) -> dict | None:
    attrs = _style_attrs(el)
    stops = _gradient_stops(el, defs, 0)
    if not stops:
        return None
    grad = {
        "kind": "linear" if el.tag == "linearGradient" else "radial",
        "units": attrs.get("gradientUnits", "objectBoundingBox"),
        "stops": stops,
    }
    if grad["kind"] == "linear":
        grad["x1"] = _frac(attrs.get("x1", "0%"))
        grad["y1"] = _frac(attrs.get("y1", "0%"))
        grad["x2"] = _frac(attrs.get("x2", "100%"))
        grad["y2"] = _frac(attrs.get("y2", "0%"))
    else:
        grad["cx"] = _frac(attrs.get("cx", "50%"))
        grad["cy"] = _frac(attrs.get("cy", "50%"))
        grad["r"] = _frac(attrs.get("r", "50%"))
        grad["fx"] = _frac(attrs.get("fx", attrs.get("cx", "50%")))
        grad["fy"] = _frac(attrs.get("fy", attrs.get("cy", "50%")))
    return grad


def _gradient_geometry(grad: dict, bbox: tuple) -> tuple:
    """Resolve gradient coordinates to user space for the given bbox."""
    bx, by, bw, bh = bbox
    obb = grad["units"] != "userSpaceOnUse"

    def resolve(value, origin, span):
        return origin + value * span if obb else value

    if grad["kind"] == "linear":
        return (
            resolve(grad["x1"], bx, bw),
            resolve(grad["y1"], by, bh),
            resolve(grad["x2"], bx, bw),
            resolve(grad["y2"], by, bh),
        )
    radius = grad["r"]
    if obb:
        radius = radius * math.hypot(bw, bh) / math.sqrt(2.0)
    return (
        resolve(grad["fx"], bx, bw),
        resolve(grad["fy"], by, bh),
        resolve(grad["cx"], bx, bw),
        resolve(grad["cy"], by, bh),
        radius,
    )


def _components(hex_val: str, cmyk: bool) -> list:
    r, g, b = (
        int(hex_val[0:2], 16) / 255,
        int(hex_val[2:4], 16) / 255,
        int(hex_val[4:6], 16) / 255,
    )
    if cmyk:
        c = rgb_to_cmyk(r, g, b)
        return [round(c.c, 4), round(c.m, 4), round(c.y, 4), round(c.k, 4)]
    return [round(r, 4), round(g, 4), round(b, 4)]


def _exp_function(c0: list, c1: list) -> dict:
    return {"FunctionType": 2, "Domain": [0.0, 1.0], "C0": c0, "C1": c1, "N": 1.0}


def _stitch_function(offsets: list, comps: list) -> dict:
    """Build a type 3 stitching function over type 2 exponential segments."""
    if len(comps) == 1:
        return _exp_function(comps[0], comps[0])
    if offsets[0] > 0.0:
        offsets = [0.0] + offsets
        comps = [comps[0]] + comps
    if offsets[-1] < 1.0:
        offsets = offsets + [1.0]
        comps = comps + [comps[-1]]
    if len(comps) == 2:
        return _exp_function(comps[0], comps[1])
    functions = [_exp_function(comps[k], comps[k + 1]) for k in range(len(comps) - 1)]
    return {
        "FunctionType": 3,
        "Domain": [0.0, 1.0],
        "Functions": functions,
        "Bounds": [round(o, 6) for o in offsets[1:-1]],
        "Encode": [0.0, 1.0] * len(functions),
    }


def gradient_shading(
    svg: SvgImage,
    gradient_id: str,
    bbox: tuple[float, float, float, float],
    color_mode: str = "rgb",
) -> dict | None:
    """Build a PDF type 2/3 /Shading dictionary for a gradient element."""
    el = svg.defs.get(gradient_id)
    if el is None or el.tag not in ("linearGradient", "radialGradient"):
        return None
    grad = _parse_gradient(el, svg.defs)
    if grad is None:
        return None
    cmyk = color_mode == "cmyk"
    stops = grad["stops"]
    comps = [_components(color, cmyk) for _, color in stops]
    shading = {
        "ColorSpace": "DeviceCMYK" if cmyk else "DeviceRGB",
        "Function": _stitch_function([offset for offset, _ in stops], comps),
        "Extend": [True, True],
    }
    if grad["kind"] == "linear":
        x1, y1, x2, y2 = _gradient_geometry(grad, bbox)
        shading["ShadingType"] = 2
        shading["Coords"] = [x1, y1, x2, y2]
    else:
        fx, fy, cx, cy, radius = _gradient_geometry(grad, bbox)
        shading["ShadingType"] = 3
        shading["Coords"] = [fx, fy, 0.0, cx, cy, radius]
    return shading


# -- legacy shape helpers (byte-stable for the original subset) --


def _parse_points(s: str, x, y, ox, oy, sx, sy):
    nums = _NUM_RE.findall(s)
    points = []
    for i in range(0, len(nums) - 1, 2):
        px = (float(nums[i]) - ox) * sx + x
        py = y - (float(nums[i + 1]) - oy) * sy
        points.append((px, py))
    return points


def _draw_circle(stream, cx, cy, r, fill, stroke, stroke_w, color_mode="rgb"):
    k = _KAPPA
    ops = []
    ops.append(f"{cx + r:.4f} {cy:.4f} m")
    ops.append(
        f"{cx + r:.4f} {cy + r * k:.4f} {cx + r * k:.4f} {cy + r:.4f} "
        f"{cx:.4f} {cy + r:.4f} c"
    )
    ops.append(
        f"{cx - r * k:.4f} {cy + r:.4f} {cx - r:.4f} {cy + r * k:.4f} "
        f"{cx - r:.4f} {cy:.4f} c"
    )
    ops.append(
        f"{cx - r:.4f} {cy - r * k:.4f} {cx - r * k:.4f} {cy - r:.4f} "
        f"{cx:.4f} {cy - r:.4f} c"
    )
    ops.append(
        f"{cx + r * k:.4f} {cy - r:.4f} {cx + r:.4f} {cy - r * k:.4f} "
        f"{cx + r:.4f} {cy:.4f} c"
    )
    _fill_stroke(stream, ops, fill, stroke, stroke_w, color_mode)


def _draw_ellipse(stream, cx, cy, rx, ry, fill, stroke, stroke_w, color_mode="rgb"):
    kx = _KAPPA * rx
    ky = _KAPPA * ry
    ops = []
    ops.append(f"{cx + rx:.4f} {cy:.4f} m")
    ops.append(
        f"{cx + rx:.4f} {cy + ky:.4f} {cx + kx:.4f} {cy + ry:.4f} "
        f"{cx:.4f} {cy + ry:.4f} c"
    )
    ops.append(
        f"{cx - kx:.4f} {cy + ry:.4f} {cx - rx:.4f} {cy + ky:.4f} "
        f"{cx - rx:.4f} {cy:.4f} c"
    )
    ops.append(
        f"{cx - rx:.4f} {cy - ky:.4f} {cx - kx:.4f} {cy - ry:.4f} "
        f"{cx:.4f} {cy - ry:.4f} c"
    )
    ops.append(
        f"{cx + kx:.4f} {cy - ry:.4f} {cx + rx:.4f} {cy - ky:.4f} "
        f"{cx + rx:.4f} {cy:.4f} c"
    )
    _fill_stroke(stream, ops, fill, stroke, stroke_w, color_mode)


def _draw_polygon(stream, points, fill, stroke, stroke_w, color_mode="rgb"):
    if not points:
        return
    ops = [f"{points[0][0]:.4f} {points[0][1]:.4f} m"]
    for px, py in points[1:]:
        ops.append(f"{px:.4f} {py:.4f} l")
    if fill:
        ops.append("h")
    _fill_stroke(stream, ops, fill, stroke, stroke_w, color_mode)


# -- renderer --


@dataclass
class _Ctx:
    """Inherited presentation state carried down the element tree."""

    transform: tuple = _IDENT
    fill: str | None = None
    stroke: str | None = None
    stroke_width: str | None = None
    opacity: float = 1.0
    fill_opacity: float = 1.0
    stroke_opacity: float = 1.0


class _Renderer:
    """Walks an SvgImage tree and emits PDF operators to a content stream."""

    def __init__(self, stream, svg: SvgImage, x, y, display_width, display_height):
        self.stream = stream
        self.color_mode = getattr(stream, "color_mode", "rgb")
        self.defs = svg.defs
        self.sx = display_width / svg.aspect_width if svg.aspect_width else 1.0
        self.sy = display_height / svg.aspect_height if svg.aspect_height else 1.0
        self.ox = svg.view_box[0] if svg.view_box else 0.0
        self.oy = svg.view_box[1] if svg.view_box else 0.0
        self.x = x
        self.y = y
        self.base = (
            self.sx,
            0.0,
            0.0,
            -self.sy,
            x - self.ox * self.sx,
            y + self.oy * self.sy,
        )

    def render(self, elements: list) -> None:
        self.stream.save()
        ctx = _Ctx()
        for el in elements:
            self._walk(el, ctx, 0)
        self.stream.restore()

    def _vmap(self, px: float, py: float) -> tuple:
        return (px - self.ox) * self.sx + self.x, self.y - (py - self.oy) * self.sy

    # -- tree walking --

    def _walk(self, el: SvgElement, ctx: _Ctx, depth: int) -> None:
        tag = el.tag
        if tag in ("g", "a", "symbol", "switch"):
            attrs = _style_attrs(el)
            if attrs.get("display") == "none":
                return
            child_ctx = self._inherit(ctx, attrs)
            clip = self._clip_ops(attrs.get("clip-path"), child_ctx.transform)
            if clip:
                self.stream.raw(b"q")
                self.stream.raw("\n".join(clip).encode("ascii"))
            for child in el.children:
                self._walk(child, child_ctx, depth)
            if clip:
                self.stream.raw(b"Q")
        elif tag == "use":
            self._use(el, ctx, depth)
        elif tag == "text":
            self._text(el, ctx)
        elif tag in _DRAWABLE:
            self._draw(el, ctx)

    def _inherit(self, ctx: _Ctx, attrs: dict) -> _Ctx:
        transform = ctx.transform
        if "transform" in attrs:
            transform = _mat_mul(transform, _parse_transform(attrs["transform"]))
        return _Ctx(
            transform=transform,
            fill=attrs.get("fill", ctx.fill),
            stroke=attrs.get("stroke", ctx.stroke),
            stroke_width=attrs.get("stroke-width", ctx.stroke_width),
            opacity=ctx.opacity * _parse_float(attrs.get("opacity"), 1.0),
            fill_opacity=_parse_float(attrs.get("fill-opacity"), ctx.fill_opacity),
            stroke_opacity=_parse_float(
                attrs.get("stroke-opacity"), ctx.stroke_opacity
            ),
        )

    def _use(self, el: SvgElement, ctx: _Ctx, depth: int) -> None:
        if depth >= _MAX_REF_DEPTH:
            return
        attrs = _style_attrs(el)
        href = attrs.get("href") or attrs.get(_XLINK_HREF) or ""
        if not href.startswith("#"):
            return
        target = self.defs.get(href[1:])
        if target is None:
            return
        child_ctx = self._inherit(ctx, attrs)
        ux = _parse_float(attrs.get("x"), 0.0)
        uy = _parse_float(attrs.get("y"), 0.0)
        if ux or uy:
            child_ctx = replace(
                child_ctx,
                transform=_mat_mul(child_ctx.transform, (1.0, 0.0, 0.0, 1.0, ux, uy)),
            )
        self._walk(target, child_ctx, depth + 1)

    # -- shapes --

    def _shape_segs(self, tag: str, attrs: dict) -> list:
        get = attrs.get
        if tag == "rect":
            return _rect_segs(
                _parse_float(get("x"), 0.0),
                _parse_float(get("y"), 0.0),
                _parse_float(get("width"), 0.0),
                _parse_float(get("height"), 0.0),
            )
        if tag == "circle":
            r = _parse_float(get("r"), 0.0)
            return _ellipse_segs(
                _parse_float(get("cx"), 0.0), _parse_float(get("cy"), 0.0), r, r
            )
        if tag == "ellipse":
            return _ellipse_segs(
                _parse_float(get("cx"), 0.0),
                _parse_float(get("cy"), 0.0),
                _parse_float(get("rx"), 0.0),
                _parse_float(get("ry"), 0.0),
            )
        if tag == "line":
            return [
                ("m", _parse_float(get("x1"), 0.0), _parse_float(get("y1"), 0.0)),
                ("l", _parse_float(get("x2"), 0.0), _parse_float(get("y2"), 0.0)),
            ]
        if tag in ("polygon", "polyline"):
            nums = [float(v) for v in _NUM_RE.findall(get("points", ""))]
            segs: list = []
            for k in range(0, len(nums) - 1, 2):
                kind = "m" if not segs else "l"
                segs.append((kind, nums[k], nums[k + 1]))
            if segs and tag == "polygon":
                segs.append(("z",))
            return segs
        if tag == "path":
            return _parse_path(get("d", ""))
        return []

    def _draw(self, el: SvgElement, ctx: _Ctx) -> None:
        tag = el.tag
        attrs = _style_attrs(el)
        if attrs.get("display") == "none":
            return
        transform = ctx.transform
        if "transform" in attrs:
            transform = _mat_mul(transform, _parse_transform(attrs["transform"]))

        fill_raw = attrs.get("fill", ctx.fill)
        stroke_raw = attrs.get("stroke", ctx.stroke)
        sw_raw = attrs.get("stroke-width", ctx.stroke_width)
        stroke_w = _parse_length(sw_raw) if sw_raw is not None else 1.0
        elem_opacity = _parse_float(attrs.get("opacity"), 1.0)
        fill_alpha = (
            ctx.opacity
            * elem_opacity
            * _parse_float(attrs.get("fill-opacity"), ctx.fill_opacity)
        )
        stroke_alpha = (
            ctx.opacity
            * elem_opacity
            * _parse_float(attrs.get("stroke-opacity"), ctx.stroke_opacity)
        )

        gradient = None
        if fill_raw and fill_raw.startswith("url("):
            ident = _url_id(fill_raw)
            grad_el = self.defs.get(ident) if ident else None
            if grad_el is not None and grad_el.tag in (
                "linearGradient",
                "radialGradient",
            ):
                gradient = _parse_gradient(grad_el, self.defs)
            fill = None
        else:
            fill = _hex_color(fill_raw)
        stroke = _hex_color(stroke_raw)
        if tag in ("line", "polyline"):
            fill = None
            gradient = None

        clip = self._clip_ops(attrs.get("clip-path"), transform)
        legacy = (
            transform == _IDENT
            and gradient is None
            and clip is None
            and fill_alpha >= 1.0
            and stroke_alpha >= 1.0
        )
        if legacy:
            self._draw_legacy(tag, attrs, fill, stroke, stroke_w)
            return
        if gradient is None and not fill and not stroke:
            return
        segs = self._shape_segs(tag, attrs)
        if not segs:
            return
        self._emit_modern(
            segs,
            transform,
            fill,
            stroke,
            stroke_w,
            gradient,
            fill_alpha,
            stroke_alpha,
            clip,
        )

    def _draw_legacy(self, tag, attrs, fill, stroke, stroke_w) -> None:
        """Render with the original ops so the old subset stays byte-stable."""
        stream = self.stream
        mode = self.color_mode
        if tag == "rect":
            rx = (float(attrs.get("x", "0")) - self.ox) * self.sx + self.x
            ry = self.y - (float(attrs.get("y", "0")) - self.oy) * self.sy
            rw = float(attrs.get("width", "0")) * self.sx
            rh = float(attrs.get("height", "0")) * self.sy
            ry -= rh
            if fill:
                stream.rect(rx, ry, rw, rh, fill=fill)
            if stroke:
                stream.rect(rx, ry, rw, rh, fill=None)
        elif tag == "circle":
            cx, cy = self._vmap(float(attrs.get("cx", "0")), float(attrs.get("cy", "0")))
            r = float(attrs.get("r", "0")) * min(self.sx, self.sy)
            _draw_circle(stream, cx, cy, r, fill, stroke, stroke_w, mode)
        elif tag == "ellipse":
            cx, cy = self._vmap(float(attrs.get("cx", "0")), float(attrs.get("cy", "0")))
            erx = float(attrs.get("rx", "0")) * self.sx
            ery = float(attrs.get("ry", "0")) * self.sy
            _draw_ellipse(stream, cx, cy, erx, ery, fill, stroke, stroke_w, mode)
        elif tag == "line":
            x1, y1 = self._vmap(float(attrs.get("x1", "0")), float(attrs.get("y1", "0")))
            x2, y2 = self._vmap(float(attrs.get("x2", "0")), float(attrs.get("y2", "0")))
            color = stroke or "000000"
            width = stroke_w * min(self.sx, self.sy)
            stream.line(x1, y1, x2, y2, color=color, width=width)
        elif tag == "path":
            d = attrs.get("d", "")
            if d:
                ops = _seg_ops(_parse_path(d), self._vmap)
                if ops:
                    _fill_stroke(stream, ops, fill, stroke, stroke_w, mode)
        elif tag in ("polygon", "polyline"):
            points_str = attrs.get("points", "")
            if points_str:
                points = _parse_points(
                    points_str, self.x, self.y, self.ox, self.oy, self.sx, self.sy
                )
                if points:
                    _draw_polygon(
                        stream,
                        points,
                        fill if tag == "polygon" else None,
                        stroke,
                        stroke_w,
                        mode,
                    )

    def _emit_modern(
        self,
        segs,
        transform,
        fill,
        stroke,
        stroke_w,
        gradient,
        fill_alpha,
        stroke_alpha,
        clip,
    ) -> None:
        """Render a shape inside q/Q with cm, ExtGState, clip, or gradient."""
        lines = ["q"]
        if clip:
            lines.extend(clip)
        if fill_alpha < 1.0 or stroke_alpha < 1.0:
            lines.append(f"/{self._gstate(fill_alpha, stroke_alpha)} gs")
        full = _mat_mul(self.base, transform)
        lines.append(
            f"{full[0]:.4f} {full[1]:.4f} {full[2]:.4f} "
            f"{full[3]:.4f} {full[4]:.4f} {full[5]:.4f} cm"
        )
        ops = _seg_ops(segs, lambda px, py: (px, py))
        if gradient is not None:
            bbox = _segs_bbox(segs)
            lines.extend(ops)
            lines.append("W n")
            if bbox is not None:
                lines.extend(self._gradient_ops(gradient, bbox))
            if stroke:
                lines.append(_color_op(stroke, self.color_mode, stroke=True))
                lines.append(f"{stroke_w:.4f} w")
                lines.extend(ops)
                lines.append("S")
        else:
            if fill:
                lines.append(_color_op(fill, self.color_mode, stroke=False))
            if stroke:
                lines.append(_color_op(stroke, self.color_mode, stroke=True))
                lines.append(f"{stroke_w:.4f} w")
            lines.extend(ops)
            if fill and stroke:
                lines.append("B")
            elif fill:
                lines.append("f")
            else:
                lines.append("S")
        lines.append("Q")
        self.stream.raw("\n".join(lines).encode("ascii"))

    # -- resources recorded on the stream for writer wiring --

    def _gstate(self, fill_alpha: float, stroke_alpha: float) -> str:
        ca = round(min(max(fill_alpha, 0.0), 1.0), 4)
        stroke_ca = round(min(max(stroke_alpha, 0.0), 1.0), 4)
        registry = getattr(self.stream, "used_svg_gstates", None)
        if registry is None:
            registry = {}
            self.stream.used_svg_gstates = registry
        for name, value in registry.items():
            if value == {"ca": ca, "CA": stroke_ca}:
                return name
        name = f"GSsvg{len(registry) + 1}"
        registry[name] = {"ca": ca, "CA": stroke_ca}
        return name

    def _register_font(self, font_name: str) -> str:
        registry = getattr(self.stream, "used_svg_fonts", None)
        if registry is None:
            registry = {}
            self.stream.used_svg_fonts = registry
        key = _FAMILY_KEYS[font_name]
        registry[key] = font_name
        return key

    # -- clipping --

    def _clip_ops(self, ref: str | None, transform: tuple) -> list | None:
        ident = _url_id(ref)
        if not ident:
            return None
        target = self.defs.get(ident)
        if target is None or target.tag != "clipPath":
            return None
        full = _mat_mul(self.base, transform)
        ops: list = []
        for child in target.children:
            cattrs = _style_attrs(child)
            child_mat = full
            if "transform" in cattrs:
                child_mat = _mat_mul(full, _parse_transform(cattrs["transform"]))
            segs = self._shape_segs(child.tag, cattrs)
            if segs:
                ops.extend(
                    _seg_ops(segs, lambda px, py, m=child_mat: _mat_apply(m, px, py))
                )
        if not ops:
            return None
        ops.append("W n")
        return ops

    # -- gradients (inline banded fills; see gradient_shading for wiring) --

    def _gradient_ops(self, grad: dict, bbox: tuple) -> list:
        if grad["kind"] == "linear":
            return self._linear_gradient_ops(grad, bbox)
        return self._radial_gradient_ops(grad, bbox)

    def _linear_gradient_ops(self, grad: dict, bbox: tuple) -> list:
        bx, by, bw, bh = bbox
        stops = grad["stops"]
        mode = self.color_mode
        x1, y1, x2, y2 = _gradient_geometry(grad, bbox)
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        lines: list = []
        if length_sq <= 0.0:
            lines.append(_color_op(stops[-1][1], mode, stroke=False))
            lines.extend(_seg_ops(_rect_segs(bx, by, bw, bh), lambda a, b: (a, b)))
            lines.append("f")
            return lines
        corners = [(bx, by), (bx + bw, by), (bx, by + bh), (bx + bw, by + bh)]
        ts = [((px - x1) * dx + (py - y1) * dy) / length_sq for px, py in corners]
        tmin = min(ts + [0.0])
        tmax = max(ts + [1.0])
        length = math.sqrt(length_sq)
        nx, ny = -dy / length, dx / length
        ext = math.hypot(bw, bh)
        edges = [tmin] + [k / _GRADIENT_BANDS for k in range(_GRADIENT_BANDS + 1)]
        edges.append(tmax)
        for t0, t1 in zip(edges, edges[1:]):
            if t1 - t0 <= 1e-12:
                continue
            color = _stop_color(stops, (t0 + t1) / 2.0)
            p0 = (x1 + dx * t0, y1 + dy * t0)
            p1 = (x1 + dx * t1, y1 + dy * t1)
            quad = [
                (p0[0] + nx * ext, p0[1] + ny * ext),
                (p1[0] + nx * ext, p1[1] + ny * ext),
                (p1[0] - nx * ext, p1[1] - ny * ext),
                (p0[0] - nx * ext, p0[1] - ny * ext),
            ]
            lines.append(_color_op(color, mode, stroke=False))
            lines.append(f"{quad[0][0]:.4f} {quad[0][1]:.4f} m")
            for px, py in quad[1:]:
                lines.append(f"{px:.4f} {py:.4f} l")
            lines.append("h")
            lines.append("f")
        return lines

    def _radial_gradient_ops(self, grad: dict, bbox: tuple) -> list:
        bx, by, bw, bh = bbox
        stops = grad["stops"]
        mode = self.color_mode
        fx, fy, cx, cy, radius = _gradient_geometry(grad, bbox)
        lines = [_color_op(stops[-1][1], mode, stroke=False)]
        lines.extend(_seg_ops(_rect_segs(bx, by, bw, bh), lambda a, b: (a, b)))
        lines.append("f")
        if radius <= 0.0:
            return lines
        for band in range(_GRADIENT_BANDS, 0, -1):
            t = band / _GRADIENT_BANDS
            mid = (band - 0.5) / _GRADIENT_BANDS
            ccx = fx + (cx - fx) * t
            ccy = fy + (cy - fy) * t
            rr = radius * t
            lines.append(_color_op(_stop_color(stops, mid), mode, stroke=False))
            lines.extend(_seg_ops(_ellipse_segs(ccx, ccy, rr, rr), lambda a, b: (a, b)))
            lines.append("f")
        return lines

    # -- text --

    def _text(self, el: SvgElement, ctx: _Ctx) -> None:
        attrs = _style_attrs(el)
        if attrs.get("display") == "none":
            return
        transform = ctx.transform
        if "transform" in attrs:
            transform = _mat_mul(transform, _parse_transform(attrs["transform"]))
        content = " ".join(_flatten_text(el).split())
        if not content:
            return
        fill_raw = attrs.get("fill", ctx.fill)
        if fill_raw == "none":
            return
        color = _hex_color(fill_raw) or "000000"
        anchor_x = _first_num(attrs.get("x", "0"))
        anchor_y = _first_num(attrs.get("y", "0"))
        size = _parse_length(attrs.get("font-size", "16")) or 16.0
        font_name = _map_family(attrs.get("font-family", ""))
        metrics = FontMetrics.base14(font_name)
        width = metrics.text_width(content, size)
        anchor = attrs.get("text-anchor", "start")
        if anchor == "middle":
            anchor_x -= width / 2.0
        elif anchor == "end":
            anchor_x -= width
        full = _mat_mul(self.base, transform)
        px, py = _mat_apply(full, anchor_x, anchor_y)
        det = abs(full[0] * full[3] - full[1] * full[2])
        page_size = size * math.sqrt(det)
        key = self._register_font(font_name)
        alpha = (
            ctx.opacity
            * _parse_float(attrs.get("opacity"), 1.0)
            * _parse_float(attrs.get("fill-opacity"), ctx.fill_opacity)
        )
        wrapped = alpha < 1.0
        if wrapped:
            self.stream.raw(b"q")
            self.stream.raw(f"/{self._gstate(alpha, alpha)} gs".encode("ascii"))
        self.stream.text_line(content, key, page_size, px, py, color)
        if wrapped:
            self.stream.raw(b"Q")


def _flatten_text(el: SvgElement) -> str:
    parts = [el.text]
    for child in el.children:
        parts.append(_flatten_text(child))
        parts.append(child.tail)
    return "".join(parts)


def _map_family(value: str) -> str:
    """Map a font-family list onto the nearest base-14 family."""
    for token in (value or "").split(","):
        fam = token.strip().strip("'\"").lower()
        if not fam:
            continue
        if "mono" in fam or "courier" in fam:
            return "Courier"
        if "sans" in fam or "helvetica" in fam or "arial" in fam:
            return "Helvetica"
        if "serif" in fam or "times" in fam:
            return "Times-Roman"
    return "Helvetica"


def render_svg(
    stream,
    svg: SvgImage,
    x: float,
    y: float,
    display_width: float,
    display_height: float,
) -> None:
    """Render a parsed SvgImage into a content stream at (x, y) top-left."""
    renderer = _Renderer(stream, svg, x, y, display_width, display_height)
    renderer.render(svg.elements)
