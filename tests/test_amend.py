"""Tests for append-only incremental amendment.

Failure paths first: a DocMDP-illegal amendment must raise, and appended
content that no signature covers must be reported. The incremental-writer,
revision-history, and coverage tests run without the cryptography package;
only the real-signing tests are gated on ``can_sign()``.
"""

from __future__ import annotations

import datetime
import io

import pytest

from emboss import Document
from emboss.amend import (
    Attestation,
    Revision,
    _read_docmdp_permission,
    amend_pdf,
    amend_sign,
    coverage_report,
    format_history,
    prepare_signature,
    revision_history,
    verify_amended,
)
from emboss.pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream
from emboss.signing import (
    SignatureField,
    build_acroform,
    build_certifying_signature,
    can_sign,
)

pytest.importorskip("pikepdf")

_TS = "D:20240101000000Z"


# -- fixtures ----------------------------------------------------------------


def _base_pdf(**kw) -> bytes:
    doc = Document(title="Amend Base", **kw)
    doc.heading("Section", level=1)
    doc.paragraph("Body text one two three four five.")
    doc.table(headers=["A", "B"], rows=[["1", "2"]])
    return doc.render()


def _certified_pdf(permission: int) -> bytes:
    """Assemble a minimal PDF certified with a DocMDP /P permission."""
    from emboss.pdf.assembler import PDFAssembler

    asm = PDFAssembler()
    content_ref = asm.add(PdfStream(data=b"BT ET", compress=False))
    pages_id = asm.allocate()
    page = PdfDict()
    page["Type"] = PdfName("Page")
    page["MediaBox"] = PdfArray([0, 0, 612, 792])
    page["Contents"] = content_ref
    page["Resources"] = PdfDict()
    page["Parent"] = PdfRef(pages_id)
    page_ref = asm.add(page)
    pages = PdfDict()
    pages["Type"] = PdfName("Pages")
    pages["Kids"] = PdfArray([page_ref])
    pages["Count"] = 1
    asm.add(pages, pages_id)
    sig = SignatureField(page_index=0, x=10, y=10, signer_name="Cert", field_name="C1")
    field_ref, perms = build_certifying_signature(
        asm, sig, page_ref, docmdp_permission=permission
    )
    acroform = build_acroform([field_ref], certifying_ref=field_ref)
    catalog = PdfDict()
    catalog["Type"] = PdfName("Catalog")
    catalog["Pages"] = PdfRef(pages_id)
    catalog["AcroForm"] = acroform
    catalog["Perms"] = perms
    catalog_ref = asm.add(catalog)
    return asm.build(catalog_ref)


def _annotation(**kw) -> Attestation:
    defaults = dict(
        kind="annotations",
        name="Alice",
        reason="Approved",
        page_index=0,
        rect=(400, 700, 560, 760),
        text="Approved by Alice",
    )
    defaults.update(kw)
    return Attestation(**defaults)


# -- failure path: DocMDP enforcement ----------------------------------------


class TestDocMDPEnforcement:
    def test_p1_forbids_every_amendment(self):
        pdf = _certified_pdf(1)
        with pytest.raises(ValueError, match=r"/P=1"):
            amend_pdf(pdf, attestation=_annotation(), timestamp=_TS)
        with pytest.raises(ValueError, match=r"/P=1"):
            amend_pdf(
                pdf,
                attestation=Attestation(
                    kind="attachment", filename="a.txt", payload=b"x"
                ),
                timestamp=_TS,
            )
        with pytest.raises(ValueError, match=r"/P=1"):
            prepare_signature(pdf, timestamp=_TS)

    def test_p2_allows_signature_but_forbids_annotations(self):
        pdf = _certified_pdf(2)
        with pytest.raises(ValueError, match="annotations"):
            amend_pdf(pdf, attestation=_annotation(), timestamp=_TS)
        with pytest.raises(ValueError, match="attachment"):
            amend_pdf(
                pdf,
                attestation=Attestation(
                    kind="attachment", filename="a.txt", payload=b"x"
                ),
                timestamp=_TS,
            )
        # signature is permitted under /P=2
        out = prepare_signature(pdf, timestamp=_TS)
        assert out.startswith(pdf)

    def test_p3_allows_annotations_and_signature_not_attachment(self):
        pdf = _certified_pdf(3)
        assert amend_pdf(pdf, attestation=_annotation(), timestamp=_TS).startswith(pdf)
        assert prepare_signature(pdf, timestamp=_TS).startswith(pdf)
        with pytest.raises(ValueError, match="attachment"):
            amend_pdf(
                pdf,
                attestation=Attestation(
                    kind="attachment", filename="a.txt", payload=b"x"
                ),
                timestamp=_TS,
            )

    def test_enforcement_names_the_violation(self):
        pdf = _certified_pdf(1)
        with pytest.raises(ValueError) as excinfo:
            amend_pdf(pdf, attestation=_annotation(), timestamp=_TS)
        message = str(excinfo.value)
        assert "annotations" in message
        assert "DocMDP" in message

    def test_enforce_flag_can_be_disabled(self):
        pdf = _certified_pdf(1)
        out = amend_pdf(
            pdf, attestation=_annotation(), timestamp=_TS, enforce_docmdp=False
        )
        assert out.startswith(pdf)

    def test_uncertified_base_has_no_permission(self):
        assert _read_docmdp_permission(_base_pdf()) is None

    def test_read_permission_matches_certification(self):
        for permission in (1, 2, 3):
            assert _read_docmdp_permission(_certified_pdf(permission)) == permission


# -- failure path: coverage-gap detection ------------------------------------


class TestCoverageGap:
    def _base_then_sig_then_content(self) -> bytes:
        base = _base_pdf()
        signed = prepare_signature(
            base, page_index=0, rect=(50, 50, 250, 110), name="Bob", timestamp=_TS
        )
        return amend_pdf(
            signed, attestation=_annotation(text="added later"), timestamp=_TS
        )

    def test_content_after_signature_is_not_covered(self):
        pdf = self._base_then_sig_then_content()
        report = coverage_report(pdf)
        assert not report.fully_covered
        assert report.uncovered == [2]

    def test_revisions_before_signature_are_covered(self):
        pdf = self._base_then_sig_then_content()
        revisions = revision_history(pdf)
        assert revisions[0].kind == "base" and revisions[0].covered
        assert revisions[1].kind == "signature" and revisions[1].covered
        assert revisions[2].kind == "annotations" and not revisions[2].covered

    def test_signature_bytebrange_end_matches_its_revision(self):
        base = _base_pdf()
        signed = prepare_signature(base, timestamp=_TS)
        sig = revision_history(signed)[1]
        assert sig.sig_byte_range is not None
        start2, len2 = sig.sig_byte_range[2], sig.sig_byte_range[3]
        assert start2 + len2 == sig.byte_range[1]

    def test_signature_with_no_later_content_is_fully_covered(self):
        base = _base_pdf()
        signed = prepare_signature(base, timestamp=_TS)
        report = coverage_report(signed)
        assert report.fully_covered
        assert report.uncovered == []
        assert report.signatures == [1]

    def test_covered_by_lists_the_signature_index(self):
        pdf = self._base_then_sig_then_content()
        revisions = revision_history(pdf)
        assert revisions[0].covered_by == [1]
        assert revisions[2].covered_by == []


# -- incremental writer ------------------------------------------------------


class TestIncrementalWriter:
    def test_prefix_invariant_annotation(self):
        base = _base_pdf()
        out = amend_pdf(base, attestation=_annotation(), timestamp=_TS)
        assert out.startswith(base)
        assert len(out) > len(base)

    def test_prefix_invariant_across_a_chain(self):
        base = _base_pdf()
        a1 = amend_pdf(base, attestation=_annotation(), timestamp=_TS)
        a2 = amend_pdf(
            a1,
            attestation=Attestation(
                kind="attachment", filename="a.txt", payload=b"data"
            ),
            timestamp=_TS,
        )
        assert a1.startswith(base)
        assert a2.startswith(a1)
        assert a2.startswith(base)

    def test_amended_pdf_reopens(self):
        import pikepdf

        out = amend_pdf(_base_pdf(), attestation=_annotation(), timestamp=_TS)
        with pikepdf.open(io.BytesIO(out)) as pdf:
            assert len(pdf.pages) == 1

    def test_object_numbering_continues(self):
        import pikepdf

        base = _base_pdf()
        with pikepdf.open(io.BytesIO(base)) as pdf:
            base_size = int(pdf.trailer.Size)
        out = amend_pdf(base, attestation=_annotation(), timestamp=_TS)
        with pikepdf.open(io.BytesIO(out)) as pdf:
            assert int(pdf.trailer.Size) > base_size

    def test_trailer_has_prev_pointer(self):
        base = _base_pdf()
        out = amend_pdf(base, attestation=_annotation(), timestamp=_TS)
        appended = out[len(base) :]
        assert b"/Prev" in appended
        assert b"%%EOF" in appended

    def test_deterministic_with_fixed_timestamp(self):
        base = _base_pdf()
        first = amend_pdf(base, attestation=_annotation(), timestamp=_TS)
        second = amend_pdf(base, attestation=_annotation(), timestamp=_TS)
        assert first == second

    def test_requires_exactly_one_of_attestation_or_build(self):
        base = _base_pdf()
        with pytest.raises(ValueError, match="exactly one"):
            amend_pdf(base, timestamp=_TS)
        with pytest.raises(ValueError, match="exactly one"):
            amend_pdf(
                base,
                attestation=_annotation(),
                build=lambda inc, b: None,
                timestamp=_TS,
            )

    def test_build_callback_appends_raw_objects(self):
        import pikepdf

        base = _base_pdf()

        def build(inc, base_info):
            note = PdfDict()
            note["Type"] = PdfName("EmbossAttestation")
            note["Note"] = "signed off"
            ref = inc.add(note)
            root = base_info.root_dict
            root["EmbossAttestations"] = PdfArray([ref])
            inc.add(root, base_info.root_ref.obj_id)
            return base_info.root_ref

        out = amend_pdf(base, build=build, kind="other", timestamp=_TS)
        assert out.startswith(base)
        with pikepdf.open(io.BytesIO(out)) as pdf:
            assert "/EmbossAttestations" in pdf.Root

    def test_encrypted_base_raises(self):
        import pikepdf

        base = _base_pdf()
        buffer = io.BytesIO()
        with pikepdf.open(io.BytesIO(base)) as pdf:
            pdf.save(buffer, encryption=pikepdf.Encryption(owner="o", user="u", R=4))
        encrypted = buffer.getvalue()
        with pytest.raises(ValueError, match="encrypted"):
            amend_pdf(
                encrypted,
                attestation=_annotation(),
                timestamp=_TS,
                enforce_docmdp=False,
            )


# -- attestation wiring ------------------------------------------------------


class TestAttestationWiring:
    def test_annotation_appears_on_page(self):
        import pikepdf

        out = amend_pdf(_base_pdf(), attestation=_annotation(), timestamp=_TS)
        with pikepdf.open(io.BytesIO(out)) as pdf:
            annots = pdf.pages[0].get("/Annots")
            assert annots is not None and len(annots) >= 1
            assert str(annots[0].Subtype) == "/Text"
            assert str(annots[0].Contents) == "Approved by Alice"

    def test_attachment_is_embedded(self):
        import pikepdf

        att = Attestation(kind="attachment", filename="approval.txt", payload=b"ok")
        out = amend_pdf(_base_pdf(), attestation=att, timestamp=_TS)
        with pikepdf.open(io.BytesIO(out)) as pdf:
            assert "approval.txt" in pdf.attachments
            data = bytes(pdf.attachments["approval.txt"].get_file().read_bytes())
            assert data == b"ok"

    def test_attachment_requires_filename(self):
        with pytest.raises(ValueError, match="filename"):
            Attestation(kind="attachment", payload=b"x")

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="annotations' or 'attachment'"):
            Attestation(kind="bogus")


# -- revision history --------------------------------------------------------


class TestRevisionHistory:
    def test_base_only_reports_single_revision(self):
        revisions = revision_history(_base_pdf())
        assert len(revisions) == 1
        assert revisions[0].kind == "base"
        assert revisions[0].covered is False

    def test_byte_ranges_are_contiguous_and_complete(self):
        base = _base_pdf()
        pdf = amend_pdf(base, attestation=_annotation(), timestamp=_TS)
        revisions = revision_history(pdf)
        assert revisions[0].byte_range[0] == 0
        for earlier, later in zip(revisions, revisions[1:]):
            assert earlier.byte_range[1] == later.byte_range[0]
        assert revisions[-1].byte_range[1] == len(pdf)

    def test_signature_signer_and_reason_parsed(self):
        base = _base_pdf()
        pdf = prepare_signature(
            base, name="Dana", reason="Final approval", timestamp=_TS
        )
        sig = revision_history(pdf)[1]
        assert sig.signer == "Dana"
        assert sig.reason == "Final approval"

    def test_prepared_signature_is_unsigned(self):
        pdf = prepare_signature(_base_pdf(), name="Eve", timestamp=_TS)
        sig = revision_history(pdf)[1]
        assert sig.sig_byte_range is not None
        assert sig.signed is False

    def test_attachment_revision_classified(self):
        att = Attestation(kind="attachment", filename="a.txt", payload=b"x")
        pdf = amend_pdf(_base_pdf(), attestation=att, timestamp=_TS)
        assert revision_history(pdf)[1].kind == "attachment"

    def test_returns_revision_dataclasses(self):
        revisions = revision_history(_base_pdf())
        assert all(isinstance(r, Revision) for r in revisions)


# -- reporting ---------------------------------------------------------------


class TestReporting:
    def test_format_history_from_bytes(self):
        base = _base_pdf()
        signed = prepare_signature(base, name="Bob", timestamp=_TS)
        pdf = amend_pdf(signed, attestation=_annotation(text="late"), timestamp=_TS)
        text = format_history(pdf)
        assert "Rev" in text
        assert "signature" in text
        assert "NOT covered by any signature" in text

    def test_format_history_from_revisions(self):
        revisions = revision_history(_base_pdf())
        text = format_history(revisions)
        assert "base" in text

    def test_coverage_report_str_is_the_table(self):
        pdf = prepare_signature(_base_pdf(), timestamp=_TS)
        report = coverage_report(pdf)
        assert str(report) == format_history(report.revisions)

    def test_verify_amended_ok(self):
        pdf = amend_pdf(_base_pdf(), attestation=_annotation(), timestamp=_TS)
        report = verify_amended(pdf)
        assert report.ok, report.problems


# -- real signing (gated on cryptography) ------------------------------------


@pytest.fixture(scope="module")
def cert_and_key(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Signer")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2020, 1, 1))
        .not_valid_after(datetime.datetime(2030, 1, 1))
        .sign(key, hashes.SHA256())
    )
    directory = tmp_path_factory.mktemp("pki")
    key_path = directory / "key.pem"
    cert_path = directory / "cert.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(cert_path), str(key_path)


@pytest.mark.skipif(not can_sign(), reason="requires the cryptography package")
class TestAmendSign:
    def test_amend_sign_preserves_prefix(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign(
            base,
            cert=cert,
            key=key,
            name="Test Signer",
            reason="Approved",
            timestamp=_TS,
        )
        assert signed.startswith(base)

    def test_amend_sign_populates_contents(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign(base, cert=cert, key=key, name="Test Signer", timestamp=_TS)
        sig = revision_history(signed)[1]
        assert sig.kind == "signature"
        assert sig.signed is True

    def test_amend_sign_byte_range_covers_whole_file(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign(base, cert=cert, key=key, name="Test Signer", timestamp=_TS)
        sig = revision_history(signed)[1]
        assert sig.sig_byte_range[0] == 0
        assert sig.sig_byte_range[2] + sig.sig_byte_range[3] == len(signed)

    def test_amend_sign_covers_base_revision(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign(base, cert=cert, key=key, name="Test Signer", timestamp=_TS)
        report = coverage_report(signed)
        assert report.fully_covered

    def test_amend_sign_reopens_with_acroform(self, cert_and_key):
        import pikepdf

        cert, key = cert_and_key
        signed = amend_sign(
            _base_pdf(), cert=cert, key=key, name="Test Signer", timestamp=_TS
        )
        with pikepdf.open(io.BytesIO(signed)) as pdf:
            assert pdf.Root.get("/AcroForm") is not None

    def test_amend_sign_blocked_by_p1_certification(self, cert_and_key):
        cert, key = cert_and_key
        pdf = _certified_pdf(1)
        with pytest.raises(ValueError, match=r"/P=1"):
            amend_sign(pdf, cert=cert, key=key, name="Test Signer", timestamp=_TS)

    def test_content_appended_after_signature_breaks_coverage(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign(base, cert=cert, key=key, name="Test Signer", timestamp=_TS)
        tampered = amend_pdf(
            signed, attestation=_annotation(text="post-signature edit"), timestamp=_TS
        )
        report = coverage_report(tampered)
        assert not report.fully_covered
        assert report.uncovered == [2]
