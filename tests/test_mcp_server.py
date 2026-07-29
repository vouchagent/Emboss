"""Tests for the MCP server's tool handlers (via dispatch, no transport)."""

import io

import pytest

from emboss import Document
from emboss.mcp_server import _TOOLS, dispatch

pikepdf = pytest.importorskip("pikepdf")


def _pdf_with_csv(tmp_path):
    spec = {
        "title": "Q3",
        "content": [
            {"type": "heading", "text": "Bookings", "level": 1, "id": "h1"},
            {"type": "paragraph", "text": "Bookings grew this quarter.", "id": "p1"},
            {
                "type": "table",
                "headers": ["Region", "Bookings"],
                "rows": [["NA", "12430"], ["EMEA", "8910"]],
                "caption": "Bookings",
                "attach_data": True,
                "id": "t1",
            },
        ],
    }
    out = str(tmp_path / "doc.pdf")
    dispatch("render_document", {"spec": spec, "output_path": out})
    return out


class TestRenderAndQuery:
    def test_render_is_self_describing(self, tmp_path):
        out = _pdf_with_csv(tmp_path)
        result = dispatch("list_embedded_data", {"pdf_path": out})
        names = {a["name"] for a in result["attachments"]}
        assert "emboss-spec.json" in names
        assert "emboss-textmap.json" in names
        assert "table-1-data.csv" in names

    def test_get_document_spec_is_exact(self, tmp_path):
        out = _pdf_with_csv(tmp_path)
        result = dispatch("get_document_spec", {"pdf_path": out})
        assert result["found"]
        assert result["spec"]["title"] == "Q3"

    def test_get_document_text_from_index(self, tmp_path):
        out = _pdf_with_csv(tmp_path)
        result = dispatch("get_document_text", {"pdf_path": out})
        assert result["found"]
        assert result["nodes"]["p1"] == "Bookings grew this quarter."

    def test_extract_embedded_csv(self, tmp_path):
        out = _pdf_with_csv(tmp_path)
        result = dispatch(
            "extract_embedded_data", {"pdf_path": out, "name": "table-1-data.csv"}
        )
        assert result["found"]
        assert "Region,Bookings" in result["text"]
        assert "12430" in result["text"]

    def test_extract_missing_data_lists_available(self, tmp_path):
        out = _pdf_with_csv(tmp_path)
        result = dispatch(
            "extract_embedded_data", {"pdf_path": out, "name": "nope.csv"}
        )
        assert not result["found"]
        assert "table-1-data.csv" in result["available"]

    def test_verify_document(self, tmp_path):
        out = _pdf_with_csv(tmp_path)
        result = dispatch("verify_document", {"pdf_path": out})
        assert result["ok"]
        assert result["tagged"]

    def test_get_spec_schema(self):
        result = dispatch("get_spec_schema", {})
        assert "schema" in result


class TestReviewTool:
    def test_extract_review_comments(self, tmp_path):
        doc = Document(title="R")
        doc.paragraph("The exposure exceeds four million dollars now.", id="p1")
        pdf = doc.render(embed_spec=True)
        idx = doc.text_index()
        s = next(sp for sp in idx._index["p1"] if sp["text"] == "exceeds")
        with pikepdf.open(io.BytesIO(pdf)) as p:
            a = pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name.StrikeOut,
                Rect=[s["x0"], s["y0"], s["x1"], s["y1"]],
                QuadPoints=[
                    s["x0"],
                    s["y1"],
                    s["x1"],
                    s["y1"],
                    s["x0"],
                    s["y0"],
                    s["x1"],
                    s["y0"],
                ],
                T="Legal",
                Contents="overstated",
            )
            p.pages[0].Annots = pikepdf.Array([p.make_indirect(a)])
            out = io.BytesIO()
            p.save(out)
            marked = tmp_path / "marked.pdf"
            marked.write_bytes(out.getvalue())
        result = dispatch("extract_review_comments", {"pdf_path": str(marked)})
        assert result["count"] == 1
        c = result["comments"][0]
        assert c["node_id"] == "p1"
        assert c["anchor_text"] == "exceeds"
        assert c["resolution"] == "exact"


class TestEditTools:
    def test_edit_document_text(self, tmp_path):
        spec = {
            "title": "Doc",
            "content": [
                {
                    "type": "paragraph",
                    "text": "Q3 exposure exceeds four million.",
                    "id": "p1",
                }
            ],
        }
        src = str(tmp_path / "src.pdf")
        dispatch("render_document", {"spec": spec, "output_path": src})
        out = str(tmp_path / "edited.pdf")
        result = dispatch(
            "edit_document_text",
            {
                "pdf_path": src,
                "node_id": "p1",
                "new_text": "Q3 exposure is 2.8 million.",
                "output_path": out,
            },
        )
        assert result["edited_field"] == "content"
        text = dispatch("get_document_text", {"pdf_path": out})["nodes"]["p1"]
        assert text == "Q3 exposure is 2.8 million."

    def test_patch_node_changes_chart(self, tmp_path):
        spec = {
            "title": "Doc",
            "content": [
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "labels": ["A", "B"],
                    "values": [1, 2],
                    "title": "C",
                    "id": "c1",
                }
            ],
        }
        src = str(tmp_path / "src.pdf")
        dispatch("render_document", {"spec": spec, "output_path": src})
        out = str(tmp_path / "patched.pdf")
        result = dispatch(
            "patch_node",
            {
                "pdf_path": src,
                "node_id": "c1",
                "changes": {"chart_type": "line"},
                "output_path": out,
            },
        )
        assert "chart_type" in result["changed"]
        spec_back = dispatch("get_document_spec", {"pdf_path": out})["spec"]
        chart = next(b for b in spec_back["content"] if b.get("id") == "c1")
        assert chart["chart_type"] == "line"


class TestStructuralEdits:
    def _two_block_pdf(self, tmp_path):
        spec = {
            "title": "Doc",
            "content": [
                {"type": "heading", "text": "Intro", "level": 1, "id": "h1"},
                {"type": "paragraph", "text": "Body.", "id": "p1"},
            ],
        }
        out = str(tmp_path / "src.pdf")
        dispatch("render_document", {"spec": spec, "output_path": out})
        return out

    def test_insert_block_keeps_ids_and_stays_tagged(self, tmp_path):
        src = self._two_block_pdf(tmp_path)
        out = str(tmp_path / "ins.pdf")
        result = dispatch(
            "insert_block",
            {
                "pdf_path": src,
                "after_node_id": "p1",
                "block": {"type": "heading", "text": "Risks", "level": 1, "id": "h2"},
                "output_path": out,
            },
        )
        assert result["total_blocks"] == 3
        spec = dispatch("get_document_spec", {"pdf_path": out})["spec"]
        assert [b.get("id") for b in spec["content"]] == ["h1", "p1", "h2"]
        # Structure stays valid and accessibility-tagged after the edit.
        assert dispatch("verify_document", {"pdf_path": out})["tagged"]

    def test_remove_node(self, tmp_path):
        src = self._two_block_pdf(tmp_path)
        out = str(tmp_path / "rm.pdf")
        result = dispatch(
            "remove_node", {"pdf_path": src, "node_id": "p1", "output_path": out}
        )
        assert result["removed"] == "p1"
        spec = dispatch("get_document_spec", {"pdf_path": out})["spec"]
        assert [b.get("id") for b in spec["content"]] == ["h1"]

    def test_insert_unknown_anchor_errors(self, tmp_path):
        src = self._two_block_pdf(tmp_path)
        result = dispatch(
            "insert_block",
            {
                "pdf_path": src,
                "after_node_id": "nope",
                "block": {"type": "paragraph", "text": "x"},
                "output_path": str(tmp_path / "x.pdf"),
            },
        )
        assert "error" in result


class TestDispatch:
    def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="unknown tool"):
            dispatch("nope", {})

    def test_handler_error_is_surfaced(self):
        result = dispatch("get_document_spec", {"pdf_path": "/no/such/file.pdf"})
        assert "error" in result

    def test_every_tool_has_description_and_schema(self):
        for name, (handler, desc, schema) in _TOOLS.items():
            assert callable(handler)
            assert desc and isinstance(desc, str)
            assert schema["type"] == "object"
