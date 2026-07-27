"""Digital signature support for PDF documents.

Provides:
  - Visual signature field appearance (border, signer name, reason)
  - AcroForm signature field dictionary for PDF readers
  - PKCS#7 cryptographic signing (requires ``cryptography`` package)

The visual appearance is always available. Actual signing requires::

    pip install emboss-pdf[signing]
"""

from __future__ import annotations

from dataclasses import dataclass

from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream

__all__ = [
    "SignatureField",
    "build_signature_appearance",
    "build_sig_field_dict",
    "build_acroform",
    "can_sign",
    "sign_pdf",
]


@dataclass
class SignatureField:
    """Visual signature field placement and metadata."""

    page_index: int
    x: float
    y: float
    width: float = 200.0
    height: float = 60.0
    signer_name: str = ""
    reason: str = ""
    location: str = ""
    field_name: str = "Signature1"


def build_signature_appearance(
    stream,
    sig: SignatureField,
    font_key: str,
    font_size: float,
) -> None:
    """Draw the visual signature field appearance on a page stream.

    Renders a bordered rectangle with a light background and text
    showing the signer details.
    """
    stream.begin_artifact("Signature")

    # Background
    stream.rect(
        sig.x, sig.y, sig.width, sig.height,
        fill="f5f5f4",
        stroke="a8a29e",
        line_width=0.75,
    )

    # Title line
    label_size = font_size * 0.85
    text_x = sig.x + 6.0
    text_y = sig.y + sig.height - label_size - 4.0

    stream.raw(b"BT")
    stream.raw(f"/{font_key} {label_size:.2f} Tf".encode("ascii"))
    stream.raw(b"0.4 0.4 0.4 rg")
    stream.raw(f"{text_x:.4f} {text_y:.4f} Td".encode("ascii"))
    stream.raw(_escape_text("Digitally Signed") + b" Tj")
    stream.raw(b"ET")

    # Signer name
    if sig.signer_name:
        text_y -= label_size + 3.0
        stream.raw(b"BT")
        stream.raw(f"/{font_key} {font_size:.2f} Tf".encode("ascii"))
        stream.raw(b"0.1 0.1 0.1 rg")
        stream.raw(f"{text_x:.4f} {text_y:.4f} Td".encode("ascii"))
        stream.raw(_escape_text(sig.signer_name) + b" Tj")
        stream.raw(b"ET")

    # Reason
    if sig.reason:
        text_y -= label_size + 2.0
        stream.raw(b"BT")
        stream.raw(f"/{font_key} {label_size:.2f} Tf".encode("ascii"))
        stream.raw(b"0.35 0.35 0.35 rg")
        stream.raw(f"{text_x:.4f} {text_y:.4f} Td".encode("ascii"))
        stream.raw(_escape_text(f"Reason: {sig.reason}") + b" Tj")
        stream.raw(b"ET")

    # Location
    if sig.location:
        text_y -= label_size + 2.0
        stream.raw(b"BT")
        stream.raw(f"/{font_key} {label_size:.2f} Tf".encode("ascii"))
        stream.raw(b"0.35 0.35 0.35 rg")
        stream.raw(f"{text_x:.4f} {text_y:.4f} Td".encode("ascii"))
        stream.raw(_escape_text(f"Location: {sig.location}") + b" Tj")
        stream.raw(b"ET")

    stream.end_marked()


def build_sig_field_dict(
    assembler,
    sig: SignatureField,
    page_ref: PdfRef,
    appearance_ref: PdfRef | None = None,
) -> PdfRef:
    """Create an AcroForm signature field dictionary.

    Returns a reference to the signature field object. The caller must
    add it to the page's /Annots array and to the document's AcroForm.
    """
    sig_value = PdfDict()
    sig_value["Type"] = PdfName("Sig")
    sig_value["Filter"] = PdfName("Adobe.PPKLite")
    sig_value["SubFilter"] = PdfName("adbe.pkcs7.detached")
    if sig.signer_name:
        sig_value["Name"] = sig.signer_name
    if sig.reason:
        sig_value["Reason"] = sig.reason
    if sig.location:
        sig_value["Location"] = sig.location
    sig_value["M"] = "D:20240101000000Z"
    sig_value["Contents"] = b"\x00" * 8192  # placeholder for actual signature
    sig_value_ref = assembler.add(sig_value)

    rect = PdfArray([sig.x, sig.y, sig.x + sig.width, sig.y + sig.height])

    field = PdfDict()
    field["Type"] = PdfName("Annot")
    field["Subtype"] = PdfName("Widget")
    field["FT"] = PdfName("Sig")
    field["T"] = sig.field_name
    field["V"] = sig_value_ref
    field["Rect"] = rect
    field["F"] = 4  # Print flag
    field["P"] = page_ref

    if appearance_ref is not None:
        ap = PdfDict()
        ap["N"] = appearance_ref
        field["AP"] = ap

    return assembler.add(field)


def build_acroform(sig_field_refs: list[PdfRef]) -> PdfDict:
    """Build an AcroForm dictionary for the document catalog.

    The caller adds this under catalog['AcroForm'].
    """
    acroform = PdfDict()
    acroform["Fields"] = PdfArray(sig_field_refs)
    acroform["SigFlags"] = 3  # SignaturesExist + AppendOnly
    return acroform


def can_sign() -> bool:
    """Check whether the ``cryptography`` package is available."""
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def sign_pdf(
    pdf_bytes: bytes,
    private_key_path: str,
    cert_path: str,
    password: bytes | None = None,
) -> bytes:
    """Sign a PDF with a PKCS#7 detached signature.

    Requires ``pip install emboss-pdf[signing]``.

    Parameters
    ----------
    pdf_bytes : bytes
        The PDF content with a placeholder signature.
    private_key_path : str
        Path to a PEM-encoded private key file.
    cert_path : str
        Path to a PEM-encoded X.509 certificate file.
    password : bytes | None
        Optional password for the private key.

    Returns
    -------
    bytes
        The signed PDF with the PKCS#7 signature injected into the
        /Contents placeholder.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.x509 import load_pem_x509_certificate
        from cryptography.hazmat.primitives.serialization import pkcs7
    except ImportError:
        raise ImportError(
            "Digital signing requires the 'cryptography' package.\n"
            "  pip install emboss-pdf[signing]"
        ) from None

    from pathlib import Path

    key_data = Path(private_key_path).read_bytes()
    cert_data = Path(cert_path).read_bytes()

    private_key = serialization.load_pem_private_key(key_data, password=password)
    certificate = load_pem_x509_certificate(cert_data)

    # Find the /Contents placeholder in the PDF
    placeholder = b"\x00" * 8192
    start = pdf_bytes.find(placeholder)
    if start == -1:
        raise ValueError("No signature placeholder found in the PDF")

    # The signed data is everything except the placeholder
    data_to_sign = pdf_bytes[:start] + pdf_bytes[start + len(placeholder):]

    # Create PKCS#7 signature
    signature = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(data_to_sign)
        .add_signer(certificate, private_key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
    )

    if len(signature) > len(placeholder):
        raise ValueError(
            f"Signature ({len(signature)} bytes) exceeds placeholder "
            f"({len(placeholder)} bytes)"
        )

    # Pad signature to placeholder size and inject
    padded = signature + b"\x00" * (len(placeholder) - len(signature))
    signed = pdf_bytes[:start] + padded + pdf_bytes[start + len(placeholder):]

    return signed


def _escape_text(text: str) -> bytes:
    out = bytearray(b"(")
    for char in text:
        code = ord(char)
        if char in "()\\":
            out.append(0x5C)
            out.append(code)
        elif code < 32 or code > 126:
            out.extend(f"\\{min(code, 255):03o}".encode("ascii"))
        else:
            out.append(code)
    out.append(0x29)
    return bytes(out)
