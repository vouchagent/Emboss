"""End-to-end tests for the amend / history / verify --revisions CLI commands."""

import datetime

import pytest

from emboss import Document
from emboss.__main__ import main
from emboss.signing import can_sign


def _base_pdf(tmp_path):
    doc = Document(title="Contract")
    doc.paragraph("This agreement is entered into by the parties.", id="p1")
    path = tmp_path / "contract.pdf"
    path.write_bytes(doc.render())
    return path


def test_history_on_base_pdf(tmp_path, capsys):
    path = _base_pdf(tmp_path)
    rc = main(["history", str(path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "base" in out
    assert "Rev" in out


def test_verify_revisions_flag(tmp_path, capsys):
    path = _base_pdf(tmp_path)
    rc = main(["verify", str(path), "--revisions"])
    # A base-only document has nothing appended after a signature.
    assert rc == 0
    assert "base" in capsys.readouterr().out


def _self_signed(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Legal")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2024, 1, 1))
        .not_valid_after(datetime.datetime(2030, 1, 1))
        .sign(key, hashes.SHA256())
    )
    key_path = tmp_path / "key.pem"
    cert_path = tmp_path / "cert.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


@pytest.mark.skipif(not can_sign(), reason="cryptography not available")
def test_amend_sign_preserves_prefix_and_records_coverage(tmp_path, capsys):
    path = _base_pdf(tmp_path)
    original = path.read_bytes()
    cert, key = _self_signed(tmp_path)
    out = tmp_path / "signed.pdf"

    rc = main(
        [
            "amend",
            str(path),
            "-o",
            str(out),
            "--sign",
            "--cert",
            str(cert),
            "--key",
            str(key),
            "--reason",
            "Approved: Legal",
            "--name",
            "R. Patel",
            "-q",
        ]
    )
    assert rc == 0
    signed = out.read_bytes()
    # Prior bytes are never rewritten.
    assert signed.startswith(original)

    capsys.readouterr()  # clear
    assert main(["history", str(out)]) == 0
    hist = capsys.readouterr().out
    assert "signature" in hist
    assert "R. Patel" in hist


@pytest.mark.skipif(not can_sign(), reason="cryptography not available")
def test_verify_revisions_flags_content_appended_after_signature(tmp_path):
    from emboss.amend import Attestation, amend_pdf, amend_sign

    path = _base_pdf(tmp_path)
    cert, key = _self_signed(tmp_path)
    signed = amend_sign(path.read_bytes(), cert=str(cert), key=str(key))
    # Append an annotation after the signature: nobody signed it.
    tampered = amend_pdf(
        signed,
        attestation=Attestation(
            kind="annotations", page_index=0, rect=(72, 72, 200, 90), text="late"
        ),
    )
    out = tmp_path / "tampered.pdf"
    out.write_bytes(tampered)
    # The headline check: exit non-zero on uncovered appended content.
    assert main(["verify", str(out), "--revisions"]) == 1


def test_amend_without_sign_errors(tmp_path):
    path = _base_pdf(tmp_path)
    assert main(["amend", str(path)]) == 1
