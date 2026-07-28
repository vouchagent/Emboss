"""Font resource construction and embedding.

Base-14 fonts need only a simple dictionary. Embedded fonts use the
Type0/CIDFontType2 composite font architecture, which supports the
full Unicode range via Identity-H encoding and 2-byte glyph IDs.
Every embedded font gets a /ToUnicode CMap so text extraction, search,
and screen readers produce correct Unicode — without it PDF/UA fails
regardless of structure tree correctness.
"""

from __future__ import annotations

from dataclasses import dataclass

from .objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream

__all__ = ["FontResource", "build_font_resource"]


@dataclass
class FontResource:
    """A font as referenced from a page's resource dictionary."""

    key: str
    metrics: object
    ref: PdfRef


def build_font_resource(assembler, key: str, metrics) -> FontResource:
    """Register the PDF objects for one font and return its resource."""
    if metrics.is_embedded:
        ref = _build_embedded(assembler, metrics)
    else:
        ref = _build_base14(assembler, metrics)
    return FontResource(key=key, metrics=metrics, ref=ref)


def _build_base14(assembler, metrics) -> PdfRef:
    font = PdfDict()
    font["Type"] = PdfName("Font")
    font["Subtype"] = PdfName("Type1")
    font["BaseFont"] = PdfName(metrics.name)
    if metrics.name not in ("Symbol", "ZapfDingbats"):
        font["Encoding"] = PdfName("WinAnsiEncoding")
    return assembler.add(font)


def _subset_font(metrics) -> tuple:
    """Subset the font to used codepoints.

    Returns (bytes, sorted_codepoints).  retain_gids=True preserves
    original glyph IDs so the CID mapping built before subsetting
    stays valid in the content streams.
    """
    from io import BytesIO

    from fontTools import subset
    from fontTools.ttLib import TTFont

    codepoints = metrics.used_codepoints or {0x20}
    font = TTFont(
        str(metrics.font_path),
        lazy=False,
        fontNumber=0,
        recalcTimestamp=False,
    )

    options = subset.Options()
    options.set(
        layout_features=["*"],
        notdef_outline=True,
        recalc_bounds=True,
        drop_tables=[],
        hinting=True,
    )
    options.retain_gids = True
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.glyph_names = True

    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=codepoints)
    subsetter.subset(font)

    buffer = BytesIO()
    font.save(buffer, reorderTables=False)
    data = buffer.getvalue()
    font.close()
    return data, sorted(codepoints)


def _subset_tag(codepoints) -> str:
    """Deterministic six-letter subset prefix derived from content.

    PDF requires a unique tag per subset. Deriving it from the glyph set
    keeps output reproducible where a random tag would not.
    """
    import hashlib

    digest = hashlib.sha256(
        ",".join(str(c) for c in sorted(codepoints)).encode("ascii")
    ).digest()
    letters = []
    for byte in digest[:6]:
        letters.append(chr(ord("A") + byte % 26))
    return "".join(letters)


def _program_advances(data: bytes) -> tuple:
    """Return (unitsPerEm, {gid: advance}) read from a font program's hmtx."""
    import io as _io

    from fontTools.ttLib import TTFont

    font = TTFont(_io.BytesIO(data), lazy=True)
    try:
        upm = int(font["head"].unitsPerEm) or 1000
        hmtx = font["hmtx"]
        order = font.getGlyphOrder()
        advances = {}
        for gid, name in enumerate(order):
            advances[gid] = hmtx[name][0]
        return upm, advances
    finally:
        font.close()


def _build_cid_widths(program_advances) -> PdfArray:
    """Build the W array for a CIDFont from the embedded program's advances.

    PDF/A clause 6.2.11.4.2 requires CIDSet to mark every CID present in
    the font program regardless of use, and clause 6.2.11.5 then requires
    every one of those CIDs to have a width matching the program's hmtx.
    Since retain_gids keeps the full glyph-slot range, W must cover every
    glyph 0..numGlyphs-1, not just the ones Emboss references.
    Groups consecutive GIDs: [startGID [w1 w2 ...] nextStartGID [w3] ...].
    """
    upm, advances = program_advances
    entries = [(gid, round(advances[gid] * 1000 / upm)) for gid in sorted(advances)]

    if not entries:
        return PdfArray()

    w = PdfArray()
    i = 0
    while i < len(entries):
        start_gid = entries[i][0]
        widths = [entries[i][1]]
        j = i + 1
        while j < len(entries) and entries[j][0] == start_gid + len(widths):
            widths.append(entries[j][1])
            j += 1
        w.items.append(start_gid)
        w.items.append(PdfArray(widths))
        i = j
    return w


def _build_cid_set(num_glyphs: int) -> bytes:
    """Build a CIDSet bitmap marking every CID present in the subset font.

    Clause 6.2.11.4.2 requires CIDSet to identify all CIDs present in the
    font program regardless of whether they are referenced or used, so
    with CIDToGIDMap Identity every glyph slot 0..num_glyphs-1 is marked.
    """
    full, remainder = divmod(max(num_glyphs, 0), 8)
    data = bytearray(b"\xff" * full)
    if remainder:
        data.append((0xFF << (8 - remainder)) & 0xFF)
    return bytes(data)


def _build_embedded(assembler, metrics) -> PdfRef:
    data, codepoints = _subset_font(metrics)
    gid_map = metrics.gid_map or {}
    tag = _subset_tag(codepoints)
    base_name = f"{tag}+{metrics.name}".replace(" ", "")

    file_stream = PdfStream(data=data)
    file_stream.dictionary["Length1"] = len(data)
    file_ref = assembler.add(file_stream)

    advances = _program_advances(data)
    cid_set_ref = assembler.add(PdfStream(data=_build_cid_set(len(advances[1]))))

    descriptor = PdfDict()
    descriptor["Type"] = PdfName("FontDescriptor")
    descriptor["FontName"] = PdfName(base_name)
    descriptor["Flags"] = metrics.flags
    descriptor["FontBBox"] = PdfArray(
        [-200, round(metrics.descender), 1200, round(metrics.ascender)]
    )
    descriptor["ItalicAngle"] = 0
    descriptor["Ascent"] = round(metrics.ascender)
    descriptor["Descent"] = round(metrics.descender)
    descriptor["CapHeight"] = round(metrics.cap_height)
    descriptor["StemV"] = 80
    descriptor["FontFile2"] = file_ref
    descriptor["CIDSet"] = cid_set_ref
    descriptor_ref = assembler.add(descriptor)

    cid_sys = PdfDict()
    cid_sys["Registry"] = "Adobe"
    cid_sys["Ordering"] = "Identity"
    cid_sys["Supplement"] = 0

    w_array = _build_cid_widths(advances)

    cid_font = PdfDict()
    cid_font["Type"] = PdfName("Font")
    cid_font["Subtype"] = PdfName("CIDFontType2")
    cid_font["BaseFont"] = PdfName(base_name)
    cid_font["CIDSystemInfo"] = cid_sys
    cid_font["W"] = w_array
    cid_font["DW"] = round(metrics._default_width)
    cid_font["FontDescriptor"] = descriptor_ref
    cid_font["CIDToGIDMap"] = PdfName("Identity")
    cid_font_ref = assembler.add(cid_font)

    to_unicode = _build_to_unicode(codepoints, gid_map)
    to_unicode_ref = assembler.add(PdfStream(data=to_unicode))

    font = PdfDict()
    font["Type"] = PdfName("Font")
    font["Subtype"] = PdfName("Type0")
    font["BaseFont"] = PdfName(base_name)
    font["Encoding"] = PdfName("Identity-H")
    font["DescendantFonts"] = PdfArray([cid_font_ref])
    font["ToUnicode"] = to_unicode_ref
    return assembler.add(font)


def _build_to_unicode(codepoints, gid_map) -> bytes:
    """Build a CMap mapping 2-byte CIDs (= GIDs) back to Unicode.

    This is what makes copy-paste, search, and screen readers work.
    """
    entries = []
    for cp in sorted(codepoints):
        gid = gid_map.get(cp)
        if gid is not None and gid > 0:
            entries.append((gid, cp))
    entries.sort()

    if not entries:
        entries = [(0, 0x20)]

    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo <</Registry (Adobe) /Ordering (UCS) /Supplement 0>> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]

    for start in range(0, len(entries), 100):
        chunk = entries[start : start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for gid, cp in chunk:
            if cp <= 0xFFFF:
                lines.append(f"<{gid:04X}> <{cp:04X}>")
            else:
                hi = 0xD800 + ((cp - 0x10000) >> 10)
                lo = 0xDC00 + ((cp - 0x10000) & 0x3FF)
                lines.append(f"<{gid:04X}> <{hi:04X}{lo:04X}>")
        lines.append("endbfchar")

    lines.extend(
        [
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
        ]
    )
    return "\n".join(lines).encode("ascii")
