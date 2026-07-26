"""Tests for the LLM integration layer: Pydantic models, CLI, and export adapters."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss.adapters.pydantic_schema import (
    DocumentSpec,
    HeadingSpec,
    ParagraphSpec,
    TableSpec,
    generate_json_schema,
)
from emboss.pdf.verify import verify_pdf


SAMPLE_SPEC = {
    "title": "Test Document",
    "style": "corporate",
    "content": [
        {"type": "heading", "text": "Introduction", "level": 1},
        {"type": "paragraph", "text": "This is a test document generated from JSON."},
        {
            "type": "table",
            "headers": ["Item", "Amount", "Change"],
            "rows": [
                ["Widget A", "$1,234.56", "+5.2%"],
                ["Widget B", "$987.65", "-2.1%"],
                ["Widget C", "$2,345.00", "+12.8%"],
            ],
            "stripe": True,
        },
        {"type": "heading", "text": "Conclusion", "level": 2},
        {"type": "paragraph", "text": "End of document."},
    ],
}


class TestDocumentSpec:
    def test_parse_minimal_spec(self):
        spec = DocumentSpec.model_validate({
            "title": "Minimal",
            "content": [{"type": "paragraph", "text": "Hello world."}],
        })
        assert spec.title == "Minimal"
        assert len(spec.content) == 1

    def test_parse_full_spec(self):
        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        assert spec.title == "Test Document"
        assert len(spec.content) == 5
        assert spec.style == "corporate"

    def test_renders_valid_pdf(self):
        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        pdf = spec.render()
        report = verify_pdf(pdf)
        assert report.ok
        assert report.has_struct_tree
        assert report.has_lang

    def test_deterministic_output(self):
        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        first = spec.render()
        second = spec.render()
        assert first == second

    def test_all_styles_render(self):
        for style in ("legal", "finance", "academic", "corporate", "minimal"):
            spec = DocumentSpec.model_validate({
                "title": f"Style {style}",
                "style": style,
                "content": [
                    {"type": "heading", "text": "Test", "level": 1},
                    {"type": "paragraph", "text": "Body text."},
                ],
            })
            report = verify_pdf(spec.render())
            assert report.ok, f"style {style} failed: {report.problems}"

    def test_invalid_style_rejected(self):
        with pytest.raises(Exception, match="literal_error"):
            DocumentSpec.model_validate({
                "title": "Bad",
                "style": "nonexistent",
                "content": [{"type": "paragraph", "text": "x"}],
            })


class TestSelfHealing:
    def test_heading_level_jump_is_healed(self):
        spec = DocumentSpec.model_validate({
            "title": "Healed",
            "content": [
                {"type": "heading", "text": "Chapter", "level": 1},
                {"type": "heading", "text": "Deep", "level": 4},
                {"type": "paragraph", "text": "Body."},
            ],
        })
        levels = [b.level for b in spec.content if isinstance(b, HeadingSpec)]
        assert levels == [1, 2]

    def test_empty_paragraph_gets_space(self):
        spec = DocumentSpec.model_validate({
            "title": "Empty",
            "content": [
                {"type": "heading", "text": "H", "level": 1},
                {"type": "paragraph"},
            ],
        })
        para = spec.content[1]
        assert isinstance(para, ParagraphSpec)
        assert para.text == " "

    def test_heading_text_stripped(self):
        spec = DocumentSpec.model_validate({
            "title": "Stripped",
            "content": [
                {"type": "heading", "text": "  Padded Heading  ", "level": 1},
                {"type": "paragraph", "text": "Body."},
            ],
        })
        assert spec.content[0].text == "Padded Heading"


class TestAutoDecimalAlignment:
    def test_detects_numeric_columns(self):
        spec = DocumentSpec.model_validate({
            "title": "Decimal",
            "content": [{
                "type": "table",
                "headers": ["Item", "Price"],
                "rows": [
                    ["A", "$1,234.56"],
                    ["B", "$987.65"],
                    ["C", "$2,345.00"],
                ],
            }],
        })
        table = spec.content[0]
        assert isinstance(table, TableSpec)
        for row in table.rows:
            cell = row[1]
            assert hasattr(cell, "align") and cell.align == "decimal"

    def test_does_not_align_text_columns(self):
        spec = DocumentSpec.model_validate({
            "title": "Text",
            "content": [{
                "type": "table",
                "headers": ["Name", "City"],
                "rows": [
                    ["Alice", "New York"],
                    ["Bob", "London"],
                ],
            }],
        })
        table = spec.content[0]
        for row in table.rows:
            for cell in row:
                if isinstance(cell, str):
                    continue
                assert cell.align is None or cell.align == "left"


class TestJsonSchema:
    def test_generates_valid_json(self):
        schema_str = generate_json_schema()
        schema = json.loads(schema_str)
        assert schema["title"] == "Emboss Document"
        assert "$defs" in schema

    def test_schema_has_content_block_types(self):
        schema = json.loads(generate_json_schema())
        defs = schema.get("$defs", {})
        expected = {"HeadingSpec", "ParagraphSpec", "TableSpec", "BulletListSpec"}
        assert expected.issubset(set(defs.keys()))

    def test_schema_validates_sample_spec(self):
        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        roundtrip = json.loads(spec.model_dump_json())
        spec2 = DocumentSpec.model_validate(roundtrip)
        assert spec2.title == spec.title
        assert len(spec2.content) == len(spec.content)


class TestHtmlExport:
    def test_produces_valid_html(self):
        from emboss.adapters.html_export import to_html

        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        html = to_html(spec.to_document())
        assert html.startswith("<!DOCTYPE html>")
        assert "<h1" in html
        assert "<table>" in html
        assert "Test Document" in html

    def test_fragment_mode(self):
        from emboss.adapters.html_export import to_html

        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        html = to_html(spec.to_document(), standalone=False)
        assert html.startswith("<article")
        assert "<!DOCTYPE" not in html


class TestMarkdownExport:
    def test_produces_markdown(self):
        from emboss.adapters.markdown_export import to_markdown

        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        md = to_markdown(spec.to_document())
        assert "# Introduction" in md
        assert "## Conclusion" in md
        assert "| Item" in md
        assert "---" in md

    def test_frontmatter_optional(self):
        from emboss.adapters.markdown_export import to_markdown

        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        md = to_markdown(spec.to_document(), include_metadata=False)
        assert not md.startswith("---")


class TestOfficeExport:
    def test_produces_structured_dict(self):
        from emboss.adapters.docx_export import to_office_dict

        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        data = to_office_dict(spec.to_document())
        assert data["metadata"]["title"] == "Test Document"
        assert len(data["content"]) == 5
        assert data["content"][0]["type"] == "heading"
        assert data["content"][2]["type"] == "table"

    def test_serializable_to_json(self):
        from emboss.adapters.docx_export import to_office_dict

        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        data = to_office_dict(spec.to_document())
        output = json.dumps(data)
        assert isinstance(output, str)
        assert len(output) > 0


class TestCli:
    def test_render_from_file(self, tmp_path):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(SAMPLE_SPEC))
        out_path = tmp_path / "output.pdf"
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "render",
             str(spec_path), "-o", str(out_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert out_path.exists()
        assert verify_pdf(out_path.read_bytes()).ok

    def test_render_from_stdin(self, tmp_path):
        out_path = tmp_path / "stdin.pdf"
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "render",
             "-", "-o", str(out_path)],
            input=json.dumps(SAMPLE_SPEC),
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert out_path.exists()

    def test_validate_valid_spec(self, tmp_path):
        spec_path = tmp_path / "valid.json"
        spec_path.write_text(json.dumps(SAMPLE_SPEC))
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "validate", str(spec_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "valid" in result.stdout

    def test_validate_invalid_spec(self, tmp_path):
        spec_path = tmp_path / "invalid.json"
        spec_path.write_text('{"title": ""}')
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "validate", str(spec_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_schema_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "schema"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        schema = json.loads(result.stdout)
        assert schema["title"] == "Emboss Document"

    def test_export_html(self, tmp_path):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(SAMPLE_SPEC))
        out_path = tmp_path / "output.html"
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "export",
             str(spec_path), "-f", "html", "-o", str(out_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert out_path.exists()
        assert "<!DOCTYPE html>" in out_path.read_text()

    def test_export_markdown(self, tmp_path):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(SAMPLE_SPEC))
        out_path = tmp_path / "output.md"
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "export",
             str(spec_path), "-f", "markdown", "-o", str(out_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert out_path.exists()
        assert "# Introduction" in out_path.read_text()

    def test_verify_valid_pdf(self, tmp_path):
        spec = DocumentSpec.model_validate(SAMPLE_SPEC)
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(spec.render())
        result = subprocess.run(
            [sys.executable, "-m", "emboss", "verify", str(pdf_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "valid" in result.stdout


class TestRichDocumentSpec:
    """Test complex document specs that exercise all features."""

    def test_legal_document(self):
        spec = DocumentSpec.model_validate({
            "title": "Memorandum of Understanding",
            "style": "legal",
            "page": {"preset": "letter", "margin_left": 108},
            "legal": {
                "watermark": "DRAFT",
                "line_numbering": True,
                "bates_prefix": "MOU-",
            },
            "content": [
                {"type": "heading", "text": "Parties", "level": 1},
                {"type": "paragraph", "text": "This Memorandum is between Party A and Party B."},
                {"type": "heading", "text": "Terms", "level": 2},
                {"type": "paragraph", "text": "The parties agree to the following terms and conditions as outlined herein. " * 10},
                {"type": "heading", "text": "Signatures", "level": 2},
                {"type": "paragraph", "text": "IN WITNESS WHEREOF, the parties have executed this agreement."},
            ],
        })
        pdf = spec.render()
        report = verify_pdf(pdf)
        assert report.ok
        assert report.page_count >= 1

    def test_mixed_formatting_runs(self):
        spec = DocumentSpec.model_validate({
            "title": "Runs",
            "content": [
                {"type": "heading", "text": "Styled Text", "level": 1},
                {
                    "type": "paragraph",
                    "runs": [
                        {"text": "Revenue increased "},
                        {"text": "24.1%", "bold": True, "color": "0d6e3f"},
                        {"text": " year over year, with "},
                        {"text": "operating margin", "italic": True},
                        {"text": " at 18.2%."},
                    ],
                },
            ],
        })
        pdf = spec.render()
        assert verify_pdf(pdf).ok

    def test_large_table_spanning_pages(self):
        rows = [[f"Row {i}", f"${i * 100:,.2f}", f"+{i % 20}%"] for i in range(100)]
        spec = DocumentSpec.model_validate({
            "title": "Large Table",
            "content": [
                {"type": "heading", "text": "Data", "level": 1},
                {
                    "type": "table",
                    "headers": ["Item", "Amount", "Change"],
                    "rows": rows,
                    "stripe": True,
                },
            ],
        })
        pdf = spec.render()
        report = verify_pdf(pdf)
        assert report.ok
        assert report.page_count > 1

    def test_all_block_types(self):
        spec = DocumentSpec.model_validate({
            "title": "Everything",
            "content": [
                {"type": "heading", "text": "Heading 1", "level": 1},
                {"type": "paragraph", "text": "Paragraph text."},
                {"type": "heading", "text": "Heading 2", "level": 2},
                {"type": "bullets", "items": ["One", "Two", "Three"]},
                {"type": "rule"},
                {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]},
                {"type": "page_break"},
                {"type": "heading", "text": "Page Two", "level": 1},
                {"type": "paragraph", "text": "On the second page."},
            ],
        })
        pdf = spec.render()
        report = verify_pdf(pdf)
        assert report.ok
        assert report.page_count == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
