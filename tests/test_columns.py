"""Tests for the `Columns` block: side-by-side content for HTML flex-row import.

Covers measurement (widths, row height = tallest column), rendering
(positions, PDF/UA structure), validation (unsupported nested types, bad
widths), pagination (atomic non-splitting placement), nesting, and the
docx/markdown/html export adapters.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Columns, Document, Heading, Paragraph, Table  # noqa: E402
from emboss.constraints import ConstraintValidator  # noqa: E402
from emboss.pdf.verify import verify_pdf  # noqa: E402
from emboss.spec import BulletList, Footnote, PageBreak  # noqa: E402
from emboss.adapters.docx_export import to_office_dict  # noqa: E402
from emboss.adapters.html_export import to_html  # noqa: E402
from emboss.adapters.markdown_export import to_markdown  # noqa: E402


def _two_column_doc(**kw) -> Document:
    doc = Document(title="Columns", language="en-US")
    doc.columns(
        columns=[
            [Paragraph("Left column text.", id="left-p")],
            [Paragraph("Right column text.", id="right-p")],
        ],
        **kw,
    )
    return doc


class TestColumnsSpec:
    def test_requires_at_least_one_column(self):
        with pytest.raises(ValueError):
            Columns(columns=[])

    def test_widths_must_match_column_count(self):
        with pytest.raises(ValueError):
            Columns(columns=[[Paragraph("a")], [Paragraph("b")]], widths=[1])

    def test_widths_must_be_positive(self):
        with pytest.raises(ValueError):
            Columns(columns=[[Paragraph("a")], [Paragraph("b")]], widths=[1, 0])
        with pytest.raises(ValueError):
            Columns(columns=[[Paragraph("a")], [Paragraph("b")]], widths=[1, -1])

    def test_document_columns_builder_chains(self):
        doc = Document(title="T", language="en-US")
        result = doc.columns(columns=[[Paragraph("a")], [Paragraph("b")]])
        assert result is doc
        assert isinstance(doc.content[0], Columns)


class TestColumnsValidation:
    def test_constraint_validator_accepts_columns(self):
        doc = _two_column_doc()
        result = ConstraintValidator().validate(doc)
        assert result.issues == []

    def test_unsupported_nested_type_raises(self):
        doc = Document(title="T", language="en-US")
        doc.columns(columns=[[Footnote(content="fn")], [Paragraph("b")]])
        with pytest.raises(ValueError, match="unsupported"):
            doc.render()

    def test_page_break_nested_raises(self):
        doc = Document(title="T", language="en-US")
        doc.columns(columns=[[PageBreak()], [Paragraph("b")]])
        with pytest.raises(ValueError, match="unsupported"):
            doc.render()


class TestColumnsRendering:
    def test_renders_valid_tagged_pdf(self):
        doc = _two_column_doc()
        data = doc.render()
        report = verify_pdf(data)
        assert report.ok, report.problems
        assert b"/StructTreeRoot" in data

    def test_deterministic_output(self):
        assert _two_column_doc().render() == _two_column_doc().render()

    def test_columns_are_placed_side_by_side(self):
        doc = _two_column_doc(gap=20.0)
        layout = doc.layout_map()
        left = layout["left-p"][0]
        right = layout["right-p"][0]
        assert left["page"] == right["page"]
        # Same top edge (row starts level) and left strictly left of right.
        assert left["y0"] == pytest.approx(right["y0"])
        assert left["x1"] <= right["x0"] + 1e-6

    def test_unequal_widths_change_column_extent(self):
        doc = Document(title="T", language="en-US")
        doc.columns(
            columns=[
                [Paragraph("Left.", id="left-p")],
                [Paragraph("Right.", id="right-p")],
            ],
            widths=[3, 1],
        )
        layout = doc.layout_map()
        left = layout["left-p"][0]
        right = layout["right-p"][0]
        left_width = left["x1"] - left["x0"]
        right_width = right["x1"] - right["x0"]
        assert left_width > right_width

    def test_row_height_is_tallest_column(self):
        doc = Document(title="T", language="en-US")
        short = Paragraph("Short.", id="short-p")
        tall = Paragraph("Long paragraph text. " * 30, id="tall-p")
        doc.columns(columns=[[short], [tall]])
        doc.add(Paragraph("After.", id="after-p"))
        layout = doc.layout_map()
        tall_box = layout["tall-p"][0]
        after_box = layout["after-p"][0]
        # Content after the row starts at or below the bottom of the tallest column.
        assert after_box["y0"] <= tall_box["y1"] + 1e-6

    def test_table_nested_in_column_draws_all_rows(self):
        doc = Document(title="T", language="en-US")
        table = Table(
            headers=["A", "B"], rows=[["1", "2"], ["3", "4"], ["5", "6"]], id="tbl"
        )
        doc.columns(columns=[[table], [Paragraph("side")]])
        data = doc.render()
        report = verify_pdf(data)
        assert report.ok, report.problems
        assert data.count(b"/TR") >= 3

    def test_bullet_list_nested_in_column(self):
        doc = Document(title="T", language="en-US")
        doc.columns(
            columns=[
                [BulletList(items=["one", "two", "three"])],
                [Paragraph("side")],
            ]
        )
        report = verify_pdf(doc.render())
        assert report.ok, report.problems

    def test_overflow_pushes_to_next_page(self):
        doc = Document(title="T", language="en-US")
        doc.add(Paragraph("intro"))
        long_par = Paragraph("Filler text that takes real space. " * 250)
        doc.columns(columns=[[long_par], [Paragraph("short")]])
        doc.add(Paragraph("after"))
        report = verify_pdf(doc.render())
        assert report.ok, report.problems
        assert report.page_count >= 2

    def test_nested_columns_in_columns(self):
        doc = Document(title="T", language="en-US")
        doc.columns(
            columns=[
                [Columns(columns=[[Paragraph("a")], [Paragraph("b")]])],
                [Paragraph("side")],
            ]
        )
        report = verify_pdf(doc.render())
        assert report.ok, report.problems

    def test_heading_nested_in_column_gets_heading_tag(self):
        doc = Document(title="T", language="en-US")
        doc.columns(columns=[[Heading("Sub", level=2)], [Paragraph("side")]])
        data = doc.render()
        assert b"/H2" in data


class TestColumnsExportAdapters:
    def test_html_export_renders_flex_row(self):
        doc = _two_column_doc()
        html = to_html(doc, standalone=False)
        assert "display:flex" in html
        assert "Left column text." in html
        assert "Right column text." in html

    def test_markdown_export_renders_sequential_sections(self):
        doc = _two_column_doc()
        md = to_markdown(doc)
        assert "Left column text." in md
        assert "Right column text." in md
        assert "---" in md

    def test_docx_export_preserves_column_structure(self):
        doc = _two_column_doc()
        data = to_office_dict(doc)
        block = data["content"][0]
        assert block["type"] == "columns"
        assert len(block["columns"]) == 2
        assert block["columns"][0][0]["type"] == "paragraph"
        assert block["columns"][0][0]["runs"][0]["text"] == "Left column text."


class TestColumnsPydanticSpec:
    """The `DocumentSpec` (LLM structured-output) path exercises `ColumnsSpec`."""

    def test_parses_nested_columns_spec(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "Pydantic columns",
                "language": "en-US",
                "content": [
                    {
                        "type": "columns",
                        "columns": [
                            [{"type": "paragraph", "text": "Left col"}],
                            [
                                {"type": "heading", "text": "Right", "level": 2},
                                {"type": "paragraph", "text": "Right col"},
                            ],
                        ],
                        "widths": [2, 1],
                        "gap": 20.0,
                    }
                ],
            }
        )
        element = spec.content[0].to_element()
        assert isinstance(element, Columns)
        assert len(element.columns) == 2
        assert element.widths == [2, 1]
        assert element.gap == 20.0
        assert isinstance(element.columns[0][0], Paragraph)
        assert isinstance(element.columns[1][0], Heading)

    def test_renders_via_to_document(self):
        from emboss.adapters.pydantic_schema import DocumentSpec

        spec = DocumentSpec.model_validate(
            {
                "title": "Pydantic columns render",
                "language": "en-US",
                "content": [
                    {
                        "type": "columns",
                        "columns": [
                            [{"type": "paragraph", "text": "A"}],
                            [{"type": "paragraph", "text": "B"}],
                        ],
                    }
                ],
            }
        )
        data = spec.render()
        report = verify_pdf(data)
        assert report.ok, report.problems

    def test_rejects_missing_columns(self):
        from pydantic import ValidationError as PydanticValidationError

        from emboss.adapters.pydantic_schema import ColumnsSpec

        with pytest.raises(PydanticValidationError):
            ColumnsSpec.model_validate({"type": "columns", "columns": []})

    def test_json_schema_includes_columns_type(self):
        from emboss.adapters.pydantic_schema import generate_json_schema

        schema = generate_json_schema()
        assert '"columns"' in schema
