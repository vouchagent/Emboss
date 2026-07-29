"""PAdES baseline electronic signatures (ETSI EN 319 142, levels B-B and B-T).

Turns Emboss's detached CMS signature into a PAdES-BASELINE one: the
signature dictionary carries ``/SubFilter /ETSI.CAdES.detached`` and the CMS
SignedData is CAdES-BES, whose signed attributes include the ESS
signing-certificate-v2 attribute (OID 1.2.840.113549.1.9.16.2.47) alongside
content-type and message-digest, all over SHA-256. Supplying ``tsa_url`` or a
pre-fetched ``timestamp_token`` upgrades the signature to B-T by embedding an
RFC 3161 signature-timestamp as an unsigned attribute.

This module reuses ``signing.py``'s placeholder/byte-range machinery: it takes
a PDF already prepared with a ``/Contents`` placeholder and injects the CAdES
CMS into it, exactly as ``signing.sign_pdf`` does for the plain profile. LTV
(document security store / DSS) is out of scope.

Requires the ``cryptography`` package::

    pip install emboss-pdf[signing]
"""

from __future__ import annotations

import datetime
from pathlib import Path

from .signing import (
    _CONTENTS_HEX_PLACEHOLDER,
    _CONTENTS_PLACEHOLDER_BYTES,
    _verify_docmdp_certification,
    can_sign,
)

__all__ = [
    "PADES_SUBFILTER",
    "TimestampError",
    "can_sign",
    "sign_pdf_pades",
    "build_signing_certificate_v2",
    "build_signing_certificate_v2_attribute",
    "build_cades_cms",
    "build_timestamp_request",
    "parse_timestamp_response",
]

#: The PAdES marker placed in the signature dictionary's /SubFilter.
PADES_SUBFILTER = "ETSI.CAdES.detached"

#: /SubFilter names as they appear in serialized PDF bytes (equal length).
_PKCS7_SUBFILTER_BYTES = b"/adbe.pkcs7.detached"
_PADES_SUBFILTER_BYTES = b"/ETSI.CAdES.detached"

#: Object identifiers used when hand-building the CAdES CMS.
_OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
_OID_ID_DATA = "1.2.840.113549.1.7.1"
_OID_CONTENT_TYPE = "1.2.840.113549.1.9.3"
_OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
_OID_SIGNING_TIME = "1.2.840.113549.1.9.5"
_OID_SIGNING_CERT_V2 = "1.2.840.113549.1.9.16.2.47"
_OID_SIGNATURE_TIMESTAMP = "1.2.840.113549.1.9.16.2.14"
_OID_SHA256 = "2.16.840.1.101.3.4.2.1"
_OID_RSA_ENCRYPTION = "1.2.840.113549.1.1.1"
_OID_ECDSA_WITH_SHA256 = "1.2.840.10045.4.3.2"

#: Deterministic default signing time; callers pass their own datetime.
_DEFAULT_SIGNING_TIME = datetime.datetime(
    2024, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
)

#: Seconds to wait on a network TSA before giving up.
_TSA_TIMEOUT = 30


class TimestampError(RuntimeError):
    """Raised when an RFC 3161 timestamp cannot be obtained or parsed."""


# -- minimal DER encoder -----------------------------------------------------


def _der_len(length: int) -> bytes:
    """Encode a DER length octet sequence."""
    if length < 0x80:
        return bytes([length])
    out = bytearray()
    while length:
        out.insert(0, length & 0xFF)
        length >>= 8
    return bytes([0x80 | len(out)]) + bytes(out)


def _tlv(tag: int, content: bytes) -> bytes:
    """Wrap *content* in a DER tag-length-value with the given tag byte."""
    return bytes([tag]) + _der_len(len(content)) + content


def _der_integer(value: int) -> bytes:
    """Encode a non-negative integer as a DER INTEGER."""
    if value < 0:
        raise ValueError("only non-negative integers are encoded here")
    if value == 0:
        return _tlv(0x02, b"\x00")
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return _tlv(0x02, raw)


def _der_oid(dotted: str) -> bytes:
    """Encode a dotted object identifier as a DER OBJECT IDENTIFIER."""
    parts = [int(p) for p in dotted.split(".")]
    body = bytearray([40 * parts[0] + parts[1]])
    for part in parts[2:]:
        stack = [part & 0x7F]
        part >>= 7
        while part:
            stack.insert(0, (part & 0x7F) | 0x80)
            part >>= 7
        body.extend(stack)
    return _tlv(0x06, bytes(body))


def _der_octet_string(data: bytes) -> bytes:
    """Encode bytes as a DER OCTET STRING."""
    return _tlv(0x04, data)


def _der_null() -> bytes:
    """Encode a DER NULL."""
    return b"\x05\x00"


def _der_sequence(elements: list[bytes]) -> bytes:
    """Encode a DER SEQUENCE from already-encoded elements."""
    return _tlv(0x30, b"".join(elements))


def _der_set_of(elements: list[bytes]) -> bytes:
    """Encode a DER SET OF, sorting elements by encoding as DER requires."""
    return _tlv(0x31, b"".join(sorted(elements)))


def _der_utctime(when: datetime.datetime) -> bytes:
    """Encode a datetime as a DER UTCTime (YYMMDDHHMMSSZ, UTC)."""
    if when.tzinfo is not None:
        when = when.astimezone(datetime.timezone.utc)
    return _tlv(0x17, when.strftime("%y%m%d%H%M%SZ").encode("ascii"))


def _alg_sha256() -> bytes:
    """AlgorithmIdentifier for SHA-256 with absent parameters (RFC 5754)."""
    return _der_sequence([_der_oid(_OID_SHA256)])


def _attribute(oid: str, value: bytes) -> bytes:
    """Encode a CMS Attribute: SEQUENCE { attrType OID, attrValues SET }."""
    return _der_sequence([_der_oid(oid), _der_set_of([value])])


# -- minimal DER reader (for parsing TSA responses) --------------------------


def _read_tlv(data: bytes, offset: int) -> tuple[int, bytes, int, bytes]:
    """Read one DER element; return (tag, content, next_offset, full_tlv)."""
    tag = data[offset]
    length = data[offset + 1]
    cursor = offset + 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[cursor : cursor + count], "big")
        cursor += count
    end = cursor + length
    return tag, data[cursor:end], end, data[offset:end]


# -- SHA-256 helper ----------------------------------------------------------


def _sha256(data: bytes) -> bytes:
    """Return the SHA-256 digest of *data*."""
    import hashlib

    return hashlib.sha256(data).digest()


# -- signing-certificate-v2 attribute ----------------------------------------


def build_signing_certificate_v2(cert_der: bytes) -> bytes:
    """Build a SigningCertificateV2 (RFC 5035) over the DER certificate.

    The ESSCertIDv2 carries only the SHA-256 certHash; hashAlgorithm is
    omitted (id-sha256 is the DEFAULT) and issuerSerial is left out, both
    permitted by RFC 5035.
    """
    ess_certid_v2 = _der_sequence([_der_octet_string(_sha256(cert_der))])
    certs = _der_sequence([ess_certid_v2])
    return _der_sequence([certs])


def build_signing_certificate_v2_attribute(cert_der: bytes) -> bytes:
    """Build the signed ESS signing-certificate-v2 attribute (OID .2.47)."""
    return _attribute(_OID_SIGNING_CERT_V2, build_signing_certificate_v2(cert_der))


# -- RFC 3161 timestamping ---------------------------------------------------


def build_timestamp_request(message_digest: bytes) -> bytes:
    """Build a DER RFC 3161 TimeStampReq over a SHA-256 message imprint."""
    version = _der_integer(1)
    hash_alg = _der_sequence([_der_oid(_OID_SHA256), _der_null()])
    imprint = _der_sequence([hash_alg, _der_octet_string(message_digest)])
    cert_req = b"\x01\x01\xff"
    return _der_sequence([version, imprint, cert_req])


def parse_timestamp_response(response: bytes) -> bytes:
    """Extract the TimeStampToken (a ContentInfo) from a TimeStampResp DER."""
    tag, content, _, _ = _read_tlv(response, 0)
    if tag != 0x30:
        raise TimestampError("TSA response is not a DER SEQUENCE")
    status_tag, status_content, after_status, _ = _read_tlv(content, 0)
    if status_tag != 0x30:
        raise TimestampError("TSA response has no PKIStatusInfo")
    int_tag, int_content, _, _ = _read_tlv(status_content, 0)
    if int_tag != 0x02:
        raise TimestampError("TSA PKIStatusInfo has no status integer")
    status = int.from_bytes(int_content, "big")
    if status not in (0, 1):
        raise TimestampError(f"TSA declined the request (PKIStatus={status})")
    if after_status >= len(content):
        raise TimestampError("TSA response contained no timestamp token")
    _, _, _, token = _read_tlv(content, after_status)
    return token


def _fetch_timestamp_token(tsa_url: str, message_digest: bytes) -> bytes:
    """POST an RFC 3161 request to *tsa_url* and return the token DER."""
    import urllib.error
    import urllib.request

    request_der = build_timestamp_request(message_digest)
    request = urllib.request.Request(
        tsa_url,
        data=request_der,
        headers={"Content-Type": "application/timestamp-query"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TSA_TIMEOUT) as response:
            body = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise TimestampError(f"TSA request to {tsa_url} failed: {exc}") from exc
    return parse_timestamp_response(body)


# -- CAdES CMS assembly ------------------------------------------------------


def _signature_algorithm(private_key) -> tuple[bytes, object]:
    """Return the (signatureAlgorithm DER, callable) for the key type."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    if isinstance(private_key, rsa.RSAPrivateKey):
        alg = _der_sequence([_der_oid(_OID_RSA_ENCRYPTION), _der_null()])

        def sign(data: bytes) -> bytes:
            return private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())

        return alg, sign
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        alg = _der_sequence([_der_oid(_OID_ECDSA_WITH_SHA256)])

        def sign(data: bytes) -> bytes:
            return private_key.sign(data, ec.ECDSA(hashes.SHA256()))

        return alg, sign
    raise ValueError(
        f"PAdES signing supports RSA and EC keys only; got {type(private_key).__name__}"
    )


def build_cades_cms(
    data_to_sign: bytes,
    private_key,
    certificate,
    *,
    signing_time: datetime.datetime | None = None,
    timestamp_token: bytes | None = None,
    tsa_url: str | None = None,
) -> bytes:
    """Build a detached CAdES-BES/EPES CMS ContentInfo over *data_to_sign*.

    The signed attributes are content-type, message-digest (SHA-256), the ESS
    signing-certificate-v2 attribute and, for B-B only, a signing-time. When a
    ``timestamp_token`` is passed or a ``tsa_url`` is fetched, the token is
    embedded as the RFC 3161 signature-timestamp unsigned attribute (B-T) and
    the signing-time signed attribute is omitted, per PAdES.
    """
    from cryptography.hazmat.primitives.serialization import Encoding

    cert_der = certificate.public_bytes(Encoding.DER)
    message_digest = _sha256(data_to_sign)
    with_timestamp = timestamp_token is not None or tsa_url is not None

    signed_attrs = [
        _attribute(_OID_CONTENT_TYPE, _der_oid(_OID_ID_DATA)),
        _attribute(_OID_MESSAGE_DIGEST, _der_octet_string(message_digest)),
        build_signing_certificate_v2_attribute(cert_der),
    ]
    if not with_timestamp:
        when = signing_time or _DEFAULT_SIGNING_TIME
        signed_attrs.append(_attribute(_OID_SIGNING_TIME, _der_utctime(when)))

    attrs_content = b"".join(sorted(signed_attrs))
    signed_attrs_der = _tlv(0x31, attrs_content)

    sig_alg, sign = _signature_algorithm(private_key)
    signature = sign(signed_attrs_der)

    token = timestamp_token
    if token is None and tsa_url is not None:
        token = _fetch_timestamp_token(tsa_url, _sha256(signature))

    unsigned_field = b""
    if token is not None:
        ts_attr = _attribute(_OID_SIGNATURE_TIMESTAMP, token)
        unsigned_field = _tlv(0xA1, ts_attr)

    issuer_der = certificate.issuer.public_bytes()
    sid = _der_sequence([issuer_der, _der_integer(certificate.serial_number)])

    signer_info = _tlv(
        0x30,
        _der_integer(1)
        + sid
        + _alg_sha256()
        + _tlv(0xA0, attrs_content)
        + sig_alg
        + _der_octet_string(signature)
        + unsigned_field,
    )

    signed_data = _der_sequence(
        [
            _der_integer(1),
            _der_set_of([_alg_sha256()]),
            _der_sequence([_der_oid(_OID_ID_DATA)]),
            _tlv(0xA0, cert_der),
            _der_set_of([signer_info]),
        ]
    )
    return _der_sequence([_der_oid(_OID_SIGNED_DATA), _tlv(0xA0, signed_data)])


# -- subfilter rewriting -----------------------------------------------------


def _ensure_pades_subfilter(pdf_bytes: bytes, placeholder_start: int) -> bytes:
    """Set the signed field's /SubFilter to the PAdES marker, equal length.

    Only the signature dictionary owning the /Contents placeholder is touched:
    the last ``/adbe.pkcs7.detached`` before *placeholder_start* is rewritten
    to ``/ETSI.CAdES.detached`` (same byte length, so no offset shifts), which
    leaves any earlier signatures in an amended file byte-for-byte intact.
    """
    if len(_PKCS7_SUBFILTER_BYTES) != len(_PADES_SUBFILTER_BYTES):
        raise AssertionError("subfilter names must be equal length")
    marker = pdf_bytes.rfind(_PKCS7_SUBFILTER_BYTES, 0, placeholder_start)
    if marker == -1:
        return pdf_bytes
    end = marker + len(_PKCS7_SUBFILTER_BYTES)
    return pdf_bytes[:marker] + _PADES_SUBFILTER_BYTES + pdf_bytes[end:]


# -- public signing entry point ----------------------------------------------


def sign_pdf_pades(
    pdf_bytes: bytes,
    private_key_path: str,
    cert_path: str,
    password: bytes | None = None,
    *,
    certify: bool = False,
    docmdp_permission: int = 2,
    tsa_url: str | None = None,
    timestamp_token: bytes | None = None,
    signing_time: datetime.datetime | None = None,
) -> bytes:
    """Sign a prepared PDF with a PAdES-BASELINE (B-B or B-T) signature.

    *pdf_bytes* must already carry a signature field with a ``/Contents``
    placeholder (as ``signing.build_sig_field_dict`` or ``amend`` produce). The
    field's /SubFilter is set to ``ETSI.CAdES.detached`` and a CAdES-BES CMS
    with the ESS signing-certificate-v2 attribute is injected. Passing
    ``tsa_url`` (fetched over HTTP) or a pre-fetched ``timestamp_token`` embeds
    an RFC 3161 signature-timestamp, producing B-T; otherwise the result is
    B-B with a deterministic signing-time signed attribute. Deterministic given
    a fixed ``signing_time`` and no network timestamp. Requires
    ``pip install emboss-pdf[signing]``.
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.x509 import load_pem_x509_certificate
    except ImportError:
        raise ImportError(
            "Digital signing requires the 'cryptography' package.\n"
            "  pip install emboss-pdf[signing]"
        ) from None

    placeholder = _CONTENTS_HEX_PLACEHOLDER
    start = pdf_bytes.find(placeholder)
    if start == -1:
        raise ValueError("No signature placeholder found in the PDF")

    pdf_bytes = _ensure_pades_subfilter(pdf_bytes, start)

    if certify:
        _verify_docmdp_certification(pdf_bytes, docmdp_permission)

    key_data = Path(private_key_path).read_bytes()
    cert_data = Path(cert_path).read_bytes()
    private_key = serialization.load_pem_private_key(key_data, password=password)
    certificate = load_pem_x509_certificate(cert_data)

    data_to_sign = pdf_bytes[:start] + pdf_bytes[start + len(placeholder) :]

    cms = build_cades_cms(
        data_to_sign,
        private_key,
        certificate,
        signing_time=signing_time,
        timestamp_token=timestamp_token,
        tsa_url=tsa_url,
    )

    max_hex_chars = _CONTENTS_PLACEHOLDER_BYTES * 2
    cms_hex = cms.hex().upper().encode("ascii")
    if len(cms_hex) > max_hex_chars:
        raise ValueError(
            f"CAdES signature ({len(cms)} bytes) exceeds placeholder "
            f"({_CONTENTS_PLACEHOLDER_BYTES} bytes)"
        )
    padded_hex = cms_hex + b"0" * (max_hex_chars - len(cms_hex))
    new_contents = b"<" + padded_hex + b">"
    return pdf_bytes[:start] + new_contents + pdf_bytes[start + len(placeholder) :]
