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
    "ArchNode",
    "ArchGroup",
    "SERVICE_TYPES",
    "render_architecture_svg",
    "architecture_alt_text",
    "architecture_svg_block",
    "SequenceParticipant",
    "SequenceMessage",
    "render_sequence_svg",
    "sequence_alt_text",
    "sequence_svg_block",
    "Entity",
    "EntityAttribute",
    "Relationship",
    "render_er_svg",
    "er_alt_text",
    "er_svg_block",
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


# ======================================================================
# Shared drawing helpers for the specialized diagram types below.
# ======================================================================


def _svg_open(width: float, height: float) -> str:
    """Open an SVG element sized to the given canvas."""
    w, h = _fmt(width), _fmt(height)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
    )


def _paint(fill: str | None, stroke: str, width: float = 1.0) -> str:
    fill_val = fill if fill is not None else "none"
    return f'fill="{fill_val}" stroke="{stroke}" stroke-width="{_fmt(width)}"'


def _ln(x1: float, y1: float, x2: float, y2: float, stroke: str) -> str:
    return (
        f'<line x1="{_fmt(x1)}" y1="{_fmt(y1)}" x2="{_fmt(x2)}" '
        f'y2="{_fmt(y2)}" stroke="{stroke}" stroke-width="1"/>'
    )


def _text_el(
    x: float, y: float, size: float, anchor: str, color: str, text: str
) -> str:
    return (
        f'<text x="{_fmt(x)}" y="{_fmt(y)}" font-family="Helvetica" '
        f'font-size="{_fmt(size)}" text-anchor="{anchor}" '
        f'fill="{color}">{_esc(text)}</text>'
    )


def _wrap_generic(text: str, metrics: FontMetrics, size: float, limit: float) -> tuple:
    """Greedy word wrap of `text` to `limit` points at the given font size."""
    words = text.split()
    if not words:
        return ("",)
    lines: list = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if metrics.text_width(candidate, size) <= limit:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return tuple(lines)


def _open_arrow_markup(tip: tuple, direction: tuple, color: str) -> str:
    """Open (line) arrowhead: two strokes meeting at `tip`, not filled."""
    dx, dy = direction
    bx, by = tip[0] - dx * _ARROW_LENGTH, tip[1] - dy * _ARROW_LENGTH
    px, py = -dy, dx
    p1 = (bx + px * _ARROW_HALF_WIDTH, by + py * _ARROW_HALF_WIDTH)
    p2 = (bx - px * _ARROW_HALF_WIDTH, by - py * _ARROW_HALF_WIDTH)
    d = (
        f"M {_fmt(p1[0])} {_fmt(p1[1])} L {_fmt(tip[0])} {_fmt(tip[1])} "
        f"L {_fmt(p2[0])} {_fmt(p2[1])}"
    )
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1"/>'


def _straight_arrow(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: str,
    style: str = "solid",
    filled: bool = True,
) -> list:
    """A straight line from (x1,y1) to (x2,y2) capped with an arrowhead."""
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 1e-9:
        return []
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    x2s, y2s = x2 - ux * _ARROW_LENGTH, y2 - uy * _ARROW_LENGTH
    points = [(x1, y1), (x2s, y2s)]
    d = _dashed_path(points) if style == "dashed" else _solid_path(points)
    out = [f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1"/>']
    if filled:
        out.append(_arrow_markup((x2, y2), (ux, uy), color))
    else:
        out.append(_open_arrow_markup((x2, y2), (ux, uy), color))
    return out


def _mid_label(
    mx: float, my: float, text: str, metrics: FontMetrics, text_color: str, bg: str
) -> list:
    """A centered edge label with a solid backing rectangle."""
    tw = metrics.text_width(text, _LABEL_FONT_SIZE)
    return [
        f'<rect x="{_fmt(mx - tw / 2.0 - 3.0)}" y="{_fmt(my - 6.0)}" '
        f'width="{_fmt(tw + 6.0)}" height="12.00" fill="{bg}"/>',
        _text_el(
            mx,
            my + _LABEL_FONT_SIZE * 0.35,
            _LABEL_FONT_SIZE,
            "middle",
            text_color,
            text,
        ),
    ]


def _rect_border(cx: float, cy: float, hw: float, hh: float, tx: float, ty: float):
    """Point where the ray from (cx,cy) toward (tx,ty) exits a rect half-extent."""
    dx, dy = tx - cx, ty - cy
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return cx, cy
    scale = float("inf")
    if abs(dx) > 1e-9:
        scale = min(scale, hw / abs(dx))
    if abs(dy) > 1e-9:
        scale = min(scale, hh / abs(dy))
    return cx + dx * scale, cy + dy * scale


def _grid_positions(sizes: list, direction: str, hgap: float, vgap: float) -> tuple:
    """Place (id, w, h) items in a deterministic wrap grid.

    Returns (positions, total_width, total_height) where positions maps each
    id to (x, y, w, h) relative to the grid origin, centered in its cell.
    """
    n = len(sizes)
    if n == 0:
        return {}, 0.0, 0.0
    if direction == "right":
        rows = max(1, math.ceil(math.sqrt(n)))
        cols = math.ceil(n / rows)
    else:
        cols = max(1, math.ceil(math.sqrt(n)))
        rows = math.ceil(n / cols)
    cell: dict = {}
    for idx, (cid, w, h) in enumerate(sizes):
        if direction == "right":
            c, r = divmod(idx, rows)
        else:
            r, c = divmod(idx, cols)
        cell[cid] = (r, c, w, h)
    colw = [0.0] * cols
    rowh = [0.0] * rows
    for _cid, (r, c, w, h) in cell.items():
        colw[c] = max(colw[c], w)
        rowh[r] = max(rowh[r], h)
    colx = [0.0] * cols
    for c in range(1, cols):
        colx[c] = colx[c - 1] + colw[c - 1] + hgap
    rowy = [0.0] * rows
    for r in range(1, rows):
        rowy[r] = rowy[r - 1] + rowh[r - 1] + vgap
    positions: dict = {}
    for cid, (r, c, w, h) in cell.items():
        px = colx[c] + (colw[c] - w) / 2.0
        py = rowy[r] + (rowh[r] - h) / 2.0
        positions[cid] = (px, py, w, h)
    total_w = colx[-1] + colw[-1]
    total_h = rowy[-1] + rowh[-1]
    return positions, total_w, total_h


# ======================================================================
# 1. Architecture diagrams
# ======================================================================

SERVICE_TYPES = (
    "compute",
    "database",
    "storage",
    "queue",
    "gateway",
    "cache",
    "cdn",
    "function",
    "loadbalancer",
    "user",
    "external",
    "generic",
)

_GLYPH_W = 30.0
_GLYPH_H = 26.0
_ARCH_PAD = 8.0
_ARCH_LABEL_SIZE = 8.5
_ARCH_LABEL_LIMIT = 104.0
_ARCH_HGAP = 30.0
_ARCH_VGAP = 30.0
_ARCH_MARGIN = 14.0
_GROUP_PAD = 14.0
_GROUP_TITLE_H = 17.0
_GROUP_TINTS = ("#eef4fb", "#eef8f0", "#fbf5ee", "#f3eefb", "#fbeef2", "#eef9fb")
_GROUP_BORDERS = ("#5b7ea6", "#4e9a6b", "#a6825b", "#7a5ba6", "#a65b7e", "#4e94a6")


@dataclass
class ArchNode:
    """A service node in an architecture diagram, drawn with a vector glyph."""

    id: str
    label: str
    service: str = "generic"
    group: str | None = None
    image: str | bytes | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("architecture node id must be a non-empty string")
        if self.service not in SERVICE_TYPES:
            raise ValueError(
                f"unknown service type {self.service!r}; expected one of {SERVICE_TYPES}"
            )


@dataclass
class ArchGroup:
    """A container region enclosing nodes and/or nested groups by id."""

    id: str
    label: str = ""
    node_ids: tuple = ()
    color: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("architecture group id must be a non-empty string")
        self.node_ids = tuple(self.node_ids)


def _as_arch_node(item) -> ArchNode:
    if isinstance(item, ArchNode):
        return item
    if isinstance(item, dict):
        return ArchNode(**item)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 5:
        return ArchNode(*item)
    raise TypeError(f"cannot build an ArchNode from {item!r}")


def _as_arch_group(item) -> ArchGroup:
    if isinstance(item, ArchGroup):
        return item
    if isinstance(item, dict):
        data = dict(item)
        if "id" not in data:
            raise ValueError("architecture group requires an 'id'")
        return ArchGroup(**data)
    raise TypeError(f"cannot build an ArchGroup from {item!r}")


def _normalize_arch(nodes: Sequence, edges: Sequence, groups: Sequence | None):
    """Validate and coerce architecture nodes, edges, and groups."""
    node_list = [_as_arch_node(n) for n in nodes]
    if not node_list:
        raise ValueError("architecture diagram requires at least one node")
    node_ids: set = set()
    for node in node_list:
        if node.id in node_ids:
            raise ValueError(f"duplicate architecture node id: {node.id!r}")
        node_ids.add(node.id)
    edge_list = [_as_edge(e) for e in edges]
    for edge in edge_list:
        for endpoint in (edge.src, edge.dst):
            if endpoint not in node_ids:
                raise ValueError(
                    f"architecture edge references unknown node id: {endpoint!r}"
                )
    group_list = [_as_arch_group(g) for g in (groups or [])]
    group_ids: set = set()
    for group in group_list:
        if group.id in group_ids or group.id in node_ids:
            raise ValueError(f"duplicate architecture group id: {group.id!r}")
        group_ids.add(group.id)
    parent: dict = {}
    for group in group_list:
        for member in group.node_ids:
            if member not in node_ids and member not in group_ids:
                raise ValueError(
                    f"architecture group {group.id!r} references unknown id: {member!r}"
                )
            if member in parent:
                raise ValueError(
                    f"id {member!r} belongs to more than one architecture group"
                )
            parent[member] = group.id
    for group in group_list:  # nesting-cycle guard
        seen = {group.id}
        cursor = parent.get(group.id)
        while cursor is not None:
            if cursor in seen:
                raise ValueError("architecture groups form a containment cycle")
            seen.add(cursor)
            cursor = parent.get(cursor)
    return node_list, edge_list, group_list, parent


def _glyph_markup(service: str, cx: float, cy: float, fill: str, stroke: str) -> list:
    """Emit the vector glyph for one service type centered at (cx, cy)."""
    p = _paint(fill, stroke)
    if service == "compute":
        x, y, w, h = cx - 13.0, cy - 11.0, 26.0, 22.0
        return [
            f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" '
            f'height="{_fmt(h)}" {p}/>',
            _ln(x, y + 7.0, x + w, y + 7.0, stroke),
            _ln(x, y + 14.0, x + w, y + 14.0, stroke),
            f'<circle cx="{_fmt(x + 4.0)}" cy="{_fmt(y + 3.5)}" r="1.3" '
            f'fill="{stroke}" stroke="none"/>',
        ]
    if service == "database":
        rx, ry = 12.0, 4.0
        x, top, h = cx - rx, cy - 13.0, 26.0
        body = (
            f"M {_fmt(x)} {_fmt(top + ry)} L {_fmt(x)} {_fmt(top + h - ry)} "
            f"A {_fmt(rx)} {_fmt(ry)} 0 0 0 {_fmt(x + 2 * rx)} {_fmt(top + h - ry)} "
            f"L {_fmt(x + 2 * rx)} {_fmt(top + ry)} "
            f"A {_fmt(rx)} {_fmt(ry)} 0 0 0 {_fmt(x)} {_fmt(top + ry)} Z"
        )
        return [
            f'<path d="{body}" {p}/>',
            f'<ellipse cx="{_fmt(cx)}" cy="{_fmt(top + ry)}" rx="{_fmt(rx)}" '
            f'ry="{_fmt(ry)}" {p}/>',
        ]
    if service == "storage":
        top_y, bot_y = cy - 11.0, cy + 12.0
        bucket = (
            f"M {_fmt(cx - 13.0)} {_fmt(top_y)} L {_fmt(cx + 13.0)} {_fmt(top_y)} "
            f"L {_fmt(cx + 9.0)} {_fmt(bot_y)} L {_fmt(cx - 9.0)} {_fmt(bot_y)} Z"
        )
        return [
            f'<path d="{bucket}" {p}/>',
            f'<ellipse cx="{_fmt(cx)}" cy="{_fmt(top_y)}" rx="13.00" ry="4.00" {p}/>',
        ]
    if service == "queue":
        bars = []
        for i in range(3):
            bx = cx - 13.0 + i * 9.0
            bars.append(
                f'<rect x="{_fmt(bx)}" y="{_fmt(cy - 10.0)}" width="6.00" '
                f'height="20.00" {p}/>'
            )
        return bars
    if service == "gateway":
        pts = []
        for k in range(6):
            ang = math.pi / 6.0 + k * math.pi / 3.0
            pts.append(
                f"{_fmt(cx + 14.0 * math.cos(ang))},{_fmt(cy + 13.0 * math.sin(ang))}"
            )
        return [f'<polygon points="{" ".join(pts)}" {p}/>']
    if service == "cache":
        bolt = (
            f"M {_fmt(cx + 3.0)} {_fmt(cy - 13.0)} L {_fmt(cx - 9.0)} {_fmt(cy + 2.0)} "
            f"L {_fmt(cx - 1.0)} {_fmt(cy + 2.0)} L {_fmt(cx - 3.0)} {_fmt(cy + 13.0)} "
            f"L {_fmt(cx + 9.0)} {_fmt(cy - 2.0)} L {_fmt(cx + 1.0)} {_fmt(cy - 2.0)} Z"
        )
        return [f'<path d="{bolt}" {p}/>']
    if service == "cdn":
        return [
            f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="13.00" {p}/>',
            f'<ellipse cx="{_fmt(cx)}" cy="{_fmt(cy)}" rx="5.00" ry="13.00" '
            f'fill="none" stroke="{stroke}" stroke-width="1"/>',
            _ln(cx - 13.0, cy, cx + 13.0, cy, stroke),
            _ln(cx - 11.0, cy - 6.0, cx + 11.0, cy - 6.0, stroke),
            _ln(cx - 11.0, cy + 6.0, cx + 11.0, cy + 6.0, stroke),
        ]
    if service == "function":
        x, y, w, h = cx - 13.0, cy - 12.0, 26.0, 24.0
        fold = 7.0
        shape = (
            f"M {_fmt(x)} {_fmt(y)} L {_fmt(x + w - fold)} {_fmt(y)} "
            f"L {_fmt(x + w)} {_fmt(y + fold)} L {_fmt(x + w)} {_fmt(y + h)} "
            f"L {_fmt(x)} {_fmt(y + h)} Z"
        )
        corner = (
            f"M {_fmt(x + w - fold)} {_fmt(y)} L {_fmt(x + w - fold)} "
            f"{_fmt(y + fold)} L {_fmt(x + w)} {_fmt(y + fold)}"
        )
        return [
            f'<path d="{shape}" {p}/>',
            f'<path d="{corner}" fill="none" stroke="{stroke}" stroke-width="1"/>',
        ]
    if service == "loadbalancer":
        top = (cx, cy - 12.0)
        outs = [(cx - 11.0, cy + 12.0), (cx, cy + 12.0), (cx + 11.0, cy + 12.0)]
        marks = [f'<circle cx="{_fmt(top[0])}" cy="{_fmt(top[1])}" r="3.0" {p}/>']
        for ox, oy in outs:
            marks.append(_ln(top[0], top[1] + 3.0, ox, oy - 3.0, stroke))
            marks.append(f'<circle cx="{_fmt(ox)}" cy="{_fmt(oy)}" r="3.0" {p}/>')
        return marks
    if service == "user":
        head = f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy - 7.0)}" r="5.0" {p}/>'
        body = (
            f"M {_fmt(cx - 10.0)} {_fmt(cy + 12.0)} "
            f"A 10.0 9.0 0 0 1 {_fmt(cx + 10.0)} {_fmt(cy + 12.0)}"
        )
        return [head, f'<path d="{body}" {p}/>']
    if service == "external":
        cloud = (
            f"M {_fmt(cx - 12.0)} {_fmt(cy + 6.0)} "
            f"A 6.0 6.0 0 0 1 {_fmt(cx - 6.0)} {_fmt(cy - 4.0)} "
            f"A 7.0 7.0 0 0 1 {_fmt(cx + 6.0)} {_fmt(cy - 4.0)} "
            f"A 6.0 6.0 0 0 1 {_fmt(cx + 12.0)} {_fmt(cy + 6.0)} Z"
        )
        return [f'<path d="{cloud}" {p}/>']
    # generic: rounded rectangle
    return [
        f'<path d="{_rounded_rect_path(cx - 14.0, cy - 11.0, 28.0, 22.0, 5.0)}" {p}/>'
    ]


def _arch_node_size(label: str, metrics: FontMetrics) -> tuple:
    """Compute the cell size and wrapped label lines for a service node."""
    lines = _wrap_generic(label, metrics, _ARCH_LABEL_SIZE, _ARCH_LABEL_LIMIT)
    text_w = max(
        (metrics.text_width(line, _ARCH_LABEL_SIZE) for line in lines), default=0.0
    )
    width = max(_GLYPH_W + 6.0, text_w) + 2.0 * _ARCH_PAD
    label_h = len(lines) * (_ARCH_LABEL_SIZE + 2.5)
    height = _ARCH_PAD + _GLYPH_H + 5.0 + label_h + _ARCH_PAD
    return width, height, lines


def _layout_architecture(node_list, group_list, parent, direction):
    """Place nodes and groups; return (node_boxes, group_boxes, width, height)."""
    metrics = _metrics()
    node_map = {n.id: n for n in node_list}
    group_map = {g.id: g for g in group_list}
    group_order = {g.id: i for i, g in enumerate(group_list)}

    node_size: dict = {}
    for node in node_list:
        node_size[node.id] = _arch_node_size(node.label, metrics)

    meas_group: dict = {}

    def measure(cid: str) -> tuple:
        if cid in node_map:
            w, h, _lines = node_size[cid]
            return w, h
        members = group_map[cid].node_ids
        sizes = [(m, *measure(m)) for m in members]
        positions, iw, ih = _grid_positions(sizes, direction, _ARCH_HGAP, _ARCH_VGAP)
        gw = iw + 2.0 * _GROUP_PAD
        gh = ih + 2.0 * _GROUP_PAD + _GROUP_TITLE_H
        meas_group[cid] = (positions, gw, gh)
        return gw, gh

    top_level = [item.id for item in (node_list + group_list) if item.id not in parent]
    top_sizes = [(cid, *measure(cid)) for cid in top_level]
    top_positions, total_w, total_h = _grid_positions(
        top_sizes, direction, _ARCH_HGAP, _ARCH_VGAP
    )

    node_boxes: dict = {}
    group_boxes: dict = {}

    def place(cid: str, x: float, y: float) -> None:
        if cid in node_map:
            w, h, lines = node_size[cid]
            gcx = x + w / 2.0
            gcy = y + _ARCH_PAD + _GLYPH_H / 2.0
            node_boxes[cid] = {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "lines": lines,
                "gcx": gcx,
                "gcy": gcy,
                "node": node_map[cid],
            }
            return
        positions, gw, gh = meas_group[cid]
        idx = group_order[group_map[cid].id]
        group_boxes[cid] = {
            "x": x,
            "y": y,
            "w": gw,
            "h": gh,
            "group": group_map[cid],
            "index": idx,
        }
        ox = x + _GROUP_PAD
        oy = y + _GROUP_PAD + _GROUP_TITLE_H
        for mid, (px, py, _pw, _ph) in positions.items():
            place(mid, ox + px, oy + py)

    for cid, (px, py, _pw, _ph) in top_positions.items():
        place(cid, _ARCH_MARGIN + px, _ARCH_MARGIN + py)

    return (
        node_boxes,
        group_boxes,
        total_w + 2.0 * _ARCH_MARGIN,
        total_h + 2.0 * _ARCH_MARGIN,
    )


def architecture_alt_text(
    nodes: Sequence, edges: Sequence = (), groups: Sequence | None = None
) -> str:
    """Deterministic accessibility summary of an architecture diagram."""
    node_list, edge_list, group_list, _parent = _normalize_arch(nodes, edges, groups)
    labels = [n.label or n.id for n in node_list]
    shown = ", ".join(labels[:5])
    if len(labels) > 5:
        shown += ", ..."
    parts = [f"{len(node_list)} service" + ("" if len(node_list) == 1 else "s")]
    if group_list:
        parts.append(f"{len(group_list)} group" + ("" if len(group_list) == 1 else "s"))
    parts.append(f"{len(edge_list)} connection" + ("" if len(edge_list) == 1 else "s"))
    return f"Architecture diagram: {', '.join(parts)} ({shown})"


def render_architecture_svg(
    nodes: Sequence,
    edges: Sequence = (),
    groups: Sequence | None = None,
    direction: str = "down",
    theme_colors: dict | None = None,
) -> str:
    """Render an architecture diagram to deterministic SVG markup."""
    if direction not in ("down", "right"):
        raise ValueError(
            f"architecture direction must be 'down' or 'right': {direction!r}"
        )
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    node_list, edge_list, group_list, parent = _normalize_arch(nodes, edges, groups)
    node_boxes, group_boxes, width, height = _layout_architecture(
        node_list, group_list, parent, direction
    )
    metrics = _metrics()
    parts = [_svg_open(width, height)]

    # Groups behind everything, outermost first (shallowest depth drawn first).
    def depth_of(gid: str) -> int:
        d = 0
        cursor = parent.get(gid)
        while cursor is not None:
            d += 1
            cursor = parent.get(cursor)
        return d

    for gid in sorted(
        group_boxes, key=lambda g: (depth_of(g), group_boxes[g]["index"])
    ):
        box = group_boxes[gid]
        idx = box["index"] % len(_GROUP_TINTS)
        tint = _GROUP_TINTS[idx]
        border = box["group"].color or _GROUP_BORDERS[idx]
        parts.append(
            f'<path d="{_rounded_rect_path(box["x"], box["y"], box["w"], box["h"], 8.0)}"'
            f' fill="{tint}" stroke="{border}" stroke-width="1"/>'
        )
        if box["group"].label:
            parts.append(
                _text_el(
                    box["x"] + _GROUP_PAD,
                    box["y"] + _GROUP_TITLE_H - 5.0,
                    9.0,
                    "start",
                    border,
                    box["group"].label,
                )
            )

    # Edges between glyph anchor boxes.
    for edge in edge_list:
        a = node_boxes[edge.src]
        b = node_boxes[edge.dst]
        x1, y1 = _rect_border(
            a["gcx"], a["gcy"], _GLYPH_W / 2.0, _GLYPH_H / 2.0, b["gcx"], b["gcy"]
        )
        x2, y2 = _rect_border(
            b["gcx"], b["gcy"], _GLYPH_W / 2.0, _GLYPH_H / 2.0, a["gcx"], a["gcy"]
        )
        parts.extend(_straight_arrow(x1, y1, x2, y2, theme["edge"], edge.style))
        if edge.label:
            parts.extend(
                _mid_label(
                    (x1 + x2) / 2.0,
                    (y1 + y2) / 2.0,
                    edge.label,
                    metrics,
                    theme["text"],
                    theme["label_background"],
                )
            )

    # Nodes: glyph plus label beneath.
    for node in node_list:
        box = node_boxes[node.id]
        parts.extend(
            _glyph_markup(
                node.service, box["gcx"], box["gcy"], "#ffffff", theme["stroke"]
            )
        )
        base_y = box["y"] + _ARCH_PAD + _GLYPH_H + 5.0 + _ARCH_LABEL_SIZE
        for i, line in enumerate(box["lines"]):
            if not line:
                continue
            parts.append(
                _text_el(
                    box["gcx"],
                    base_y + i * (_ARCH_LABEL_SIZE + 2.5),
                    _ARCH_LABEL_SIZE,
                    "middle",
                    theme["text"],
                    line,
                )
            )
    parts.append("</svg>")
    return "\n".join(parts)


def architecture_svg_block(
    nodes: Sequence,
    edges: Sequence = (),
    groups: Sequence | None = None,
    direction: str = "down",
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock for an architecture diagram with generated alt text."""
    from .spec import SvgBlock

    source = render_architecture_svg(
        nodes, edges, groups=groups, direction=direction, theme_colors=theme_colors
    )
    kw.setdefault("alt_text", architecture_alt_text(nodes, edges, groups))
    return SvgBlock(source=source, caption=caption, **kw)


# ======================================================================
# 2. Sequence diagrams
# ======================================================================

_SEQ_MSG_STYLES = ("sync", "async", "return")
_SEQ_PART_H = 26.0
_SEQ_TOP = 12.0
_SEQ_STEP = 34.0
_SEQ_GAP = 40.0
_SEQ_MARGIN = 14.0
_SEQ_PAD = 10.0
_SEQ_ACT_W = 8.0
_SEQ_SELF_W = 28.0
_SEQ_FONT = 9.0


@dataclass
class SequenceParticipant:
    """A participant (lifeline) in a sequence diagram."""

    id: str
    label: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("sequence participant id must be a non-empty string")
        if not self.label:
            self.label = self.id


@dataclass
class SequenceMessage:
    """One message between participants at a vertical time step."""

    src: str
    dst: str
    label: str = ""
    style: str = "sync"
    activate: bool = False

    def __post_init__(self) -> None:
        if self.style not in _SEQ_MSG_STYLES:
            raise ValueError(
                f"unknown message style {self.style!r}; expected one of "
                f"{_SEQ_MSG_STYLES}"
            )


def _as_participant(item) -> SequenceParticipant:
    if isinstance(item, SequenceParticipant):
        return item
    if isinstance(item, dict):
        return SequenceParticipant(**item)
    if isinstance(item, (tuple, list)) and 1 <= len(item) <= 2:
        return SequenceParticipant(*item)
    if isinstance(item, str):
        return SequenceParticipant(id=item)
    raise TypeError(f"cannot build a SequenceParticipant from {item!r}")


def _as_message(item) -> SequenceMessage:
    if isinstance(item, SequenceMessage):
        return item
    if isinstance(item, dict):
        data = dict(item)
        if "from" in data:
            data["src"] = data.pop("from")
        if "to" in data:
            data["dst"] = data.pop("to")
        return SequenceMessage(**data)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 5:
        return SequenceMessage(*item)
    raise TypeError(f"cannot build a SequenceMessage from {item!r}")


def _normalize_sequence(participants: Sequence, messages: Sequence):
    """Validate and coerce sequence participants and messages."""
    part_list = [_as_participant(p) for p in participants]
    if not part_list:
        raise ValueError("sequence diagram requires at least one participant")
    ids: set = set()
    for part in part_list:
        if part.id in ids:
            raise ValueError(f"duplicate sequence participant id: {part.id!r}")
        ids.add(part.id)
    msg_list = [_as_message(m) for m in messages]
    for msg in msg_list:
        for endpoint in (msg.src, msg.dst):
            if endpoint not in ids:
                raise ValueError(
                    f"sequence message references unknown participant: {endpoint!r}"
                )
    return part_list, msg_list


def sequence_alt_text(participants: Sequence, messages: Sequence = ()) -> str:
    """Deterministic accessibility summary of a sequence diagram."""
    part_list, msg_list = _normalize_sequence(participants, messages)
    p_word = "participant" if len(part_list) == 1 else "participants"
    m_word = "message" if len(msg_list) == 1 else "messages"
    return f"Sequence diagram: {len(part_list)} {p_word}, {len(msg_list)} {m_word}"


def render_sequence_svg(
    participants: Sequence,
    messages: Sequence = (),
    theme_colors: dict | None = None,
) -> str:
    """Render a sequence diagram to deterministic SVG markup."""
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    part_list, msg_list = _normalize_sequence(participants, messages)
    metrics = _metrics()

    widths = {
        p.id: max(64.0, metrics.text_width(p.label, _SEQ_FONT) + 2.0 * _SEQ_PAD)
        for p in part_list
    }
    centers: dict = {}
    cursor = _SEQ_MARGIN
    for part in part_list:
        centers[part.id] = cursor + widths[part.id] / 2.0
        cursor += widths[part.id] + _SEQ_GAP
    content_right = cursor - _SEQ_GAP

    has_self = any(m.src == m.dst for m in msg_list)
    width = content_right + _SEQ_MARGIN + (_SEQ_SELF_W + 8.0 if has_self else 0.0)

    msg_top = _SEQ_TOP + _SEQ_PART_H + _SEQ_STEP
    lifeline_bottom = msg_top + max(1, len(msg_list)) * _SEQ_STEP
    height = lifeline_bottom + _SEQ_MARGIN

    parts = [_svg_open(width, height)]

    # Lifelines (dashed) beneath the participant boxes.
    for part in part_list:
        cx = centers[part.id]
        pts = [(cx, _SEQ_TOP + _SEQ_PART_H), (cx, lifeline_bottom)]
        parts.append(
            f'<path d="{_dashed_path(pts)}" fill="none" '
            f'stroke="{theme["edge"]}" stroke-width="1"/>'
        )

    # Activation bars: match activate flags to return messages per participant.
    active: dict = {p.id: [] for p in part_list}
    bars: list = []
    for i, msg in enumerate(msg_list):
        y = msg_top + i * _SEQ_STEP
        if msg.activate:
            active[msg.dst].append(y)
        if msg.style == "return" and active[msg.src]:
            start = active[msg.src].pop()
            bars.append((msg.src, start, y))
    for pid, stack in active.items():
        for start in stack:
            bars.append((pid, start, lifeline_bottom))
    for pid, y0, y1 in bars:
        cx = centers[pid]
        parts.append(
            f'<rect x="{_fmt(cx - _SEQ_ACT_W / 2.0)}" y="{_fmt(y0)}" '
            f'width="{_fmt(_SEQ_ACT_W)}" height="{_fmt(max(6.0, y1 - y0))}" '
            f'fill="{theme["fill"]}" stroke="{theme["stroke"]}" stroke-width="1"/>'
        )

    # Participant boxes across the top.
    for part in part_list:
        w = widths[part.id]
        x = centers[part.id] - w / 2.0
        parts.append(
            f'<rect x="{_fmt(x)}" y="{_fmt(_SEQ_TOP)}" width="{_fmt(w)}" '
            f'height="{_fmt(_SEQ_PART_H)}" rx="3" fill="{theme["fill"]}" '
            f'stroke="{theme["stroke"]}" stroke-width="1"/>'
        )
        parts.append(
            _text_el(
                centers[part.id],
                _SEQ_TOP + _SEQ_PART_H / 2.0 + _SEQ_FONT * 0.35,
                _SEQ_FONT,
                "middle",
                theme["text"],
                part.label,
            )
        )

    # Messages.
    for i, msg in enumerate(msg_list):
        y = msg_top + i * _SEQ_STEP
        filled = msg.style == "sync"
        line_style = "dashed" if msg.style == "return" else "solid"
        if msg.src == msg.dst:
            cx = centers[msg.src]
            right = cx + _SEQ_ACT_W / 2.0
            ext = right + _SEQ_SELF_W
            loop = [(right, y), (ext, y), (ext, y + 12.0)]
            parts.append(
                f'<path d="{_solid_path(loop)}" fill="none" '
                f'stroke="{theme["edge"]}" stroke-width="1"/>'
            )
            parts.extend(
                _straight_arrow(
                    ext, y + 12.0, right, y + 12.0, theme["edge"], line_style, filled
                )
            )
            if msg.label:
                parts.append(
                    _text_el(
                        ext + 3.0,
                        y + 3.0,
                        _LABEL_FONT_SIZE,
                        "start",
                        theme["text"],
                        msg.label,
                    )
                )
            continue
        x1 = centers[msg.src]
        x2 = centers[msg.dst]
        step = _SEQ_ACT_W / 2.0 if x2 > x1 else -_SEQ_ACT_W / 2.0
        parts.extend(
            _straight_arrow(
                x1 + step, y, x2 - step, y, theme["edge"], line_style, filled
            )
        )
        if msg.label:
            parts.append(
                _text_el(
                    (x1 + x2) / 2.0,
                    y - 4.0,
                    _LABEL_FONT_SIZE,
                    "middle",
                    theme["text"],
                    msg.label,
                )
            )
    parts.append("</svg>")
    return "\n".join(parts)


def sequence_svg_block(
    participants: Sequence,
    messages: Sequence = (),
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock for a sequence diagram with generated alt text."""
    from .spec import SvgBlock

    source = render_sequence_svg(participants, messages, theme_colors=theme_colors)
    kw.setdefault("alt_text", sequence_alt_text(participants, messages))
    return SvgBlock(source=source, caption=caption, **kw)


# ======================================================================
# 3. Entity-relationship diagrams
# ======================================================================

_ER_KEYS = (None, "PK", "FK")
_ER_TITLE_H = 18.0
_ER_ROW_H = 14.0
_ER_PAD = 8.0
_ER_KEY_W = 20.0
_ER_GAP = 12.0
_ER_HGAP = 56.0
_ER_VGAP = 44.0
_ER_MARGIN = 14.0
_ER_NAME_FONT = 8.5
_ER_TITLE_FONT = 9.5


@dataclass
class EntityAttribute:
    """One attribute row of an entity: name, optional key marker, type."""

    name: str
    key: str | None = None
    type: str | None = None

    def __post_init__(self) -> None:
        if self.key not in _ER_KEYS:
            raise ValueError(
                f"unknown attribute key {self.key!r}; expected PK, FK, or None"
            )


@dataclass
class Entity:
    """A named entity box with a list of attributes."""

    id: str
    name: str = ""
    attributes: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("entity id must be a non-empty string")
        if not self.name:
            self.name = self.id
        self.attributes = tuple(_as_attribute(a) for a in self.attributes)


@dataclass
class Relationship:
    """A relationship line between two entities with cardinality labels."""

    src: str
    dst: str
    label: str | None = None
    src_card: str | None = None
    dst_card: str | None = None


def _as_attribute(item) -> EntityAttribute:
    if isinstance(item, EntityAttribute):
        return item
    if isinstance(item, dict):
        return EntityAttribute(**item)
    if isinstance(item, (tuple, list)) and 1 <= len(item) <= 3:
        return EntityAttribute(*item)
    if isinstance(item, str):
        return EntityAttribute(name=item)
    raise TypeError(f"cannot build an EntityAttribute from {item!r}")


def _as_entity(item) -> Entity:
    if isinstance(item, Entity):
        return item
    if isinstance(item, dict):
        return Entity(**item)
    raise TypeError(f"cannot build an Entity from {item!r}")


def _as_relationship(item) -> Relationship:
    if isinstance(item, Relationship):
        return item
    if isinstance(item, dict):
        data = dict(item)
        if "from" in data:
            data["src"] = data.pop("from")
        if "to" in data:
            data["dst"] = data.pop("to")
        if "from_card" in data:
            data["src_card"] = data.pop("from_card")
        if "to_card" in data:
            data["dst_card"] = data.pop("to_card")
        return Relationship(**data)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 5:
        return Relationship(*item)
    raise TypeError(f"cannot build a Relationship from {item!r}")


def _normalize_er(entities: Sequence, relationships: Sequence):
    """Validate and coerce ER entities and relationships."""
    entity_list = [_as_entity(e) for e in entities]
    if not entity_list:
        raise ValueError("ER diagram requires at least one entity")
    ids: set = set()
    for entity in entity_list:
        if entity.id in ids:
            raise ValueError(f"duplicate entity id: {entity.id!r}")
        ids.add(entity.id)
    rel_list = [_as_relationship(r) for r in relationships]
    for rel in rel_list:
        for endpoint in (rel.src, rel.dst):
            if endpoint not in ids:
                raise ValueError(
                    f"relationship references unknown entity: {endpoint!r}"
                )
    return entity_list, rel_list


def _entity_size(entity: Entity, metrics: FontMetrics) -> tuple:
    """Compute (width, height) for an entity box from its attributes."""
    name_w = 0.0
    type_w = 0.0
    for attr in entity.attributes:
        name_w = max(name_w, metrics.text_width(attr.name, _ER_NAME_FONT))
        if attr.type:
            type_w = max(type_w, metrics.text_width(attr.type, _ER_NAME_FONT))
    row_w = _ER_KEY_W + name_w + (_ER_GAP + type_w if type_w else 0.0)
    title_w = metrics.text_width(entity.name, _ER_TITLE_FONT)
    width = max(90.0, title_w, row_w) + 2.0 * _ER_PAD
    height = _ER_TITLE_H + max(1, len(entity.attributes)) * _ER_ROW_H
    return width, height


def er_alt_text(entities: Sequence, relationships: Sequence = ()) -> str:
    """Deterministic accessibility summary of an ER diagram."""
    entity_list, rel_list = _normalize_er(entities, relationships)
    e_word = "entity" if len(entity_list) == 1 else "entities"
    r_word = "relationship" if len(rel_list) == 1 else "relationships"
    names = ", ".join(e.name for e in entity_list[:5])
    if len(entity_list) > 5:
        names += ", ..."
    return (
        f"Entity-relationship diagram: {len(entity_list)} {e_word}, "
        f"{len(rel_list)} {r_word} ({names})"
    )


def render_er_svg(
    entities: Sequence,
    relationships: Sequence = (),
    theme_colors: dict | None = None,
) -> str:
    """Render an entity-relationship diagram to deterministic SVG markup."""
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    entity_list, rel_list = _normalize_er(entities, relationships)
    metrics = _metrics()

    sizes = [(e.id, *_entity_size(e, metrics)) for e in entity_list]
    positions, total_w, total_h = _grid_positions(sizes, "down", _ER_HGAP, _ER_VGAP)
    boxes: dict = {}
    for eid, (px, py, w, h) in positions.items():
        boxes[eid] = (px + _ER_MARGIN, py + _ER_MARGIN, w, h)

    width = total_w + 2.0 * _ER_MARGIN
    height = total_h + 2.0 * _ER_MARGIN
    parts = [_svg_open(width, height)]

    # Relationship lines first (behind entity boxes).
    for rel in rel_list:
        ax, ay, aw, ah = boxes[rel.src]
        bx, by, bw, bh = boxes[rel.dst]
        acx, acy = ax + aw / 2.0, ay + ah / 2.0
        bcx, bcy = bx + bw / 2.0, by + bh / 2.0
        x1, y1 = _rect_border(acx, acy, aw / 2.0, ah / 2.0, bcx, bcy)
        x2, y2 = _rect_border(bcx, bcy, bw / 2.0, bh / 2.0, acx, acy)
        parts.append(
            f'<path d="{_solid_path([(x1, y1), (x2, y2)])}" fill="none" '
            f'stroke="{theme["edge"]}" stroke-width="1"/>'
        )
        ux, uy = x2 - x1, y2 - y1
        length = math.hypot(ux, uy) or 1.0
        ux, uy = ux / length, uy / length
        if rel.src_card:
            parts.append(
                _text_el(
                    x1 + ux * 12.0,
                    y1 + uy * 12.0 - 3.0,
                    _LABEL_FONT_SIZE,
                    "middle",
                    theme["text"],
                    rel.src_card,
                )
            )
        if rel.dst_card:
            parts.append(
                _text_el(
                    x2 - ux * 12.0,
                    y2 - uy * 12.0 - 3.0,
                    _LABEL_FONT_SIZE,
                    "middle",
                    theme["text"],
                    rel.dst_card,
                )
            )
        if rel.label:
            parts.extend(
                _mid_label(
                    (x1 + x2) / 2.0,
                    (y1 + y2) / 2.0,
                    rel.label,
                    metrics,
                    theme["text"],
                    theme["label_background"],
                )
            )

    # Entity boxes with title bar and attribute rows.
    for entity in entity_list:
        x, y, w, h = boxes[entity.id]
        parts.append(
            f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" '
            f'height="{_fmt(h)}" fill="#ffffff" stroke="{theme["stroke"]}" '
            f'stroke-width="1"/>'
        )
        parts.append(
            f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" '
            f'height="{_fmt(_ER_TITLE_H)}" fill="{theme["stroke"]}" '
            f'stroke="{theme["stroke"]}" stroke-width="1"/>'
        )
        parts.append(
            _text_el(
                x + w / 2.0,
                y + _ER_TITLE_H / 2.0 + _ER_TITLE_FONT * 0.35,
                _ER_TITLE_FONT,
                "middle",
                "#ffffff",
                entity.name,
            )
        )
        for i, attr in enumerate(entity.attributes):
            ry = y + _ER_TITLE_H + i * _ER_ROW_H
            if i:
                parts.append(_ln(x, ry, x + w, ry, "#e2e8f0"))
            baseline = ry + _ER_ROW_H / 2.0 + _ER_NAME_FONT * 0.35
            if attr.key:
                parts.append(
                    _text_el(
                        x + _ER_PAD,
                        baseline,
                        _ER_NAME_FONT,
                        "start",
                        theme["text"],
                        attr.key,
                    )
                )
            name_x = x + _ER_PAD + _ER_KEY_W
            parts.append(
                _text_el(
                    name_x, baseline, _ER_NAME_FONT, "start", theme["text"], attr.name
                )
            )
            if attr.key == "PK":
                name_w = metrics.text_width(attr.name, _ER_NAME_FONT)
                parts.append(
                    _ln(
                        name_x,
                        baseline + 1.5,
                        name_x + name_w,
                        baseline + 1.5,
                        theme["text"],
                    )
                )
            if attr.type:
                parts.append(
                    _text_el(
                        x + w - _ER_PAD,
                        baseline,
                        _ER_NAME_FONT,
                        "end",
                        theme["muted"] if "muted" in theme else theme["text"],
                        attr.type,
                    )
                )
    parts.append("</svg>")
    return "\n".join(parts)


def er_svg_block(
    entities: Sequence,
    relationships: Sequence = (),
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock for an ER diagram with generated alt text."""
    from .spec import SvgBlock

    source = render_er_svg(entities, relationships, theme_colors=theme_colors)
    kw.setdefault("alt_text", er_alt_text(entities, relationships))
    return SvgBlock(source=source, caption=caption, **kw)
