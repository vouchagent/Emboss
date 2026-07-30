"""Layered node/edge diagrams compiled to SVG for the SvgBlock render path."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
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
    "RoadmapBar",
    "RoadmapWorkstream",
    "RoadmapMilestone",
    "STATUS_COLORS",
    "render_roadmap_svg",
    "roadmap_alt_text",
    "roadmap_svg_block",
    "layout_org_chart",
    "render_org_chart_svg",
    "org_chart_alt_text",
    "org_chart_svg_block",
    "GanttTask",
    "GanttMilestone",
    "render_gantt_svg",
    "gantt_alt_text",
    "gantt_svg_block",
    "layout_diagram_force",
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
_LANE_GAP = 20.0
_LANE_LABEL_H = 22.0
_LANE_LABEL_SIZE = 9.5
_LANE_FILLS = ("#f7f9fb", "#eef4fb")
_LANE_BORDER = "#c7d2dd"
_ARROW_LENGTH = 7.0
_ARROW_HALF_WIDTH = 3.0
_DASH_ON = 4.0
_DASH_OFF = 3.0
_STORE_CAP = 7.0
_ROUND_RADIUS = 7.0
_LOOP_EXTENT = 18.0
_FORCE_ITERATIONS = 200
_FORCE_K = 70.0
_FORCE_INITIAL_TEMP = 60.0
_FORCE_MIN_DIST = 0.01

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
    lane: str | None = None

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
    lane_bands: tuple = ()  # tuple of (name, start, extent), in lane order

    @property
    def by_id(self) -> dict:
        return {placed.node.id: placed for placed in self.nodes}


def _as_node(item) -> DiagramNode:
    """Coerce a DiagramNode, (id, label[, shape]) tuple, or dict to a node."""
    if isinstance(item, DiagramNode):
        return item
    if isinstance(item, dict):
        return DiagramNode(**item)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 5:
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


def _resolve_lanes(node_list: list, lanes: Sequence | None) -> list | None:
    """Return the lane order, or None if no lanes are in play.

    Raises ValueError naming the offending node if lanes are active but a
    node has no lane, or names a lane outside the given/inferred set.
    """
    has_lane = any(n.lane is not None for n in node_list)
    if lanes is None and not has_lane:
        return None
    if lanes is not None:
        lane_order = list(lanes)
    else:
        lane_order = []
        for n in node_list:
            if n.lane is not None and n.lane not in lane_order:
                lane_order.append(n.lane)
    lane_set = set(lane_order)
    for n in node_list:
        if n.lane is None or n.lane not in lane_set:
            raise ValueError(
                f"node {n.id!r} has no valid lane; expected one of {tuple(lane_order)}"
            )
    return lane_order


def layout_diagram(
    nodes: Sequence,
    edges: Sequence = (),
    direction: str = "down",
    lanes: Sequence | None = None,
) -> DiagramLayout:
    """Compute a layered DAG layout with even spacing for a node/edge graph.

    `lanes` (an explicit ordered list of lane names, or None to infer the
    order from each node's `lane` in first-appearance order) turns this
    into a swimlane layout: every node must then carry a `lane` from that
    set, and each lane occupies a fixed band along the cross axis --
    vertical bands for `direction="down"`, horizontal bands for `"right"`.
    """
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

    lane_order = _resolve_lanes(node_list, lanes)

    if lane_order is None:
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
        lane_bands: tuple = ()
    else:
        by_lane_layer = [
            {
                lane: [nid for nid in members if node_map[nid].lane == lane]
                for lane in lane_order
            }
            for members in layers
        ]
        lane_width = {lane: 0.0 for lane in lane_order}
        for row in by_lane_layer:
            for lane, ids in row.items():
                if not ids:
                    continue
                w = sum(cross_size(nid) for nid in ids) + _SIBLING_GAP * (len(ids) - 1)
                lane_width[lane] = max(lane_width[lane], w)

        lane_start: dict = {}
        cursor = _MARGIN
        for lane in lane_order:
            lane_start[lane] = cursor
            cursor += max(lane_width[lane], _MIN_NODE_WIDTH) + _LANE_GAP
        cross_extent = cursor - _LANE_GAP + _MARGIN
        lane_bands = tuple(
            (lane, lane_start[lane], max(lane_width[lane], _MIN_NODE_WIDTH))
            for lane in lane_order
        )

        placement = {}
        flow_cursor = _MARGIN + _LANE_LABEL_H
        for members, row in zip(layers, by_lane_layer):
            thickness = max(flow_size(nid) for nid in members)
            for lane, ids in row.items():
                if not ids:
                    continue
                band_w = max(lane_width[lane], _MIN_NODE_WIDTH)
                content_w = sum(cross_size(nid) for nid in ids) + _SIBLING_GAP * (
                    len(ids) - 1
                )
                cross_cursor = lane_start[lane] + (band_w - content_w) / 2.0
                for nid in ids:
                    flow_pos = flow_cursor + (thickness - flow_size(nid)) / 2.0
                    placement[nid] = (cross_cursor, flow_pos)
                    cross_cursor += cross_size(nid) + _SIBLING_GAP
            flow_cursor += thickness + _LAYER_GAP
        flow_extent = flow_cursor - _LAYER_GAP + _MARGIN

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
        lane_bands=lane_bands,
    )


def layout_diagram_force(nodes: Sequence, edges: Sequence = ()) -> DiagramLayout:
    """Force-directed (spring-embedder) layout for graphs with no natural flow.

    Deterministic by construction: initial positions are seeded evenly
    around a circle in input node order (no randomness), and a fixed
    number of iterations with a fixed linear cooling schedule always
    converges to the same result for the same input.
    """
    node_list, edge_list = _normalize(nodes, edges)
    node_ids = [n.id for n in node_list]
    node_map = {n.id: n for n in node_list}
    n = len(node_list)

    metrics = _metrics()
    lines_of = {nid: _wrap_label(node_map[nid].label, metrics) for nid in node_ids}
    size_of = {
        nid: _node_size(node_map[nid], lines_of[nid], metrics) for nid in node_ids
    }

    radius = _FORCE_K * max(1.0, n / 2.0)
    pos = {}
    for i, nid in enumerate(node_ids):
        angle = (2.0 * math.pi * i / n) if n > 1 else 0.0
        pos[nid] = [radius * math.cos(angle), radius * math.sin(angle)]

    pairs = [(e.src, e.dst) for e in edge_list if e.src != e.dst]
    k = _FORCE_K

    for step in range(_FORCE_ITERATIONS):
        temp = _FORCE_INITIAL_TEMP * (1.0 - step / _FORCE_ITERATIONS)
        disp = {nid: [0.0, 0.0] for nid in node_ids}
        for i in range(n):
            for j in range(i + 1, n):
                a, b = node_ids[i], node_ids[j]
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                dist = math.hypot(dx, dy) or _FORCE_MIN_DIST
                force = k * k / dist
                ux, uy = dx / dist, dy / dist
                disp[a][0] += ux * force
                disp[a][1] += uy * force
                disp[b][0] -= ux * force
                disp[b][1] -= uy * force
        for src, dst in pairs:
            dx = pos[src][0] - pos[dst][0]
            dy = pos[src][1] - pos[dst][1]
            dist = math.hypot(dx, dy) or _FORCE_MIN_DIST
            force = dist * dist / k
            ux, uy = dx / dist, dy / dist
            disp[src][0] -= ux * force
            disp[src][1] -= uy * force
            disp[dst][0] += ux * force
            disp[dst][1] += uy * force
        for nid in node_ids:
            dx, dy = disp[nid]
            dlen = math.hypot(dx, dy) or _FORCE_MIN_DIST
            capped = min(dlen, max(temp, 0.0))
            pos[nid][0] += dx / dlen * capped
            pos[nid][1] += dy / dlen * capped

    min_x = min(pos[nid][0] - size_of[nid][0] / 2.0 for nid in node_ids)
    min_y = min(pos[nid][1] - size_of[nid][1] / 2.0 for nid in node_ids)
    shift_x, shift_y = _MARGIN - min_x, _MARGIN - min_y

    placed_nodes = []
    for node in node_list:
        w, h = size_of[node.id]
        cx, cy = pos[node.id][0] + shift_x, pos[node.id][1] + shift_y
        placed_nodes.append(
            PlacedNode(
                node=node,
                x=cx - w / 2.0,
                y=cy - h / 2.0,
                width=w,
                height=h,
                lines=lines_of[node.id],
                layer=0,
            )
        )
    canvas_w = max(p.x + p.width for p in placed_nodes) + _MARGIN
    canvas_h = max(p.y + p.height for p in placed_nodes) + _MARGIN
    return DiagramLayout(
        nodes=placed_nodes,
        edges=edge_list,
        width=canvas_w,
        height=canvas_h,
        direction="down",
        layers=[node_ids],
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


def _force_edge_markup(
    edge: DiagramEdge, layout: DiagramLayout, theme: dict, metrics: FontMetrics
) -> list:
    """Emit a straight edge (not orthogonally routed) for a force layout."""
    by_id = layout.by_id
    a, b = by_id[edge.src], by_id[edge.dst]
    color = theme["edge"]
    if edge.src == edge.dst:
        points = _route_edge(a, b, "down")
        tip, prev = points[-1], points[-2]
        length = math.hypot(tip[0] - prev[0], tip[1] - prev[1])
        ux, uy = (tip[0] - prev[0]) / length, (tip[1] - prev[1]) / length
        shortened = points[:-1] + [
            (tip[0] - ux * _ARROW_LENGTH, tip[1] - uy * _ARROW_LENGTH)
        ]
        d = (
            _dashed_path(shortened)
            if edge.style == "dashed"
            else _solid_path(shortened)
        )
        return [
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1"/>',
            _arrow_markup(tip, (ux, uy), color),
        ]
    x1, y1 = _rect_border(
        a.center_x, a.center_y, a.width / 2.0, a.height / 2.0, b.center_x, b.center_y
    )
    x2, y2 = _rect_border(
        b.center_x, b.center_y, b.width / 2.0, b.height / 2.0, a.center_x, a.center_y
    )
    out = _straight_arrow(x1, y1, x2, y2, color, edge.style)
    if edge.label:
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
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


def _lane_band_markup(layout: "DiagramLayout", theme: dict) -> list:
    """Emit background bands and title labels for each active lane."""
    if not layout.lane_bands:
        return []
    parts = []
    for i, (lane, start, extent) in enumerate(layout.lane_bands):
        fill = _LANE_FILLS[i % len(_LANE_FILLS)]
        if layout.direction == "down":
            parts.append(
                f'<rect x="{_fmt(start)}" y="2.00" width="{_fmt(extent)}" '
                f'height="{_fmt(layout.height - 4.0)}" fill="{fill}" '
                f'stroke="{_LANE_BORDER}" stroke-width="1"/>'
            )
            parts.append(
                _text_el(
                    start + extent / 2.0,
                    _LANE_LABEL_H / 2.0 + _LANE_LABEL_SIZE / 2.0 - 2.0,
                    _LANE_LABEL_SIZE,
                    "middle",
                    theme["text"],
                    lane,
                )
            )
        else:
            parts.append(
                f'<rect x="2.00" y="{_fmt(start)}" width="{_fmt(layout.width - 4.0)}" '
                f'height="{_fmt(extent)}" fill="{fill}" '
                f'stroke="{_LANE_BORDER}" stroke-width="1"/>'
            )
            parts.append(
                _text_el(
                    6.0,
                    start + extent / 2.0 + _LANE_LABEL_SIZE / 2.0 - 2.0,
                    _LANE_LABEL_SIZE,
                    "start",
                    theme["text"],
                    lane,
                )
            )
    return parts


def render_diagram_svg(
    nodes: Sequence,
    edges: Sequence = (),
    direction: str = "down",
    lanes: Sequence | None = None,
    layout: str = "layered",
    theme_colors: dict | None = None,
) -> str:
    """Render a node/edge graph to deterministic SVG markup.

    `layout` is `"layered"` (the default Sugiyama-style flow layout) or
    `"force"` (a spring-embedder layout for graphs with no natural
    hierarchy, e.g. a mesh/peer-to-peer network diagram). `lanes` is only
    valid with `layout="layered"`.
    """
    if layout not in ("layered", "force"):
        raise ValueError(f"diagram layout must be 'layered' or 'force': {layout!r}")
    if layout == "force" and lanes is not None:
        raise ValueError("swimlanes ('lanes') are not supported with layout='force'")
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    if layout == "force":
        diagram_layout = layout_diagram_force(nodes, edges)
    else:
        diagram_layout = layout_diagram(nodes, edges, direction=direction, lanes=lanes)
    metrics = _metrics()
    w, h = _fmt(diagram_layout.width), _fmt(diagram_layout.height)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
    ]
    parts.extend(_lane_band_markup(diagram_layout, theme))
    for edge in diagram_layout.edges:
        if layout == "force":
            parts.extend(_force_edge_markup(edge, diagram_layout, theme, metrics))
        else:
            parts.extend(_edge_markup(edge, diagram_layout, theme, metrics))
    for placed in diagram_layout.nodes:
        parts.extend(_shape_markup(placed, theme["fill"], theme["stroke"]))
        parts.extend(_label_markup(placed, theme["text"]))
    parts.append("</svg>")
    return "\n".join(parts)


def diagram_alt_text(
    nodes: Sequence, edges: Sequence = (), lanes: Sequence | None = None
) -> str:
    """Build a deterministic accessibility summary of the graph."""
    node_list, edge_list = _normalize(nodes, edges)
    labels = [node.label or node.id for node in node_list]
    shown = ", ".join(labels[:5])
    if len(labels) > 5:
        shown += ", ..."
    node_word = "node" if len(node_list) == 1 else "nodes"
    edge_word = "connection" if len(edge_list) == 1 else "connections"
    text = (
        f"Diagram: {len(node_list)} {node_word} ({shown}), {len(edge_list)} {edge_word}"
    )
    lane_order = _resolve_lanes(node_list, lanes)
    if lane_order:
        lane_word = "lane" if len(lane_order) == 1 else "lanes"
        text += f", {len(lane_order)} {lane_word} ({', '.join(lane_order)})"
    return text


def diagram_svg_block(
    nodes: Sequence,
    edges: Sequence = (),
    direction: str = "down",
    lanes: Sequence | None = None,
    layout: str = "layered",
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock carrying the rendered diagram plus generated alt text."""
    from .spec import SvgBlock

    node_list, edge_list = _normalize(nodes, edges)
    source = render_diagram_svg(
        node_list,
        edge_list,
        direction=direction,
        lanes=lanes,
        layout=layout,
        theme_colors=theme_colors,
    )
    kw.setdefault("alt_text", diagram_alt_text(node_list, edge_list, lanes=lanes))
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

# Status palette for landscape/capability-map coloring, in canonical
# (fill, label) order — used both for badges and for a deterministic
# legend ordering independent of node input order.
STATUS_COLORS = {
    "ok": ("#22c55e", "#166534"),
    "warning": ("#f59e0b", "#92400e"),
    "critical": ("#ef4444", "#991b1b"),
    "planned": ("#60a5fa", "#1e3a8a"),
    "retired": ("#9ca3af", "#374151"),
}
_LEGEND_H = 24.0
_LEGEND_SWATCH = 10.0
_LEGEND_GAP = 18.0
_LEGEND_FONT = 8.5
_STATUS_BADGE_R = 5.0


@dataclass
class ArchNode:
    """A service node in an architecture diagram, drawn with a vector glyph."""

    id: str
    label: str
    service: str = "generic"
    group: str | None = None
    image: str | bytes | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("architecture node id must be a non-empty string")
        if self.service not in SERVICE_TYPES:
            raise ValueError(
                f"unknown service type {self.service!r}; expected one of {SERVICE_TYPES}"
            )
        if self.status is not None and self.status not in STATUS_COLORS:
            raise ValueError(
                f"unknown status {self.status!r}; expected one of "
                f"{tuple(STATUS_COLORS)}"
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
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 6:
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
    statuses_used = [s for s in STATUS_COLORS if any(n.status == s for n in node_list)]
    legend_h = _LEGEND_H if statuses_used else 0.0
    parts = [_svg_open(width, height + legend_h)]

    # Groups behind everything, outermost first (shallowest depth drawn first).
    def depth_of(gid: str) -> int:
        d = 0
        cursor = parent.get(gid)
        while cursor is not None:
            d += 1
            cursor = parent.get(cursor)
        return d

    group_titles: list = []
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
            # Draw the zone title last, on a solid chip, so it stays crisp
            # over any edge or edge-label that crosses the zone boundary.
            tw = metrics.text_width(box["group"].label, 9.0)
            group_titles.append(
                f'<rect x="{_fmt(box["x"] + _GROUP_PAD - 3.0)}" '
                f'y="{_fmt(box["y"] + 2.0)}" width="{_fmt(tw + 6.0)}" '
                f'height="{_fmt(_GROUP_TITLE_H - 2.0)}" fill="{tint}"/>'
            )
            group_titles.append(
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
        if node.status is not None:
            fill, _label_color = STATUS_COLORS[node.status]
            bx = box["x"] + box["w"] - _STATUS_BADGE_R - 1.0
            by = box["y"] + _STATUS_BADGE_R + 1.0
            parts.append(
                f'<circle cx="{_fmt(bx)}" cy="{_fmt(by)}" r="{_fmt(_STATUS_BADGE_R)}" '
                f'fill="{fill}" stroke="#ffffff" stroke-width="1.5"/>'
            )
    # Zone titles overlay everything so they never collide with edge labels.
    parts.extend(group_titles)
    if statuses_used:
        parts.extend(_status_legend(statuses_used, width, height))
    parts.append("</svg>")
    return "\n".join(parts)


def _status_legend(statuses_used: list, width: float, top_y: float) -> list:
    """Emit a left-to-right legend row for the statuses actually in use."""
    metrics = _metrics()
    entries = []
    for status in statuses_used:
        fill, _border = STATUS_COLORS[status]
        label = status
        entries.append((fill, label, metrics.text_width(label, _LEGEND_FONT)))
    row_w = sum(_LEGEND_SWATCH + 4.0 + w + _LEGEND_GAP for _f, _l, w in entries)
    row_w -= _LEGEND_GAP
    x = max(_ARCH_MARGIN, (width - row_w) / 2.0)
    cy = top_y + _LEGEND_H / 2.0
    parts = []
    for fill, label, text_w in entries:
        parts.append(
            f'<rect x="{_fmt(x)}" y="{_fmt(cy - _LEGEND_SWATCH / 2.0)}" '
            f'width="{_fmt(_LEGEND_SWATCH)}" height="{_fmt(_LEGEND_SWATCH)}" '
            f'rx="2" fill="{fill}"/>'
        )
        parts.append(
            _text_el(
                x + _LEGEND_SWATCH + 4.0,
                cy + _LEGEND_FONT / 2.0 - 1.0,
                _LEGEND_FONT,
                "start",
                "#374151",
                label,
            )
        )
        x += _LEGEND_SWATCH + 4.0 + text_w + _LEGEND_GAP
    return parts


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


# ======================================================================
# 5. Roadmap / timeline diagrams
# ======================================================================

_RM_PERIOD_W_MIN = 56.0
_RM_ROW_H = 32.0
_RM_HEADER_H = 24.0
_RM_MILESTONE_H = 20.0
_RM_BAR_PAD = 5.0
_RM_PAD = 8.0
_RM_GUTTER_PAD = 10.0
_RM_GUTTER_MIN = 60.0
_RM_MARGIN = 14.0
_RM_HEADER_SIZE = 9.0
_RM_LABEL_SIZE = 9.0
_RM_BAR_LABEL_SIZE = 8.0
_RM_BAR_FILL = "#dbeafe"
_RM_BAR_BORDER = "#3b82f6"
_RM_GRID = "#e5e7eb"
_RM_MILESTONE_FILL = "#f59e0b"
_RM_MILESTONE_BORDER = "#92400e"


@dataclass
class RoadmapBar:
    """One bar in a workstream, spanning an inclusive period range."""

    label: str
    start: str
    end: str
    status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.start, str) or not self.start:
            raise ValueError("roadmap bar requires a non-empty 'start' period")
        if not isinstance(self.end, str) or not self.end:
            raise ValueError("roadmap bar requires a non-empty 'end' period")
        if self.status is not None and self.status not in STATUS_COLORS:
            raise ValueError(
                f"unknown status {self.status!r}; expected one of "
                f"{tuple(STATUS_COLORS)}"
            )


@dataclass
class RoadmapWorkstream:
    """One row of the roadmap: a name and its bars."""

    name: str
    bars: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("roadmap workstream requires a non-empty 'name'")
        self.bars = tuple(_as_roadmap_bar(b) for b in self.bars)


@dataclass
class RoadmapMilestone:
    """A diamond marker at a period, optionally pinned to one workstream row."""

    label: str
    at: str
    workstream: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.at, str) or not self.at:
            raise ValueError("roadmap milestone requires a non-empty 'at' period")


def _as_roadmap_bar(item) -> RoadmapBar:
    if isinstance(item, RoadmapBar):
        return item
    if isinstance(item, dict):
        return RoadmapBar(**item)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 4:
        return RoadmapBar(*item)
    raise TypeError(f"cannot build a RoadmapBar from {item!r}")


def _as_workstream(item) -> RoadmapWorkstream:
    if isinstance(item, RoadmapWorkstream):
        return item
    if isinstance(item, dict):
        return RoadmapWorkstream(**item)
    raise TypeError(f"cannot build a RoadmapWorkstream from {item!r}")


def _as_milestone(item) -> RoadmapMilestone:
    if isinstance(item, RoadmapMilestone):
        return item
    if isinstance(item, dict):
        return RoadmapMilestone(**item)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 3:
        return RoadmapMilestone(*item)
    raise TypeError(f"cannot build a RoadmapMilestone from {item!r}")


def _normalize_roadmap(periods: Sequence, workstreams: Sequence, milestones: Sequence):
    """Validate and coerce roadmap periods, workstreams, and milestones."""
    period_list = list(periods)
    if not period_list:
        raise ValueError("roadmap requires at least one period")
    if len(set(period_list)) != len(period_list):
        raise ValueError("roadmap periods must be unique")
    period_index = {p: i for i, p in enumerate(period_list)}

    ws_list = [_as_workstream(w) for w in workstreams]
    if not ws_list:
        raise ValueError("roadmap requires at least one workstream")
    ws_names: set = set()
    for ws in ws_list:
        if ws.name in ws_names:
            raise ValueError(f"duplicate roadmap workstream name: {ws.name!r}")
        ws_names.add(ws.name)
        for bar in ws.bars:
            if bar.start not in period_index:
                raise ValueError(
                    f"roadmap bar {bar.label!r} references unknown period: "
                    f"{bar.start!r}"
                )
            if bar.end not in period_index:
                raise ValueError(
                    f"roadmap bar {bar.label!r} references unknown period: {bar.end!r}"
                )
            if period_index[bar.end] < period_index[bar.start]:
                raise ValueError(
                    f"roadmap bar {bar.label!r} ends before it starts "
                    f"({bar.start!r} -> {bar.end!r})"
                )

    ms_list = [_as_milestone(m) for m in milestones]
    for ms in ms_list:
        if ms.at not in period_index:
            raise ValueError(
                f"roadmap milestone {ms.label!r} references unknown period: {ms.at!r}"
            )
        if ms.workstream is not None and ms.workstream not in ws_names:
            raise ValueError(
                f"roadmap milestone {ms.label!r} references unknown workstream: "
                f"{ms.workstream!r}"
            )
    return period_list, ws_list, ms_list


def roadmap_alt_text(
    periods: Sequence, workstreams: Sequence, milestones: Sequence = ()
) -> str:
    """Deterministic accessibility summary of a roadmap diagram."""
    period_list, ws_list, ms_list = _normalize_roadmap(periods, workstreams, milestones)
    bar_count = sum(len(ws.bars) for ws in ws_list)
    parts = [
        f"Roadmap: {len(period_list)} period" + ("" if len(period_list) == 1 else "s"),
        f"{len(ws_list)} workstream" + ("" if len(ws_list) == 1 else "s"),
        f"{bar_count} bar" + ("" if bar_count == 1 else "s"),
    ]
    if ms_list:
        parts.append(f"{len(ms_list)} milestone" + ("" if len(ms_list) == 1 else "s"))
    names = ", ".join(ws.name for ws in ws_list[:5])
    if len(ws_list) > 5:
        names += ", ..."
    return f"{', '.join(parts)} ({names})"


def render_roadmap_svg(
    periods: Sequence,
    workstreams: Sequence,
    milestones: Sequence = (),
    theme_colors: dict | None = None,
) -> str:
    """Render a roadmap/timeline diagram to deterministic SVG markup."""
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    period_list, ws_list, ms_list = _normalize_roadmap(periods, workstreams, milestones)
    period_index = {p: i for i, p in enumerate(period_list)}
    metrics = _metrics()

    period_w = max(
        _RM_PERIOD_W_MIN,
        max(metrics.text_width(p, _RM_HEADER_SIZE) for p in period_list) + 2 * _RM_PAD,
    )
    gutter_w = max(
        _RM_GUTTER_MIN,
        max(metrics.text_width(ws.name, _RM_LABEL_SIZE) for ws in ws_list)
        + 2 * _RM_GUTTER_PAD,
    )
    shared_milestones = [m for m in ms_list if m.workstream is None]
    milestone_h = _RM_MILESTONE_H if shared_milestones else 0.0

    statuses_used = [
        s
        for s in STATUS_COLORS
        if any(bar.status == s for ws in ws_list for bar in ws.bars)
    ]
    legend_h = _LEGEND_H if statuses_used else 0.0

    timeline_x0 = _RM_MARGIN + gutter_w
    rows_y0 = _RM_MARGIN + _RM_HEADER_H + milestone_h
    total_w = timeline_x0 + period_w * len(period_list) + _RM_MARGIN
    total_h = rows_y0 + _RM_ROW_H * len(ws_list) + _RM_MARGIN + legend_h

    def period_x(name: str) -> float:
        return timeline_x0 + period_index[name] * period_w

    parts = [_svg_open(total_w, total_h)]

    # Vertical period gridlines and header labels.
    for i, p in enumerate(period_list):
        x = timeline_x0 + i * period_w
        parts.append(_ln(x, rows_y0, x, rows_y0 + _RM_ROW_H * len(ws_list), _RM_GRID))
        parts.append(
            _text_el(
                x + period_w / 2.0,
                _RM_MARGIN + _RM_HEADER_H - 7.0,
                _RM_HEADER_SIZE,
                "middle",
                theme["text"],
                p,
            )
        )
    end_x = timeline_x0 + len(period_list) * period_w
    parts.append(
        _ln(end_x, rows_y0, end_x, rows_y0 + _RM_ROW_H * len(ws_list), _RM_GRID)
    )

    # Workstream rows: label, horizontal gridline, and bars.
    for row, ws in enumerate(ws_list):
        row_y = rows_y0 + row * _RM_ROW_H
        parts.append(
            _text_el(
                _RM_MARGIN,
                row_y + _RM_ROW_H / 2.0 + _RM_LABEL_SIZE / 2.0 - 2.0,
                _RM_LABEL_SIZE,
                "start",
                theme["text"],
                ws.name,
            )
        )
        parts.append(_ln(timeline_x0, row_y, total_w - _RM_MARGIN, row_y, _RM_GRID))
        for bar in ws.bars:
            bx = period_x(bar.start)
            bw = (period_index[bar.end] - period_index[bar.start] + 1) * period_w
            by = row_y + _RM_BAR_PAD
            bh = _RM_ROW_H - 2.0 * _RM_BAR_PAD
            fill = STATUS_COLORS[bar.status][0] if bar.status else _RM_BAR_FILL
            border = STATUS_COLORS[bar.status][1] if bar.status else _RM_BAR_BORDER
            parts.append(
                f'<path d="{_rounded_rect_path(bx + 2.0, by, bw - 4.0, bh, 4.0)}" '
                f'fill="{fill}" stroke="{border}" stroke-width="1"/>'
            )
            if bar.label:
                parts.append(
                    _text_el(
                        bx + bw / 2.0,
                        by + bh / 2.0 + _RM_BAR_LABEL_SIZE / 2.0 - 2.0,
                        _RM_BAR_LABEL_SIZE,
                        "middle",
                        theme["text"],
                        bar.label,
                    )
                )
    bottom_y = rows_y0 + _RM_ROW_H * len(ws_list)
    parts.append(_ln(timeline_x0, bottom_y, total_w - _RM_MARGIN, bottom_y, _RM_GRID))

    # Milestone diamonds: shared strip, or centered on a named workstream row.
    ws_row = {ws.name: i for i, ws in enumerate(ws_list)}
    for ms in ms_list:
        cx = period_x(ms.at) + period_w / 2.0
        if ms.workstream is None:
            cy = _RM_MARGIN + _RM_HEADER_H + milestone_h / 2.0
        else:
            row_y = rows_y0 + ws_row[ms.workstream] * _RM_ROW_H
            cy = row_y + _RM_ROW_H / 2.0
        r = 5.0
        parts.append(
            f'<polygon points="{_fmt(cx)},{_fmt(cy - r)} {_fmt(cx + r)},{_fmt(cy)} '
            f'{_fmt(cx)},{_fmt(cy + r)} {_fmt(cx - r)},{_fmt(cy)}" '
            f'fill="{_RM_MILESTONE_FILL}" stroke="{_RM_MILESTONE_BORDER}" '
            f'stroke-width="1"/>'
        )
        if ms.label:
            parts.append(
                _text_el(
                    cx,
                    cy - r - 3.0,
                    _RM_BAR_LABEL_SIZE,
                    "middle",
                    theme["text"],
                    ms.label,
                )
            )

    if statuses_used:
        parts.extend(_status_legend(statuses_used, total_w, total_h - legend_h))
    parts.append("</svg>")
    return "\n".join(parts)


def roadmap_svg_block(
    periods: Sequence,
    workstreams: Sequence,
    milestones: Sequence = (),
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock for a roadmap/timeline diagram with generated alt text."""
    from .spec import SvgBlock

    source = render_roadmap_svg(
        periods, workstreams, milestones, theme_colors=theme_colors
    )
    kw.setdefault("alt_text", roadmap_alt_text(periods, workstreams, milestones))
    return SvgBlock(source=source, caption=caption, **kw)


# ======================================================================
# 6. Org charts
# ======================================================================


def _validate_tree(node_list: list, edge_list: list) -> tuple:
    """Return (children, roots), or raise ValueError if not a tree/forest."""
    ids = {n.id for n in node_list}
    indegree = {nid: 0 for nid in ids}
    parent_of: dict = {}
    children: dict = {nid: [] for nid in ids}
    for edge in edge_list:
        if edge.src == edge.dst:
            raise ValueError(f"org chart node {edge.src!r} cannot be its own parent")
        indegree[edge.dst] += 1
        if indegree[edge.dst] > 1:
            raise ValueError(f"org chart node {edge.dst!r} has more than one parent")
        parent_of[edge.dst] = edge.src
        children[edge.src].append(edge.dst)
    roots = [n.id for n in node_list if indegree[n.id] == 0]
    if not roots:
        raise ValueError("org chart has no root; every node has a parent (a cycle)")
    for nid in ids:
        seen: set = set()
        cursor = nid
        while cursor in parent_of:
            if cursor in seen:
                raise ValueError("org chart nodes form a cycle")
            seen.add(cursor)
            cursor = parent_of[cursor]
    return children, roots


def _tree_widths(nid: str, children: dict, cross_size, memo: dict) -> float:
    if nid in memo:
        return memo[nid]
    kids = children.get(nid, [])
    own = cross_size(nid)
    if not kids:
        memo[nid] = own
        return own
    kids_w = sum(_tree_widths(k, children, cross_size, memo) for k in kids)
    kids_w += _SIBLING_GAP * (len(kids) - 1)
    width = max(own, kids_w)
    memo[nid] = width
    return width


def _place_tree(
    nid: str, cross_start: float, children: dict, cross_size, width_of: dict, out: dict
) -> None:
    width = width_of[nid]
    kids = children.get(nid, [])
    if kids:
        kids_w = sum(width_of[k] for k in kids) + _SIBLING_GAP * (len(kids) - 1)
        cursor = cross_start + (width - kids_w) / 2.0
        for k in kids:
            _place_tree(k, cursor, children, cross_size, width_of, out)
            cursor += width_of[k] + _SIBLING_GAP
    out[nid] = cross_start + (width - cross_size(nid)) / 2.0


def layout_org_chart(
    nodes: Sequence, edges: Sequence = (), direction: str = "down"
) -> DiagramLayout:
    """Lay out a tree/forest with each parent centered over its children.

    Every node must have at most one incoming edge; a node with two or
    more parents, or a cycle, raises ValueError naming the problem.
    """
    if direction not in ("down", "right"):
        raise ValueError(f"diagram direction must be 'down' or 'right': {direction!r}")
    node_list, edge_list = _normalize(nodes, edges)
    node_ids = [n.id for n in node_list]
    node_map = {n.id: n for n in node_list}
    children, roots = _validate_tree(node_list, edge_list)

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

    width_of: dict = {}
    for root in roots:
        _tree_widths(root, children, cross_size, width_of)
    cross_placement: dict = {}
    cursor = _MARGIN
    for root in roots:
        _place_tree(root, cursor, children, cross_size, width_of, cross_placement)
        cursor += width_of[root] + _SIBLING_GAP
    cross_extent = cursor - _SIBLING_GAP + _MARGIN

    layer_of = _assign_layers(node_ids, [(e.src, e.dst) for e in edge_list])
    layer_count = max(layer_of.values()) + 1 if layer_of else 1
    layers: list = [[] for _ in range(layer_count)]
    for nid in node_ids:
        layers[layer_of[nid]].append(nid)

    flow_pos: dict = {}
    flow_cursor = _MARGIN
    for members in layers:
        thickness = max(flow_size(nid) for nid in members)
        for nid in members:
            flow_pos[nid] = flow_cursor + (thickness - flow_size(nid)) / 2.0
        flow_cursor += thickness + _LAYER_GAP
    flow_extent = flow_cursor - _LAYER_GAP + _MARGIN

    placed_nodes = []
    for node in node_list:
        cross, flow = cross_placement[node.id], flow_pos[node.id]
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


def render_org_chart_svg(
    nodes: Sequence,
    edges: Sequence = (),
    direction: str = "down",
    theme_colors: dict | None = None,
) -> str:
    """Render an org chart to deterministic SVG markup."""
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    layout = layout_org_chart(nodes, edges, direction=direction)
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


def org_chart_alt_text(nodes: Sequence, edges: Sequence = ()) -> str:
    """Build a deterministic accessibility summary of the org chart."""
    node_list, edge_list = _normalize(nodes, edges)
    _children, roots = _validate_tree(node_list, edge_list)
    labels = [node.label or node.id for node in node_list]
    shown = ", ".join(labels[:5])
    if len(labels) > 5:
        shown += ", ..."
    node_word = "node" if len(node_list) == 1 else "nodes"
    root_word = "root" if len(roots) == 1 else "roots"
    return (
        f"Org chart: {len(node_list)} {node_word} ({shown}), {len(roots)} {root_word}"
    )


def org_chart_svg_block(
    nodes: Sequence,
    edges: Sequence = (),
    direction: str = "down",
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock for an org chart with generated alt text."""
    from .spec import SvgBlock

    node_list, edge_list = _normalize(nodes, edges)
    source = render_org_chart_svg(
        node_list, edge_list, direction=direction, theme_colors=theme_colors
    )
    kw.setdefault("alt_text", org_chart_alt_text(node_list, edge_list))
    return SvgBlock(source=source, caption=caption, **kw)


# ======================================================================
# 7. Gantt charts
# ======================================================================

_GT_ROW_H = 32.0
_GT_HEADER_H = 28.0
_GT_BAR_PAD = 5.0
_GT_GUTTER_PAD = 10.0
_GT_GUTTER_MIN = 70.0
_GT_MARGIN = 14.0
_GT_LABEL_SIZE = 9.0
_GT_HEADER_SIZE = 8.5
_GT_TIMELINE_W = 380.0
_GT_MIN_BAR_W = 4.0
_GT_PROGRESS_FILL = "#1d4ed8"
_GT_BAR_FILL = "#dbeafe"
_GT_BAR_BORDER = "#3b82f6"
_GT_GRID = "#e5e7eb"
_GT_DEP_COLOR = "#6b7280"


def _parse_gantt_date(value, field: str, context: str = "") -> date:
    if not isinstance(value, str) or not value:
        raise ValueError(f"gantt {context}requires a non-empty {field!r} date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"gantt {context}has an invalid {field!r} date: {value!r} "
            f"(expected YYYY-MM-DD)"
        ) from None


@dataclass
class GanttTask:
    """One task bar: an inclusive date range, optional progress and status."""

    name: str
    start: str
    end: str
    progress: float = 0.0
    status: str | None = None
    dependencies: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("gantt task requires a non-empty 'name'")
        context = f"task {self.name!r} "
        start_d = _parse_gantt_date(self.start, "start", context)
        end_d = _parse_gantt_date(self.end, "end", context)
        if end_d < start_d:
            raise ValueError(
                f"gantt task {self.name!r} ends before it starts "
                f"({self.start!r} -> {self.end!r})"
            )
        if not (0.0 <= self.progress <= 1.0):
            raise ValueError(
                f"gantt task {self.name!r} progress must be between 0.0 and "
                f"1.0, got {self.progress!r}"
            )
        if self.status is not None and self.status not in STATUS_COLORS:
            raise ValueError(
                f"unknown status {self.status!r}; expected one of "
                f"{tuple(STATUS_COLORS)}"
            )
        self.dependencies = tuple(self.dependencies)


@dataclass
class GanttMilestone:
    """A diamond marker at a date, shared across the whole timeline."""

    label: str
    at: str

    def __post_init__(self) -> None:
        _parse_gantt_date(self.at, "at", f"milestone {self.label!r} ")


def _as_gantt_task(item) -> GanttTask:
    if isinstance(item, GanttTask):
        return item
    if isinstance(item, dict):
        return GanttTask(**item)
    if isinstance(item, (tuple, list)) and 2 <= len(item) <= 5:
        return GanttTask(*item)
    raise TypeError(f"cannot build a GanttTask from {item!r}")


def _as_gantt_milestone(item) -> GanttMilestone:
    if isinstance(item, GanttMilestone):
        return item
    if isinstance(item, dict):
        return GanttMilestone(**item)
    if isinstance(item, (tuple, list)) and len(item) == 2:
        return GanttMilestone(*item)
    raise TypeError(f"cannot build a GanttMilestone from {item!r}")


def _normalize_gantt(tasks: Sequence, milestones: Sequence) -> tuple:
    """Validate and coerce gantt tasks and milestones."""
    task_list = [_as_gantt_task(t) for t in tasks]
    if not task_list:
        raise ValueError("gantt chart requires at least one task")
    names: set = set()
    for t in task_list:
        if t.name in names:
            raise ValueError(f"duplicate gantt task name: {t.name!r}")
        names.add(t.name)
    for t in task_list:
        for dep in t.dependencies:
            if dep == t.name:
                raise ValueError(f"gantt task {t.name!r} cannot depend on itself")
            if dep not in names:
                raise ValueError(
                    f"gantt task {t.name!r} depends on unknown task: {dep!r}"
                )
    ms_list = [_as_gantt_milestone(m) for m in milestones]
    return task_list, ms_list


def gantt_alt_text(tasks: Sequence, milestones: Sequence = ()) -> str:
    """Deterministic accessibility summary of a Gantt chart."""
    task_list, ms_list = _normalize_gantt(tasks, milestones)
    names = ", ".join(t.name for t in task_list[:5])
    if len(task_list) > 5:
        names += ", ..."
    parts = [
        f"Gantt chart: {len(task_list)} task" + ("" if len(task_list) == 1 else "s")
    ]
    if ms_list:
        parts.append(f"{len(ms_list)} milestone" + ("" if len(ms_list) == 1 else "s"))
    return f"{', '.join(parts)} ({names})"


def render_gantt_svg(
    tasks: Sequence, milestones: Sequence = (), theme_colors: dict | None = None
) -> str:
    """Render a Gantt chart to deterministic SVG markup."""
    theme = dict(_DEFAULT_THEME)
    if theme_colors:
        theme.update(theme_colors)
    task_list, ms_list = _normalize_gantt(tasks, milestones)
    metrics = _metrics()

    task_dates = {}
    all_dates = []
    for t in task_list:
        s, e = date.fromisoformat(t.start), date.fromisoformat(t.end)
        task_dates[t.name] = (s, e)
        all_dates.extend([s, e])
    ms_dates = []
    for m in ms_list:
        d = date.fromisoformat(m.at)
        ms_dates.append((m, d))
        all_dates.append(d)
    range_start, range_end = min(all_dates), max(all_dates)
    span_days = (range_end - range_start).days or 1

    gutter_w = max(
        _GT_GUTTER_MIN,
        max(metrics.text_width(t.name, _GT_LABEL_SIZE) for t in task_list)
        + 2 * _GT_GUTTER_PAD,
    )
    timeline_x0 = _GT_MARGIN + gutter_w

    def date_x(d: date) -> float:
        return timeline_x0 + (d - range_start).days / span_days * _GT_TIMELINE_W

    statuses_used = [s for s in STATUS_COLORS if any(t.status == s for t in task_list)]
    legend_h = _LEGEND_H if statuses_used else 0.0

    rows_y0 = _GT_MARGIN + _GT_HEADER_H
    total_w = timeline_x0 + _GT_TIMELINE_W + _GT_MARGIN
    total_h = rows_y0 + _GT_ROW_H * len(task_list) + _GT_MARGIN + legend_h
    bottom_y = rows_y0 + _GT_ROW_H * len(task_list)

    parts = [_svg_open(total_w, total_h)]

    for d in sorted(set(all_dates)):
        x = date_x(d)
        parts.append(_ln(x, rows_y0, x, bottom_y, _GT_GRID))
    parts.append(
        _text_el(
            timeline_x0,
            _GT_MARGIN + _GT_HEADER_H - 7.0,
            _GT_HEADER_SIZE,
            "start",
            theme["text"],
            range_start.isoformat(),
        )
    )
    parts.append(
        _text_el(
            timeline_x0 + _GT_TIMELINE_W,
            _GT_MARGIN + _GT_HEADER_H - 7.0,
            _GT_HEADER_SIZE,
            "end",
            theme["text"],
            range_end.isoformat(),
        )
    )

    row_y_of = {t.name: rows_y0 + i * _GT_ROW_H for i, t in enumerate(task_list)}
    for t in task_list:
        row_y = row_y_of[t.name]
        parts.append(
            _text_el(
                _GT_MARGIN,
                row_y + _GT_ROW_H / 2.0 + _GT_LABEL_SIZE / 2.0 - 2.0,
                _GT_LABEL_SIZE,
                "start",
                theme["text"],
                t.name,
            )
        )
        parts.append(_ln(timeline_x0, row_y, total_w - _GT_MARGIN, row_y, _GT_GRID))
        s, e = task_dates[t.name]
        bx, ex = date_x(s), date_x(e)
        bw = max(ex - bx, _GT_MIN_BAR_W)
        by = row_y + _GT_BAR_PAD
        bh = _GT_ROW_H - 2.0 * _GT_BAR_PAD
        fill = STATUS_COLORS[t.status][0] if t.status else _GT_BAR_FILL
        border = STATUS_COLORS[t.status][1] if t.status else _GT_BAR_BORDER
        parts.append(
            f'<path d="{_rounded_rect_path(bx, by, bw, bh, 4.0)}" '
            f'fill="{fill}" stroke="{border}" stroke-width="1"/>'
        )
        if t.progress > 0.0:
            pw = bw * t.progress
            parts.append(
                f'<path d="{_rounded_rect_path(bx, by, pw, bh, 4.0)}" '
                f'fill="{_GT_PROGRESS_FILL}" stroke="none"/>'
            )
    parts.append(_ln(timeline_x0, bottom_y, total_w - _GT_MARGIN, bottom_y, _GT_GRID))

    for t in task_list:
        t_s, _t_e = task_dates[t.name]
        t_cy = row_y_of[t.name] + _GT_ROW_H / 2.0
        for dep in t.dependencies:
            _dep_s, dep_e = task_dates[dep]
            dep_cy = row_y_of[dep] + _GT_ROW_H / 2.0
            parts.extend(
                _straight_arrow(date_x(dep_e), dep_cy, date_x(t_s), t_cy, _GT_DEP_COLOR)
            )

    for m, d in ms_dates:
        cx = date_x(d)
        cy = _GT_MARGIN + _GT_HEADER_H / 2.0
        r = 5.0
        parts.append(
            f'<polygon points="{_fmt(cx)},{_fmt(cy - r)} {_fmt(cx + r)},{_fmt(cy)} '
            f'{_fmt(cx)},{_fmt(cy + r)} {_fmt(cx - r)},{_fmt(cy)}" '
            f'fill="{_RM_MILESTONE_FILL}" stroke="{_RM_MILESTONE_BORDER}" '
            f'stroke-width="1"/>'
        )
        if m.label:
            parts.append(
                _text_el(
                    cx, cy - r - 3.0, _GT_HEADER_SIZE, "middle", theme["text"], m.label
                )
            )

    if statuses_used:
        parts.extend(_status_legend(statuses_used, total_w, total_h - legend_h))
    parts.append("</svg>")
    return "\n".join(parts)


def gantt_svg_block(
    tasks: Sequence,
    milestones: Sequence = (),
    caption: str | None = None,
    theme_colors: dict | None = None,
    **kw,
):
    """Build an SvgBlock for a Gantt chart with generated alt text."""
    from .spec import SvgBlock

    source = render_gantt_svg(tasks, milestones, theme_colors=theme_colors)
    kw.setdefault("alt_text", gantt_alt_text(tasks, milestones))
    return SvgBlock(source=source, caption=caption, **kw)
