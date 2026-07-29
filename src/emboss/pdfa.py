"""PDF/A-2b and PDF/A-3b conformance utilities.

Adds the metadata and output intent entries that upgrade a standard PDF
to PDF/A-2b (ISO 19005-2) or PDF/A-3b (ISO 19005-3, which additionally
permits arbitrary embedded files). Level B requires:

  - XMP metadata with pdfaid:part=2, conformance=B
  - An output intent with /DestOutputProfile (sRGB for RGB documents,
    a generic CGATS TR 001 CMYK condition for color_mode="cmyk")
  - All fonts embedded (already handled by the core font pipeline)
  - No transparency issues (not applicable — we emit only opaque fills)

Dates are pinned to a deterministic value so output stays reproducible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream

if TYPE_CHECKING:
    from .facturx import FacturXMeta

__all__ = [
    "build_xmp_metadata",
    "build_xmp_stream",
    "build_output_intent",
    "pdfa_catalog_entries",
    "pdfa_part_for",
    "WTPDF_REUSE_ID",
]

_FIXED_DATE = "2024-01-01T00:00:00Z"

_VALID_PARTS = (2, 3)

_PDFUA_SCHEMA_LI = """
          <rdf:li rdf:parseType="Resource">
            <pdfaSchema:schema>PDF/UA identification schema</pdfaSchema:schema>
            <pdfaSchema:namespaceURI>http://www.aiim.org/pdfua/ns/id/</pdfaSchema:namespaceURI>
            <pdfaSchema:prefix>pdfuaid</pdfaSchema:prefix>
            <pdfaSchema:property>
              <rdf:Seq>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>part</pdfaProperty:name>
                  <pdfaProperty:valueType>Integer</pdfaProperty:valueType>
                  <pdfaProperty:category>internal</pdfaProperty:category>
                  <pdfaProperty:description>PDF/UA conformance level</pdfaProperty:description>
                </rdf:li>
              </rdf:Seq>
            </pdfaSchema:property>
          </rdf:li>"""

_FACTURX_SCHEMA_LI = """
          <rdf:li rdf:parseType="Resource">
            <pdfaSchema:schema>Factur-X PDFA Extension Schema</pdfaSchema:schema>
            <pdfaSchema:namespaceURI>urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#</pdfaSchema:namespaceURI>
            <pdfaSchema:prefix>fx</pdfaSchema:prefix>
            <pdfaSchema:property>
              <rdf:Seq>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>DocumentType</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>INVOICE</pdfaProperty:description>
                </rdf:li>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>DocumentFileName</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>Name of the embedded XML invoice file</pdfaProperty:description>
                </rdf:li>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>Version</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>The actual version of the Factur-X data</pdfaProperty:description>
                </rdf:li>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>ConformanceLevel</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>external</pdfaProperty:category>
                  <pdfaProperty:description>The conformance level of the Factur-X data</pdfaProperty:description>
                </rdf:li>
              </rdf:Seq>
            </pdfaSchema:property>
          </rdf:li>"""

_PDFX_SCHEMA_LI = """
          <rdf:li rdf:parseType="Resource">
            <pdfaSchema:schema>PDF/X identification schema</pdfaSchema:schema>
            <pdfaSchema:namespaceURI>http://www.npes.org/pdfx/ns/id/</pdfaSchema:namespaceURI>
            <pdfaSchema:prefix>pdfxid</pdfaSchema:prefix>
            <pdfaSchema:property>
              <rdf:Seq>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>GTS_PDFXVersion</pdfaProperty:name>
                  <pdfaProperty:valueType>Text</pdfaProperty:valueType>
                  <pdfaProperty:category>internal</pdfaProperty:category>
                  <pdfaProperty:description>ID of PDF/X standard</pdfaProperty:description>
                </rdf:li>
              </rdf:Seq>
            </pdfaSchema:property>
          </rdf:li>"""

_WTPDF_SCHEMA_LI = """
          <rdf:li rdf:parseType="Resource">
            <pdfaSchema:schema>PDF Declarations schema</pdfaSchema:schema>
            <pdfaSchema:namespaceURI>http://pdfa.org/declarations/</pdfaSchema:namespaceURI>
            <pdfaSchema:prefix>pdfd</pdfaSchema:prefix>
            <pdfaSchema:property>
              <rdf:Seq>
                <rdf:li rdf:parseType="Resource">
                  <pdfaProperty:name>declarations</pdfaProperty:name>
                  <pdfaProperty:valueType>Bag Declaration</pdfaProperty:valueType>
                  <pdfaProperty:category>internal</pdfaProperty:category>
                  <pdfaProperty:description>Set of PDF declarations of conformance</pdfaProperty:description>
                </rdf:li>
              </rdf:Seq>
            </pdfaSchema:property>
          </rdf:li>"""

#: XMP conformsTo identifier for WTPDF 1.0, "Reuse" conformance level.
WTPDF_REUSE_ID = "http://pdfa.org/declarations/wtpdf/#reuse1.0"


def pdfa_part_for(has_attachments: bool) -> int:
    """Return the PDF/A part to declare: 3 when files are attached, else 2."""
    return 3 if has_attachments else 2


def _validate_part(part: int) -> None:
    """Reject PDF/A parts this library cannot declare."""
    if part not in _VALID_PARTS:
        raise ValueError(f"unsupported PDF/A part {part!r}; must be one of 2, 3")


def build_xmp_metadata(
    title: str,
    author: str,
    subject: str,
    keywords: str,
    creator: str,
    producer: str,
    language: str,
    pdfa: bool = True,
    tagged: bool = True,
    part: int = 2,
    facturx: "FacturXMeta | None" = None,
    pdfx: str | None = None,
    wtpdf: bool = False,
) -> bytes:
    """Generate an XMP metadata packet for PDF/A (2b or 3b) and PDF/UA-1.

    The packet is a well-formed XML document with all required namespaces.
    ``pdfa`` controls the pdfaid part/conformance declaration and ``part``
    selects PDF/A-2 or PDF/A-3 (level B either way); ``tagged`` controls
    the pdfuaid part declaration (PDF/UA-1 for tagged output). ``facturx``
    injects the ZUGFeRD/Factur-X ``fx`` namespace values plus its
    pdfaExtension schema so the packet declares the embedded invoice.
    ``pdfx`` (e.g. ``"PDF/X-4"``) adds the pdfxid GTS_PDFXVersion key and
    ``wtpdf`` adds the PDF Association WTPDF 1.0 "Reuse" conformance
    declaration; each also emits a matching pdfaExtension schema entry.
    Dates are deterministic for reproducible output.
    """
    _validate_part(part)
    keyword_tags = ""
    if keywords:
        items = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        if items:
            keyword_tags = f"""
         <pdf:Keywords>{_xml_escape(keywords)}</pdf:Keywords>"""

    pdfa_ns = ""
    pdfa_props = ""
    if pdfa:
        pdfa_ns = '\n      xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"'
        pdfa_props = f"""
      <pdfaid:part>{part}</pdfaid:part>
      <pdfaid:conformance>B</pdfaid:conformance>
"""
    pdfua_ns = ""
    pdfua_props = ""
    if tagged:
        pdfua_ns = '\n      xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/"'
        pdfua_props = """
      <pdfuaid:part>1</pdfuaid:part>
"""
    pdfx_ns = ""
    pdfx_props = ""
    if pdfx:
        pdfx_ns = '\n      xmlns:pdfxid="http://www.npes.org/pdfx/ns/id/"'
        pdfx_props = f"""
      <pdfxid:GTS_PDFXVersion>{_xml_escape(pdfx)}</pdfxid:GTS_PDFXVersion>
"""
    fx_ns = ""
    fx_props = ""
    if facturx is not None:
        fx_ns = (
            '\n      xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#"'
        )
        fx_props = f"""
      <fx:DocumentType>{_xml_escape(facturx.document_type)}</fx:DocumentType>
      <fx:DocumentFileName>{_xml_escape(facturx.filename)}</fx:DocumentFileName>
      <fx:Version>{_xml_escape(facturx.version)}</fx:Version>
      <fx:ConformanceLevel>{_xml_escape(facturx.conformance_level)}</fx:ConformanceLevel>
"""

    schema_items = []
    if tagged and pdfa:
        schema_items.append(_PDFUA_SCHEMA_LI)
    if facturx is not None:
        schema_items.append(_FACTURX_SCHEMA_LI)
    if pdfx:
        schema_items.append(_PDFX_SCHEMA_LI)
    if wtpdf:
        schema_items.append(_WTPDF_SCHEMA_LI)
    pdfua_ext = ""
    if schema_items:
        joined = "".join(schema_items)
        pdfua_ext = f"""
    <rdf:Description rdf:about=""
      xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/"
      xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#"
      xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">
      <pdfaExtension:schemas>
        <rdf:Bag>{joined}
        </rdf:Bag>
      </pdfaExtension:schemas>
    </rdf:Description>
"""

    wtpdf_block = ""
    if wtpdf:
        wtpdf_block = f"""
    <rdf:Description rdf:about=""
      xmlns:pdfd="http://pdfa.org/declarations/">
      <pdfd:declarations>
        <rdf:Bag>
          <rdf:li rdf:parseType="Resource">
            <pdfd:conformsTo>{WTPDF_REUSE_ID}</pdfd:conformsTo>
          </rdf:li>
        </rdf:Bag>
      </pdfd:declarations>
    </rdf:Description>
"""

    xmp = f"""<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:xmp="http://ns.adobe.com/xap/1.0/"
      xmlns:pdf="http://ns.adobe.com/pdf/1.3/"{pdfa_ns}{pdfua_ns}{pdfx_ns}{fx_ns}>

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
{pdfa_props}{pdfua_props}{pdfx_props}{fx_props}
    </rdf:Description>{pdfua_ext}{wtpdf_block}
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
        tag_entries.append(
            sig + data_offset.to_bytes(4, "big") + len(payload).to_bytes(4, "big")
        )
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
    desc_payload += b"\x00"  # ScriptCode count (no localized description)
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

    # rTRC, gTRC, bTRC — sRGB tone curve as an ICC v2 'curv' gamma tag.
    # The 'para' parametric type is ICC v4-only and invalid in a v2 profile;
    # a single-entry curv tag encodes gamma 2.2 (the standard sRGB
    # approximation) as a u8Fixed8 value.
    gamma_payload = b"curv" + b"\x00" * 4
    gamma_payload += (1).to_bytes(4, "big")  # count 1 => gamma value follows
    gamma_payload += int(round(2.2 * 256)).to_bytes(2, "big")  # u8Fixed8 2.2

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


def _build_minimal_cmyk_icc() -> bytes:
    """Build a minimal CMYK output (prtr) ICC v2 profile.

    Constructs the header plus the required tags for an output-class
    profile: desc, wtpt, cprt, and lut8 A2B0/B2A0 tables. The lookup
    tables use identity ramps and a 2-point CLUT derived from the naive
    CMYK<->RGB conversion — enough for output intent validation, not
    for colorimetric accuracy.
    """
    header = bytearray(128)
    header[4:8] = b"appl"
    header[8:12] = b"\x02\x10\x00\x00"
    header[12:16] = b"prtr"
    header[16:20] = b"CMYK"
    header[20:24] = b"XYZ "
    header[24:26] = (2024).to_bytes(2, "big")
    header[26:28] = (1).to_bytes(2, "big")
    header[28:30] = (1).to_bytes(2, "big")
    header[36:40] = b"acsp"
    header[40:44] = b"APPL"
    header[64:68] = (0).to_bytes(4, "big")
    header[68:72] = _s15f16(0.9642)
    header[72:76] = _s15f16(1.0)
    header[76:80] = _s15f16(0.8249)
    header[80:84] = b"none"

    tag_count = 10
    tag_entries: list[tuple[bytes, int, int]] = []
    tag_payloads: list[bytes] = []
    data_offset = 128 + 4 + tag_count * 12

    def add_tag(sig: bytes, payload: bytes) -> tuple[int, int]:
        nonlocal data_offset
        while len(payload) % 4 != 0:
            payload += b"\x00"
        entry = (sig, data_offset, len(payload))
        tag_entries.append(entry)
        tag_payloads.append(payload)
        data_offset += len(payload)
        return entry[1], entry[2]

    def add_alias(sig: bytes, offset: int, size: int) -> None:
        tag_entries.append((sig, offset, size))

    desc_text = b"Generic CMYK (CGATS TR 001 compatible)"
    desc_payload = b"desc" + b"\x00" * 4
    desc_payload += (len(desc_text) + 1).to_bytes(4, "big")
    desc_payload += desc_text + b"\x00"
    desc_payload += b"\x00" * 4
    desc_payload += b"\x00" * 4
    desc_payload += b"\x00" * 2
    desc_payload += b"\x00"  # ScriptCode count (no localized description)
    desc_payload += b"\x00" * 67
    add_tag(b"desc", desc_payload)

    xyz_payload = b"XYZ " + b"\x00" * 4
    xyz_payload += _s15f16(0.9642) + _s15f16(1.0) + _s15f16(0.8249)
    add_tag(b"wtpt", xyz_payload)

    identity_matrix = (
        _s15f16(1.0)
        + _s15f16(0.0)
        + _s15f16(0.0)
        + _s15f16(0.0)
        + _s15f16(1.0)
        + _s15f16(0.0)
        + _s15f16(0.0)
        + _s15f16(0.0)
        + _s15f16(1.0)
    )
    ramp = bytes(range(256))

    def clut_a2b() -> bytes:
        out = bytearray()
        for c in (0, 1):
            for m in (0, 1):
                for y_ in (0, 1):
                    for k in (0, 1):
                        r = (1 - c) * (1 - k)
                        g = (1 - m) * (1 - k)
                        b = (1 - y_) * (1 - k)
                        x_val = 0.4124 * r + 0.3576 * g + 0.1805 * b
                        y_val = 0.2126 * r + 0.7152 * g + 0.0722 * b
                        z_val = 0.0193 * r + 0.1192 * g + 0.9505 * b
                        for v in (x_val, y_val, z_val):
                            out.append(min(255, int(round(v * 255))))
        return bytes(out)

    a2b0 = b"mft1" + b"\x00" * 4
    a2b0 += bytes([4, 3, 2, 0])
    a2b0 += identity_matrix
    a2b0 += ramp * 4
    a2b0 += clut_a2b()
    a2b0 += ramp * 3
    a2b_offset, a2b_size = add_tag(b"A2B0", a2b0)
    # ICC v2 output-class profiles require all three rendering-intent
    # LUTs; the colorimetric and saturation intents share the data.
    add_alias(b"A2B1", a2b_offset, a2b_size)
    add_alias(b"A2B2", a2b_offset, a2b_size)

    def clut_b2a() -> bytes:
        out = bytearray()
        for x_ in (0, 1):
            for y_ in (0, 1):
                for z_ in (0, 1):
                    k = 1 - max(x_, y_, z_)
                    out.extend(
                        [(1 - x_) * 255, (1 - y_) * 255, (1 - z_) * 255, k * 255]
                    )
        return bytes(out)

    b2a0 = b"mft1" + b"\x00" * 4
    b2a0 += bytes([3, 4, 2, 0])
    b2a0 += identity_matrix
    b2a0 += ramp * 3
    b2a0 += clut_b2a()
    b2a0 += ramp * 4
    b2a_offset, b2a_size = add_tag(b"B2A0", b2a0)
    add_alias(b"B2A1", b2a_offset, b2a_size)
    add_alias(b"B2A2", b2a_offset, b2a_size)

    # gamt — required gamut tag: 3-in/1-out LUT, everything in gamut (0)
    gamut = b"mft1" + b"\x00" * 4
    gamut += bytes([3, 1, 2, 0])
    gamut += identity_matrix
    gamut += ramp * 3
    gamut += b"\x00" * 8
    gamut += ramp
    add_tag(b"gamt", gamut)

    cprt_text = b"No copyright, use freely"
    cprt_payload = b"text" + b"\x00" * 4 + cprt_text + b"\x00"
    add_tag(b"cprt", cprt_payload)

    tag_table = tag_count.to_bytes(4, "big") + b"".join(
        sig + offset.to_bytes(4, "big") + size.to_bytes(4, "big")
        for sig, offset, size in tag_entries
    )
    body = b"".join(tag_payloads)
    profile = bytes(header) + tag_table + body
    return len(profile).to_bytes(4, "big") + profile[4:]


def build_output_intent(assembler, color_mode: str = "rgb") -> PdfRef:
    """Create an output intent for PDF/A color management.

    RGB documents get the sRGB IEC61966-2.1 intent (N=3); CMYK documents
    get an N=4 intent whose OutputConditionIdentifier names the standard
    CGATS TR 001 (SWOP) printing condition. PDF/A-2 permits omitting
    DestOutputProfile when the identifier names a registered standard
    condition, but a minimal profile is embedded anyway so readers that
    expect one can still color-manage the file.
    """
    if color_mode == "cmyk":
        icc_data = _build_minimal_cmyk_icc()
        components = 4
        condition = "CGATS TR 001"
    else:
        icc_data = _build_minimal_srgb_icc()
        components = 3
        condition = "sRGB IEC61966-2.1"

    icc_stream = PdfStream(data=icc_data, compress=True)
    icc_stream.dictionary["N"] = components
    icc_ref = assembler.add(icc_stream)

    intent = PdfDict()
    intent["Type"] = PdfName("OutputIntent")
    intent["S"] = PdfName("GTS_PDFA1")
    intent["OutputConditionIdentifier"] = condition
    intent["RegistryName"] = "http://www.color.org"
    intent["Info"] = condition
    intent["DestOutputProfile"] = icc_ref

    return assembler.add(intent)


def build_xmp_stream(assembler, document, pdfa: bool = True, part: int = 2) -> PdfRef:
    """Add an XMP metadata stream for *document* and return its reference.

    Usable for non-PDF/A documents too (``pdfa=False`` drops the pdfaid
    declaration but keeps the PDF/UA identifier for tagged output). The
    caller sets the returned reference as the catalog's /Metadata entry.
    """
    from .pdfx import PDFX_VERSION

    xmp_bytes = build_xmp_metadata(
        title=document.title,
        author=document.author,
        subject=document.subject,
        keywords=document.keywords,
        creator=document.creator,
        producer=document.producer,
        language=document.language,
        pdfa=pdfa,
        tagged=getattr(document, "tagged", True),
        part=part,
        facturx=getattr(document, "_facturx_meta", None),
        pdfx=PDFX_VERSION if getattr(document, "pdfx", False) else None,
        wtpdf=getattr(document, "wtpdf", False),
    )

    xmp_stream = PdfStream(data=xmp_bytes, compress=False)
    xmp_stream.dictionary["Type"] = PdfName("Metadata")
    xmp_stream.dictionary["Subtype"] = PdfName("XML")
    return assembler.add(xmp_stream)


def pdfa_catalog_entries(assembler, document, part: int = 2) -> dict:
    """Return entries to add to the PDF catalog for PDF/A conformance.

    ``part`` selects PDF/A-2b (default) or PDF/A-3b; part 3 is required
    when arbitrary files are attached (use ``pdfa_part_for``). The caller
    merges the returned dict into the catalog PdfDict before finalizing.
    """
    _validate_part(part)
    metadata_ref = build_xmp_stream(assembler, document, pdfa=True, part=part)
    intent_ref = build_output_intent(assembler, getattr(document, "color_mode", "rgb"))

    return {
        "Metadata": metadata_ref,
        "OutputIntents": PdfArray([intent_ref]),
    }
