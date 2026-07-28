"""Tests for embedded files, /AF relationships, PDF/A-3, and veraPDF checks."""

from __future__ import annotations

import hashlib
import io
import os
import shutil

import pytest

from emboss.pdf.assembler import PDFAssembler
from emboss.pdf.attachments import (
    VALID_RELATIONSHIPS,
    FileAttachment,
    af_array,
    attach_files,
    build_embedded_file,
    build_names_tree,
)
from emboss.pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream, PdfString
from emboss.pdf.verify import (
    ConformanceReport,
    verify_conformance,
)
from emboss.pdfa import build_xmp_metadata, pdfa_part_for

PAYLOAD = b"month,revenue\nJan,100\nFeb,200\n"


def _minimal_pdf(files: list) -> bytes:
    """Assemble a one-page PDF with *files* attached, mirroring writer wiring."""
    assembler = PDFAssembler()
    catalog_id = assembler.allocate()
    pages_id = assembler.allocate()

    content_ref = assembler.add(PdfStream(data=b"BT ET", compress=False))
    page = PdfDict()
    page["Type"] = PdfName("Page")
    page["Parent"] = PdfRef(pages_id)
    page["MediaBox"] = PdfArray([0, 0, 612, 792])
    page["Contents"] = content_ref
    page["Resources"] = PdfDict()
    page_ref = assembler.add(page)

    pages = PdfDict()
    pages["Type"] = PdfName("Pages")
    pages["Kids"] = PdfArray([page_ref])
    pages["Count"] = 1
    assembler.add(pages, obj_id=pages_id)

    catalog = PdfDict()
    catalog["Type"] = PdfName("Catalog")
    catalog["Pages"] = PdfRef(pages_id)
    attach_files(assembler, catalog, files)
    assembler.add(catalog, obj_id=catalog_id)
    return assembler.build(PdfRef(catalog_id))


class TestBuildEmbeddedFile:
    def test_stream_holds_payload_and_md5_checksum(self):
        assembler = PDFAssembler()
        _spec_ref, ef_ref = build_embedded_file(
            assembler, "data.csv", PAYLOAD, "text/csv"
        )
        stream = assembler._objects[ef_ref.obj_id]
        assert stream.data == PAYLOAD
        assert stream.dictionary["Type"] == PdfName("EmbeddedFile")
        assert stream.dictionary["Subtype"] == PdfName("text/csv")
        params = stream.dictionary["Params"]
        assert params["Size"] == len(PAYLOAD)
        assert params["CheckSum"].value == hashlib.md5(PAYLOAD).digest()
        assert "CreationDate" not in params

    def test_payload_bytes_appear_in_assembled_file(self):
        pdf = _minimal_pdf([FileAttachment(name="data.csv", data=PAYLOAD)])
        assert PAYLOAD in pdf

    def test_filespec_has_relationship_uf_and_desc(self):
        assembler = PDFAssembler()
        spec_ref, ef_ref = build_embedded_file(
            assembler,
            "notes.txt",
            b"hello",
            "text/plain",
            description="Design notes",
            relationship="Source",
        )
        filespec = assembler._objects[spec_ref.obj_id]
        assert filespec["Type"] == PdfName("Filespec")
        assert filespec["F"] == PdfString("notes.txt")
        assert filespec["UF"] == PdfString("notes.txt")
        assert filespec["AFRelationship"] == PdfName("Source")
        assert filespec["Desc"] == PdfString("Design notes")
        assert filespec["EF"]["F"] == ef_ref
        assert filespec["EF"]["UF"] == ef_ref

    def test_creation_date_gets_pdf_date_prefix(self):
        assembler = PDFAssembler()
        _spec_ref, ef_ref = build_embedded_file(
            assembler, "a.txt", b"x", "text/plain", creation_date="20240101000000Z"
        )
        params = assembler._objects[ef_ref.obj_id].dictionary["Params"]
        assert params["CreationDate"] == PdfString("D:20240101000000Z")

    def test_invalid_relationship_raises(self):
        assembler = PDFAssembler()
        with pytest.raises(ValueError, match="AFRelationship"):
            build_embedded_file(
                assembler, "a.txt", b"x", "text/plain", relationship="Sibling"
            )

    def test_empty_name_raises(self):
        assembler = PDFAssembler()
        with pytest.raises(ValueError, match="non-empty"):
            build_embedded_file(assembler, "", b"x", "text/plain")

    def test_relationship_vocabulary_is_complete(self):
        assert VALID_RELATIONSHIPS == {
            "Source",
            "Data",
            "Alternative",
            "Supplement",
            "EncryptedPayload",
            "FormData",
            "Schema",
            "Unspecified",
        }


class TestNamesTree:
    def test_entries_sorted_by_name(self):
        refs = [PdfRef(10), PdfRef(11), PdfRef(12)]
        tree = build_names_tree(
            [("zeta.txt", refs[0]), ("alpha.txt", refs[1]), ("mid.txt", refs[2])]
        )
        items = tree["Names"].items
        assert [items[0], items[2], items[4]] == [
            PdfString("alpha.txt"),
            PdfString("mid.txt"),
            PdfString("zeta.txt"),
        ]
        assert [items[1], items[3], items[5]] == [refs[1], refs[2], refs[0]]

    def test_pairs_alternate_name_then_ref(self):
        tree = build_names_tree([("a", PdfRef(5)), ("b", PdfRef(6))])
        items = tree["Names"].items
        assert len(items) % 2 == 0
        assert all(isinstance(items[i], PdfString) for i in range(0, len(items), 2))
        assert all(isinstance(items[i], PdfRef) for i in range(1, len(items), 2))

    def test_duplicate_names_raise(self):
        with pytest.raises(ValueError, match="duplicate"):
            build_names_tree([("a", PdfRef(5)), ("a", PdfRef(6))])

    def test_af_array_wraps_refs(self):
        arr = af_array([PdfRef(3), PdfRef(4)])
        assert isinstance(arr, PdfArray)
        assert arr.items == [PdfRef(3), PdfRef(4)]


class TestAssembledAttachments:
    def test_pikepdf_sees_attachment_name_mime_relationship(self):
        pikepdf = pytest.importorskip("pikepdf")
        pdf_bytes = _minimal_pdf(
            [
                FileAttachment(
                    name="report-data.csv",
                    data=PAYLOAD,
                    mime="text/csv",
                    description="Source data",
                    relationship="Data",
                )
            ]
        )
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            assert list(pdf.attachments.keys()) == ["report-data.csv"]
            spec = pdf.attachments["report-data.csv"]
            attached = spec.get_file()
            assert attached.mime_type == "text/csv"
            assert attached.read_bytes() == PAYLOAD
            assert spec.obj.AFRelationship == pikepdf.Name("/Data")
            assert len(pdf.Root.AF) == 1
            assert pdf.Root.AF[0].F == "report-data.csv"

    def test_multiple_attachments_sorted_in_names_tree(self):
        pikepdf = pytest.importorskip("pikepdf")
        pdf_bytes = _minimal_pdf(
            [
                FileAttachment(name="z-last.txt", data=b"z", mime="text/plain"),
                FileAttachment(name="a-first.txt", data=b"a", mime="text/plain"),
            ]
        )
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            assert list(pdf.attachments.keys()) == ["a-first.txt", "z-last.txt"]
            assert len(pdf.Root.AF) == 2

    def test_attach_files_merges_existing_names_dict(self):
        assembler = PDFAssembler()
        catalog = PdfDict()
        existing = PdfDict()
        existing["Dests"] = PdfDict()
        catalog["Names"] = existing
        attach_files(assembler, catalog, [FileAttachment(name="x.txt", data=b"x")])
        assert catalog["Names"] is existing
        assert "Dests" in existing
        assert "EmbeddedFiles" in existing

    def test_attach_files_empty_list_is_noop(self):
        assembler = PDFAssembler()
        catalog = PdfDict()
        assert attach_files(assembler, catalog, []) == []
        assert "AF" not in catalog
        assert "Names" not in catalog

    def test_double_build_is_byte_identical(self):
        files = [
            FileAttachment(name="data.csv", data=PAYLOAD, mime="text/csv"),
            FileAttachment(name="spec.json", data=b'{"a":1}', mime="application/json"),
        ]
        assert _minimal_pdf(files) == _minimal_pdf(files)


class TestPdfaPart:
    _KW = dict(
        title="T",
        author="A",
        subject="S",
        keywords="",
        creator="C",
        producer="P",
        language="en-US",
    )

    def test_part_3_declares_pdfa3_conformance_b(self):
        text = build_xmp_metadata(**self._KW, part=3).decode("utf-8")
        assert "<pdfaid:part>3</pdfaid:part>" in text
        assert "<pdfaid:conformance>B</pdfaid:conformance>" in text
        assert "<pdfaid:part>2</pdfaid:part>" not in text

    def test_default_part_2_output_unchanged(self):
        default = build_xmp_metadata(**self._KW)
        explicit = build_xmp_metadata(**self._KW, part=2)
        assert default == explicit
        text = default.decode("utf-8")
        assert "<pdfaid:part>2</pdfaid:part>" in text
        assert "<pdfaid:conformance>B</pdfaid:conformance>" in text

    def test_invalid_part_raises(self):
        with pytest.raises(ValueError, match="part"):
            build_xmp_metadata(**self._KW, part=4)

    def test_pdfa_part_for_attachments(self):
        assert pdfa_part_for(False) == 2
        assert pdfa_part_for(True) == 3


def _emboss_pdfa_bytes() -> bytes:
    """Render a real, tagged PDF/A document for conformance checking."""
    from emboss import Document

    doc = Document(title="Conformance Sample", pdfa=True)
    doc.heading("Overview", level=1)
    doc.paragraph("A short document rendered by Emboss for veraPDF checking.")
    return doc.render()


_VERAPDF = os.environ.get("VERAPDF_PATH") or shutil.which("verapdf")
_requires_verapdf = pytest.mark.skipif(
    not _VERAPDF,
    reason="veraPDF not installed; set VERAPDF_PATH or add verapdf to PATH",
)


@_requires_verapdf
class TestVeraPdfIntegration:
    def test_report_structure_against_real_verapdf(self):
        report = verify_conformance(_emboss_pdfa_bytes(), flavour="2b")
        assert isinstance(report, ConformanceReport)
        assert report.flavour == "2b"
        assert isinstance(report.violations, list)
        assert str(report)

    @pytest.mark.xfail(
        strict=True,
        reason="PDF/A requires embedded fonts; base-14 embedding not yet wired",
    )
    def test_pdfa_output_is_conformant(self):
        report = verify_conformance(_emboss_pdfa_bytes(), flavour="2b")
        assert report.compliant, str(report)


class TestVeraPdfErrors:
    def test_absent_verapdf_raises_with_install_hint(self, monkeypatch):
        monkeypatch.delenv("VERAPDF_PATH", raising=False)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        with pytest.raises(RuntimeError, match="verapdf.org"):
            verify_conformance(_minimal_pdf([]), flavour="3b")

    def test_unknown_flavour_raises_value_error(self):
        with pytest.raises(ValueError, match="flavour"):
            verify_conformance(b"%PDF-1.7", flavour="9z")


@_requires_verapdf
class TestCliConformance:
    def _write_pdf(self, tmp_path) -> str:
        path = tmp_path / "doc.pdf"
        path.write_bytes(_emboss_pdfa_bytes())
        return str(path)

    def test_cli_conformance_runs_against_real_verapdf(self, tmp_path, capsys):
        from emboss.__main__ import main

        code = main(["verify", self._write_pdf(tmp_path), "--conformance", "2b"])
        out = capsys.readouterr().out
        assert code in (0, 1)
        assert "veraPDF conformance (2b)" in out


class TestCliConformanceErrors:
    def _write_pdf(self, tmp_path) -> str:
        path = tmp_path / "doc.pdf"
        path.write_bytes(_minimal_pdf([]))
        return str(path)

    def test_cli_missing_verapdf_reports_gracefully(
        self, tmp_path, monkeypatch, capsys
    ):
        from emboss.__main__ import main

        monkeypatch.delenv("VERAPDF_PATH", raising=False)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        code = main(["verify", self._write_pdf(tmp_path), "--conformance", "2b"])
        captured = capsys.readouterr()
        assert code == 1
        assert "conformance check unavailable" in captured.err

    def test_cli_without_flag_skips_conformance(self, tmp_path, capsys):
        from emboss.__main__ import main

        code = main(["verify", self._write_pdf(tmp_path)])
        out = capsys.readouterr().out
        assert code == 0
        assert "veraPDF" not in out
