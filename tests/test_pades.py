"""Tests for PAdES baseline (ETSI EN 319 142) signatures, levels B-B and B-T.

The DER/attribute helpers need no private key and run without the cryptography
package; the real-signing tests are gated on ``can_sign()``. A B-T timestamp is
supplied as a pre-fetched ``timestamp_token`` fixture so no network is touched.
"""

from __future__ import annotations

import datetime
import hashlib
import re

import pytest

from emboss import Document
from emboss.amend import amend_sign_pades, prepare_signature, revision_history
from emboss.pades import (
    PADES_SUBFILTER,
    TimestampError,
    build_signing_certificate_v2,
    build_signing_certificate_v2_attribute,
    build_timestamp_request,
    can_sign,
    parse_timestamp_response,
    sign_pdf_pades,
)

pytest.importorskip("pikepdf")

_TS = "D:20240101000000Z"
_SIGNING_TIME = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

# Independently derived OID DER encodings (not produced by emboss code).
_OID_SIGNING_CERT_V2_DER = bytes.fromhex("060B2A864886F70D010910022F")
_OID_MESSAGE_DIGEST_DER = bytes.fromhex("06092A864886F70D010904")
_OID_SHA256_DER = bytes.fromhex("0609608648016503040201")
_OID_SIGNATURE_TIMESTAMP_DER = bytes.fromhex("060B2A864886F70D010910020E")
_OID_ETSI_CADES = b"/ETSI.CAdES.detached"


# -- helpers -----------------------------------------------------------------


def _base_pdf() -> bytes:
    doc = Document(title="PAdES Base")
    doc.heading("Section", level=1)
    doc.paragraph("Body text one two three four five.")
    return doc.render()


def _der_total_len(der: bytes) -> int:
    """Return the total byte length of the first DER element in *der*."""
    length = der[1]
    idx = 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(der[idx : idx + count], "big")
        idx += count
    return idx + length


def _extract_cms(signed: bytes) -> bytes:
    """Pull the CMS DER out of the last /Contents hex string in *signed*."""
    matches = list(re.finditer(rb"/Contents\s*<([0-9A-Fa-f]+)>", signed))
    assert matches, "no /Contents hex string found"
    raw = bytes.fromhex(matches[-1].group(1).decode("ascii"))
    return raw[: _der_total_len(raw)]


# -- non-crypto helper tests -------------------------------------------------


class TestDerHelpers:
    def test_subfilter_constant(self):
        assert PADES_SUBFILTER == "ETSI.CAdES.detached"

    def test_signing_certificate_v2_carries_sha256_of_cert(self):
        cert_der = b"pretend certificate bytes"
        attr = build_signing_certificate_v2_attribute(cert_der)
        assert _OID_SIGNING_CERT_V2_DER in attr
        assert hashlib.sha256(cert_der).digest() in attr

    def test_signing_certificate_v2_is_well_formed_der(self):
        value = build_signing_certificate_v2(b"x")
        # SigningCertificateV2 is a SEQUENCE whose declared length matches.
        assert value[0] == 0x30
        assert _der_total_len(value) == len(value)

    def test_timestamp_request_round_trips_the_digest(self):
        digest = hashlib.sha256(b"signature value").digest()
        request = build_timestamp_request(digest)
        assert request[0] == 0x30
        assert digest in request
        assert _OID_SHA256_DER in request

    def test_parse_timestamp_response_extracts_token(self):
        # TimeStampResp = SEQUENCE { PKIStatusInfo{status 0}, token }.
        token = bytes.fromhex("3003020101")  # a stand-in ContentInfo SEQUENCE
        status_info = bytes.fromhex("3003020100")  # SEQUENCE { INTEGER 0 }
        body = status_info + token
        resp = bytes([0x30, len(body)]) + body
        assert parse_timestamp_response(resp) == token

    def test_parse_timestamp_response_rejects_declined_status(self):
        status_info = bytes.fromhex("3003020102")  # status 2 = rejection
        resp = bytes([0x30, len(status_info)]) + status_info
        with pytest.raises(TimestampError, match="PKIStatus=2"):
            parse_timestamp_response(resp)


# -- real signing (gated on cryptography) ------------------------------------


@pytest.fixture(scope="module")
def cert_and_key(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PAdES Signer")])
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


@pytest.fixture(scope="module")
def fake_timestamp_token(cert_and_key):
    """A valid ContentInfo DER standing in for an RFC 3161 token (B-T)."""
    from cryptography.x509 import load_pem_x509_certificate
    from cryptography.hazmat.primitives import serialization

    from emboss.pades import build_cades_cms

    cert, key = cert_and_key
    private_key = serialization.load_pem_private_key(open(key, "rb").read(), None)
    certificate = load_pem_x509_certificate(open(cert, "rb").read())
    # A B-T-style CMS so the token itself carries no signing-time attribute.
    stub = bytes.fromhex("3003020101")
    return build_cades_cms(
        b"timestamp payload", private_key, certificate, timestamp_token=stub
    )


@pytest.mark.skipif(not can_sign(), reason="requires the cryptography package")
class TestSignPdfPades:
    def test_subfilter_is_etsi_cades(self, cert_and_key):
        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        signed = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        assert _OID_ETSI_CADES in signed
        assert b"/adbe.pkcs7.detached" not in signed[len(_base_pdf()) :]

    def test_pades_prepared_field_signs(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        prepared = prepare_signature(
            base, name="PAdES Signer", timestamp=_TS, pades=True
        )
        assert _OID_ETSI_CADES in prepared
        signed = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        assert signed.startswith(base)

    def test_signed_attributes_present(self, cert_and_key):
        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        signed = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        cms = _extract_cms(signed)
        assert _OID_SIGNING_CERT_V2_DER in cms
        assert _OID_MESSAGE_DIGEST_DER in cms
        assert _OID_SHA256_DER in cms

    def test_cms_loads_and_embeds_signer_cert(self, cert_and_key):
        from cryptography.hazmat.primitives.serialization import pkcs7

        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        signed = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        cms = _extract_cms(signed)
        certs = pkcs7.load_der_pkcs7_certificates(cms)
        assert len(certs) == 1

    def test_message_digest_matches_byte_range(self, cert_and_key):
        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        signed = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        # Recompute the ByteRange-covered digest and confirm it appears.
        placeholder = re.search(rb"/Contents\s*<([0-9A-Fa-f]+)>", signed)
        c_start = signed.find(b"<", placeholder.start())
        c_end = signed.find(b">", c_start) + 1
        covered = signed[:c_start] + signed[c_end:]
        assert hashlib.sha256(covered).digest() in _extract_cms(signed)

    def test_deterministic_with_fixed_signing_time(self, cert_and_key):
        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        first = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        second = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        assert first == second

    def test_signed_pdf_reopens(self, cert_and_key):
        import io

        import pikepdf

        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        signed = sign_pdf_pades(prepared, key, cert, signing_time=_SIGNING_TIME)
        with pikepdf.open(io.BytesIO(signed)) as pdf:
            assert pdf.Root.get("/AcroForm") is not None

    def test_b_t_embeds_signature_timestamp(self, cert_and_key, fake_timestamp_token):
        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        signed = sign_pdf_pades(
            prepared, key, cert, timestamp_token=fake_timestamp_token
        )
        cms = _extract_cms(signed)
        assert _OID_SIGNATURE_TIMESTAMP_DER in cms

    def test_b_t_omits_signing_time_attribute(self, cert_and_key, fake_timestamp_token):
        from cryptography.hazmat.primitives.serialization import pkcs7

        cert, key = cert_and_key
        prepared = prepare_signature(_base_pdf(), name="PAdES Signer", timestamp=_TS)
        signed = sign_pdf_pades(
            prepared, key, cert, timestamp_token=fake_timestamp_token
        )
        # signing-time OID 1.2.840.113549.1.9.5 must be absent from the CMS.
        signing_time_oid = bytes.fromhex("06092A864886F70D010905")
        assert signing_time_oid not in _extract_cms(signed)
        # It still parses as a CMS.
        assert pkcs7.load_der_pkcs7_certificates(_extract_cms(signed))


@pytest.mark.skipif(not can_sign(), reason="requires the cryptography package")
class TestAmendSignPades:
    def test_amend_sign_pades_preserves_prefix(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign_pades(
            base,
            cert=cert,
            key=key,
            name="PAdES Signer",
            timestamp=_TS,
            signing_time=_SIGNING_TIME,
        )
        assert signed.startswith(base)
        assert _OID_ETSI_CADES in signed

    def test_amend_sign_pades_populates_and_covers(self, cert_and_key):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign_pades(
            base,
            cert=cert,
            key=key,
            name="PAdES Signer",
            timestamp=_TS,
            signing_time=_SIGNING_TIME,
        )
        sig = revision_history(signed)[1]
        assert sig.kind == "signature"
        assert sig.signed is True
        assert sig.sig_byte_range[0] == 0
        assert sig.sig_byte_range[2] + sig.sig_byte_range[3] == len(signed)

    def test_amend_sign_pades_b_t(self, cert_and_key, fake_timestamp_token):
        cert, key = cert_and_key
        base = _base_pdf()
        signed = amend_sign_pades(
            base,
            cert=cert,
            key=key,
            name="PAdES Signer",
            timestamp=_TS,
            timestamp_token=fake_timestamp_token,
        )
        assert signed.startswith(base)
        assert _OID_SIGNATURE_TIMESTAMP_DER in _extract_cms(signed)
