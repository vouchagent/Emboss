"""Tests for architecture, sequence, and entity-relationship diagram types."""

import json
import re
import zlib

import pytest

from emboss import (
    ArchGroup,
    ArchNode,
    Document,
    Entity,
    EntityAttribute,
    Relationship,
    SequenceMessage,
    SequenceParticipant,
    architecture_alt_text,
    architecture_svg_block,
    er_alt_text,
    er_svg_block,
    parse_spec_json,
    render_architecture_svg,
    render_er_svg,
    render_sequence_svg,
    sequence_alt_text,
    sequence_svg_block,
)
from emboss.diagrams import (
    SERVICE_TYPES,
    _layout_architecture,
    _normalize_arch,
)
from emboss.spec import SvgBlock
from emboss.svg import parse_svg


def _content_ops(data: bytes) -> bytes:
    out = b""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        try:
            out += zlib.decompress(raw.strip(b"\r\n"))
        except zlib.error:
            out += raw
    return out


_PATH_RE = re.compile(r'<path d="([^"]*)" fill="([^"]*)"[^>]*/>')


def _paths(svg: str) -> list:
    """Return (d, fill) tuples for every <path> element."""
    return _PATH_RE.findall(svg)


def _filled_arrowheads(svg: str) -> int:
    """Filled arrowheads are edge-colored triangles (M, two L, Z)."""
    return sum(
        1
        for d, fill in _paths(svg)
        if fill == "#4a5866"
        and d.rstrip().endswith("Z")
        and d.count("M ") == 1
        and d.count(" L ") == 2
    )


def _open_arrowheads(svg: str) -> int:
    return sum(
        1
        for d, fill in _paths(svg)
        if fill == "none" and d.count(" L ") == 2 and d.count("M ") == 1
    )


def _dashed_paths(svg: str) -> int:
    return sum(1 for d, fill in _paths(svg) if fill == "none" and d.count("M ") >= 2)


# ----------------------------------------------------------------------
# Architecture diagrams
# ----------------------------------------------------------------------


class TestArchitecture:
    NODES = [
        {"id": "u", "label": "User", "service": "user"},
        {"id": "cdn", "label": "CDN", "service": "cdn"},
        {"id": "api", "label": "API", "service": "compute", "group": "app"},
        {"id": "db", "label": "Postgres", "service": "database", "group": "app"},
        {"id": "q", "label": "Jobs", "service": "queue", "group": "app"},
    ]
    GROUPS = [
        {"id": "app", "label": "App Tier", "node_ids": ["api", "db", "q"]},
    ]
    EDGES = [
        ("u", "cdn"),
        ("u", "api", "https"),
        ("api", "db", "sql", "dashed"),
        ("api", "q"),
    ]

    def test_all_service_glyphs_render_valid_svg(self):
        assert len(SERVICE_TYPES) == 12
        for service in SERVICE_TYPES:
            svg = render_architecture_svg(
                [{"id": "n", "label": service.title(), "service": service}]
            )
            image = parse_svg(svg)
            assert image.width > 0 and image.height > 0
            # A glyph is more than the bare label text.
            assert svg.count("<") > 3

    def test_distinct_glyph_primitives_present(self):
        svg = render_architecture_svg(
            [{"id": s, "label": s, "service": s} for s in SERVICE_TYPES]
        )
        assert "<polygon" in svg  # gateway
        assert "<ellipse" in svg  # database / storage / cdn
        assert "<circle" in svg  # user / cdn / loadbalancer
        assert "<rect" in svg  # compute / queue
        parse_svg(svg)

    def test_nested_groups_render_as_nested_rectangles(self):
        nodes = [
            {"id": "lb", "label": "LB", "service": "loadbalancer", "group": "vpc"},
            {"id": "api", "label": "API", "service": "compute", "group": "app"},
            {"id": "db", "label": "DB", "service": "database", "group": "app"},
        ]
        groups = [
            {"id": "app", "label": "App", "node_ids": ["api", "db"]},
            {"id": "vpc", "label": "VPC", "node_ids": ["lb", "app"]},
        ]
        node_list, edges, group_list, parent = _normalize_arch(nodes, [], groups)
        boxes, gboxes, _w, _h = _layout_architecture(
            node_list, group_list, parent, "down"
        )
        outer, inner = gboxes["vpc"], gboxes["app"]

        def encloses(a, b):
            return (
                a["x"] <= b["x"] + 0.01
                and a["y"] <= b["y"] + 0.01
                and a["x"] + a["w"] >= b["x"] + b["w"] - 0.01
                and a["y"] + a["h"] >= b["y"] + b["h"] - 0.01
            )

        assert encloses(outer, inner)  # VPC encloses App
        for member in ("api", "db"):
            box = boxes[member]
            member_rect = {"x": box["x"], "y": box["y"], "w": box["w"], "h": box["h"]}
            assert encloses(inner, member_rect)  # App encloses its nodes

        svg = render_architecture_svg(nodes, [], groups=groups)
        # Two group tint fills => two nested boundary zones.
        assert svg.count('fill="#eef4fb"') + svg.count('fill="#eef8f0"') >= 2

    def test_edges_solid_and_dashed(self):
        svg = render_architecture_svg(self.NODES, self.EDGES, groups=self.GROUPS)
        assert _filled_arrowheads(svg) == len(self.EDGES)
        assert _dashed_paths(svg) >= 1  # the dashed api->db edge

    def test_edge_labels_backed(self):
        svg = render_architecture_svg(self.NODES, self.EDGES, groups=self.GROUPS)
        assert ">https</text>" in svg
        assert 'fill="#ffffff"' in svg  # label backing rect

    def test_image_node_falls_back_to_glyph(self):
        svg = render_architecture_svg(
            [{"id": "n", "label": "N", "service": "compute", "image": "/logo.png"}]
        )
        parse_svg(svg)
        assert "<rect" in svg  # compute glyph still drawn

    def test_unknown_edge_endpoint_rejected(self):
        with pytest.raises(ValueError, match="unknown node id"):
            render_architecture_svg([{"id": "a", "label": "A"}], [("a", "ghost")])

    def test_unknown_group_member_rejected(self):
        with pytest.raises(ValueError, match="unknown id"):
            render_architecture_svg(
                [{"id": "a", "label": "A"}],
                groups=[{"id": "g", "node_ids": ["missing"]}],
            )

    def test_group_containment_cycle_rejected(self):
        with pytest.raises(ValueError, match="cycle"):
            render_architecture_svg(
                [{"id": "a", "label": "A", "group": "g1"}],
                groups=[
                    {"id": "g1", "node_ids": ["a", "g2"]},
                    {"id": "g2", "node_ids": ["g1"]},
                ],
            )

    def test_unknown_service_rejected(self):
        with pytest.raises(ValueError, match="service"):
            ArchNode("a", "A", service="kubernetes")

    def test_alt_text(self):
        text = architecture_alt_text(self.NODES, self.EDGES, self.GROUPS)
        assert text.startswith(
            "Architecture diagram: 5 services, 1 group, 4 connections"
        )

    def test_render_is_deterministic(self):
        first = render_architecture_svg(self.NODES, self.EDGES, groups=self.GROUPS)
        second = render_architecture_svg(self.NODES, self.EDGES, groups=self.GROUPS)
        assert first == second

    def test_accepts_dataclasses(self):
        block = architecture_svg_block(
            [ArchNode("a", "A", "compute"), ArchNode("b", "B", "database")],
            [("a", "b")],
            groups=[ArchGroup("g", "G", ("a", "b"))],
        )
        assert isinstance(block, SvgBlock)

    def test_document_end_to_end(self):
        doc = Document(title="Arch")
        doc.architecture_diagram(
            self.NODES, self.EDGES, groups=self.GROUPS, caption="Topology"
        )
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"Architecture diagram: 5 services" in data  # /Alt
        assert b"/Figure" in data
        assert b"(Topology)" in _content_ops(data) or b"Topology" in _content_ops(data)

    def test_full_render_deterministic(self):
        def build():
            doc = Document(title="Arch")
            doc.architecture_diagram(self.NODES, self.EDGES, groups=self.GROUPS)
            return doc.render()

        assert build() == build()


# ----------------------------------------------------------------------
# Sequence diagrams
# ----------------------------------------------------------------------


class TestSequence:
    PARTS = [
        {"id": "u", "label": "User"},
        {"id": "api", "label": "API"},
        {"id": "db", "label": "Database"},
    ]
    MSGS = [
        {"from": "u", "to": "api", "label": "login", "style": "sync", "activate": True},
        {"from": "api", "to": "db", "label": "query", "style": "async"},
        {"from": "db", "to": "api", "label": "row", "style": "return"},
        {"from": "api", "to": "u", "label": "token", "style": "return"},
    ]

    def test_lifelines_present(self):
        svg = render_sequence_svg(self.PARTS, self.MSGS)
        # One dashed lifeline per participant (vertical dashed multi-segment path).
        vertical = [
            d
            for d, fill in _paths(svg)
            if fill == "none" and d.count("M ") >= 2 and _is_vertical(d)
        ]
        assert len(vertical) == len(self.PARTS)
        parse_svg(svg)

    def test_participant_boxes_and_labels(self):
        svg = render_sequence_svg(self.PARTS, self.MSGS)
        assert svg.count("<rect") >= len(self.PARTS)
        for label in ("User", "API", "Database"):
            assert f">{label}</text>" in svg

    def test_sync_async_return_differ(self):
        parts = [{"id": "a"}, {"id": "b"}]
        sync = render_sequence_svg(parts, [{"src": "a", "dst": "b", "style": "sync"}])
        asyncd = render_sequence_svg(
            parts, [{"src": "a", "dst": "b", "style": "async"}]
        )
        ret = render_sequence_svg(parts, [{"src": "a", "dst": "b", "style": "return"}])

        # sync: filled arrowhead, no open head.
        assert _filled_arrowheads(sync) == 1
        assert _open_arrowheads(sync) == 0
        # async: open arrowhead, no filled head, solid message line.
        assert _filled_arrowheads(asyncd) == 0
        assert _open_arrowheads(asyncd) == 1
        assert _dashed_paths(asyncd) == len(parts)  # only lifelines are dashed
        # return: open arrowhead, dashed message line (one extra dashed path).
        assert _filled_arrowheads(ret) == 0
        assert _open_arrowheads(ret) == 1
        assert _dashed_paths(ret) == len(parts) + 1

    def test_self_message_renders_loop(self):
        parts = [{"id": "a", "label": "A"}]
        empty = render_sequence_svg(parts, [])
        looped = render_sequence_svg(
            parts, [{"src": "a", "dst": "a", "label": "retry"}]
        )
        assert len(_paths(looped)) > len(_paths(empty))
        assert ">retry</text>" in looped
        parse_svg(looped)

    def test_activation_bar_present_only_when_activated(self):
        parts = [{"id": "a"}, {"id": "b"}]
        active = render_sequence_svg(
            parts,
            [
                {"src": "a", "dst": "b", "style": "sync", "activate": True},
                {"src": "b", "dst": "a", "style": "return"},
            ],
        )
        plain = render_sequence_svg(parts, [{"src": "a", "dst": "b", "style": "sync"}])
        assert 'width="8.00"' in active  # activation bar rect
        assert 'width="8.00"' not in plain

    def test_unknown_participant_rejected(self):
        with pytest.raises(ValueError, match="unknown participant"):
            render_sequence_svg([{"id": "a"}], [{"src": "a", "dst": "ghost"}])

    def test_bad_style_rejected(self):
        with pytest.raises(ValueError, match="style"):
            SequenceMessage("a", "b", style="fire-and-forget")

    def test_duplicate_participant_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            render_sequence_svg([{"id": "a"}, {"id": "a"}], [])

    def test_alt_text(self):
        assert sequence_alt_text(self.PARTS, self.MSGS) == (
            "Sequence diagram: 3 participants, 4 messages"
        )

    def test_render_is_deterministic(self):
        assert render_sequence_svg(self.PARTS, self.MSGS) == render_sequence_svg(
            self.PARTS, self.MSGS
        )

    def test_accepts_dataclasses(self):
        block = sequence_svg_block(
            [SequenceParticipant("a", "A"), SequenceParticipant("b", "B")],
            [SequenceMessage("a", "b", "hi", "sync")],
        )
        assert isinstance(block, SvgBlock)

    def test_document_end_to_end(self):
        doc = Document(title="Flow")
        doc.sequence_diagram(self.PARTS, self.MSGS, caption="Login")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"Sequence diagram: 3 participants, 4 messages" in data
        assert b"/Figure" in data


def _is_vertical(d: str) -> bool:
    xs = re.findall(r"[ML] ([\d.]+) [\d.]+", d)
    return len(set(xs)) == 1 if xs else False


# ----------------------------------------------------------------------
# Entity-relationship diagrams
# ----------------------------------------------------------------------


class TestEntityRelationship:
    ENTITIES = [
        {
            "id": "user",
            "name": "User",
            "attributes": [
                {"name": "id", "key": "PK", "type": "int"},
                {"name": "email", "type": "text"},
            ],
        },
        {
            "id": "order",
            "name": "Order",
            "attributes": [
                {"name": "id", "key": "PK", "type": "int"},
                {"name": "user_id", "key": "FK", "type": "int"},
            ],
        },
    ]
    RELS = [
        {
            "from": "user",
            "to": "order",
            "label": "places",
            "from_card": "1",
            "to_card": "N",
        },
    ]

    def test_entity_boxes_and_attribute_rows(self):
        svg = render_er_svg(self.ENTITIES, self.RELS)
        assert svg.count("<rect") >= len(self.ENTITIES) * 2  # box + title bar each
        for name in ("User", "Order", "email", "user_id"):
            assert f">{name}</text>" in svg
        assert ">PK</text>" in svg
        assert ">FK</text>" in svg
        parse_svg(svg)

    def test_cardinality_labels(self):
        svg = render_er_svg(self.ENTITIES, self.RELS)
        assert ">1</text>" in svg
        assert ">N</text>" in svg
        assert ">places</text>" in svg

    def test_pk_underline_drawn(self):
        svg = render_er_svg(
            [{"id": "e", "name": "E", "attributes": [{"name": "pkcol", "key": "PK"}]}]
        )
        assert "<line" in svg  # underline beneath the primary-key name

    def test_relationship_line_present(self):
        svg = render_er_svg(self.ENTITIES, self.RELS)
        # A relationship draws a straight connecting line (single-segment path).
        singles = [
            d for d, fill in _paths(svg) if fill == "none" and d.count("M ") == 1
        ]
        assert singles

    def test_unknown_relationship_entity_rejected(self):
        with pytest.raises(ValueError, match="unknown entity"):
            render_er_svg([{"id": "a", "name": "A"}], [{"src": "a", "dst": "ghost"}])

    def test_bad_key_rejected(self):
        with pytest.raises(ValueError, match="key"):
            EntityAttribute("id", key="UNIQUE")

    def test_duplicate_entity_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            render_er_svg([{"id": "a"}, {"id": "a"}])

    def test_alt_text(self):
        text = er_alt_text(self.ENTITIES, self.RELS)
        assert text.startswith(
            "Entity-relationship diagram: 2 entities, 1 relationship"
        )

    def test_render_is_deterministic(self):
        assert render_er_svg(self.ENTITIES, self.RELS) == render_er_svg(
            self.ENTITIES, self.RELS
        )

    def test_accepts_dataclasses(self):
        block = er_svg_block(
            [
                Entity("u", "User", (EntityAttribute("id", "PK", "int"),)),
                Entity("o", "Order", (EntityAttribute("id", "PK"),)),
            ],
            [Relationship("u", "o", "has", "1", "N")],
        )
        assert isinstance(block, SvgBlock)

    def test_document_end_to_end(self):
        doc = Document(title="Schema")
        doc.er_diagram(self.ENTITIES, self.RELS, caption="Data model")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"Entity-relationship diagram: 2 entities" in data
        assert b"/Figure" in data


# ----------------------------------------------------------------------
# Pydantic spec integration
# ----------------------------------------------------------------------


class TestPydanticSpecs:
    def test_architecture_spec_parses(self):
        pytest.importorskip("pydantic")
        payload = {
            "title": "T",
            "content": [
                {
                    "type": "architecture_diagram",
                    "nodes": [
                        {"id": "a", "label": "A", "service": "compute", "group": "g"},
                        {"id": "b", "label": "B", "service": "database", "group": "g"},
                    ],
                    "groups": [{"id": "g", "label": "Tier", "node_ids": ["a", "b"]}],
                    "edges": [{"src": "a", "dst": "b", "style": "dashed"}],
                    "caption": "C",
                }
            ],
        }
        doc = parse_spec_json(json.dumps(payload), strict=True)
        el = doc.content[0]
        assert isinstance(el, SvgBlock)
        assert el.caption == "C"
        assert "Architecture diagram: 2 services" in el.alt_text

    def test_sequence_spec_parses(self):
        pytest.importorskip("pydantic")
        payload = {
            "title": "T",
            "content": [
                {
                    "type": "sequence_diagram",
                    "participants": [{"id": "a", "label": "A"}, {"id": "b"}],
                    "messages": [
                        {"src": "a", "dst": "b", "label": "go", "style": "async"}
                    ],
                }
            ],
        }
        doc = parse_spec_json(json.dumps(payload), strict=True)
        assert "Sequence diagram: 2 participants, 1 message" in doc.content[0].alt_text

    def test_er_spec_parses(self):
        pytest.importorskip("pydantic")
        payload = {
            "title": "T",
            "content": [
                {
                    "type": "er_diagram",
                    "entities": [
                        {
                            "id": "u",
                            "name": "User",
                            "attributes": [{"name": "id", "key": "PK"}],
                        }
                    ],
                    "relationships": [],
                }
            ],
        }
        doc = parse_spec_json(json.dumps(payload), strict=True)
        assert "Entity-relationship diagram: 1 entity" in doc.content[0].alt_text

    def test_bad_architecture_edge_rejected(self):
        pydantic = pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        payload = {
            "title": "T",
            "content": [
                {
                    "type": "architecture_diagram",
                    "nodes": [{"id": "a", "label": "A"}],
                    "edges": [{"src": "a", "dst": "missing"}],
                }
            ],
        }
        with pytest.raises(pydantic.ValidationError, match="unknown node id"):
            DocumentSpec.model_validate(payload)

    def test_bad_sequence_message_rejected(self):
        pydantic = pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        payload = {
            "title": "T",
            "content": [
                {
                    "type": "sequence_diagram",
                    "participants": [{"id": "a"}],
                    "messages": [{"src": "a", "dst": "ghost"}],
                }
            ],
        }
        with pytest.raises(pydantic.ValidationError, match="unknown participant"):
            DocumentSpec.model_validate(payload)

    def test_manual_path_builds_diagrams(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "emboss.adapters.pydantic_schema", None)
        data = {
            "title": "T",
            "content": [
                {
                    "type": "architecture_diagram",
                    "nodes": [{"id": "a", "label": "A", "service": "compute"}],
                },
                {
                    "type": "sequence_diagram",
                    "participants": [{"id": "a"}],
                    "messages": [],
                },
                {"type": "er_diagram", "entities": [{"id": "e", "name": "E"}]},
            ],
        }
        doc = parse_spec_json(json.dumps(data))
        assert [type(el).__name__ for el in doc.content] == ["SvgBlock"] * 3


class TestSpecPrompt:
    def test_prompt_teaches_new_diagrams(self):
        from emboss import spec_prompt

        prompt = spec_prompt()
        assert '"type": "architecture_diagram"' in prompt
        assert '"type": "sequence_diagram"' in prompt
        assert '"type": "er_diagram"' in prompt
