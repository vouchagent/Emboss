"""Tests for the Mermaid diagram parser and its Markdown integration."""

import pytest

from emboss import Document
from emboss.mermaid import (
    MermaidError,
    parse_er,
    parse_flowchart,
    parse_mermaid,
    parse_sequence,
)
from emboss.markdown import parse_markdown
from emboss.spec import CodeBlock, SvgBlock


def _render(block) -> bytes:
    doc = Document(title="T")
    doc.add(block)
    return doc.render()


class TestFlowchart:
    def test_basic_nodes_and_edges(self):
        block = parse_mermaid("flowchart TD\n    A[Start] --> B[End]")
        assert isinstance(block, SvgBlock)
        assert "2 nodes" in block.alt_text
        assert "1 connection" in block.alt_text

    def test_renders_to_pdf(self):
        block = parse_mermaid("flowchart TD\n    A[Start] --> B[End]")
        assert _render(block)[:5] == b"%PDF-"

    def test_all_node_shapes(self):
        src = (
            "flowchart TD\n"
            "    A[Box] --> B(Round)\n"
            "    B --> C{Decision}\n"
            "    C --> D[(Store)]\n"
            "    D --> E([Pill])"
        )
        block = parse_flowchart(src)
        assert "5 nodes" in block.alt_text
        assert _render(block)[:5] == b"%PDF-"

    def test_direction_lr_is_right(self):
        # Direction maps into layout; distinct sources render distinctly.
        down = parse_mermaid("flowchart TD\n A[X] --> B[Y]").source
        right = parse_mermaid("flowchart LR\n A[X] --> B[Y]").source
        assert down != right

    @pytest.mark.parametrize("token", ["TD", "TB", "BT", "LR", "RL"])
    def test_direction_tokens_accepted(self, token):
        block = parse_mermaid(f"flowchart {token}\n A --> B")
        assert isinstance(block, SvgBlock)

    def test_bad_direction_raises(self):
        with pytest.raises(MermaidError):
            parse_mermaid("flowchart XY\n A --> B")

    def test_edge_label(self):
        block = parse_mermaid("flowchart TD\n A --> |go| B")
        assert isinstance(block, SvgBlock)

    def test_dashed_edge(self):
        solid = parse_mermaid("flowchart TD\n A[X] --> B[Y]").source
        dashed = parse_mermaid("flowchart TD\n A[X] -.-> B[Y]").source
        # A dashed edge emits multiple short subpaths, not one solid path.
        assert dashed != solid

    def test_graph_keyword(self):
        block = parse_mermaid("graph LR\n A[X] --> B[Y]")
        assert isinstance(block, SvgBlock)

    def test_chained_edges(self):
        block = parse_mermaid("flowchart LR\n A --> B --> C")
        assert "3 nodes" in block.alt_text
        assert "2 connections" in block.alt_text

    def test_label_updates_reused_node(self):
        block = parse_mermaid("flowchart TD\n A --> B\n A[Named]")
        assert "Named" in block.alt_text

    def test_styling_lines_ignored(self):
        src = (
            "flowchart TD\n"
            "    A[X] --> B[Y]\n"
            "    classDef big fill:#f00\n"
            "    class A big\n"
            "    style B color:#000"
        )
        block = parse_flowchart(src)
        assert "2 nodes" in block.alt_text


class TestSequence:
    def test_basic(self):
        src = (
            "sequenceDiagram\n"
            "    participant A as Alice\n"
            "    participant B as Bob\n"
            "    A->>B: hello\n"
            "    B-->>A: hi"
        )
        block = parse_mermaid(src)
        assert "2 participants" in block.alt_text
        assert "2 messages" in block.alt_text
        assert _render(block)[:5] == b"%PDF-"

    def test_message_styles(self):
        src = "sequenceDiagram\n    A->>B: sync\n    B-->>A: return\n    A-)B: async"
        block = parse_sequence(src)
        assert "3 messages" in block.alt_text

    def test_auto_participants(self):
        block = parse_mermaid("sequenceDiagram\n A->>B: hi")
        assert "2 participants" in block.alt_text

    def test_activation_suffix(self):
        src = "sequenceDiagram\n A->>+B: go\n B-->>-A: done"
        block = parse_sequence(src)
        assert _render(block)[:5] == b"%PDF-"

    def test_activate_keyword(self):
        src = "sequenceDiagram\n A->>B: go\n activate B\n B-->>A: done"
        block = parse_sequence(src)
        assert isinstance(block, SvgBlock)

    def test_note_and_loop_ignored(self):
        src = (
            "sequenceDiagram\n"
            "    A->>B: go\n"
            "    Note over A: a note\n"
            "    loop every day\n"
            "    B-->>A: done\n"
            "    end"
        )
        block = parse_sequence(src)
        assert "2 messages" in block.alt_text

    def test_invalid_message_raises(self):
        with pytest.raises(MermaidError):
            parse_mermaid("sequenceDiagram\n this is not a message")


class TestEr:
    def test_entities_and_relationship(self):
        src = (
            "erDiagram\n"
            "    USER {\n"
            "        int id PK\n"
            "        string email\n"
            "    }\n"
            "    ORDER {\n"
            "        int id PK\n"
            "        int user_id FK\n"
            "    }\n"
            "    USER ||--o{ ORDER : places"
        )
        block = parse_mermaid(src)
        assert "2 entities" in block.alt_text
        assert "1 relationship" in block.alt_text
        assert _render(block)[:5] == b"%PDF-"

    def test_cardinality_mapping(self):
        src = "erDiagram\n A ||--o{ B : has"
        block = parse_er(src)
        assert "USER" not in block.alt_text
        assert isinstance(block, SvgBlock)

    def test_auto_entities_from_relationship(self):
        block = parse_mermaid("erDiagram\n A }|..|{ B : links")
        assert "2 entities" in block.alt_text

    def test_bad_cardinality_raises(self):
        with pytest.raises(MermaidError):
            parse_mermaid("erDiagram\n A xx--yy B : bad")

    def test_unterminated_block_raises(self):
        with pytest.raises(MermaidError):
            parse_mermaid("erDiagram\n USER {\n int id PK")


class TestUnsupported:
    def test_class_diagram_raises(self):
        with pytest.raises(MermaidError) as exc:
            parse_mermaid("classDiagram\n A <|-- B")
        assert "classDiagram" in str(exc.value)

    def test_state_diagram_raises(self):
        with pytest.raises(MermaidError):
            parse_mermaid("stateDiagram-v2\n [*] --> S")

    def test_empty_raises(self):
        with pytest.raises(MermaidError):
            parse_mermaid("   \n  %% comment\n")


class TestDeterminism:
    def test_double_parse_equal(self):
        src = (
            "flowchart LR\n"
            "    A[Start] -->|go| B{Choice}\n"
            "    B -.-> C[(Store)]\n"
            "    B --> D([Done])"
        )
        assert parse_mermaid(src).source == parse_mermaid(src).source

    def test_sequence_deterministic(self):
        src = "sequenceDiagram\n A->>+B: go\n B-->>-A: done"
        assert parse_sequence(src).source == parse_sequence(src).source

    def test_er_deterministic(self):
        src = "erDiagram\n A ||--o{ B : has"
        assert parse_er(src).source == parse_er(src).source


class TestMarkdownIntegration:
    def test_mermaid_fence_produces_diagram(self):
        md = "# Title\n\n```mermaid\nflowchart TD\n A[X] --> B[Y]\n```\n"
        elements = parse_markdown(md)
        svgs = [e for e in elements if isinstance(e, SvgBlock)]
        assert len(svgs) == 1
        assert "2 nodes" in svgs[0].alt_text

    def test_failed_mermaid_degrades_to_code(self):
        warnings = []
        md = "```mermaid\nclassDiagram\n A <|-- B\n```"
        elements = parse_markdown(md, on_warning=warnings.append)
        assert isinstance(elements[0], CodeBlock)
        assert elements[0].language == "mermaid"
        assert len(warnings) == 1
        assert warnings[0].kind == "mermaid"

    def test_strict_reraises(self):
        md = "```mermaid\nclassDiagram\n A <|-- B\n```"
        with pytest.raises(MermaidError):
            parse_markdown(md, strict=True)

    def test_document_from_markdown_renders(self):
        md = "# Diagram\n\n```mermaid\nsequenceDiagram\n A->>B: hi\n```\n"
        doc = Document.from_markdown(md)
        assert doc.render()[:5] == b"%PDF-"
