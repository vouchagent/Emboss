"""Layered node/edge diagrams compiled to SVG for the SvgBlock render path."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Sequence

from .typography.font_metrics import FontMetrics

__all__ = [
    "DiagramNode",
    "DiagramEdge",
    "PlacedNode",
    "DiagramLayout",
    "layout_diagram",
    "render_diagram_svg",
    "diagram_alt_text",
    "diagram_svg_block",
    "parse_diagram_source",
    "diagram_block_from_source",
]

NodeShape = Literal["box", "decision", "store", "rounded", "start_end"]
EdgeStyle = Literal["solid", "dashed"]

_SHAPES = ("box", "decision", "store", "rounded", "start_end")
_STYLES = ("solid", "dashed")

_FONT_SIZE = 9.0
_LABEL_FONT_SIZE = 8.0
_LINE_HEIGHT = 11.0
_MAX_NODE_WIDTH = 140.0
_MIN_NODE_WIDTH = 60.0
_MIN_NODE_HEIGHT = 28.0
_PADDING = 8.0
_LAYER_GAP = 44.0
_SIBLING_GAP = 24.0
_MARGIN = 12.0
_ARROW_LENGTH = 7.0
_ARROW_HALF_WIDTH = 3.0
_DASH_ON = 4.0
_DASH_OFF = 3.0
_STORE_CAP = 7.0
_ROUND_RADIUS = 7.0
_LOOP_EXTENT = 18.0

_DEFAULT_THEME = {
    "fill": "#f7f9fb",
    "stroke": "#4a5866",
    "text": "#1f2933",
    "edge": "#4a5866",
    "label_background": "#ffffff",
}

_NODE_LINE_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:\s*(.+?)(?:\s*\[([a-z_]+)\])?\s*$")
_EDGE_LINE_RE = re.compile(
    r"^([A-Za-z0-9_.-]+)\s*(-->|->)\s*([A-Za-z0-9_.-]+)\s*(?::\s*(.+?)\s*)?$"
)
_DIRECTION_LINE_RE = re.compile(r"^direction\s*:\s*(\S+)\s*$", re.IGNORECASE)


@dataclass
class DiagramNode:
    """One node in a diagram; `group` is carried as metadata for callers."""

    id: str
    label: str
    shape: str = "box"
    group: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("diagram node id must be a non-empty string")
        if self.shape not in _SHAPES:
            raise ValueError(
                f"unknown node shape {self.shape!r}; expected one of {_SHAPES}"
            )


@dataclass
class DiagramEdge:
    """A directed connection between two node ids."""

    src: str
    dst: str
    label: str | None = None
    style: str = "solid"

    def __post_init__(self) -> None:
        if self.style not in _STYLES:
            raise ValueError(
                f"unknown edge style {self.style!r}; expected one of {_STYLES}"
            )


@dataclass
class PlacedNode:
    """A node with its resolved page-space box and wrapped label lines."""

    node: DiagramNode
    x: float
    y: float
    width: float
    height: float
    lines: tuple
    layer: int

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0


@dataclass
class DiagramLayout:
    """A positioned diagram: placed nodes, canvas size, and layer ordering."""

    nodes: list
    edges: list
    width: float
    height: float
    direction: str
    layers: list

    @property
    def by_id(self) -> dict:
        return {placed.node.id: placed for placed in self.nodes}


def _as_node(item) -> DiagramNode:
    """Coerce a DiagramNode, (id, label[, shape]) tuple, or dict to a node."""
    if isinstance(item, DiagramNode):
        return item
    if isinstance(item, dict):
        return DiagramNode(**item)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 4:
        return DiagramNode(*item)
    raise TypeError(f"cannot build a DiagramNode from {item!r}")


def _as_edge(item) -> DiagramEdge:
    """Coerce a DiagramEdge, (src, dst[, label[, style]]) tuple, or dict."""
    if isinstance(item, DiagramEdge):
        return item
    if isinstance(item, dict):
        return DiagramEdge(**item)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 4:
        return DiagramEdge(*item)
    raise TypeError(f"cannot build a DiagramEdge from {item!r}")


def _normalize(nodes: Sequence, edges: Sequence) -> tuple:
    """Validate and coerce loose node/edge input into model instances."""
    node_list = [_as_node(n) for n in nodes]
    if not node_list:
        raise ValueError("diagram requires at least one node")
    seen: set = set()
    for node in node_list:
        if node.id in seen:
            raise ValueError(f"duplicate diagram node id: {node.id!r}")
        seen.add(node.id)
    edge_list = [_as_edge(e) for e in edges]
    for edge in edge_list:
        for endpoint in (edge.src, edge.dst):
            if endpoint not in seen:
                raise ValueError(
                    f"diagram edge references unknown node id: {endpoint!r}"
                )
    return node_list, edge_list


# -- label measurement --


def _metrics() -> FontMetrics:
    return FontMetrics.base14("Helvetica")


def _wrap_label(label: str, metrics: FontMetrics) -> tuple:
    """Greedy word wrap of `label` to the maximum node text width."""
    limit = _MAX_NODE_WIDTH - 2.0 * _PADDING
    words = label.split()
    if not words:
        return ("",)
    lines: list = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if metrics.text_width(candidate, _FONT_SIZE) <= limit:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return tuple(lines)


def _node_size(node: DiagramNode, lines: tuple, metrics: FontMetrics) -> tuple:
    """Compute the node box size from wrapped label lines plus shape allowance."""
    text_w = max(metrics.text_width(line, _FONT_SIZE) for line in lines)
    width = max(_MIN_NODE_WIDTH, text_w + 2.0 * _PADDING)
    height = max(_MIN_NODE_HEIGHT, len(lines) * _LINE_HEIGHT + 2.0 * _PADDING)
    if node.shape == "decision":
        width *= 1.4
        height *= 1.6
    elif node.shape == "store":
        height += 2.0 * _STORE_CAP
    elif node.shape == "start_end":
        width += height
    return width, height


# -- graph algorithms --


def _acyclic_pairs(node_ids: list, edges: list) -> set:
    """Find back-edge (src, dst) pairs via iterative DFS in input order."""
    adjacency: dict = {nid: [] for nid in node_ids}
    for edge in edges:
        if edge.src != edge.dst:
            adjacency[edge.src].append(edge.dst)
    state = {nid: 0 for nid in node_ids}
    back: set = set()
    for root in node_ids:
        if state[root]:
            continue
        state[root] = 1
        stack = [(root, iter(adjacency[root]))]
        while stack:
            current, children = stack[-1]
            child = next(children, None)
            if child is None:
                state[current] = 2
                stack.pop()
                continue
            if state[child] == 0:
                state[child] = 1
                stack.append((child, iter(adjacency[child])))
            elif state[child] == 1:
                back.add((current, child))
    return back


def _layout_edges(edges: list, back: set) -> list:
    """Return (src, dst) pairs with back edges reversed and self-loops dropped."""
    pairs = []
    for edge in edges:
        if edge.src == edge.dst:
            continue
        if (edge.src, edge.dst) in back:
            pairs.append((edge.dst, edge.src))
        else:
            pairs.append((edge.src, edge.dst))
    return pairs


def _assign_layers(node_ids: list, pairs: list) -> dict:
    """Longest-path layering over the acyclic edge pairs."""
    indegree = {nid: 0 for nid in node_ids}
    successors: dict = {nid: [] for nid in node_ids}
    for src, dst in pairs:
        successors[src].append(dst)
        indegree[dst] += 1
    layer = {nid: 0 for nid in node_ids}
    queue = [nid for nid in node_ids if indegree[nid] == 0]
    index = 0
    while index < len(queue):
        current = queue[index]
        index += 1
        for succ in successors[current]:
            layer[succ] = max(layer[succ], layer[current] + 1)
            indegree[succ] -= 1
            if indegree[succ] == 0:
                queue.append(succ)
    return layer


def _order_layers(node_ids: list, layer_of: dict, pairs: list) -> list:
    """Within-layer ordering by barycenter sweeps (2 down + 2 up passes)."""
    count = max(layer_of.values()) + 1 if layer_of else 1
    layers: list = [[] for _ in range(count)]
    for nid in node_ids:
        layers[layer_of[nid]].append(nid)

    predecessors: dict = {nid: [] for nid in node_ids}
    successors: dict = {nid: [] for nid in node_ids}
    for src, dst in pairs:
        if dst not in successors[src]:
            successors[src].append(dst)
        if src not in predecessors[dst]:
            predecessors[dst].append(src)

    def positions() -> dict:
        pos = {}
        for members in layers:
            for idx, nid in enumerate(members):
                pos[nid] = (idx + 0.5) / len(members)
        return pos

    def sweep(indices, neighbors: dict) -> None:
        for li in indices:
            pos = positions()
            members = layers[li]
            barys = {}
            for idx, nid in enumerate(members):
                linked = neighbors[nid]
                if linked:
                    barys[nid] = sum(pos[n] for n in linked) / len(linked)
                else:
                    barys[nid] = (idx + 0.5) / len(members)
            members.sort(key=lambda nid: (barys[nid], nid))

    down = range(1, count)
    up = range(count - 2, -1, -1)
    for indices, neighbors in ((down, predecessors), (up, successors)) * 2:
        sweep(indices, neighbors)
    return layers


def layout_diagram(
    nodes: Sequence, edges: Sequence = (), direction: str = "down"
) -> DiagramLayout:
    """Compute a layered DAG layout with even spacing for a node/edge graph."""
    if direction not in ("down", "right"):
        raise ValueError(f"diagram direction must be 'down' or 'right': {direction!r}")
    node_list, edge_list = _normalize(nodes, edges)
    node_ids = [n.id for n in node_list]
    node_map = {n.id: n for n in node_list}

    back = _acyclic_pairs(node_ids, edge_list)
    pairs = _layout_edges(edge_list, back)
    layer_of = _assign_layers(node_ids, pairs)
    layers = _order_layers(node_ids, layer_of, pairs)

    metrics = _metrics()
    lines_of = {nid: _wrap_label(node_map[nid].label, metrics) for nid in node_ids}
    size_of = {
        nid: _node_size(node_map[nid], lines_of[nid], metrics) for nid in node_ids
    }

    def cross_size(nid: str) -> float:
        width, height = size_of[nid]
        return width if direction == "down" else height

    def flow_size(nid: str) -> float:
        width, height = size_of[nid]
        return height if direction == "down" else width

    breadths = [
        sum(cross_size(nid) for nid in members) + _SIBLING_GAP * (len(members) - 1)
        for members in layers
    ]
    max_breadth = max(breadths)

    placement: dict = {}
    flow_cursor = _MARGIN
    for members, breadth in zip(layers, breadths):
        thickness = max(flow_size(nid) for nid in members)
        cross_cursor = _MARGIN + (max_breadth - breadth) / 2.0
        for nid in members:
            flow_pos = flow_cursor + (thickness - flow_size(nid)) / 2.0
            placement[nid] = (cross_cursor, flow_pos)
            cross_cursor += cross_size(nid) + _SIBLING_GAP
        flow_cursor += thickness + _LAYER_GAP
    flow_extent = flow_cursor - _LAYER_GAP + _MARGIN
    cross_extent = max_breadth + 2.0 * _MARGIN

    placed_nodes = []
    for node in node_list:
        cross, flow = placement[node.id]
        width, height = size_of[node.id]
        if direction == "down":
            x, y = cross, flow
        else:
            x, y = flow, cross
        placed_nodes.append(
            PlacedNode(
                node=node,
                x=x,
                y=y,
                width=width,
                height=height,
                lines=lines_of[node.id],
                layer=layer_of[node.id],
            )
        )

    if direction == "down":
        canvas_w, canvas_h = cross_extent, flow_extent
    else:
        canvas_w, canvas_h = flow_extent, cross_extent
    return DiagramLayout(
        nodes=placed_nodes,
        edges=edge_list,
        width=canvas_w,
        height=canvas_h,
        direction=direction,
        layers=layers,
    )


# -- SVG emission --


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rounded_rect_path(x, y, w, h, r) -> str:
    """Rounded-rect path with real arcs (the SVG subset ignores rect rx)."""
    r = min(r, w / 2.0, h / 2.0)
    arc = f"A {_fmt(r)} {_fmt(r)} 0 0 1"
    return (
        f"M {_fmt(x + r)} {_fmt(y)} "
        f"L {_fmt(x + w - r)} {_fmt(y)} {arc} {_fmt(x + w)} {_fmt(y + r)} "
        f"L {_fmt(x + w)} {_fmt(y + h - r)} {arc} {_fmt(x + w - r)} {_fmt(y + h)} "
        f"L {_fmt(x + r)} {_fmt(y + h)} {arc} {_fmt(x)} {_fmt(y + h - r)} "
        f"L {_fmt(x)} {_fmt(y + r)} {arc} {_fmt(x + r)} {_fmt(y)} Z"
    )


def _shape_markup(placed: PlacedNode, fill: str, stroke: str) -> list:
    """Emit the outline element(s) for one node shape."""
    x, y, w, h = placed.x, placed.y, placed.width, placed.height
    paint = f'fill="{fill}" stroke="{stroke}" stroke-width="1"'
    shape = placed.node.shape
    if shape == "box":
        return [
            f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" '
            f'height="{_fmt(h)}" rx="2" {paint}/>'
        ]
    if shape == "rounded":
        return [f'<path d="{_rounded_rect_path(x, y, w, h, _ROUND_RADIUS)}" {paint}/>']
    if shape == "start_end":
        return [f'<path d="{_rounded_rect_path(x, y, w, h, h / 2.0)}" {paint}/>']
    if shape == "decision":
        cx, cy = placed.center_x, placed.center_y
        d = (
            f"M {_fmt(cx)} {_fmt(y)} L {_fmt(x + w)} {_fmt(cy)} "
            f"L {_fmt(cx)} {_fmt(y + h)} L {_fmt(x)} {_fmt(cy)} Z"
        )
        return [f'<path d="{d}" {paint}/>']
    # store: cylinder = body path with an elliptical bottom + top rim ellipse
    rx, ry = w / 2.0, _STORE_CAP
    cx = placed.center_x
    body = (
        f"M {_fmt(x)} {_fmt(y + ry)} L {_fmt(x)} {_fmt(y + h - ry)} "
        f"A {_fmt(rx)} {_fmt(ry)} 0 0 0 {_fmt(x + w)} {_fmt(y + h - ry)} "
        f"L {_fmt(x + w)} {_fmt(y + ry)} "
        f"A {_fmt(rx)} {_fmt(ry)} 0 0 0 {_fmt(x)} {_fmt(y + ry)} Z"
    )
    return [
        f'<path d="{body}" {paint}/>',
        f'<ellipse cx="{_fmt(cx)}" cy="{_fmt(y + ry)}" rx="{_fmt(rx)}" '
        f'ry="{_fmt(ry)}" {paint}/>',
    ]


def _label_markup(placed: PlacedNode, color: str) -> list:
    """Emit centered multi-line label text for one node."""
    count = len(placed.lines)
    cy = placed.center_y
    if placed.node.shape == "store":
        cy += _STORE_CAP / 2.0
    out = []
    for i, line in enumerate(placed.lines):
        if not line:
            continue
        baseline = cy + (i - (count - 1) / 2.0) * _LINE_HEIGHT + _FONT_SIZE * 0.35
        out.append(
            f'<text x="{_fmt(placed.center_x)}" y="{_fmt(baseline)}" '
            f'font-family="Helvetica" font-size="{_fmt(_FONT_SIZE)}" '
            f'text-anchor="middle" fill="{color}">{_esc(line)}</text>'
        )
    return out


def _route_edge(a: PlacedNode, b: PlacedNode, direction: str) -> list:
    """Route an orthogonal-ish polyline from node a to node b."""
    if a.node.id == b.node.id:
        r = a.x + a.width
        cy = a.center_y
        return [
            (r, cy - 5.0),
            (r + _LOOP_EXTENT, cy - 5.0),
            (r + _LOOP_EXTENT, cy + 5.0),
            (r, cy + 5.0),
        ]

    if direction == "down":

        def point(cross, flow):
            return (cross, flow)

        a_lo, a_hi, a_cc, a_fc = a.y, a.y + a.height, a.center_x, a.center_y
        b_lo, b_hi, b_cc, b_fc = b.y, b.y + b.height, b.center_x, b.center_y
        a_xlo, a_xhi = a.x, a.x + a.width
        b_xlo, b_xhi = b.x, b.x + b.width
    else:

        def point(cross, flow):
            return (flow, cross)

        a_lo, a_hi, a_cc, a_fc = a.x, a.x + a.width, a.center_y, a.center_x
        b_lo, b_hi, b_cc, b_fc = b.x, b.x + b.width, b.center_y, b.center_x
        a_xlo, a_xhi = a.y, a.y + a.height
        b_xlo, b_xhi = b.y, b.y + b.height

    if b_lo >= a_hi:  # forward flow: exit bottom/right, enter top/left
        mid = (a_hi + b_lo) / 2.0
        if abs(a_cc - b_cc) < 0.01:
            return [point(a_cc, a_hi), point(b_cc, b_lo)]
        return [
            point(a_cc, a_hi),
            point(a_cc, mid),
            point(b_cc, mid),
            point(b_cc, b_lo),
        ]
    if b_hi <= a_lo:  # backward flow (rendered along the true edge direction)
        mid = (b_hi + a_lo) / 2.0
        if abs(a_cc - b_cc) < 0.01:
            return [point(a_cc, a_lo), point(b_cc, b_hi)]
        return [
            point(a_cc, a_lo),
            point(a_cc, mid),
            point(b_cc, mid),
            point(b_cc, b_hi),
        ]
    # same layer band: route along the cross axis between the facing sides
    if b_cc >= a_cc:
        start, end = a_xhi, b_xlo
    else:
        start, end = a_xlo, b_xhi
    mid = (start + end) / 2.0
    if abs(a_fc - b_fc) < 0.01:
        return [point(start, a_fc), point(end, b_fc)]
    return [
        point(start, a_fc),
        point(mid, a_fc),
        point(mid, b_fc),
        point(end, b_fc),
    ]


def _arrow_markup(tip: tuple, direction: tuple, color: str) -> str:
    """Solid triangular arrowhead path with its tip at `tip`."""
    dx, dy = direction
    bx, by = tip[0] - dx * _ARROW_LENGTH, tip[1] - dy * _ARROW_LENGTH
    px, py = -dy, dx
    p1 = (bx + px * _ARROW_HALF_WIDTH, by + py * _ARROW_HALF_WIDTH)
    p2 = (bx - px * _ARROW_HALF_WIDTH, by - py * _ARROW_HALF_WIDTH)
    d = (
        f"M {_fmt(tip[0])} {_fmt(tip[1])} L {_fmt(p1[0])} {_fmt(p1[1])} "
        f"L {_fmt(p2[0])} {_fmt(p2[1])} Z"
    )
    return f'<path d="{d}" fill="{color}"/>'


def _solid_path(points: list) -> str:
    parts = [f"M {_fmt(points[0][0])} {_fmt(points[0][1])}"]
    parts.extend(f"L {_fmt(px)} {_fmt(py)}" for px, py in points[1:])
    return " ".join(parts)


def _dashed_path(points: list) -> str:
    """Emit dashes as explicit subpaths; the SVG subset has no dasharray."""
    parts: list = []
    drawing = True
    remaining = _DASH_ON
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg <= 1e-9:
            continue
        ux, uy = (x2 - x1) / seg, (y2 - y1) / seg
        pos = 0.0
        while pos < seg - 1e-9:
            step = min(remaining, seg - pos)
            if drawing:
                parts.append(
                    f"M {_fmt(x1 + ux * pos)} {_fmt(y1 + uy * pos)} "
                    f"L {_fmt(x1 + ux * (pos + step))} {_fmt(y1 + uy * (pos + step))}"
                )
            pos += step
            remaining -= step
            if remaining <= 1e-9:
                drawing = not drawing
                remaining = _DASH_ON if drawing else _DASH_OFF
    return " ".join(parts)


def _edge_markup(
    edge: DiagramEdge, layout: DiagramLayout, theme: dict, metrics: FontMetrics
) -> list:
    """Emit the line, arrowhead, and optional label for one edge."""
    by_id = layout.by_id
    points = _route_edge(by_id[edge.src], by_id[edge.dst], layout.direction)
    tip = points[-1]
    prev = points[-2]
    length = math.hypot(tip[0] - prev[0], tip[1] - prev[1])
    ux, uy = (tip[0] - prev[0]) / length, (tip[1] - prev[1]) / length
    shortened = points[:-1] + [
        (tip[0] - ux * _ARROW_LENGTH, tip[1] - uy * _ARROW_LENGTH)
    ]
    color = theme["edge"]
    if edge.style == "dashed":
        d = _dashed_path(shortened)
    else:
        d = _solid_path(shortened)
    out = [
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1"/>',
        _arrow_markup(tip, (ux, uy), color),
    ]
    if edge.label:
        mid_a = points[len(points) // 2 - 1]
        mid_b = points[len(points) // 2]
        mx, my = (mid_a[0] + mid_b[0]) / 2.0, (mid_a[1] + mid_b[1]) / 2.0
        text_w = metrics.text_width(edge.label, _LABEL_FONT_SIZE)
        out.append(
            f'<rect x="{_fmt(mx - text_w / 2.0 - 3.0)}" y="{_fmt(my - 6.0)}" '
            f'width="{_fmt(text_w + 6.0)}" height="12.00" '
            f'fill="{theme["label_background"]}"/>'
        )
        out.append(
            f'<text x="{_fmt(mx)}" y="{_fmt(my + _LABEL_FONT_SIZE * 0.35)}" '
            f'font-family="Helvetica" font-size="{_fmt(_LABEL_FONT_SIZE)}" '
            f'text-anchor="middle" fill="{theme["text"]}">{_esc(edge.label)}</text>'
        )
    return out


def render_diagram_svg(
    nodes: Sequence,
    edges: Sequence = (),
    direction: str = "down",
    theme_colors: dict | None = None,
) -> str:
    """Render a node/edge graph to deterministic SVG markup."""
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    layout = layout_diagram(nodes, edges, direction=direction)
    metrics = _metrics()
    w, h = _fmt(layout.width), _fmt(layout.height)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
    ]
    for edge in layout.edges:
        parts.extend(_edge_markup(edge, layout, theme, metrics))
    for placed in layout.nodes:
        parts.extend(_shape_markup(placed, theme["fill"], theme["stroke"]))
        parts.extend(_label_markup(placed, theme["text"]))
    parts.append("</svg>")
    return "\n".join(parts)


def diagram_alt_text(nodes: Sequence, edges: Sequence = ()) -> str:
    """Build a deterministic accessibility summary of the graph."""
    node_list, edge_list = _normalize(nodes, edges)
    labels = [node.label or node.id for node in node_list]
    shown = ", ".join(labels[:5])
    if len(labels) > 5:
        shown += ", ..."
    node_word = "node" if len(node_list) == 1 else "nodes"
    edge_word = "connection" if len(edge_list) == 1 else "connections"
    return (
        f"Diagram: {len(node_list)} {node_word} ({shown}), {len(edge_list)} {edge_word}"
    )


def diagram_svg_block(
    nodes: Sequence,
    edges: Sequence = (),
    direction: str = "down",
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock carrying the rendered diagram plus generated alt text."""
    from .spec import SvgBlock

    node_list, edge_list = _normalize(nodes, edges)
    source = render_diagram_svg(
        node_list, edge_list, direction=direction, theme_colors=theme_colors
    )
    kw.setdefault("alt_text", diagram_alt_text(node_list, edge_list))
    return SvgBlock(source=source, caption=caption, **kw)


# -- fenced ```diagram text syntax --


def parse_diagram_source(text: str) -> tuple:
    """Parse the minimal diagram line syntax into (nodes, edges, direction).

    Lines: ``id: Label [shape]`` declares a node, ``a -> b: label`` an
    edge (``-->`` for dashed), ``direction: right`` sets the flow axis.
    Blank lines and ``#`` comments are ignored; ids referenced only by
    edges become implicit box nodes. Malformed lines raise ValueError
    quoting the offending line so an LLM can correct it.
    """
    nodes: list = []
    edges: list = []
    ids: set = set()
    direction = "down"

    def ensure(node_id: str) -> None:
        if node_id not in ids:
            ids.add(node_id)
            nodes.append(DiagramNode(id=node_id, label=node_id))

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        dm = _DIRECTION_LINE_RE.match(line)
        if dm:
            value = dm.group(1).lower()
            if value not in ("down", "right"):
                raise ValueError(
                    f"invalid diagram direction (use down or right): {line!r}"
                )
            direction = value
            continue
        em = _EDGE_LINE_RE.match(line)
        if em:
            src, arrow, dst, label = em.groups()
            ensure(src)
            ensure(dst)
            edges.append(
                DiagramEdge(
                    src=src,
                    dst=dst,
                    label=label,
                    style="dashed" if arrow == "-->" else "solid",
                )
            )
            continue
        nm = _NODE_LINE_RE.match(line)
        if nm and "->" not in line:
            node_id, label, shape = nm.groups()
            if node_id in ids:
                raise ValueError(f"duplicate diagram node id in line: {line!r}")
            if shape is not None and shape not in _SHAPES:
                raise ValueError(
                    f"unknown diagram node shape {shape!r} in line: {line!r}"
                )
            ids.add(node_id)
            nodes.append(DiagramNode(id=node_id, label=label, shape=shape or "box"))
            continue
        raise ValueError(f"invalid diagram line: {line!r}")

    if not nodes:
        raise ValueError("diagram block declares no nodes or edges")
    return nodes, edges, direction


def diagram_block_from_source(text: str, caption: str | None = None):
    """Parse fenced-diagram text and return the rendered SvgBlock."""
    nodes, edges, direction = parse_diagram_source(text)
    return diagram_svg_block(nodes, edges, direction=direction, caption=caption)
