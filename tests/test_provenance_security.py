"""Tests for the reproducibility manifest, redaction-by-construction,
DocMDP certification, encrypted attachments, and signed lineage."""

from __future__ import annotations

import hashlib
import io
import json
import re

import pytest

from emboss import Document
from emboss.manifest import MANIFEST_FILENAME, build_manifest, reproduce
from emboss.pdf.assembler import PDFAssembler
from emboss.pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream
from emboss.recovery import document_to_spec_dict, spec_dict_to_json
from emboss.redaction import (
    RedactionRule,
    decrypt_attachment,
    encrypt_attachment,
    redact_document,
)
from emboss.signing import (
    SignatureField,
    build_acroform,
    build_certifying_signature,
    build_docmdp_reference,
    build_perms_dict,
    build_sig_field_dict,
)


def _sample_document(**kw) -> Document:
    doc = Document(title="Provenance Test", **kw)
    doc.heading("Section", level=1)
    doc.paragraph("Body text for the provenance test document.")
    doc.table(headers=["A", "B"], rows=[["1", "2"]])
    return doc


# -- reproducibility manifest ------------------------------------------------


class TestManifest:
    def test_spec_sha256_matches_independent_hash(self):
        doc = _sample_document()
        manifest = doc.reproducibility_manifest()
        expected = hashlib.sha256(
            spec_dict_to_json(document_to_spec_dict(doc))
        ).hexdigest()
        assert manifest["spec_sha256"] == expected

    def test_manifest_has_expected_shape(self):
        doc = _sample_document()
        manifest = doc.reproducibility_manifest()
        assert set(manifest) >= {
            "spec_sha256",
            "emboss_version",
            "fonts",
            "render_options",
        }
        assert (
            isinstance(manifest["emboss_version"], str) and manifest["emboss_version"]
        )
        assert manifest["render_options"] == {}

    def test_manifest_lists_embedded_font_hashes(self):
        doc = _sample_document(pdfa=True)
        manifest = doc.reproducibility_manifest()
        assert manifest["fonts"], "expected at least one embedded font"
        for entry in manifest["fonts"]:
            assert set(entry) == {"family", "sha256"}
            assert len(entry["sha256"]) == 64
            int(entry["sha256"], 16)  # valid hex
        assert manifest["render_options"]["pdfa"] is True

    def test_render_options_capture_non_defaults(self):
        doc = _sample_document(color_mode="cmyk", toc=True)
        manifest = doc.reproducibility_manifest(embed_spec=True)
        assert manifest["render_options"]["color_mode"] == "cmyk"
        assert manifest["render_options"]["toc"] is True
        assert manifest["render_options"]["embed_spec"] is True

    def test_manifest_attached_and_extractable(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = _sample_document()
        pdf_bytes = doc.render(manifest=True)
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            filespec = pdf.attachments[MANIFEST_FILENAME]
            assert str(filespec.obj.AFRelationship) == "/Supplement"
            raw = filespec.get_file().read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
        assert manifest["spec_sha256"] == doc.reproducibility_manifest()["spec_sha256"]

    def test_predecessor_sha256_argument_in_lineage(self):
        doc = _sample_document()
        predecessor = "deadbeef" * 8
        manifest = doc.reproducibility_manifest(predecessor_sha256=predecessor)
        assert manifest["lineage"]["predecessor_sha256"] == predecessor

    def test_predecessor_manifest_sha256_in_lineage(self):
        doc = _sample_document()
        manifest = build_manifest(
            doc,
            predecessor_sha256="a" * 64,
            predecessor_manifest_sha256="b" * 64,
        )
        assert manifest["lineage"] == {
            "predecessor_sha256": "a" * 64,
            "predecessor_manifest_sha256": "b" * 64,
        }

    def test_document_predecessor_field_feeds_manifest(self):
        doc = _sample_document()
        doc.predecessor = "cafebabe" * 8
        manifest = doc.reproducibility_manifest()
        assert manifest["lineage"]["predecessor_sha256"] == "cafebabe" * 8

    def test_no_lineage_key_when_no_predecessor(self):
        doc = _sample_document()
        manifest = doc.reproducibility_manifest()
        assert "lineage" not in manifest

    def test_manifest_is_deterministic(self):
        def build() -> dict:
            return _sample_document().reproducibility_manifest()

        first = build()
        second = build()
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_manifest_render_is_byte_deterministic(self):
        def render() -> bytes:
            return _sample_document().render(manifest=True)

        assert render() == render()


# -- emboss reproduce --------------------------------------------------------


_TJ_STRING_RE = re.compile(rb"\(([ -~]{3,})\)\s*Tj")


def _tamper_visible_text(pdf_bytes: bytes) -> bytes:
    """Hand-tamper a rendered PDF's visible text via pikepdf, post-render."""
    import pikepdf

    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        tampered = False
        for page in pdf.pages:
            contents = page.get("/Contents")
            if contents is None:
                continue
            data = bytearray(contents.read_bytes())
            match = _TJ_STRING_RE.search(bytes(data))
            if match is None:
                continue
            pos = match.start(1)
            original = data[pos]
            data[pos] = ord("Z") if chr(original) != "Z" else ord("Q")
            page.Contents.write(bytes(data))
            tampered = True
            break
        assert tampered, "no Tj text found in the PDF to tamper with"
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()


class TestReproduce:
    def test_round_trip_passes(self, tmp_path):
        pytest.importorskip("pikepdf")
        doc = _sample_document()
        pdf_bytes = doc.render(embed_spec=True, manifest=True)
        path = tmp_path / "original.pdf"
        path.write_bytes(pdf_bytes)

        report = reproduce(path)
        assert report.ok, str(report)
        assert "PASS" in str(report)
        assert report.original_pages == report.reproduced_pages

    def test_round_trip_passes_from_bytes(self):
        pytest.importorskip("pikepdf")
        doc = _sample_document()
        pdf_bytes = doc.render(embed_spec=True, manifest=True)
        report = reproduce(pdf_bytes)
        assert report.ok, str(report)

    def test_tampered_pdf_reports_fail(self, tmp_path):
        pytest.importorskip("pikepdf")
        doc = _sample_document()
        pdf_bytes = doc.render(embed_spec=True, manifest=True)
        tampered = _tamper_visible_text(pdf_bytes)
        assert tampered != pdf_bytes

        path = tmp_path / "tampered.pdf"
        path.write_bytes(tampered)

        report = reproduce(path)
        assert not report.ok
        text = str(report)
        assert "FAIL" in text
        assert report.diffs, "expected a diff summary explaining the mismatch"


# -- redaction by construction -----------------------------------------------


class TestRedactionByConstruction:
    def _ssn_document(self) -> Document:
        doc = Document(title="Redaction Test")
        doc.paragraph("Employee SSN: 123-45-6789 is on file.")
        doc.paragraph("This paragraph is unrelated and stays in the output.")
        return doc

    def test_ssn_removed_from_decompressed_content_streams(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = self._ssn_document()
        rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}")

        redacted = doc.redact([rule])
        pdf_bytes = redacted.render()

        assert b"123-45-6789" not in pdf_bytes
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                contents = page.get("/Contents")
                if contents is None:
                    continue
                assert b"123-45-6789" not in contents.read_bytes()

    def test_unrelated_content_survives(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = self._ssn_document()
        rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}")
        redacted = doc.redact([rule])
        pdf_bytes = redacted.render()

        found = False
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                contents = page.get("/Contents")
                if contents is not None and b"unrelated" in contents.read_bytes():
                    found = True
        assert found, "expected the unredacted paragraph's text to survive"

    def test_redaction_log_records_rule_and_text(self):
        doc = self._ssn_document()
        rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}")
        redacted = doc.redact([rule])

        log = redacted.redaction_log
        assert len(log) == 1
        entry = log[0]
        assert entry["rule"] == "ssn"
        assert entry["element_type"] == "Paragraph"
        assert "123-45-6789" in entry["text"]
        assert entry["mode"] == "placeholder"
        assert entry["node_id"]

    def test_redaction_log_never_in_output_attachments(self):
        pikepdf = pytest.importorskip("pikepdf")
        doc = self._ssn_document()
        rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}")
        redacted = doc.redact([rule])

        pdf_bytes = redacted.render(embed_spec=True, manifest=True)
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            names = list(pdf.attachments.keys())
            assert names, "expected embed_spec/manifest attachments to be present"
            for name in names:
                payload = bytes(pdf.attachments[name].get_file().read_bytes())
                assert b"123-45-6789" not in payload, (
                    f"redacted SSN leaked into attachment {name!r}"
                )

    def test_redaction_log_not_a_document_attribute_by_default(self):
        doc = self._ssn_document()
        assert not hasattr(doc, "redaction_log")

    def test_remove_mode_drops_block_entirely(self):
        doc = self._ssn_document()
        rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}", mode="remove")
        redacted = doc.redact([rule])

        assert len(redacted.content) == 1
        assert "unrelated" in redacted.content[0].plain_text
        pdf_bytes = redacted.render()
        assert b"123-45-6789" not in pdf_bytes

    def test_node_id_rule_matches_specific_block(self):
        import copy

        from emboss.nodeid import assign_node_ids

        doc = self._ssn_document()
        probe = copy.deepcopy(doc)
        ids = assign_node_ids(probe.content)
        target_id = ids[0]

        rule = RedactionRule(name="by-id", node_id=target_id, mode="remove")
        redacted = doc.redact([rule])
        assert len(redacted.content) == 1

    def test_element_type_rule_matches_by_type(self):
        doc = Document(title="Type Rule Test")
        doc.heading("Heading stays", level=1)
        doc.paragraph("Paragraph removed by type.")
        from emboss.spec import Paragraph

        rule = RedactionRule(
            name="all-paragraphs", element_type=Paragraph, mode="remove"
        )
        redacted = doc.redact([rule])
        assert len(redacted.content) == 1
        assert redacted.content[0].text == "Heading stays"

    def test_rule_requires_at_least_one_criterion(self):
        with pytest.raises(ValueError, match="must match on at least one"):
            RedactionRule(name="empty")

    def test_placeholder_mode_unsupported_type_raises(self):
        doc = Document(title="Unsupported Placeholder")
        doc.image("nonexistent.png", alt_text="a photo")
        rule = RedactionRule(name="img", element_type=type(doc.content[0]))
        with pytest.raises(TypeError, match="no construction-time placeholder"):
            doc.redact([rule])

    def test_redact_document_helper_returns_tuple(self):
        doc = self._ssn_document()
        rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}")
        redacted, log = redact_document(doc, [rule])
        assert isinstance(redacted, Document)
        assert isinstance(log, list) and log

    def test_redaction_is_deterministic(self):
        def build() -> bytes:
            doc = self._ssn_document()
            rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}")
            return doc.redact([rule]).render()

        assert build() == build()

    def test_original_document_untouched(self):
        doc = self._ssn_document()
        rule = RedactionRule(name="ssn", pattern=r"\d{3}-\d{2}-\d{4}")
        doc.redact([rule])
        assert "123-45-6789" in doc.content[0].plain_text


# -- DocMDP certification ----------------------------------------------------


def _assembler_with_page():
    assembler = PDFAssembler()
    content_ref = assembler.add(PdfStream(data=b"BT ET", compress=False))
    page = PdfDict()
    page["Type"] = PdfName("Page")
    page["MediaBox"] = PdfArray([0, 0, 612, 792])
    page["Contents"] = content_ref
    page["Resources"] = PdfDict()
    page_ref = assembler.add(page)
    return assembler, page_ref


class TestDocMDP:
    def test_build_docmdp_reference_shape(self):
        reference = build_docmdp_reference(2)
        assert reference["TransformMethod"] == PdfName("DocMDP")
        assert reference["Type"] == PdfName("SigRef")
        assert reference["TransformParams"]["P"] == 2
        assert reference["TransformParams"]["Type"] == PdfName("TransformParams")

    def test_build_docmdp_reference_rejects_bad_permission(self):
        with pytest.raises(ValueError, match="docmdp_permission"):
            build_docmdp_reference(9)

    def test_certify_true_adds_docmdp_reference_with_permission(self):
        assembler, page_ref = _assembler_with_page()
        sig = SignatureField(page_index=0, x=10, y=10, signer_name="Alice")

        field_ref = build_sig_field_dict(
            assembler, sig, page_ref, certify=True, docmdp_permission=2
        )
        field = assembler._objects[field_ref.obj_id]
        sig_value = assembler._objects[field["V"].obj_id]

        assert "Reference" in sig_value
        reference_array = sig_value["Reference"]
        assert len(reference_array) == 1
        transform = reference_array.items[0]
        assert transform["TransformMethod"] == PdfName("DocMDP")
        assert transform["TransformParams"]["P"] == 2

    def test_certify_false_has_no_reference(self):
        assembler, page_ref = _assembler_with_page()
        sig = SignatureField(page_index=0, x=10, y=10)
        field_ref = build_sig_field_dict(assembler, sig, page_ref)
        field = assembler._objects[field_ref.obj_id]
        sig_value = assembler._objects[field["V"].obj_id]
        assert "Reference" not in sig_value

    def test_certifying_signature_is_structurally_first(self):
        assembler, page_ref = _assembler_with_page()

        other_sig = SignatureField(page_index=0, x=10, y=10, field_name="Signature1")
        other_ref = build_sig_field_dict(assembler, other_sig, page_ref)

        cert_sig = SignatureField(page_index=0, x=100, y=10, field_name="Signature2")
        cert_field_ref, perms = build_certifying_signature(
            assembler, cert_sig, page_ref, docmdp_permission=1
        )

        acroform = build_acroform(
            [other_ref, cert_field_ref], certifying_ref=cert_field_ref
        )
        assert acroform["Fields"].items[0] == cert_field_ref
        assert acroform["Fields"].items[1] == other_ref

        sig_value = assembler._objects[perms["DocMDP"].obj_id]
        assert sig_value["Reference"].items[0]["TransformParams"]["P"] == 1

    def test_build_acroform_rejects_unknown_certifying_ref(self):
        assembler, page_ref = _assembler_with_page()
        sig = SignatureField(page_index=0, x=10, y=10)
        ref = build_sig_field_dict(assembler, sig, page_ref)
        with pytest.raises(ValueError, match="certifying_ref"):
            build_acroform([ref], certifying_ref=PdfRef(999))

    def test_build_perms_dict_points_at_sig_value(self):
        ref = PdfRef(42)
        perms = build_perms_dict(ref)
        assert perms["DocMDP"] == ref


# -- encrypted attachment payloads -------------------------------------------


class TestEncryptedAttachment:
    def test_round_trip(self):
        pytest.importorskip("cryptography")
        blob = encrypt_attachment(b"top secret payload", "correct horse battery staple")
        assert (
            decrypt_attachment(blob, "correct horse battery staple")
            == b"top secret payload"
        )

    def test_wrong_password_fails(self):
        pytest.importorskip("cryptography")
        from cryptography.exceptions import InvalidTag

        blob = encrypt_attachment(b"top secret payload", "right password")
        with pytest.raises(InvalidTag):
            decrypt_attachment(blob, "wrong password")

    def test_blob_format_is_salt_nonce_ciphertext(self):
        pytest.importorskip("cryptography")
        data = b"x" * 100
        blob = encrypt_attachment(data, "pw")
        assert len(blob) == 16 + 12 + len(data) + 16  # salt + nonce + data + GCM tag

    def test_nonce_and_salt_are_random_excluded_from_determinism(self):
        pytest.importorskip("cryptography")
        blob1 = encrypt_attachment(b"same data", "same password")
        blob2 = encrypt_attachment(b"same data", "same password")
        assert blob1 != blob2
        assert decrypt_attachment(blob1, "same password") == b"same data"
        assert decrypt_attachment(blob2, "same password") == b"same data"

    def test_attach_encrypted_wires_relationship_and_round_trips(self):
        pytest.importorskip("cryptography")
        pikepdf = pytest.importorskip("pikepdf")

        doc = Document(title="Encrypted Attachment Test")
        doc.paragraph("Public content.")
        doc.attach_encrypted("secret.bin", b"classified payload", "hunter2")

        pdf_bytes = doc.render()
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            filespec = pdf.attachments["secret.bin"]
            assert str(filespec.obj.AFRelationship) == "/EncryptedPayload"
            ciphertext = bytes(filespec.get_file().read_bytes())

        assert decrypt_attachment(ciphertext, "hunter2") == b"classified payload"
        with pytest.raises(Exception):
            decrypt_attachment(ciphertext, "wrong")

    def test_attach_encrypted_returns_self_for_chaining(self):
        doc = Document(title="Chaining Test")
        pytest.importorskip("cryptography")
        result = doc.attach_encrypted("a.bin", b"data", "pw")
        assert result is doc


# -- signed lineage (manifest + DocMDP together) -----------------------------


class TestSignedLineage:
    def test_manifest_lineage_combines_with_predecessor_and_render(self):
        original = _sample_document()
        original_manifest = original.reproducibility_manifest()
        predecessor_sha = original_manifest["spec_sha256"]

        derivative = _sample_document()
        derivative.predecessor = predecessor_sha
        pdf_bytes = derivative.render(manifest=True)

        pikepdf = pytest.importorskip("pikepdf")
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            raw = pdf.attachments[MANIFEST_FILENAME].get_file().read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
        assert manifest["lineage"]["predecessor_sha256"] == predecessor_sha
