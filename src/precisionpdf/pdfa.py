"""PDF/A-2b conformance utilities.

Adds the metadata and output intent entries that upgrade a standard PDF
to PDF/A-2b (ISO 19005-2, level B). Level B requires:

  - XMP metadata with pdfaid:part=2, conformance=B
  - sRGB output intent with /DestOutputProfile
  - All fonts embedded (already handled by the core font pipeline)
  - No transparency issues (not applicable — we emit only opaque fills)

Dates are pinned to a deterministic value so output stays reproducible.
"""

from __future__ import annotations

import zlib

from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream

__all__ = [
    "build_xmp_metadata",
    "build_output_intent",
    "pdfa_catalog_entries",
]

_FIXED_DATE = "2024-01-01T00:00:00Z"


def build_xmp_metadata(
    title: str,
    author: str,
    subject: str,
    keywords: str,
    creator: str,
    producer: str,
    language: str,
) -> bytes:
    """Generate an XMP metadata packet for PDF/A-2b conformance.

    The packet is a well-formed XML document with all required namespaces.
    Dates are deterministic for reproducible output.
    """
    keyword_tags = ""
    if keywords:
        items = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        if items:
            li = "\n".join(f"            <rdf:li>{_xml_escape(k)}</rdf:li>" for k in items)
            keyword_tags = f"""
         <pdf:Keywords>{_xml_escape(keywords)}</pdf:Keywords>"""

    xmp = f"""<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:xmp="http://ns.adobe.com/xap/1.0/"
      xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
      xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">

      <dc:title>
        <rdf:Alt>
          <rdf:li xml:lang="x-default">{_xml_escape(title)}</rdf:li>
        </rdf:Alt>
      </dc:title>

      <dc:creator>
        <rdf:Seq>
          <rdf:li>{_xml_escape(author)}</rdf:li>
        </rdf:Seq>
      </dc:creator>

      <dc:subject>
        <rdf:Bag>
          <rdf:li>{_xml_escape(subject)}</rdf:li>
        </rdf:Bag>
      </dc:subject>

      <dc:description>
        <rdf:Alt>
          <rdf:li xml:lang="x-default">{_xml_escape(subject)}</rdf:li>
        </rdf:Alt>
      </dc:description>

      <dc:language>
        <rdf:Bag>
          <rdf:li>{_xml_escape(language)}</rdf:li>
        </rdf:Bag>
      </dc:language>

      <xmp:CreatorTool>{_xml_escape(creator)}</xmp:CreatorTool>
      <xmp:CreateDate>{_FIXED_DATE}</xmp:CreateDate>
      <xmp:ModifyDate>{_FIXED_DATE}</xmp:ModifyDate>
      <xmp:MetadataDate>{_FIXED_DATE}</xmp:MetadataDate>

      <pdf:Producer>{_xml_escape(producer)}</pdf:Producer>{keyword_tags}

      <pdfaid:part>2</pdfaid:part>
      <pdfaid:conformance>B</pdfaid:conformance>

    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""
    return xmp.encode("utf-8")


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _build_minimal_srgb_icc() -> bytes:
    """Build a minimal sRGB ICC profile.

    A full sRGB profile is ~3 KB. This constructs the minimal valid
    ICC v2 profile header + required tags for an sRGB monitor profile,
    sufficient for PDF/A output intent validation.
    """
    # ICC profile header (128 bytes)
    header = bytearray(128)

    # Profile size — filled in at the end
    # Preferred CMM type
    header[4:8] = b"appl"
    # Profile version 2.1.0
    header[8:12] = b"\x02\x10\x00\x00"
    # Device class: 'mntr' (monitor)
    header[12:16] = b"mntr"
    # Color space: 'RGB '
    header[16:20] = b"RGB "
    # Connection space: 'XYZ '
    header[20:24] = b"XYZ "
    # Creation date: 2024-01-01 00:00:00
    header[24:26] = (2024).to_bytes(2, "big")
    header[26:28] = (1).to_bytes(2, "big")
    header[28:30] = (1).to_bytes(2, "big")
    # Time fields stay zero
    # Profile signature 'acsp'
    header[36:40] = b"acsp"
    # Primary platform: Apple
    header[40:44] = b"APPL"
    # Rendering intent: perceptual
    header[64:68] = (0).to_bytes(4, "big")
    # D50 illuminant (X=0.9642, Y=1.0, Z=0.8249 as s15Fixed16)
    header[68:72] = _s15f16(0.9642)
    header[72:76] = _s15f16(1.0)
    header[76:80] = _s15f16(0.8249)
    # Profile creator
    header[80:84] = b"none"

    # Tag table
    tag_count = 9
    tags_data = tag_count.to_bytes(4, "big")

    tag_entries = []
    tag_payloads = []

    # Offset starts after header (128) + tag count (4) + tag entries (9 * 12 = 108)
    data_offset = 128 + 4 + tag_count * 12

    # Helper to add a tag
    def add_tag(sig: bytes, payload: bytes) -> None:
        nonlocal data_offset
        # Pad to 4-byte boundary
        while len(payload) % 4 != 0:
            payload += b"\x00"
        tag_entries.append(sig + data_offset.to_bytes(4, "big") + len(payload).to_bytes(4, "big"))
        tag_payloads.append(payload)
        data_offset += len(payload)

    # desc tag — profile description
    desc_text = b"sRGB IEC61966-2.1"
    desc_payload = b"desc" + b"\x00" * 4
    desc_payload += (len(desc_text) + 1).to_bytes(4, "big")
    desc_payload += desc_text + b"\x00"
    # Unicode and ScriptCode localizations (minimal)
    desc_payload += b"\x00" * 4  # Unicode language code
    desc_payload += b"\x00" * 4  # Unicode count
    desc_payload += b"\x00" * 2  # ScriptCode code
    desc_payload += (67).to_bytes(1, "big")  # ScriptCode count (pad)
    desc_payload += b"\x00" * 67
    add_tag(b"desc", desc_payload)

    # wtpt — white point (D50)
    xyz_payload = b"XYZ " + b"\x00" * 4
    xyz_payload += _s15f16(0.9505) + _s15f16(1.0) + _s15f16(1.0890)
    add_tag(b"wtpt", xyz_payload)

    # rXYZ, gXYZ, bXYZ — sRGB primaries adapted to D50
    r_xyz = b"XYZ " + b"\x00" * 4 + _s15f16(0.4360) + _s15f16(0.2225) + _s15f16(0.0139)
    g_xyz = b"XYZ " + b"\x00" * 4 + _s15f16(0.3851) + _s15f16(0.7169) + _s15f16(0.0971)
    b_xyz = b"XYZ " + b"\x00" * 4 + _s15f16(0.1431) + _s15f16(0.0606) + _s15f16(0.7141)
    add_tag(b"rXYZ", r_xyz)
    add_tag(b"gXYZ", g_xyz)
    add_tag(b"bXYZ", b_xyz)

    # rTRC, gTRC, bTRC — sRGB gamma curves (use parametric curve type 3)
    # sRGB transfer function: if L <= 0.04045 then L/12.92 else ((L+0.055)/1.055)^2.4
    # Parametric type 3: Y = (aX+b)^g + c for X >= d, Y = eX + f for X < d
    # g=2.4, a=1/1.055≈0.9479, b=0.055/1.055≈0.0521, c=0, d=0.04045, e=1/12.92≈0.0774, f=0
    gamma_payload = b"para" + b"\x00" * 4
    gamma_payload += (3).to_bytes(2, "big") + b"\x00" * 2  # function type 3
    gamma_payload += _s15f16(2.4)      # g
    gamma_payload += _s15f16(0.9479)   # a
    gamma_payload += _s15f16(0.0521)   # b
    gamma_payload += _s15f16(0.0)      # c (not used for type 3 in this form)
    gamma_payload += _s15f16(0.04045)  # d
    gamma_payload += _s15f16(0.0774)   # e
    gamma_payload += _s15f16(0.0)      # f

    # All three channels share the same curve
    add_tag(b"rTRC", gamma_payload)
    add_tag(b"gTRC", gamma_payload)
    add_tag(b"bTRC", gamma_payload)

    # cprt — copyright
    cprt_text = b"No copyright, use freely"
    cprt_payload = b"text" + b"\x00" * 4 + cprt_text + b"\x00"
    add_tag(b"cprt", cprt_payload)

    # Assemble
    tag_table = tags_data + b"".join(tag_entries)
    body = b"".join(tag_payloads)
    profile = bytes(header) + tag_table + body

    # Patch profile size
    size_bytes = len(profile).to_bytes(4, "big")
    profile = size_bytes + profile[4:]

    return profile


def _s15f16(value: float) -> bytes:
    """Encode a float as ICC s15Fixed16Number (4 bytes, big-endian)."""
    fixed = int(round(value * 65536))
    if fixed < 0:
        fixed += 1 << 32
    return fixed.to_bytes(4, "big")


def build_output_intent(assembler) -> PdfRef:
    """Create an sRGB output intent for PDF/A color management."""
    icc_data = _build_minimal_srgb_icc()

    icc_stream = PdfStream(data=icc_data, compress=True)
    icc_stream.dictionary["N"] = 3  # number of color components
    icc_ref = assembler.add(icc_stream)

    intent = PdfDict()
    intent["Type"] = PdfName("OutputIntent")
    intent["S"] = PdfName("GTS_PDFA1")
    intent["OutputConditionIdentifier"] = "sRGB IEC61966-2.1"
    intent["RegistryName"] = "http://www.color.org"
    intent["Info"] = "sRGB IEC61966-2.1"
    intent["DestOutputProfile"] = icc_ref

    return assembler.add(intent)


def pdfa_catalog_entries(assembler, document) -> dict:
    """Return entries to add to the PDF catalog for PDF/A-2b compliance.

    The caller should merge the returned dict into the catalog PdfDict
    before finalizing the document.
    """
    xmp_bytes = build_xmp_metadata(
        title=document.title,
        author=document.author,
        subject=document.subject,
        keywords=document.keywords,
        creator=document.creator,
        producer=document.producer,
        language=document.language,
    )

    xmp_stream = PdfStream(data=xmp_bytes, compress=False)
    xmp_stream.dictionary["Type"] = PdfName("Metadata")
    xmp_stream.dictionary["Subtype"] = PdfName("XML")
    metadata_ref = assembler.add(xmp_stream)

    intent_ref = build_output_intent(assembler)

    return {
        "Metadata": metadata_ref,
        "OutputIntents": PdfArray([intent_ref]),
    }
