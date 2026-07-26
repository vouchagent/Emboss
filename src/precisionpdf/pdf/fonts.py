"""Font resource construction and embedding.

Base-14 fonts need only a simple dictionary. Embedded fonts are subsetted
with fontTools so only glyphs actually used are written, and every
embedded font gets a /ToUnicode CMap -- without it text extraction and
screen readers produce garbage, which fails PDF/UA regardless of how
correct the structure tree is.
"""

from __future__ import annotations

from dataclasses import dataclass

from .objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream

__all__ = ["FontResource", "build_font_resource"]

_WINANSI_FIRST = 32
_WINANSI_LAST = 255


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
    """Subset the font to used codepoints. Returns (bytes, glyph_order)."""
    from io import BytesIO

    from fontTools import subset
    from fontTools.ttLib import TTFont

    codepoints = metrics.used_codepoints or {0x20}
    font = TTFont(str(metrics.font_path), lazy=False, fontNumber=0)

    options = subset.Options()
    options.set(layout_features=["*"], notdef_outline=True,
                recalc_bounds=True, drop_tables=[], hinting=True)
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


def _build_embedded(assembler, metrics) -> PdfRef:
    from fontTools.ttLib import TTFont

    data, codepoints = _subset_font(metrics)
    tag = _subset_tag(codepoints)
    base_name = f"{tag}+{metrics.name}".replace(" ", "")

    # Widths must be indexed by character code for a simple font, so we
    # emit the WinAnsi range and fall back to the missing width elsewhere.
    first, last = _WINANSI_FIRST, _WINANSI_LAST
    widths = PdfArray([
        round(metrics.width_of(code), 2) for code in range(first, last + 1)
    ])

    file_stream = PdfStream(data=data)
    file_stream.dictionary["Length1"] = len(data)
    file_ref = assembler.add(file_stream)

    descriptor = PdfDict()
    descriptor["Type"] = PdfName("FontDescriptor")
    descriptor["FontName"] = PdfName(base_name)
    descriptor["Flags"] = metrics.flags
    descriptor["FontBBox"] = PdfArray([
        -200, round(metrics.descender), 1200, round(metrics.ascender)
    ])
    descriptor["ItalicAngle"] = 0
    descriptor["Ascent"] = round(metrics.ascender)
    descriptor["Descent"] = round(metrics.descender)
    descriptor["CapHeight"] = round(metrics.cap_height)
    descriptor["StemV"] = 80
    descriptor["FontFile2"] = file_ref
    descriptor_ref = assembler.add(descriptor)

    to_unicode = _build_to_unicode(codepoints)
    to_unicode_ref = assembler.add(PdfStream(data=to_unicode))

    font = PdfDict()
    font["Type"] = PdfName("Font")
    font["Subtype"] = PdfName("TrueType")
    font["BaseFont"] = PdfName(base_name)
    font["FirstChar"] = first
    font["LastChar"] = last
    font["Widths"] = widths
    font["FontDescriptor"] = descriptor_ref
    font["Encoding"] = PdfName("WinAnsiEncoding")
    font["ToUnicode"] = to_unicode_ref
    return assembler.add(font)


def _build_to_unicode(codepoints) -> bytes:
    """Build a CMap mapping character codes back to Unicode.

    This is what makes copy-paste, search, and screen readers work.
    """
    entries = [c for c in codepoints if _WINANSI_FIRST <= c <= _WINANSI_LAST]
    if not entries:
        entries = [0x20]

    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo <</Registry (Adobe) /Ordering (UCS) /Supplement 0>> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<00> <FF>",
        "endcodespacerange",
    ]

    # bfchar sections are capped at 100 entries by the specification.
    for start in range(0, len(entries), 100):
        chunk = entries[start:start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for code in chunk:
            lines.append(f"<{code:02X}> <{code:04X}>")
        lines.append("endbfchar")

    lines.extend([
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ])
    return "\n".join(lines).encode("ascii")
