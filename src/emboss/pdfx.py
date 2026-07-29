"""PDF/X-4 (ISO 15930-7) print/prepress conformance utilities.

PDF/X-4 is a print-ready profile: every device color must be covered by a
single PDF/X OutputIntent whose DestOutputProfile is an ICC output profile,
all fonts are embedded, and the file declares ``GTS_PDFXVersion`` in both
the XMP packet (pdfxid namespace) and the Info dictionary.

No third-party CMYK ICC is redistributed with Emboss. By default the
OutputIntent uses the same minimal generic CMYK profile Emboss builds for
its PDF/A CMYK output intent (``pdfa._build_minimal_cmyk_icc``): a valid,
deterministic ICC profile suitable for validation and general print, but
not a colorimetrically exact FOGRA/GRACoL characterization. For real
prepress, pass a licensed profile and its condition via
``Document(pdfx=True, pdfx_output_profile=icc_bytes,
pdfx_condition="FOGRA39")``.
"""

from __future__ import annotations

from .pdf.objects import PdfDict, PdfName, PdfRef, PdfStream
from .pdfa import _build_minimal_cmyk_icc

__all__ = [
    "PDFX_VERSION",
    "pdfx_output_intent_profile",
    "build_pdfx_output_intent",
]

#: The GTS_PDFXVersion string this library declares.
PDFX_VERSION = "PDF/X-4"

#: Condition identifier used when the caller supplies no profile of its own.
_DEFAULT_CONDITION = "Generic CMYK (CGATS TR 001 compatible)"


def pdfx_output_intent_profile(document) -> tuple[bytes, str]:
    """Return the (ICC bytes, OutputConditionIdentifier) for *document*.

    Uses ``document.pdfx_output_profile`` when supplied (caller's licensed
    CMYK profile), otherwise the bundled minimal generic CMYK profile.
    """
    supplied = getattr(document, "pdfx_output_profile", None)
    condition = getattr(document, "pdfx_condition", None)
    if supplied is not None:
        if not isinstance(supplied, (bytes, bytearray)):
            raise TypeError("pdfx_output_profile must be bytes")
        return bytes(supplied), condition or "Custom CMYK"
    return _build_minimal_cmyk_icc(), condition or _DEFAULT_CONDITION


def build_pdfx_output_intent(assembler, document) -> PdfRef:
    """Create the /GTS_PDFX output intent for PDF/X-4 and return its ref."""
    icc_data, condition = pdfx_output_intent_profile(document)

    icc_stream = PdfStream(data=icc_data, compress=True)
    icc_stream.dictionary["N"] = 4
    icc_ref = assembler.add(icc_stream)

    intent = PdfDict()
    intent["Type"] = PdfName("OutputIntent")
    intent["S"] = PdfName("GTS_PDFX")
    intent["OutputConditionIdentifier"] = condition
    intent["OutputCondition"] = condition
    intent["RegistryName"] = "http://www.color.org"
    intent["Info"] = condition
    intent["DestOutputProfile"] = icc_ref

    return assembler.add(intent)
