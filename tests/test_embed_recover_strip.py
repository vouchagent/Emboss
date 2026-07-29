"""Tests for embed_spec, Document.from_pdf recovery, and `emboss strip`."""

from __future__ import annotations

import io
import json

import pytest

from emboss import Document
from emboss.spec import BulletList, Heading, NumberedList, Paragraph, Table
from emboss.pdf.verify import verify_pdf
from emboss.recovery import (
    document_from_spec_dict,
    document_to_spec_dict,
    recover_from_attachment,
    recover_from_structure_tree,
    strip_pdf,
)

pikepdf = pytest.importorskip("pikepdf")


def _sample_document(**kw) -> Document:
    doc = Document(title="Sample Report", **kw)
    doc.heading("Overview", level=1)
    doc.paragraph("This is a test paragraph with some words.")
    doc.bullets(["first item", "second item", "third item"])
    doc.numbered(["step one", "step two"])
    doc.table(headers=["A", "B"], rows=[["1", "2"], ["3", "4"]], caption="A table")
    return doc


def _strip_attachment_names(data: bytes) -> bytes:
    """Simulate a manual, pre-strip removal of the /Names/EmbeddedFiles tree."""
    with pikepdf.open(io.BytesIO(data)) as pdf:
        if "/Names" in pdf.Root:
            del pdf.Root["/Names"]
        if "/AF" in pdf.Root:
            del pdf.Root["/AF"]
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()


def _tree_ids(pdf) -> list:
    ids: list = []

    def walk(node) -> None:
        if "/ID" in node:
            ids.append(str(node["/ID"]))
        k = node.get("/K")
        if k is None:
            return
        items = list(k) if isinstance(k, pikepdf.Array) else [k]
        for item in items:
            if hasattr(item, "keys"):
                walk(item)

    walk(pdf.Root.StructTreeRoot)
    return ids


# -- document_to_spec_dict / document_from_spec_dict --


class TestSpecDictRoundTrip:
    def test_round_trips_headings_and_paragraph_text(self):
        doc = _sample_document()
        spec = document_to_spec_dict(doc)
        rebuilt = document_from_spec_dict(spec)

        headings = [e for e in rebuilt.content if isinstance(e, Heading)]
        paragraphs = [e for e in rebuilt.content if isinstance(e, Paragraph)]
        assert headings[0].text == "Overview"
        assert paragraphs[0].plain_text == "This is a test paragraph with some words."

    def test_round_trips_lists_and_table(self):
        doc = _sample_document()
        spec = document_to_spec_dict(doc)
        rebuilt = document_from_spec_dict(spec)

        bullets = next(e for e in rebuilt.content if isinstance(e, BulletList))
        numbered = next(e for e in rebuilt.content if isinstance(e, NumberedList))
        table = next(e for e in rebuilt.content if isinstance(e, Table))
        assert ["".join(r.text for r in runs) for runs in bullets.item_runs] == [
            "first item",
            "second item",
            "third item",
        ]
        assert ["".join(r.text for r in runs) for runs in numbered.item_runs] == [
            "step one",
            "step two",
        ]
        assert [c.plain_text for c in table.header_cells] == ["A", "B"]
        assert [[c.plain_text for c in row] for row in table.body_rows] == [
            ["1", "2"],
            ["3", "4"],
        ]

    def test_content_is_deterministic_key_order(self):
        doc = _sample_document()
        first = json.dumps(document_to_spec_dict(doc), sort_keys=True)
        second = json.dumps(document_to_spec_dict(doc), sort_keys=True)
        assert first == second

    def test_explicit_ids_survive_the_round_trip(self):
        doc = Document(
            title="A", content=[Heading("A", 1, id="sec-a"), Paragraph("body", id="p1")]
        )
        spec = document_to_spec_dict(doc)
        rebuilt = document_from_spec_dict(spec)
        assert rebuilt.content[0].id == "sec-a"
        assert rebuilt.content[1].id == "p1"


# -- render(embed_spec=True) --


class TestEmbedSpecAttachments:
    def test_produces_a_real_source_attachment(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert "emboss-spec.json" in pdf.attachments
            spec_file = pdf.attachments["emboss-spec.json"]
            assert spec_file.obj.AFRelationship == pikepdf.Name("/Source")
            payload = json.loads(spec_file.get_file().read_bytes().decode("utf-8"))
            assert payload["title"] == "Sample Report"

    def test_spec_json_round_trips_into_equivalent_document(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(data)) as pdf:
            raw = pdf.attachments["emboss-spec.json"].get_file().read_bytes()

        from emboss.generate import parse_spec_json

        rebuilt = parse_spec_json(raw.decode("utf-8"))
        original_headings = [e.text for e in doc.content if isinstance(e, Heading)]
        rebuilt_headings = [e.text for e in rebuilt.content if isinstance(e, Heading)]
        assert rebuilt_headings == original_headings
        original_paragraph = next(
            e for e in doc.content if isinstance(e, Paragraph)
        ).plain_text
        rebuilt_paragraph = next(
            e for e in rebuilt.content if isinstance(e, Paragraph)
        ).plain_text
        assert rebuilt_paragraph == original_paragraph

    def test_layout_map_attachment_present_and_valid_json(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert "emboss-layout.json" in pdf.attachments
            layout_file = pdf.attachments["emboss-layout.json"]
            assert layout_file.obj.AFRelationship == pikepdf.Name("/Supplement")
            layout = json.loads(layout_file.get_file().read_bytes().decode("utf-8"))
        assert isinstance(layout, dict) and layout
        for entries in layout.values():
            assert entries and all("page" in e for e in entries)

    def test_markdown_twin_attachment_present(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert "emboss-doc.md" in pdf.attachments
            md_file = pdf.attachments["emboss-doc.md"]
            assert md_file.obj.AFRelationship == pikepdf.Name("/Alternative")
            text = md_file.get_file().read_bytes().decode("utf-8")
        assert "Overview" in text

    def test_embed_spec_false_by_default_produces_no_attachment(self):
        doc = _sample_document()
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            assert list(pdf.attachments.keys()) == []
            assert "/AF" not in pdf.Root

    def test_non_pdfa_document_unaffected_by_default(self):
        doc = _sample_document()
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            with pdf.open_metadata() as meta:
                assert "pdfaid:part" not in meta

    def test_embed_spec_double_build_is_byte_identical(self):
        doc = _sample_document()
        first = doc.render(embed_spec=True)
        second = doc.render(embed_spec=True)
        assert first == second


class TestEmbedSpecPdfaPart:
    def test_pdfa_document_forces_part_3(self):
        doc = _sample_document(pdfa=True)
        data = doc.render(embed_spec=True)
        with pikepdf.open(io.BytesIO(data)) as pdf:
            with pdf.open_metadata() as meta:
                assert meta["pdfaid:part"] == "3"

    def test_pdfa_document_without_embed_spec_stays_part_2(self):
        # No table/chart: those auto-attach CSV data under pdfa=True
        # regardless of embed_spec, which would legitimately force part 3.
        doc = Document(title="Plain", pdfa=True)
        doc.heading("Overview", level=1)
        doc.paragraph("No attachments here.")
        data = doc.render()
        with pikepdf.open(io.BytesIO(data)) as pdf:
            with pdf.open_metadata() as meta:
                assert meta["pdfaid:part"] == "2"


# -- Document.from_pdf --


class TestFromPdfAttachmentRecovery:
    def test_recovers_equivalent_document_from_attachment(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        recovered = Document.from_pdf(data)

        original_headings = [e.text for e in doc.content if isinstance(e, Heading)]
        recovered_headings = [
            e.text for e in recovered.content if isinstance(e, Heading)
        ]
        assert recovered_headings == original_headings
        original_paragraph = next(
            e for e in doc.content if isinstance(e, Paragraph)
        ).plain_text
        recovered_paragraph = next(
            e for e in recovered.content if isinstance(e, Paragraph)
        ).plain_text
        assert recovered_paragraph == original_paragraph

    def test_recover_from_attachment_returns_none_without_one(self):
        doc = _sample_document()
        data = doc.render()
        assert recover_from_attachment(data) is None

    def test_from_pdf_accepts_a_path(self, tmp_path):
        doc = _sample_document()
        path = tmp_path / "doc.pdf"
        doc.save(path, embed_spec=True)
        recovered = Document.from_pdf(path)
        assert recovered.title == "Sample Report"


class TestFromPdfStructureTreeRecovery:
    def test_recovers_headings_paragraphs_and_table_after_attachment_stripped(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        stripped = _strip_attachment_names(data)

        recovered = Document.from_pdf(stripped)

        headings = [e.text for e in recovered.content if isinstance(e, Heading)]
        assert "Overview" in headings
        paragraph = next(e for e in recovered.content if isinstance(e, Paragraph))
        assert paragraph.plain_text == "This is a test paragraph with some words."
        table = next(e for e in recovered.content if isinstance(e, Table))
        assert [c.plain_text for c in table.header_cells] == ["A", "B"]
        assert [[c.plain_text for c in row] for row in table.body_rows] == [
            ["1", "2"],
            ["3", "4"],
        ]

    def test_recovers_bullet_and_numbered_lists_in_order(self):
        doc = _sample_document()
        data = doc.render()
        recovered = Document.from_pdf(data)

        types_in_order = [type(e).__name__ for e in recovered.content]
        assert "BulletList" in types_in_order
        assert "NumberedList" in types_in_order
        assert types_in_order.index("BulletList") < types_in_order.index("NumberedList")
        bullets = next(e for e in recovered.content if isinstance(e, BulletList))
        assert ["".join(r.text for r in runs) for runs in bullets.item_runs] == [
            "first item",
            "second item",
            "third item",
        ]

    def test_content_order_matches_original(self):
        doc = _sample_document()
        data = doc.render()
        recovered = Document.from_pdf(data)
        # "Sample Report" != "Overview" so the render pipeline prepends its
        # own title heading; both Headings precede the body content below.
        tags = [type(e).__name__ for e in recovered.content]
        body_order = [
            t for t in tags if t in ("Paragraph", "BulletList", "NumberedList", "Table")
        ]
        assert body_order == ["Paragraph", "BulletList", "NumberedList", "Table"]
        assert tags.index("Paragraph") > tags.index("Heading")

    def test_node_ids_survive_with_split_suffix_stripped(self):
        long_text = ("word " * 900).strip()
        doc = Document(title="Split", content=[Paragraph(long_text, id="big")])
        data = doc.render()

        with pikepdf.open(io.BytesIO(data)) as pdf:
            ids_in_tree = _tree_ids(pdf)
        assert "big" in ids_in_tree
        assert "big~1" in ids_in_tree

        recovered = Document.from_pdf(data)
        big_paragraphs = [
            e for e in recovered.content if isinstance(e, Paragraph) and e.id == "big"
        ]
        assert len(big_paragraphs) == 2
        # The inter-page word-gap isn't a drawn character, so summing the
        # two recovered halves loses exactly the one boundary space.
        recovered_total = sum(len(p.plain_text) for p in big_paragraphs)
        assert len(long_text) - recovered_total <= 1
        assert all(p.plain_text.strip() for p in big_paragraphs)

    def test_strict_raises_without_attachment(self):
        doc = _sample_document()
        data = doc.render()
        with pytest.raises(ValueError, match="strict"):
            Document.from_pdf(data, strict=True)

    def test_recover_from_structure_tree_directly(self):
        doc = _sample_document()
        data = doc.render()
        recovered = recover_from_structure_tree(data)
        assert recovered.title == "Sample Report"
        assert any(isinstance(e, Heading) for e in recovered.content)


# -- emboss strip --


class TestStripPdf:
    def test_removes_all_attachments(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        stripped = strip_pdf(data)
        with pikepdf.open(io.BytesIO(stripped)) as pdf:
            assert dict(pdf.attachments) == {}
            assert "/AF" not in pdf.Root

    def test_removes_id_tree_and_element_ids(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        stripped = strip_pdf(data)
        with pikepdf.open(io.BytesIO(stripped)) as pdf:
            assert "/IDTree" not in pdf.Root.StructTreeRoot
            assert _tree_ids(pdf) == []

    def test_keeps_title_author_and_dates_removes_producer_creator(self):
        doc = _sample_document(author="Jane Doe")
        data = doc.render(embed_spec=True)
        stripped = strip_pdf(data)
        with pikepdf.open(io.BytesIO(stripped)) as pdf:
            info = pdf.docinfo
            assert str(info["/Title"]) == "Sample Report"
            assert str(info["/Author"]) == "Jane Doe"
            assert "/Producer" not in info
            assert "/Creator" not in info
            with pdf.open_metadata() as meta:
                assert "xmp:CreatorTool" not in meta
                assert "pdf:Producer" not in meta
                assert str(meta["dc:title"]) == "Sample Report"

    def test_output_remains_valid_and_renderable(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        stripped = strip_pdf(data)
        report = verify_pdf(stripped)
        assert report.ok, report.problems
        with pikepdf.open(io.BytesIO(stripped)) as pdf:
            assert len(pdf.pages) >= 1

    def test_strip_is_deterministic(self):
        doc = _sample_document()
        data = doc.render(embed_spec=True)
        first = strip_pdf(data)
        second = strip_pdf(data)
        assert first == second

    def test_cli_strip_subcommand(self, tmp_path):
        from emboss.__main__ import main

        doc = _sample_document()
        src = tmp_path / "in.pdf"
        doc.save(src, embed_spec=True)
        out = tmp_path / "out.pdf"

        code = main(["strip", str(src), "-o", str(out), "-q"])
        assert code == 0
        with pikepdf.open(out) as pdf:
            assert dict(pdf.attachments) == {}

    def test_cli_strip_missing_file_reports_error(self, tmp_path, capsys):
        from emboss.__main__ import main

        code = main(["strip", str(tmp_path / "missing.pdf")])
        captured = capsys.readouterr()
        assert code == 1
        assert "not found" in captured.err
