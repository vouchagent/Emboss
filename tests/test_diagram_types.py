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
    GanttMilestone,
    GanttTask,
    Relationship,
    RoadmapBar,
    RoadmapMilestone,
    RoadmapWorkstream,
    SequenceMessage,
    SequenceParticipant,
    architecture_alt_text,
    architecture_svg_block,
    er_alt_text,
    er_svg_block,
    gantt_alt_text,
    gantt_svg_block,
    layout_org_chart,
    org_chart_alt_text,
    org_chart_svg_block,
    parse_spec_json,
    render_architecture_svg,
    render_er_svg,
    render_gantt_svg,
    render_org_chart_svg,
    render_roadmap_svg,
    render_sequence_svg,
    roadmap_alt_text,
    roadmap_svg_block,
    sequence_alt_text,
    sequence_svg_block,
    spec_prompt,
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


class TestStatusColoring:
    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError, match="status"):
            ArchNode("a", "A", status="unknown")

    def test_no_legend_without_status(self):
        svg = render_architecture_svg([{"id": "a", "label": "A", "service": "compute"}])
        assert ">ok<" not in svg
        assert 'rx="2"' not in svg  # legend swatch marker

    def test_legend_only_lists_statuses_in_use(self):
        nodes = [
            {"id": "a", "label": "A", "status": "ok"},
            {"id": "b", "label": "B", "status": "critical"},
        ]
        svg = render_architecture_svg(nodes)
        assert ">ok<" in svg
        assert ">critical<" in svg
        assert ">warning<" not in svg
        assert ">planned<" not in svg
        assert ">retired<" not in svg
        parse_svg(svg)

    def test_legend_order_independent_of_node_order(self):
        forward = render_architecture_svg(
            [
                {"id": "a", "label": "A", "status": "critical"},
                {"id": "b", "label": "B", "status": "ok"},
            ]
        )
        reversed_ = render_architecture_svg(
            [
                {"id": "b", "label": "B", "status": "ok"},
                {"id": "a", "label": "A", "status": "critical"},
            ]
        )
        assert forward.index(">ok<") < forward.index(">critical<")
        assert reversed_.index(">ok<") < reversed_.index(">critical<")

    def test_status_badge_drawn_per_node(self):
        svg = render_architecture_svg(
            [
                {"id": "a", "label": "A", "status": "ok"},
                {"id": "b", "label": "B"},
            ]
        )
        assert svg.count('stroke="#ffffff" stroke-width="1.5"') == 1

    def test_render_is_deterministic(self):
        nodes = [{"id": "a", "label": "A", "status": "ok"}]
        assert render_architecture_svg(nodes) == render_architecture_svg(nodes)

    def test_document_end_to_end(self):
        doc = Document(title="Landscape")
        doc.architecture_diagram(
            [
                {"id": "a", "label": "CRM", "status": "ok"},
                {"id": "b", "label": "Legacy", "status": "retired"},
            ],
            caption="Landscape",
        )
        data = doc.render()
        assert data.startswith(b"%PDF-")


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
# Roadmap / timeline diagrams
# ----------------------------------------------------------------------


class TestRoadmap:
    PERIODS = ["Q1", "Q2", "Q3", "Q4"]
    WORKSTREAMS = [
        {
            "name": "Platform",
            "bars": [
                {"label": "Migration", "start": "Q1", "end": "Q2", "status": "ok"}
            ],
        },
        {
            "name": "Data",
            "bars": [
                {"label": "Warehouse", "start": "Q2", "end": "Q4", "status": "planned"}
            ],
        },
    ]
    MILESTONES = [
        {"label": "Launch", "at": "Q3"},
        {"label": "GA", "at": "Q4", "workstream": "Data"},
    ]

    def test_renders_valid_svg(self):
        svg = render_roadmap_svg(self.PERIODS, self.WORKSTREAMS, self.MILESTONES)
        parse_svg(svg)
        assert ">Q1<" in svg
        assert ">Platform<" in svg
        assert ">Launch<" in svg

    def test_status_legend_present_and_scoped(self):
        svg = render_roadmap_svg(self.PERIODS, self.WORKSTREAMS)
        assert ">ok<" in svg
        assert ">planned<" in svg
        assert ">critical<" not in svg

    def test_no_legend_without_status(self):
        workstreams = [
            {"name": "A", "bars": [{"label": "X", "start": "Q1", "end": "Q2"}]}
        ]
        svg = render_roadmap_svg(self.PERIODS, workstreams)
        assert ">ok<" not in svg

    def test_unknown_bar_period_rejected(self):
        with pytest.raises(ValueError, match="unknown period"):
            render_roadmap_svg(
                ["Q1"],
                [{"name": "A", "bars": [{"label": "X", "start": "Q1", "end": "Q9"}]}],
            )

    def test_bar_end_before_start_rejected(self):
        with pytest.raises(ValueError, match="ends before it starts"):
            render_roadmap_svg(
                ["Q1", "Q2"],
                [{"name": "A", "bars": [{"label": "X", "start": "Q2", "end": "Q1"}]}],
            )

    def test_duplicate_period_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            render_roadmap_svg(["Q1", "Q1"], [{"name": "A", "bars": []}])

    def test_empty_periods_rejected(self):
        with pytest.raises(ValueError, match="at least one period"):
            render_roadmap_svg([], [{"name": "A", "bars": []}])

    def test_empty_workstreams_rejected(self):
        with pytest.raises(ValueError, match="at least one workstream"):
            render_roadmap_svg(["Q1"], [])

    def test_duplicate_workstream_name_rejected(self):
        with pytest.raises(ValueError, match="duplicate roadmap workstream"):
            render_roadmap_svg(
                ["Q1"], [{"name": "A", "bars": []}, {"name": "A", "bars": []}]
            )

    def test_unknown_milestone_period_rejected(self):
        with pytest.raises(ValueError, match="unknown period"):
            render_roadmap_svg(
                ["Q1"], [{"name": "A", "bars": []}], [{"label": "M", "at": "Q9"}]
            )

    def test_unknown_milestone_workstream_rejected(self):
        with pytest.raises(ValueError, match="unknown workstream"):
            render_roadmap_svg(
                ["Q1"],
                [{"name": "A", "bars": []}],
                [{"label": "M", "at": "Q1", "workstream": "Ghost"}],
            )

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError, match="status"):
            RoadmapBar(label="X", start="Q1", end="Q1", status="nope")

    def test_accepts_dataclasses(self):
        block = roadmap_svg_block(
            self.PERIODS,
            [RoadmapWorkstream("A", (RoadmapBar("X", "Q1", "Q2"),))],
            [RoadmapMilestone("M", "Q3")],
        )
        assert isinstance(block, SvgBlock)

    def test_alt_text(self):
        text = roadmap_alt_text(self.PERIODS, self.WORKSTREAMS, self.MILESTONES)
        assert text.startswith(
            "Roadmap: 4 periods, 2 workstreams, 2 bars, 2 milestones"
        )

    def test_render_is_deterministic(self):
        first = render_roadmap_svg(self.PERIODS, self.WORKSTREAMS, self.MILESTONES)
        second = render_roadmap_svg(self.PERIODS, self.WORKSTREAMS, self.MILESTONES)
        assert first == second

    def test_document_end_to_end(self):
        doc = Document(title="Roadmap")
        doc.roadmap(self.PERIODS, self.WORKSTREAMS, self.MILESTONES, caption="FY26")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"Roadmap: 4 periods" in data
        assert b"/Figure" in data

    def test_full_render_deterministic(self):
        def build():
            doc = Document(title="Roadmap")
            doc.roadmap(self.PERIODS, self.WORKSTREAMS, self.MILESTONES)
            return doc.render()

        assert build() == build()

    def test_pydantic_spec_parses(self):
        pytest.importorskip("pydantic")
        doc = parse_spec_json(
            json.dumps(
                {
                    "title": "T",
                    "content": [
                        {
                            "type": "roadmap",
                            "periods": self.PERIODS,
                            "workstreams": self.WORKSTREAMS,
                            "milestones": self.MILESTONES,
                        }
                    ],
                }
            ),
            strict=True,
        )
        assert isinstance(doc.content[0], SvgBlock)

    def test_pydantic_rejects_duplicate_periods(self):
        pytest.importorskip("pydantic")
        with pytest.raises(Exception):
            parse_spec_json(
                json.dumps(
                    {
                        "title": "T",
                        "content": [
                            {
                                "type": "roadmap",
                                "periods": ["Q1", "Q1"],
                                "workstreams": [{"name": "A"}],
                            }
                        ],
                    }
                ),
                strict=True,
            )

    def test_spec_prompt_teaches_roadmap(self):
        prompt = spec_prompt()
        assert '"type": "roadmap"' in prompt


# ----------------------------------------------------------------------
# Org charts
# ----------------------------------------------------------------------


class TestOrgChart:
    NODES = [
        {"id": "ceo", "label": "CEO"},
        {"id": "cto", "label": "CTO"},
        {"id": "cfo", "label": "CFO"},
        {"id": "eng1", "label": "Eng Lead 1"},
        {"id": "eng2", "label": "Eng Lead 2"},
    ]
    EDGES = [("ceo", "cto"), ("ceo", "cfo"), ("cto", "eng1"), ("cto", "eng2")]

    def test_parent_centered_between_children_extremes(self):
        layout = layout_org_chart(self.NODES, self.EDGES)
        ceo = layout.by_id["ceo"]
        cto, cfo = layout.by_id["cto"], layout.by_id["cfo"]
        assert (
            min(cto.center_x, cfo.center_x)
            <= ceo.center_x
            <= max(cto.center_x, cfo.center_x)
        )

    def test_siblings_do_not_overlap(self):
        layout = layout_org_chart(self.NODES, self.EDGES)
        eng1, eng2 = layout.by_id["eng1"], layout.by_id["eng2"]
        assert eng1.x + eng1.width <= eng2.x or eng2.x + eng2.width <= eng1.x

    def test_layers_increase_from_parent_to_child(self):
        layout = layout_org_chart(self.NODES, self.EDGES)
        ceo, cto, eng1 = layout.by_id["ceo"], layout.by_id["cto"], layout.by_id["eng1"]
        assert ceo.layer < cto.layer < eng1.layer

    def test_forest_of_multiple_roots_allowed(self):
        layout = layout_org_chart(
            [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], []
        )
        a, b = layout.by_id["a"], layout.by_id["b"]
        assert a.x != b.x

    def test_direction_right_also_supported(self):
        svg = render_org_chart_svg(self.NODES, self.EDGES, direction="right")
        parse_svg(svg)

    def test_two_parents_rejected(self):
        with pytest.raises(ValueError, match="more than one parent"):
            layout_org_chart(
                [
                    {"id": "a", "label": "A"},
                    {"id": "b", "label": "B"},
                    {"id": "c", "label": "C"},
                ],
                [("a", "c"), ("b", "c")],
            )

    def test_self_parent_rejected(self):
        with pytest.raises(ValueError, match="own parent"):
            layout_org_chart([{"id": "a", "label": "A"}], [("a", "a")])

    def test_cycle_rejected(self):
        with pytest.raises(ValueError, match="cycle"):
            layout_org_chart(
                [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                [("a", "b"), ("b", "a")],
            )

    def test_renders_valid_svg(self):
        svg = render_org_chart_svg(self.NODES, self.EDGES)
        parse_svg(svg)
        assert ">CEO<" in svg

    def test_render_is_deterministic(self):
        first = render_org_chart_svg(self.NODES, self.EDGES)
        second = render_org_chart_svg(self.NODES, self.EDGES)
        assert first == second

    def test_alt_text(self):
        text = org_chart_alt_text(self.NODES, self.EDGES)
        assert text.startswith("Org chart: 5 nodes")
        assert "1 root" in text

    def test_accepts_dataclasses(self):
        from emboss import DiagramEdge, DiagramNode

        block = org_chart_svg_block(
            [DiagramNode("a", "A"), DiagramNode("b", "B")],
            [DiagramEdge("a", "b")],
        )
        assert isinstance(block, SvgBlock)

    def test_document_end_to_end(self):
        doc = Document(title="Org")
        doc.org_chart(self.NODES, self.EDGES, caption="Leadership")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"Org chart: 5 nodes" in data
        assert b"/Figure" in data

    def test_full_render_deterministic(self):
        def build():
            doc = Document(title="Org")
            doc.org_chart(self.NODES, self.EDGES)
            return doc.render()

        assert build() == build()

    def test_pydantic_spec_parses(self):
        pytest.importorskip("pydantic")
        doc = parse_spec_json(
            json.dumps(
                {
                    "title": "T",
                    "content": [
                        {
                            "type": "org_chart",
                            "nodes": self.NODES,
                            "edges": [{"src": s, "dst": d} for s, d in self.EDGES],
                        }
                    ],
                }
            ),
            strict=True,
        )
        assert isinstance(doc.content[0], SvgBlock)

    def test_pydantic_path_rejects_two_parents_at_render(self):
        pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "T",
                "content": [
                    {
                        "type": "org_chart",
                        "nodes": [
                            {"id": "a", "label": "A"},
                            {"id": "b", "label": "B"},
                            {"id": "c", "label": "C"},
                        ],
                        "edges": [{"src": "a", "dst": "c"}, {"src": "b", "dst": "c"}],
                    }
                ],
            }
        )
        with pytest.raises(ValueError, match="more than one parent"):
            spec.to_document().render()

    def test_spec_prompt_teaches_org_chart(self):
        prompt = spec_prompt()
        assert '"type": "org_chart"' in prompt


# ----------------------------------------------------------------------
# Gantt charts
# ----------------------------------------------------------------------


class TestGantt:
    TASKS = [
        {
            "name": "Design",
            "start": "2026-01-01",
            "end": "2026-01-15",
            "progress": 1.0,
            "status": "ok",
        },
        {
            "name": "Build",
            "start": "2026-01-10",
            "end": "2026-02-15",
            "progress": 0.4,
            "status": "planned",
            "dependencies": ["Design"],
        },
    ]
    MILESTONES = [{"label": "Kickoff", "at": "2026-01-01"}]

    def test_renders_valid_svg(self):
        svg = render_gantt_svg(self.TASKS, self.MILESTONES)
        parse_svg(svg)
        assert ">Design<" in svg
        assert ">Build<" in svg
        assert ">Kickoff<" in svg

    def test_status_legend_present_and_scoped(self):
        svg = render_gantt_svg(self.TASKS)
        assert ">ok<" in svg
        assert ">planned<" in svg
        assert ">critical<" not in svg

    def test_no_legend_without_status(self):
        tasks = [{"name": "A", "start": "2026-01-01", "end": "2026-01-02"}]
        svg = render_gantt_svg(tasks)
        assert ">ok<" not in svg

    def test_invalid_date_format_rejected(self):
        with pytest.raises(ValueError, match="invalid 'start' date"):
            GanttTask(name="X", start="not-a-date", end="2026-01-01")

    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError, match="ends before it starts"):
            GanttTask(name="X", start="2026-02-01", end="2026-01-01")

    def test_progress_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="progress must be between"):
            GanttTask(name="X", start="2026-01-01", end="2026-01-02", progress=1.5)

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError, match="status"):
            GanttTask(name="X", start="2026-01-01", end="2026-01-02", status="nope")

    def test_empty_tasks_rejected(self):
        with pytest.raises(ValueError, match="at least one task"):
            render_gantt_svg([])

    def test_duplicate_task_name_rejected(self):
        with pytest.raises(ValueError, match="duplicate gantt task name"):
            render_gantt_svg(
                [
                    {"name": "A", "start": "2026-01-01", "end": "2026-01-02"},
                    {"name": "A", "start": "2026-01-01", "end": "2026-01-02"},
                ]
            )

    def test_self_dependency_rejected(self):
        with pytest.raises(ValueError, match="cannot depend on itself"):
            render_gantt_svg(
                [
                    {
                        "name": "A",
                        "start": "2026-01-01",
                        "end": "2026-01-02",
                        "dependencies": ["A"],
                    }
                ]
            )

    def test_unknown_dependency_rejected(self):
        with pytest.raises(ValueError, match="unknown task"):
            render_gantt_svg(
                [
                    {
                        "name": "A",
                        "start": "2026-01-01",
                        "end": "2026-01-02",
                        "dependencies": ["Ghost"],
                    }
                ]
            )

    def test_single_day_span_does_not_divide_by_zero(self):
        svg = render_gantt_svg(
            [{"name": "A", "start": "2026-01-01", "end": "2026-01-01"}]
        )
        parse_svg(svg)

    def test_accepts_dataclasses(self):
        block = gantt_svg_block(
            [GanttTask("A", "2026-01-01", "2026-01-02")],
            [GanttMilestone("M", "2026-01-01")],
        )
        assert isinstance(block, SvgBlock)

    def test_alt_text(self):
        text = gantt_alt_text(self.TASKS, self.MILESTONES)
        assert text.startswith("Gantt chart: 2 tasks, 1 milestone")

    def test_render_is_deterministic(self):
        first = render_gantt_svg(self.TASKS, self.MILESTONES)
        second = render_gantt_svg(self.TASKS, self.MILESTONES)
        assert first == second

    def test_document_end_to_end(self):
        doc = Document(title="Gantt")
        doc.gantt(self.TASKS, self.MILESTONES, caption="Q1 plan")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"Gantt chart: 2 tasks" in data
        assert b"/Figure" in data

    def test_full_render_deterministic(self):
        def build():
            doc = Document(title="Gantt")
            doc.gantt(self.TASKS, self.MILESTONES)
            return doc.render()

        assert build() == build()

    def test_pydantic_spec_parses(self):
        pytest.importorskip("pydantic")
        doc = parse_spec_json(
            json.dumps(
                {
                    "title": "T",
                    "content": [
                        {
                            "type": "gantt",
                            "tasks": self.TASKS,
                            "milestones": self.MILESTONES,
                        }
                    ],
                }
            ),
            strict=True,
        )
        assert isinstance(doc.content[0], SvgBlock)

    def test_pydantic_rejects_invalid_date(self):
        pytest.importorskip("pydantic")
        with pytest.raises(Exception):
            parse_spec_json(
                json.dumps(
                    {
                        "title": "T",
                        "content": [
                            {
                                "type": "gantt",
                                "tasks": [
                                    {"name": "A", "start": "nope", "end": "2026-01-01"}
                                ],
                            }
                        ],
                    }
                ),
                strict=True,
            )

    def test_pydantic_rejects_unknown_dependency(self):
        pytest.importorskip("pydantic")
        with pytest.raises(Exception):
            parse_spec_json(
                json.dumps(
                    {
                        "title": "T",
                        "content": [
                            {
                                "type": "gantt",
                                "tasks": [
                                    {
                                        "name": "A",
                                        "start": "2026-01-01",
                                        "end": "2026-01-02",
                                        "dependencies": ["Ghost"],
                                    }
                                ],
                            }
                        ],
                    }
                ),
                strict=True,
            )

    def test_spec_prompt_teaches_gantt(self):
        prompt = spec_prompt()
        assert '"type": "gantt"' in prompt


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
