"""Parse Mermaid diagram source into Emboss diagram SvgBlock elements.

Supported kinds and their targets:

    flowchart / graph  -> diagram_svg_block (node/edge flowchart)
    sequenceDiagram    -> sequence_svg_block
    erDiagram          -> er_svg_block

The public entry point is ``parse_mermaid(source)``, which auto-detects
the kind from the first keyword. Per-kind helpers are also exported. Any
malformed or unsupported input raises ``MermaidError`` quoting the
offending line. Output is deterministic: nodes, participants, and
entities keep their source order.

Unsupported kinds (classDiagram, stateDiagram, and anything else) raise
``MermaidError`` naming the kind rather than rendering something wrong.
"""

from __future__ import annotations

import re

from .diagrams import (
    DiagramEdge,
    DiagramNode,
    Entity,
    EntityAttribute,
    Relationship,
    SequenceMessage,
    SequenceParticipant,
    diagram_svg_block,
    er_svg_block,
    sequence_svg_block,
)

__all__ = [
    "MermaidError",
    "parse_mermaid",
    "parse_flowchart",
    "parse_sequence",
    "parse_er",
]


class MermaidError(ValueError):
    """Raised for malformed or unsupported Mermaid diagram source."""


def _clean_lines(source: str) -> list[str]:
    """Return non-blank, non-comment lines with trailing semicolons removed."""
    out: list[str] = []
    for raw in source.split("\n"):
        line = raw.strip()
        if not line or line.startswith("%%"):
            continue
        if line.endswith(";"):
            line = line[:-1].rstrip()
        if line:
            out.append(line)
    return out


def _detect_kind(source: str) -> str:
    """Return the Mermaid diagram kind from the first meaningful token."""
    lines = _clean_lines(source)
    if not lines:
        raise MermaidError("empty Mermaid source")
    head = lines[0]
    first = head.split()[0] if head.split() else head
    lowered = first.lower()
    if lowered in ("flowchart", "graph"):
        return "flowchart"
    if first == "sequenceDiagram":
        return "sequence"
    if first == "erDiagram":
        return "er"
    raise MermaidError(f"unsupported Mermaid diagram kind: {first!r}")


def parse_mermaid(source: str):
    """Parse Mermaid source into a diagram SvgBlock, auto-detecting its kind."""
    kind = _detect_kind(source)
    if kind == "flowchart":
        return parse_flowchart(source)
    if kind == "sequence":
        return parse_sequence(source)
    return parse_er(source)


# ======================================================================
# Flowchart / graph
# ======================================================================

_FLOW_DIRECTIONS = {
    "TD": "down",
    "TB": "down",
    "BT": "down",
    "LR": "right",
    "RL": "right",
}
_FLOW_SKIP = (
    "subgraph",
    "end",
    "direction",
    "classdef",
    "class",
    "style",
    "click",
    "linkstyle",
)
_FLOW_ID_RE = re.compile(r"^([A-Za-z0-9_]+)(.*)$", re.DOTALL)
_FLOW_EDGE_RE = re.compile(r"\s*(-\.->|-->|-\.-|---)\s*(?:\|([^|]*)\|)?\s*")
_FLOW_SHAPES = (
    ("[(", ")]", "store"),
    ("([", "])", "start_end"),
    ("[", "]", "box"),
    ("(", ")", "rounded"),
    ("{", "}", "decision"),
)


def _unquote(label: str) -> str:
    """Strip a single pair of surrounding double quotes from a label."""
    label = label.strip()
    if len(label) >= 2 and label[0] == '"' and label[-1] == '"':
        return label[1:-1]
    return label


def _split_flow_node(token: str) -> tuple[str, str | None, str | None]:
    """Parse a flowchart node token into (id, label_or_None, shape_or_None)."""
    token = token.strip()
    match = _FLOW_ID_RE.match(token)
    if match is None:
        raise MermaidError(f"invalid flowchart node: {token!r}")
    node_id, rest = match.group(1), match.group(2).strip()
    if not rest:
        return node_id, None, None
    for open_tok, close_tok, shape in _FLOW_SHAPES:
        if (
            rest.startswith(open_tok)
            and rest.endswith(close_tok)
            and len(rest) >= len(open_tok) + len(close_tok)
        ):
            label = rest[len(open_tok) : len(rest) - len(close_tok)]
            return node_id, _unquote(label), shape
    raise MermaidError(f"invalid flowchart node shape: {token!r}")


def parse_flowchart(source: str):
    """Parse a Mermaid flowchart/graph into a flowchart diagram SvgBlock."""
    lines = _clean_lines(source)
    if not lines:
        raise MermaidError("empty flowchart source")
    header = lines[0].split()
    direction = "down"
    if len(header) >= 2:
        direction = _FLOW_DIRECTIONS.get(header[1].upper())
        if direction is None:
            raise MermaidError(f"invalid flowchart direction: {lines[0]!r}")

    nodes: dict[str, DiagramNode] = {}
    order: list[str] = []
    edges: list[DiagramEdge] = []

    def register(token: str) -> str:
        node_id, label, shape = _split_flow_node(token)
        if node_id in nodes:
            node = nodes[node_id]
            if label is not None:
                node.label = label
            if shape is not None:
                node.shape = shape
        else:
            nodes[node_id] = DiagramNode(
                id=node_id,
                label=label if label is not None else node_id,
                shape=shape or "box",
            )
            order.append(node_id)
        return node_id

    for line in lines[1:]:
        first = line.split()[0].lower() if line.split() else ""
        if first in _FLOW_SKIP:
            continue
        matches = list(_FLOW_EDGE_RE.finditer(line))
        if not matches:
            register(line)
            continue
        parts: list[str] = []
        ops: list[tuple[str, str | None]] = []
        prev = 0
        for match in matches:
            parts.append(line[prev : match.start()])
            style = "dashed" if match.group(1) in ("-.->", "-.-") else "solid"
            label = match.group(2).strip() if match.group(2) else None
            ops.append((style, label))
            prev = match.end()
        parts.append(line[prev:])
        ids = [register(part) for part in parts]
        for i, (style, label) in enumerate(ops):
            edges.append(
                DiagramEdge(src=ids[i], dst=ids[i + 1], label=label, style=style)
            )

    node_list = [nodes[nid] for nid in order]
    if not node_list:
        raise MermaidError("flowchart declares no nodes or edges")
    return diagram_svg_block(node_list, edges, direction=direction)


# ======================================================================
# Sequence diagrams
# ======================================================================

_SEQ_PART_RE = re.compile(r"^(?:participant|actor)\s+(\w+)(?:\s+as\s+(.+))?$")
_SEQ_MSG_RE = re.compile(
    r"^(\w+)\s*(-->>|->>|--\)|-\)|-->|->)\s*([+-]?)\s*(\w+)\s*(?::\s*(.*))?$"
)
_SEQ_ACTIVATE_RE = re.compile(r"^(activate|deactivate)\s+(\w+)$")
_SEQ_STYLES = {
    "->>": "sync",
    "-->>": "return",
    "-)": "async",
    "--)": "async",
    "->": "sync",
    "-->": "return",
}
_SEQ_SKIP = (
    "note",
    "loop",
    "alt",
    "opt",
    "par",
    "else",
    "end",
    "rect",
    "autonumber",
    "critical",
    "break",
)


def parse_sequence(source: str):
    """Parse a Mermaid sequenceDiagram into a sequence diagram SvgBlock."""
    lines = _clean_lines(source)
    if not lines or lines[0] != "sequenceDiagram":
        raise MermaidError("sequence source must start with 'sequenceDiagram'")

    participants: dict[str, SequenceParticipant] = {}
    order: list[str] = []
    messages: list[SequenceMessage] = []
    pending_activate: set[str] = set()

    def ensure(pid: str, label: str | None = None) -> None:
        if pid not in participants:
            participants[pid] = SequenceParticipant(id=pid, label=label or pid)
            order.append(pid)
        elif label:
            participants[pid].label = label

    for line in lines[1:]:
        first = line.split()[0].lower() if line.split() else ""
        pm = _SEQ_PART_RE.match(line)
        if pm:
            ensure(pm.group(1), pm.group(2).strip() if pm.group(2) else None)
            continue
        am = _SEQ_ACTIVATE_RE.match(line)
        if am:
            keyword, target = am.group(1), am.group(2)
            ensure(target)
            if keyword == "activate":
                if messages and messages[-1].dst == target:
                    messages[-1].activate = True
                else:
                    pending_activate.add(target)
            continue
        if first in _SEQ_SKIP:
            continue
        mm = _SEQ_MSG_RE.match(line)
        if mm is None:
            raise MermaidError(f"invalid sequence line: {line!r}")
        src, arrow, activation, dst, label = mm.groups()
        style = _SEQ_STYLES[arrow]
        ensure(src)
        ensure(dst)
        activate = activation == "+" or dst in pending_activate
        pending_activate.discard(dst)
        messages.append(
            SequenceMessage(
                src=src,
                dst=dst,
                label=label.strip() if label else "",
                style=style,
                activate=activate,
            )
        )

    part_list = [participants[pid] for pid in order]
    if not part_list:
        raise MermaidError("sequence diagram declares no participants")
    return sequence_svg_block(part_list, messages)


# ======================================================================
# Entity-relationship diagrams
# ======================================================================

_ER_ENTITY_OPEN_RE = re.compile(r"^(\w+)\s*\{$")
_ER_REL_RE = re.compile(r"^(\w+)\s+(\S+)\s+(\w+)\s*(?::\s*(.*))?$")
_ER_CONN_RE = re.compile(r"^(..)(--|\.\.)(..)$")
_ER_ATTR_KEYS = ("PK", "FK")
_ER_CARDINALITY = {
    "||": "1",
    "|o": "0..1",
    "o|": "0..1",
    "}o": "0..*",
    "o{": "0..*",
    "}|": "1..*",
    "|{": "1..*",
}


def _parse_er_attr(line: str) -> EntityAttribute:
    """Parse an ER attribute row 'type name [key] [comment]'."""
    tokens = line.split()
    if len(tokens) < 2:
        raise MermaidError(f"invalid ER attribute: {line!r}")
    attr_type, name = tokens[0], tokens[1]
    key = None
    if len(tokens) >= 3 and tokens[2] in _ER_ATTR_KEYS:
        key = tokens[2]
    return EntityAttribute(name=name, key=key, type=attr_type)


def parse_er(source: str):
    """Parse a Mermaid erDiagram into an entity-relationship SvgBlock."""
    lines = _clean_lines(source)
    if not lines or lines[0] != "erDiagram":
        raise MermaidError("ER source must start with 'erDiagram'")

    entities: dict[str, Entity] = {}
    order: list[str] = []
    relationships: list[Relationship] = []

    def ensure(eid: str) -> Entity:
        if eid not in entities:
            entities[eid] = Entity(id=eid, name=eid)
            order.append(eid)
        return entities[eid]

    i = 1
    while i < len(lines):
        line = lines[i]
        open_match = _ER_ENTITY_OPEN_RE.match(line)
        if open_match:
            eid = open_match.group(1)
            entity = ensure(eid)
            attrs = list(entity.attributes)
            i += 1
            while i < len(lines) and lines[i] != "}":
                attrs.append(_parse_er_attr(lines[i]))
                i += 1
            if i >= len(lines):
                raise MermaidError(f"unterminated ER entity block: {eid!r}")
            entity.attributes = tuple(attrs)
            i += 1
            continue
        rel_match = _ER_REL_RE.match(line)
        if rel_match:
            left, conn, right, label = rel_match.groups()
            conn_match = _ER_CONN_RE.match(conn)
            if conn_match is None:
                raise MermaidError(f"invalid ER relationship: {line!r}")
            left_card, _mid, right_card = conn_match.groups()
            if left_card not in _ER_CARDINALITY or right_card not in _ER_CARDINALITY:
                raise MermaidError(f"invalid ER cardinality: {line!r}")
            ensure(left)
            ensure(right)
            relationships.append(
                Relationship(
                    src=left,
                    dst=right,
                    label=label.strip() if label else None,
                    src_card=_ER_CARDINALITY[left_card],
                    dst_card=_ER_CARDINALITY[right_card],
                )
            )
            i += 1
            continue
        if re.fullmatch(r"\w+", line):
            ensure(line)
            i += 1
            continue
        raise MermaidError(f"invalid ER line: {line!r}")

    entity_list = [entities[eid] for eid in order]
    if not entity_list:
        raise MermaidError("ER diagram declares no entities")
    return er_svg_block(entity_list, relationships)
