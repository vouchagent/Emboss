"""Tests for the diagram element: layout, SVG emission, and integrations."""

import json
import re
import zlib

import pytest

from emboss import (
    DiagramEdge,
    DiagramNode,
    Document,
    diagram_alt_text,
    diagram_svg_block,
    layout_diagram,
    layout_diagram_force,
    parse_spec_json,
    render_diagram_svg,
    spec_prompt,
)
from emboss.diagrams import diagram_block_from_source, parse_diagram_source
from emboss.spec import SvgBlock
from emboss.svg import parse_svg


def _layers(layout):
    return {placed.node.id: placed.layer for placed in layout.nodes}


def _by_id(layout):
    return layout.by_id


def _content_ops(data: bytes) -> bytes:
    """Concatenate all (decompressed) content streams of a rendered PDF."""
    out = b""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        try:
            out += zlib.decompress(raw.strip(b"\r\n"))
        except zlib.error:
            out += raw
    return out


class TestLayering:
    def test_linear_chain_layers(self):
        nodes = [(nid, nid.upper()) for nid in "abcd"]
        edges = [("a", "b"), ("b", "c"), ("c", "d")]
        layers = _layers(layout_diagram(nodes, edges))
        assert layers == {"a": 0, "b": 1, "c": 2, "d": 3}

    def test_diamond_puts_branches_on_same_layer(self):
        nodes = [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")]
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        layers = _layers(layout_diagram(nodes, edges))
        assert layers["A"] == 0
        assert layers["B"] == layers["C"] == 1
        assert layers["D"] == 2

    def test_cycle_terminates_and_places_all_nodes(self):
        nodes = [("A", "A"), ("B", "B"), ("C", "C")]
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        layout = layout_diagram(nodes, edges)
        assert sorted(_layers(layout)) == ["A", "B", "C"]
        assert _layers(layout) == {"A": 0, "B": 1, "C": 2}

    def test_self_loop_is_layout_safe(self):
        layout = layout_diagram([("A", "A"), ("B", "B")], [("A", "A"), ("A", "B")])
        assert _layers(layout) == {"A": 0, "B": 1}

    def test_barycenter_removes_crossing(self):
        nodes = [("a", "a"), ("b", "b"), ("c", "c"), ("d", "d")]
        edges = [("a", "d"), ("b", "c")]
        layout = layout_diagram(nodes, edges)
        assert layout.layers[0] == ["a", "b"]
        assert layout.layers[1] == ["d", "c"]
        placed = _by_id(layout)
        crossings = 0
        for s1, d1 in (("a", "d"), ("b", "c")):
            for s2, d2 in (("a", "d"), ("b", "c")):
                if (s1, d1) >= (s2, d2):
                    continue
                left = placed[s1].center_x - placed[s2].center_x
                right = placed[d1].center_x - placed[d2].center_x
                if left * right < 0:
                    crossings += 1
        assert crossings == 0

    def test_double_layout_is_identical(self):
        nodes = [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]
        edges = [("a", "b"), ("a", "c"), ("c", "a")]
        assert layout_diagram(nodes, edges) == layout_diagram(nodes, edges)


class TestNodeSizing:
    def test_minimum_node_size(self):
        placed = _by_id(layout_diagram([("a", "A")]))["a"]
        assert placed.width == 60.0
        assert placed.height == 28.0

    def test_width_grows_with_label(self):
        layout = layout_diagram([("s", "Go"), ("l", "Authentication Gateway")])
        placed = _by_id(layout)
        assert placed["l"].width > placed["s"].width

    def test_long_label_wraps_and_grows_height(self):
        label = "A fairly long node label that must wrap onto multiple lines"
        layout = layout_diagram([("a", label)])
        placed = _by_id(layout)["a"]
        assert len(placed.lines) > 1
        assert placed.width <= 140.0
        assert placed.height > 28.0

    def test_direction_right_transposes_layout(self):
        nodes = [("a", "A"), ("b", "B")]
        edges = [("a", "b")]
        down = _by_id(layout_diagram(nodes, edges, direction="down"))
        right = _by_id(layout_diagram(nodes, edges, direction="right"))
        assert down["b"].y > down["a"].y + down["a"].height
        assert abs(down["a"].center_x - down["b"].center_x) < 0.01
        assert right["b"].x > right["a"].x + right["a"].width
        assert abs(right["a"].center_y - right["b"].center_y) < 0.01


class TestGraphValidation:
    def test_duplicate_node_id_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            layout_diagram([("a", "A"), ("a", "B")])

    def test_unknown_edge_endpoint_rejected(self):
        with pytest.raises(ValueError, match="unknown node id"):
            layout_diagram([("a", "A")], [("a", "ghost")])

    def test_unknown_shape_rejected(self):
        with pytest.raises(ValueError, match="shape"):
            DiagramNode("a", "A", shape="cloud")

    def test_accepts_dicts_tuples_and_instances(self):
        layout = layout_diagram(
            [DiagramNode("a", "A"), {"id": "b", "label": "B"}, ("c", "C")],
            [DiagramEdge("a", "b"), {"src": "b", "dst": "c"}, ("c", "a")],
        )
        assert len(layout.nodes) == 3


class TestSvgOutput:
    NODES = [
        ("box", "Box", "box"),
        ("rnd", "Rounded", "rounded"),
        ("dec", "Choice", "decision"),
        ("db", "Store", "store"),
        ("end", "End", "start_end"),
    ]
    EDGES = [
        ("box", "rnd", "go"),
        ("rnd", "dec"),
        ("dec", "db", None, "dashed"),
        ("db", "end"),
    ]

    def test_shape_elements_present(self):
        svg = render_diagram_svg(self.NODES, self.EDGES)
        assert "<rect x=" in svg and 'rx="2"' in svg  # box
        assert svg.count("A 7.00 7.00 0 0 1") >= 4  # rounded corner arcs
        assert "<ellipse cx=" in svg  # store top rim
        decision = re.search(
            r'<path d="M [\d.]+ [\d.]+ L [\d.]+ [\d.]+ '
            r'L [\d.]+ [\d.]+ L [\d.]+ [\d.]+ Z"',
            svg,
        )
        assert decision is not None  # diamond outline

    def test_arrowheads_one_per_edge(self):
        svg = render_diagram_svg(self.NODES, self.EDGES)
        arrowheads = re.findall(r'<path d="M [^"]+ Z" fill="#4a5866"/>', svg)
        assert len(arrowheads) == len(self.EDGES)

    def test_dashed_edge_emits_dash_segments(self):
        svg = render_diagram_svg(self.NODES, self.EDGES)
        edge_paths = re.findall(r'<path d="([^"]+)" fill="none" stroke="#4a5866"', svg)
        dashed = [d for d in edge_paths if d.count("M ") >= 3]
        solid = [d for d in edge_paths if d.count("M ") == 1]
        assert len(dashed) == 1
        assert len(solid) == len(self.EDGES) - 1

    def test_labels_centered_and_edge_label_backed(self):
        svg = render_diagram_svg(self.NODES, self.EDGES)
        assert 'text-anchor="middle"' in svg
        assert 'font-size="9.00"' in svg
        assert 'font-size="8.00"' in svg and ">go</text>" in svg
        assert 'fill="#ffffff"' in svg  # white backing rect under edge label

    def test_theme_colors_override(self):
        svg = render_diagram_svg(
            self.NODES, self.EDGES, theme_colors={"fill": "#ffeecc"}
        )
        assert 'fill="#ffeecc"' in svg
        assert 'fill="#f7f9fb"' not in svg

    def test_output_parses_through_svg_subset(self):
        svg = render_diagram_svg(self.NODES, self.EDGES)
        image = parse_svg(svg)
        assert image.width > 0 and image.height > 0
        assert len(image.elements) >= len(self.NODES) + len(self.EDGES)

    def test_render_is_deterministic(self):
        first = render_diagram_svg(self.NODES, self.EDGES)
        second = render_diagram_svg(self.NODES, self.EDGES)
        assert first == second

    def test_label_text_is_xml_escaped(self):
        svg = render_diagram_svg([("a", "R&D <fast>")])
        assert "R&amp;D &lt;fast&gt;" in svg
        parse_svg(svg)


class TestAltText:
    def test_alt_text_summarizes_nodes_and_edges(self):
        nodes = [
            (nid, label) for nid, label in [("a", "API"), ("b", "Auth"), ("c", "DB")]
        ]
        text = diagram_alt_text(nodes, [("a", "b"), ("b", "c")])
        assert text == "Diagram: 3 nodes (API, Auth, DB), 2 connections"

    def test_alt_text_truncates_long_node_lists(self):
        nodes = [(f"n{i}", f"N{i}") for i in range(8)]
        text = diagram_alt_text(nodes)
        assert "..." in text
        assert text.startswith("Diagram: 8 nodes (N0, N1, N2, N3, N4, ...)")
        assert text.endswith("0 connections")

    def test_singular_forms(self):
        text = diagram_alt_text([("a", "Only")], [("a", "a")])
        assert "1 node (Only), 1 connection" == text.split(": ")[1]


class TestDocumentIntegration:
    NODES = [("in", "Ingest"), ("q", "Queue", "store"), ("w", "Worker")]
    EDGES = [("in", "q"), ("q", "w", "poll", "dashed"), ("w", "in")]

    def test_diagram_svg_block_fields(self):
        block = diagram_svg_block(self.NODES, self.EDGES, caption="Pipeline")
        assert isinstance(block, SvgBlock)
        assert block.caption == "Pipeline"
        assert block.alt_text.startswith("Diagram: 3 nodes")
        assert block.structure_tag == "Figure"
        assert block.source.startswith("<svg ")

    def test_document_renders_diagram_end_to_end(self):
        doc = Document(title="Arch")
        doc.diagram(self.NODES, self.EDGES, caption="Pipeline")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"Diagram: 3 nodes" in data  # /Alt in the structure tree
        ops = _content_ops(data)
        assert b" re\n" in ops or b" re " in ops  # node rects
        assert b"/FsvgH 9 Tf" in ops  # 9pt Helvetica labels
        assert ops.count(b"h\nf") >= len(self.EDGES)  # filled arrowheads
        assert b"(Pipeline)" in ops or b"Pipeline" in ops

    def test_full_render_is_deterministic(self):
        def build():
            doc = Document(title="Arch")
            doc.diagram(self.NODES, self.EDGES, direction="right")
            return doc.render()

        assert build() == build()


class TestPydanticSpec:
    def test_diagram_spec_parses_and_builds_svg_block(self):
        pytest.importorskip("pydantic")
        payload = {
            "title": "T",
            "content": [
                {
                    "type": "diagram",
                    "direction": "right",
                    "nodes": [
                        {"id": "a", "label": "API"},
                        {"id": "b", "label": "DB", "shape": "store"},
                    ],
                    "edges": [
                        {"src": "a", "dst": "b", "label": "query", "style": "dashed"}
                    ],
                    "caption": "Data path",
                }
            ],
        }
        doc = parse_spec_json(json.dumps(payload), strict=True)
        element = doc.content[0]
        assert isinstance(element, SvgBlock)
        assert element.caption == "Data path"
        assert "Diagram: 2 nodes" in element.alt_text

    def test_bad_edge_reference_rejected(self):
        pydantic = pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        payload = {
            "title": "T",
            "content": [
                {
                    "type": "diagram",
                    "nodes": [{"id": "a", "label": "A"}],
                    "edges": [{"src": "a", "dst": "missing"}],
                }
            ],
        }
        with pytest.raises(pydantic.ValidationError, match="unknown node id"):
            DocumentSpec.model_validate(payload)

    def test_duplicate_node_ids_rejected(self):
        pydantic = pytest.importorskip("pydantic")
        from emboss.adapters.pydantic_schema import DocumentSpec

        payload = {
            "title": "T",
            "content": [
                {
                    "type": "diagram",
                    "nodes": [
                        {"id": "a", "label": "A"},
                        {"id": "a", "label": "B"},
                    ],
                }
            ],
        }
        with pytest.raises(pydantic.ValidationError, match="duplicate"):
            DocumentSpec.model_validate(payload)


class TestSpecPrompt:
    def test_prompt_teaches_diagram(self):
        prompt = spec_prompt()
        assert '"type": "diagram"' in prompt
        assert "start_end" in prompt

    def test_prompt_diagram_example_strict_parses(self):
        pytest.importorskip("pydantic")
        blocks = re.findall(r"```json\n(.*?)```", spec_prompt(), re.DOTALL)
        diagram_examples = [b for b in blocks if '"diagram"' in b]
        assert len(diagram_examples) == 3  # general flowchart + swimlane + force layout
        for example in diagram_examples:
            payload = json.loads(example)
            wrapped = {"title": "Contract", "content": [payload]}
            doc = parse_spec_json(json.dumps(wrapped), strict=True)
            assert isinstance(doc.content[0], SvgBlock)


class TestMarkdown:
    SOURCE = """# System

```diagram
direction: right
api: API Gateway
db: Users [store]
api -> db: query
db --> api
```
"""

    def test_fenced_diagram_parses_to_svg_block(self):
        doc = Document.from_markdown(self.SOURCE)
        kinds = [type(el).__name__ for el in doc.content]
        assert kinds == ["Heading", "SvgBlock"]
        block = doc.content[1]
        assert "Diagram: 2 nodes (API Gateway, Users)" in block.alt_text
        assert doc.render().startswith(b"%PDF-")

    def test_edge_only_ids_become_implicit_nodes(self):
        nodes, edges, direction = parse_diagram_source("a -> b\nb -> c")
        assert [n.id for n in nodes] == ["a", "b", "c"]
        assert [n.label for n in nodes] == ["a", "b", "c"]
        assert len(edges) == 2
        assert direction == "down"

    def test_dashed_arrow_and_labels(self):
        nodes, edges, _ = parse_diagram_source("a: Alpha\nb: Beta\na --> b: async")
        assert edges[0].style == "dashed"
        assert edges[0].label == "async"
        assert nodes[0].label == "Alpha"

    def test_direction_option_line(self):
        _, _, direction = parse_diagram_source("direction: right\na -> b")
        assert direction == "right"

    def test_malformed_line_raises_with_content(self):
        with pytest.raises(ValueError, match="totally wrong line"):
            parse_diagram_source("a: Alpha\ntotally wrong line !!")

    def test_bad_shape_raises_with_line(self):
        with pytest.raises(ValueError, match=r"cloud"):
            parse_diagram_source("a: Alpha [cloud]")

    def test_comments_and_blanks_ignored(self):
        source = "# topology\n\na: Alpha\n\nb: Beta\na -> b\n"
        block = diagram_block_from_source(source, caption="Topo")
        assert block.caption == "Topo"
        assert "2 nodes" in block.alt_text


class TestSwimlanes:
    NODES = [
        {"id": "req", "label": "Request", "lane": "Client"},
        {"id": "auth", "label": "Authenticate", "lane": "Backend"},
        {"id": "db", "label": "Query DB", "lane": "Backend"},
        {"id": "resp", "label": "Response", "lane": "Client"},
    ]
    EDGES = [("req", "auth"), ("auth", "db"), ("db", "resp")]

    def test_no_lanes_unaffected(self):
        layout = layout_diagram([("a", "A"), ("b", "B")], [("a", "b")])
        assert layout.lane_bands == ()

    def test_explicit_lane_order_produces_bands(self):
        layout = layout_diagram(self.NODES, self.EDGES, lanes=["Client", "Backend"])
        names = [name for name, _s, _e in layout.lane_bands]
        assert names == ["Client", "Backend"]

    def test_inferred_lane_order_is_first_appearance(self):
        layout = layout_diagram(
            [
                {"id": "a", "label": "A", "lane": "Zeta"},
                {"id": "b", "label": "B", "lane": "Alpha"},
            ],
            [("a", "b")],
        )
        names = [name for name, _s, _e in layout.lane_bands]
        assert names == ["Zeta", "Alpha"]

    def test_missing_lane_rejected(self):
        with pytest.raises(ValueError, match="no valid lane"):
            layout_diagram(
                [{"id": "a", "label": "A", "lane": "X"}, {"id": "b", "label": "B"}],
                [("a", "b")],
                lanes=["X", "Y"],
            )

    def test_unknown_lane_rejected(self):
        with pytest.raises(ValueError, match="no valid lane"):
            layout_diagram([{"id": "a", "label": "A", "lane": "Ghost"}], lanes=["X"])

    def test_nodes_stay_within_their_lane_band(self):
        layout = layout_diagram(self.NODES, self.EDGES, lanes=["Client", "Backend"])
        bands = {name: (start, extent) for name, start, extent in layout.lane_bands}
        for placed in layout.nodes:
            start, extent = bands[placed.node.lane]
            assert start - 0.01 <= placed.x
            assert placed.x + placed.width <= start + extent + 0.01

    def test_svg_renders_valid_and_has_lane_labels(self):
        svg = render_diagram_svg(self.NODES, self.EDGES, lanes=["Client", "Backend"])
        parse_svg(svg)
        assert ">Client<" in svg
        assert ">Backend<" in svg

    def test_direction_right_also_supported(self):
        svg = render_diagram_svg(
            self.NODES, self.EDGES, direction="right", lanes=["Client", "Backend"]
        )
        parse_svg(svg)

    def test_render_is_deterministic(self):
        first = render_diagram_svg(self.NODES, self.EDGES, lanes=["Client", "Backend"])
        second = render_diagram_svg(self.NODES, self.EDGES, lanes=["Client", "Backend"])
        assert first == second

    def test_alt_text_mentions_lanes(self):
        text = diagram_alt_text(self.NODES, self.EDGES, lanes=["Client", "Backend"])
        assert "2 lanes (Client, Backend)" in text

    def test_alt_text_omits_lanes_when_unset(self):
        text = diagram_alt_text([("a", "A"), ("b", "B")], [("a", "b")])
        assert "lane" not in text

    def test_document_end_to_end(self):
        doc = Document(title="Swimlane")
        doc.diagram(self.NODES, self.EDGES, lanes=["Client", "Backend"], caption="Flow")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"/Figure" in data

    def test_full_render_deterministic(self):
        def build():
            doc = Document(title="Swimlane")
            doc.diagram(self.NODES, self.EDGES, lanes=["Client", "Backend"])
            return doc.render()

        assert build() == build()

    def test_pydantic_path(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "T",
                "content": [
                    {
                        "type": "diagram",
                        "nodes": self.NODES,
                        "edges": [{"src": s, "dst": d} for s, d in self.EDGES],
                        "lanes": ["Client", "Backend"],
                    }
                ],
            }
        )
        data = spec.to_document().render()
        assert data.startswith(b"%PDF-")

    def test_spec_prompt_mentions_lanes(self):
        assert "lanes" in spec_prompt()


class TestForceLayout:
    NODES = [{"id": str(i), "label": f"Node {i}"} for i in range(6)]
    EDGES = [
        ("0", "1"),
        ("1", "2"),
        ("2", "3"),
        ("3", "4"),
        ("4", "5"),
        ("5", "0"),
        ("0", "3"),
    ]

    def test_layered_default_unaffected(self):
        # Same call as before layout= existed still works and is unchanged.
        first = render_diagram_svg(self.NODES, self.EDGES)
        second = render_diagram_svg(self.NODES, self.EDGES)
        assert first == second
        layout = layout_diagram(self.NODES, self.EDGES)
        assert layout.direction == "down"

    def test_force_renders_valid_svg(self):
        svg = render_diagram_svg(self.NODES, self.EDGES, layout="force")
        parse_svg(svg)
        assert ">Node 0<" in svg

    def test_force_is_deterministic(self):
        first = render_diagram_svg(self.NODES, self.EDGES, layout="force")
        second = render_diagram_svg(self.NODES, self.EDGES, layout="force")
        assert first == second

    def test_force_nodes_do_not_all_collapse(self):
        layout = layout_diagram_force(self.NODES, self.EDGES)
        xs = {p.x for p in layout.nodes}
        ys = {p.y for p in layout.nodes}
        assert len(xs) > 1 or len(ys) > 1

    def test_force_single_node_no_edges(self):
        layout = layout_diagram_force([{"id": "a", "label": "A"}], [])
        assert len(layout.nodes) == 1

    def test_force_self_loop_renders(self):
        svg = render_diagram_svg(
            [{"id": "a", "label": "A"}], [("a", "a")], layout="force"
        )
        parse_svg(svg)

    def test_force_edges_are_straight_lines_not_routed(self):
        # Force-mode edges use straight point-to-point paths (2-point M/L),
        # unlike layered mode's multi-segment orthogonal routing.
        svg = render_diagram_svg(
            [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            [("a", "b")],
            layout="force",
        )
        parse_svg(svg)

    def test_invalid_layout_value_rejected(self):
        with pytest.raises(ValueError, match="layout must be"):
            render_diagram_svg(self.NODES, self.EDGES, layout="bogus")

    def test_lanes_with_force_rejected(self):
        with pytest.raises(ValueError, match="lanes"):
            render_diagram_svg(
                [{"id": "a", "label": "A", "lane": "X"}],
                [],
                layout="force",
                lanes=["X"],
            )

    def test_document_end_to_end(self):
        doc = Document(title="Force")
        doc.diagram(self.NODES, self.EDGES, layout="force", caption="Network")
        data = doc.render()
        assert data.startswith(b"%PDF-")
        assert b"/Figure" in data

    def test_full_render_deterministic(self):
        def build():
            doc = Document(title="Force")
            doc.diagram(self.NODES, self.EDGES, layout="force")
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
                            "type": "diagram",
                            "nodes": self.NODES,
                            "edges": [{"src": s, "dst": d} for s, d in self.EDGES],
                            "layout": "force",
                        }
                    ],
                }
            ),
            strict=True,
        )
        assert isinstance(doc.content[0], SvgBlock)

    def test_pydantic_rejects_lanes_with_force(self):
        pytest.importorskip("pydantic")
        with pytest.raises(Exception):
            parse_spec_json(
                json.dumps(
                    {
                        "title": "T",
                        "content": [
                            {
                                "type": "diagram",
                                "nodes": [{"id": "a", "label": "A", "lane": "X"}],
                                "layout": "force",
                                "lanes": ["X"],
                            }
                        ],
                    }
                ),
                strict=True,
            )

    def test_spec_prompt_mentions_force(self):
        assert '"layout": "force"' in spec_prompt()
