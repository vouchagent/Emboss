"""Font metrics: exact glyph advances, kerning, and vertical metrics.

Embedded fonts are parsed with fontTools rather than a hand-written
TrueType parser. Font formats have decades of accumulated edge cases
(malformed cmaps, missing OS/2 tables, CFF vs glyf outlines) and
fontTools already handles them.

The base-14 PDF fonts need no embedding, so their metrics ship as data.
This lets Phase 1 produce valid PDFs with no font files present.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["FontMetrics", "FontRegistry", "BASE_14"]

# Widths for the standard 14 fonts, in 1000-unit em space, for the
# printable ASCII range. Values are from the Adobe Core Font AFM set.
_HELVETICA_WIDTHS = (
    278,
    278,
    355,
    556,
    556,
    889,
    667,
    191,
    333,
    333,
    389,
    584,
    278,
    333,
    278,
    278,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    278,
    278,
    584,
    584,
    584,
    556,
    1015,
    667,
    667,
    722,
    722,
    667,
    611,
    778,
    722,
    278,
    500,
    667,
    556,
    833,
    722,
    778,
    667,
    778,
    722,
    667,
    611,
    722,
    667,
    944,
    667,
    667,
    611,
    278,
    278,
    278,
    469,
    556,
    333,
    556,
    556,
    500,
    556,
    556,
    278,
    556,
    556,
    222,
    222,
    500,
    222,
    833,
    556,
    556,
    556,
    556,
    333,
    500,
    278,
    556,
    500,
    722,
    500,
    500,
    500,
    334,
    260,
    334,
    584,
)
_HELVETICA_BOLD_WIDTHS = (
    278,
    333,
    474,
    556,
    556,
    889,
    722,
    238,
    333,
    333,
    389,
    584,
    278,
    333,
    278,
    278,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    556,
    333,
    333,
    584,
    584,
    584,
    611,
    975,
    722,
    722,
    722,
    722,
    667,
    611,
    778,
    722,
    278,
    556,
    722,
    611,
    833,
    722,
    778,
    667,
    778,
    722,
    667,
    611,
    722,
    667,
    944,
    667,
    667,
    611,
    333,
    278,
    333,
    584,
    556,
    333,
    556,
    611,
    556,
    611,
    556,
    333,
    611,
    611,
    278,
    278,
    556,
    278,
    889,
    611,
    611,
    611,
    611,
    389,
    556,
    333,
    611,
    556,
    778,
    556,
    556,
    500,
    389,
    280,
    389,
    584,
)
_TIMES_WIDTHS = (
    250,
    333,
    408,
    500,
    500,
    833,
    778,
    180,
    333,
    333,
    500,
    564,
    250,
    333,
    250,
    278,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    278,
    278,
    564,
    564,
    564,
    444,
    921,
    722,
    667,
    667,
    722,
    611,
    556,
    722,
    722,
    333,
    389,
    722,
    611,
    889,
    722,
    722,
    556,
    722,
    667,
    556,
    611,
    722,
    722,
    944,
    722,
    722,
    611,
    333,
    278,
    333,
    469,
    500,
    333,
    444,
    500,
    444,
    500,
    444,
    333,
    500,
    500,
    278,
    278,
    500,
    278,
    778,
    500,
    500,
    500,
    500,
    333,
    389,
    278,
    500,
    500,
    722,
    500,
    500,
    444,
    480,
    200,
    480,
    541,
)
_TIMES_BOLD_WIDTHS = (
    250,
    333,
    555,
    500,
    500,
    1000,
    833,
    278,
    333,
    333,
    500,
    570,
    250,
    333,
    250,
    278,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    500,
    333,
    333,
    570,
    570,
    570,
    500,
    930,
    722,
    667,
    722,
    722,
    667,
    611,
    778,
    778,
    389,
    500,
    778,
    667,
    944,
    722,
    778,
    611,
    778,
    722,
    556,
    667,
    722,
    722,
    1000,
    722,
    722,
    667,
    333,
    278,
    333,
    581,
    500,
    333,
    500,
    556,
    444,
    556,
    444,
    333,
    500,
    556,
    278,
    333,
    556,
    278,
    833,
    556,
    500,
    556,
    556,
    444,
    389,
    333,
    556,
    500,
    722,
    500,
    500,
    444,
    394,
    220,
    394,
    520,
)
_COURIER_WIDTHS = tuple([600] * 95)

# Exact AFM widths for high-frequency WinAnsi codepoints beyond ASCII.
# Keys are Unicode codepoints; values are 1000-unit em advances taken from
# the Adobe Core Font AFM files. NBSP (U+00A0) and soft hyphen (U+00AD)
# are derived from space and hyphen at table-build time.
_HELVETICA_EXT = {
    0x00A2: 556,
    0x00A3: 556,
    0x00A5: 556,
    0x00A7: 556,
    0x00A9: 737,
    0x00AB: 556,
    0x00AE: 737,
    0x00B0: 400,
    0x00B1: 584,
    0x00B5: 556,
    0x00B7: 278,
    0x00BB: 556,
    0x00D7: 584,
    0x00F7: 584,
    0x2013: 556,
    0x2014: 1000,
    0x2018: 222,
    0x2019: 222,
    0x201A: 222,
    0x201C: 333,
    0x201D: 333,
    0x201E: 333,
    0x2020: 556,
    0x2021: 556,
    0x2022: 350,
    0x2026: 1000,
    0x2030: 1000,
    0x2039: 333,
    0x203A: 333,
    0x20AC: 556,
    0x2122: 1000,
}
_HELVETICA_BOLD_EXT = {
    0x00A2: 556,
    0x00A3: 556,
    0x00A5: 556,
    0x00A7: 556,
    0x00A9: 737,
    0x00AB: 556,
    0x00AE: 737,
    0x00B0: 400,
    0x00B1: 584,
    0x00B5: 611,
    0x00B7: 278,
    0x00BB: 556,
    0x00D7: 584,
    0x00F7: 584,
    0x2013: 556,
    0x2014: 1000,
    0x2018: 278,
    0x2019: 278,
    0x201A: 278,
    0x201C: 500,
    0x201D: 500,
    0x201E: 500,
    0x2020: 556,
    0x2021: 556,
    0x2022: 350,
    0x2026: 1000,
    0x2030: 1000,
    0x2039: 333,
    0x203A: 333,
    0x20AC: 556,
    0x2122: 1000,
}
_TIMES_EXT = {
    0x00A2: 500,
    0x00A3: 500,
    0x00A5: 500,
    0x00A7: 500,
    0x00A9: 760,
    0x00AB: 500,
    0x00AE: 760,
    0x00B0: 400,
    0x00B1: 564,
    0x00B5: 500,
    0x00B7: 250,
    0x00BB: 500,
    0x00D7: 564,
    0x00F7: 564,
    0x2013: 500,
    0x2014: 1000,
    0x2018: 333,
    0x2019: 333,
    0x201A: 333,
    0x201C: 444,
    0x201D: 444,
    0x201E: 444,
    0x2020: 500,
    0x2021: 500,
    0x2022: 350,
    0x2026: 1000,
    0x2030: 1000,
    0x2039: 333,
    0x203A: 333,
    0x20AC: 500,
    0x2122: 980,
}
_TIMES_BOLD_EXT = {
    0x00A2: 500,
    0x00A3: 500,
    0x00A5: 500,
    0x00A7: 500,
    0x00A9: 747,
    0x00AB: 500,
    0x00AE: 747,
    0x00B0: 400,
    0x00B1: 570,
    0x00B5: 556,
    0x00B7: 250,
    0x00BB: 500,
    0x00D7: 570,
    0x00F7: 570,
    0x2013: 500,
    0x2014: 1000,
    0x2018: 333,
    0x2019: 333,
    0x201A: 333,
    0x201C: 500,
    0x201D: 500,
    0x201E: 500,
    0x2020: 500,
    0x2021: 500,
    0x2022: 350,
    0x2026: 1000,
    0x2030: 1000,
    0x2039: 333,
    0x203A: 333,
    0x20AC: 500,
    0x2122: 1000,
}
_COURIER_EXT = dict.fromkeys(_HELVETICA_EXT, 600)
_SYMBOL_EXT = {
    0x00AC: 713,
    0x00B0: 400,
    0x00B1: 549,
    0x00B7: 250,
    0x00D7: 549,
    0x00F7: 549,
    # Uppercase Greek (exact Symbol AFM values)
    0x0391: 722,
    0x0392: 667,
    0x0393: 603,
    0x0394: 612,
    0x0395: 611,
    0x0396: 611,
    0x0397: 722,
    0x0398: 741,
    0x0399: 333,
    0x039A: 722,
    0x039B: 686,
    0x039C: 889,
    0x039D: 722,
    0x039E: 645,
    0x039F: 722,
    0x03A0: 768,
    0x03A1: 556,
    0x03A3: 592,
    0x03A4: 611,
    0x03A5: 690,
    0x03A6: 763,
    0x03A7: 722,
    0x03A8: 795,
    0x03A9: 768,
    # Lowercase Greek (exact Symbol AFM values)
    0x03B1: 631,
    0x03B2: 549,
    0x03B3: 411,
    0x03B4: 494,
    0x03B5: 439,
    0x03B6: 494,
    0x03B7: 603,
    0x03B8: 521,
    0x03B9: 329,
    0x03BA: 549,
    0x03BB: 549,
    0x03BC: 576,
    0x03BD: 521,
    0x03BE: 493,
    0x03BF: 549,
    0x03C0: 549,
    0x03C1: 549,
    0x03C2: 439,
    0x03C3: 603,
    0x03C4: 439,
    0x03C5: 576,
    0x03C6: 521,
    0x03C7: 549,
    0x03C8: 686,
    0x03C9: 686,
    # Math operators, relations, arrows (exact Symbol AFM values)
    0x2022: 460,
    0x2026: 1000,
    0x2032: 247,
    0x2033: 411,
    0x2135: 823,
    0x2190: 987,
    0x2191: 603,
    0x2192: 987,
    0x2193: 603,
    0x2194: 1042,
    0x21D0: 987,
    0x21D1: 603,
    0x21D2: 987,
    0x21D3: 603,
    0x21D4: 1042,
    0x2200: 713,
    0x2202: 494,
    0x2203: 549,
    0x2205: 823,
    0x2207: 713,
    0x2208: 713,
    0x2209: 713,
    0x220B: 439,
    0x220F: 823,
    0x2211: 713,
    0x221A: 549,
    0x221D: 713,
    0x221E: 713,
    0x2220: 768,
    0x2227: 603,
    0x2228: 603,
    0x2229: 768,
    0x222A: 768,
    0x222B: 274,
    0x223C: 549,
    0x2245: 549,
    0x2248: 549,
    0x2260: 549,
    0x2261: 549,
    0x2264: 549,
    0x2265: 549,
    0x2282: 713,
    0x2283: 713,
    0x2284: 713,
    0x2286: 713,
    0x2287: 713,
    0x2295: 768,
    0x2297: 768,
    0x22A5: 658,
}

# name -> extended width table (oblique/italic variants share the tables,
# matching how the ASCII width tuples above are shared).
_EXTENDED_WIDTHS: dict[str, dict[int, int]] = {
    "Helvetica": _HELVETICA_EXT,
    "Helvetica-Bold": _HELVETICA_BOLD_EXT,
    "Helvetica-Oblique": _HELVETICA_EXT,
    "Helvetica-BoldOblique": _HELVETICA_BOLD_EXT,
    "Times-Roman": _TIMES_EXT,
    "Times-Bold": _TIMES_BOLD_EXT,
    "Times-Italic": _TIMES_EXT,
    "Times-BoldItalic": _TIMES_BOLD_EXT,
    "Courier": _COURIER_EXT,
    "Courier-Bold": _COURIER_EXT,
    "Courier-Oblique": _COURIER_EXT,
    "Courier-BoldOblique": _COURIER_EXT,
    "Symbol": _SYMBOL_EXT,
}

# name -> (widths, ascender, descender, cap_height, is_fixed, flags)
BASE_14: dict[str, tuple] = {
    "Helvetica": (_HELVETICA_WIDTHS, 718, -207, 718, False, 32),
    "Helvetica-Bold": (_HELVETICA_BOLD_WIDTHS, 718, -207, 718, False, 32),
    "Helvetica-Oblique": (_HELVETICA_WIDTHS, 718, -207, 718, False, 96),
    "Helvetica-BoldOblique": (_HELVETICA_BOLD_WIDTHS, 718, -207, 718, False, 96),
    "Times-Roman": (_TIMES_WIDTHS, 683, -217, 662, False, 34),
    "Times-Bold": (_TIMES_BOLD_WIDTHS, 683, -217, 676, False, 34),
    "Times-Italic": (_TIMES_WIDTHS, 683, -217, 653, False, 98),
    "Times-BoldItalic": (_TIMES_BOLD_WIDTHS, 683, -217, 669, False, 98),
    "Courier": (_COURIER_WIDTHS, 629, -157, 562, True, 33),
    "Courier-Bold": (_COURIER_WIDTHS, 629, -157, 562, True, 33),
    "Courier-Oblique": (_COURIER_WIDTHS, 629, -157, 562, True, 97),
    "Courier-BoldOblique": (_COURIER_WIDTHS, 629, -157, 562, True, 97),
    "Symbol": (_HELVETICA_WIDTHS, 700, -200, 700, False, 4),
    "ZapfDingbats": (_HELVETICA_WIDTHS, 700, -200, 700, False, 4),
}

_FIRST_PRINTABLE = 32
_MISSING_WIDTH = 500


@dataclass
class FontMetrics:
    """Glyph metrics for one font, in 1000-unit text space."""

    name: str
    ascender: float
    descender: float
    cap_height: float
    flags: int
    is_embedded: bool = False
    font_path: Path | None = None
    _widths: dict = field(default_factory=dict)
    _kerning: dict = field(default_factory=dict)
    _class_kerning: list = field(default_factory=list)
    _default_width: float = _MISSING_WIDTH
    _used_codepoints: set = field(default_factory=set)
    _gid_map: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._text_width_cache: dict[tuple, float] = {}
        self._class_kern_memo: dict[tuple, float] = {}

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other) -> bool:
        return self is other

    # -- construction --

    @classmethod
    def base14(cls, name: str) -> "FontMetrics":
        if name not in BASE_14:
            raise KeyError(f"{name!r} is not a base-14 PDF font")
        widths, asc, desc, cap, _fixed, flags = BASE_14[name]
        table = {_FIRST_PRINTABLE + i: float(w) for i, w in enumerate(widths)}
        for codepoint, width in _EXTENDED_WIDTHS.get(name, {}).items():
            table[codepoint] = float(width)
        table[0x00A0] = table[0x20]  # NBSP advances like a space
        table[0x00AD] = table[0x2D]  # soft hyphen advances like a hyphen
        return cls(
            name=name,
            ascender=float(asc),
            descender=float(desc),
            cap_height=float(cap),
            flags=flags,
            is_embedded=False,
            _widths=table,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "FontMetrics":
        """Load metrics from a TrueType/OpenType file via fontTools."""
        from fontTools.ttLib import TTFont

        path = Path(path)
        font = TTFont(str(path), lazy=True, fontNumber=0)
        try:
            upem = font["head"].unitsPerEm or 1000
            scale = 1000.0 / upem

            cmap = font.getBestCmap()
            hmtx = font["hmtx"]
            widths = {}
            for codepoint, glyph_name in cmap.items():
                try:
                    advance = hmtx[glyph_name][0]
                except KeyError:
                    continue
                widths[codepoint] = advance * scale

            if "OS/2" in font:
                os2 = font["OS/2"]
                ascender = os2.sTypoAscender * scale
                descender = os2.sTypoDescender * scale
                cap_height = getattr(os2, "sCapHeight", None)
                cap_height = cap_height * scale if cap_height else ascender * 0.7
            else:
                hhea = font["hhea"]
                ascender = hhea.ascent * scale
                descender = hhea.descent * scale
                cap_height = ascender * 0.7

            gid_map = {}
            for codepoint_key, glyph_name in cmap.items():
                try:
                    gid_map[codepoint_key] = font.getGlyphID(glyph_name)
                except Exception:
                    pass

            name = _postscript_name(font) or path.stem
            metrics = cls(
                name=name,
                ascender=ascender,
                descender=descender,
                cap_height=cap_height,
                flags=32,
                is_embedded=True,
                font_path=path,
                _widths=widths,
                _gid_map=gid_map,
            )
            class_tables: list = []
            metrics._kerning = _extract_kerning(font, scale, class_tables)
            metrics._class_kerning = class_tables
            return metrics
        finally:
            font.close()

    # -- measurement --

    def width_of(self, codepoint: int) -> float:
        width = self._widths.get(codepoint)
        if width is None:
            width = self._fallback_width(codepoint)
        return width

    def _fallback_width(self, codepoint: int) -> float:
        """Resolve a missing codepoint via NFD decomposition to its base letter."""
        if not self.is_embedded:
            base = ord(unicodedata.normalize("NFD", chr(codepoint))[0])
            if base != codepoint:
                width = self._widths.get(base)
                if width is not None:
                    # Base-14 fonts carry the precomposed Latin glyphs at
                    # the base letter's advance; cache so later lookups
                    # are plain dict hits.
                    self._widths[codepoint] = width
                    return width
        return self._default_width

    def text_width(self, text: str, size: float, kerning: bool = True) -> float:
        """Exact advance width of `text` at `size` points."""
        if not text:
            return 0.0
        cache_key = (text, size, kerning)
        cached = self._text_width_cache.get(cache_key)
        if cached is not None:
            return cached
        total = 0.0
        previous = None
        widths = self._widths
        kern_map = self._kerning
        lazy = self._class_kerning
        for char in text:
            code = ord(char)
            width = widths.get(code)
            if width is None:
                width = self._fallback_width(code)
            total += width
            if kerning and previous is not None:
                adjust = kern_map.get((previous, code))
                if adjust is None and lazy:
                    adjust = self._resolve_class_kern(previous, code)
                if adjust:
                    total += adjust
            previous = code
        result = total * size / 1000.0
        if len(self._text_width_cache) < 4096:
            self._text_width_cache[cache_key] = result
        return result

    def kern(self, left: int, right: int) -> float:
        """Kerning adjustment for a codepoint pair, in 1000-unit em space."""
        adjust = self._kerning.get((left, right))
        if adjust is None and self._class_kerning:
            adjust = self._resolve_class_kern(left, right)
        return adjust or 0.0

    def _resolve_class_kern(self, left: int, right: int) -> float:
        """Resolve GPOS Format 2 class kerning on demand, memoized per pair."""
        key = (left, right)
        cached = self._class_kern_memo.get(key)
        if cached is not None:
            return cached
        value = 0.0
        for table in self._class_kerning:
            adjust = table.lookup(left, right)
            if adjust:
                value = adjust
                break
        if len(self._class_kern_memo) < 65536:
            self._class_kern_memo[key] = value
        return value

    def kern_pairs(self, text: str) -> list:
        """Return (index, adjustment) pairs for kerning inside `text`."""
        if len(text) < 2 or (not self._kerning and not self._class_kerning):
            return []
        pairs = []
        for i in range(1, len(text)):
            adjust = self.kern(ord(text[i - 1]), ord(text[i]))
            if adjust:
                pairs.append((i, adjust))
        return pairs

    def small_caps_width(self, text: str, size: float) -> float:
        """Width of text rendered in small caps.

        Lowercase letters are measured as their uppercase counterpart at
        80% of the requested size; uppercase letters and non-alphabetic
        characters use the full size.
        """
        total = 0.0
        sc_size = size * 0.8
        for char in text:
            if char.islower():
                total += self.width_of(ord(char.upper())) * sc_size / 1000.0
            else:
                total += self.width_of(ord(char)) * size / 1000.0
        return total

    def line_height(self, size: float, multiplier: float = 1.2) -> float:
        natural = (self.ascender - self.descender) / 1000.0 * size
        return natural * multiplier

    def ascent(self, size: float) -> float:
        return self.ascender / 1000.0 * size

    def descent(self, size: float) -> float:
        return self.descender / 1000.0 * size

    # -- subsetting support --

    def note_usage(self, text: str) -> None:
        """Record codepoints so only used glyphs get embedded."""
        if self.is_embedded:
            self._used_codepoints.update(ord(c) for c in text)

    @property
    def used_codepoints(self) -> set:
        return set(self._used_codepoints)

    def supports(self, char: str) -> bool:
        return ord(char) in self._widths

    @property
    def gid_map(self) -> dict | None:
        return self._gid_map if self.is_embedded and self._gid_map else None


def _postscript_name(font) -> str | None:
    try:
        record = font["name"].getDebugName(6)
    except Exception:
        return None
    return record


def _is_symbolic(font) -> bool:
    try:
        return font["OS/2"].usWidthClass == 0
    except Exception:
        return False


def _extract_kerning(font, scale: float, class_tables: list | None = None) -> dict:
    """Pull kern pairs from the legacy ``kern`` table, then supplement
    with GPOS PairPos subtables.

    Legacy kern pairs take precedence when both tables define the same
    pair, because hand-tuned kern table values are typically more
    carefully adjusted for specific pairs. Lazy GPOS Format 2 class
    tables are appended to ``class_tables`` when a list is supplied.
    """
    reverse_cmap: dict = {}
    for codepoint, glyph_name in font.getBestCmap().items():
        reverse_cmap.setdefault(glyph_name, codepoint)

    pairs: dict = {}

    # -- legacy kern table --
    if "kern" in font:
        try:
            for subtable in font["kern"].kernTables:
                for (left, right), value in subtable.kernTable.items():
                    left_cp = reverse_cmap.get(left)
                    right_cp = reverse_cmap.get(right)
                    if left_cp is not None and right_cp is not None:
                        pairs[(left_cp, right_cp)] = value * scale
        except Exception:
            pass

    # -- GPOS PairPos subtables --
    tables = _extract_gpos_kerning(font, scale, reverse_cmap, pairs)
    if class_tables is not None:
        class_tables.extend(tables)

    return pairs


def _extract_gpos_kerning(font, scale: float, reverse_cmap: dict, pairs: dict) -> list:
    """Extract GPOS PairPos kerning; Format 1 fills ``pairs`` eagerly and
    Format 2 subtables are returned as lazy class tables.

    Uses ``setdefault`` so that legacy kern values are never overwritten.
    Extension lookups (LookupType 9) are unwrapped to their inner PairPos
    subtables. Wrapped in a broad ``except`` so unusual GPOS structures
    do not crash font loading.
    """
    tables: list = []
    if "GPOS" not in font:
        return tables
    try:
        gpos = font["GPOS"].table
        seen: set = set()
        for feature_record in gpos.FeatureList.FeatureRecord:
            if feature_record.FeatureTag != "kern":
                continue
            for lookup_index in feature_record.Feature.LookupListIndex:
                if lookup_index in seen:
                    continue
                seen.add(lookup_index)
                lookup = gpos.LookupList.Lookup[lookup_index]
                for subtable in _pair_subtables(lookup):
                    fmt = getattr(subtable, "Format", None)
                    if fmt == 1:
                        _gpos_format1(subtable, reverse_cmap, scale, pairs)
                    elif fmt == 2:
                        tables.append(
                            _ClassKernTable.from_subtable(subtable, reverse_cmap, scale)
                        )
    except Exception:
        pass
    return tables


def _pair_subtables(lookup):
    """Yield PairPos subtables, unwrapping Extension (LookupType 9) wrappers."""
    lookup_type = getattr(lookup, "LookupType", 2)
    if lookup_type == 9:
        for ext in lookup.SubTable:
            if getattr(ext, "ExtensionLookupType", None) == 2:
                inner = getattr(ext, "ExtSubTable", None)
                if inner is not None:
                    yield inner
    elif lookup_type == 2:
        yield from lookup.SubTable


def _pair_adjustment(record, scale: float) -> float:
    """Summed XAdvance of Value1 and Value2, scaled to 1000-unit em space."""
    adj = 0
    value1 = getattr(record, "Value1", None)
    if value1 is not None:
        adj += getattr(value1, "XAdvance", 0) or 0
    value2 = getattr(record, "Value2", None)
    if value2 is not None:
        adj += getattr(value2, "XAdvance", 0) or 0
    return adj * scale


def _gpos_format1(subtable, reverse_cmap, scale, pairs) -> None:
    """PairPos Format 1: explicit individual pair list."""
    for pairset_idx, pairset in enumerate(subtable.PairSet):
        first_glyph = subtable.Coverage.glyphs[pairset_idx]
        first_cp = reverse_cmap.get(first_glyph)
        if first_cp is None:
            continue
        for pvr in pairset.PairValueRecord:
            second_cp = reverse_cmap.get(pvr.SecondGlyph)
            if second_cp is None:
                continue
            adj = _pair_adjustment(pvr, scale)
            if adj:
                pairs.setdefault((first_cp, second_cp), adj)


@dataclass(frozen=True)
class _ClassKernTable:
    """Lazy GPOS PairPos Format 2 class kerning, keyed by codepoint."""

    coverage: frozenset
    class1: dict
    class2: dict
    values: tuple

    @classmethod
    def from_subtable(
        cls, subtable, reverse_cmap: dict, scale: float
    ) -> "_ClassKernTable":
        """Convert a fontTools Format 2 subtable to codepoint-keyed form."""
        coverage = frozenset(
            cp
            for g in subtable.Coverage.glyphs
            if (cp := reverse_cmap.get(g)) is not None
        )
        class1 = {
            cp: klass
            for g, klass in subtable.ClassDef1.classDefs.items()
            if (cp := reverse_cmap.get(g)) is not None
        }
        class2 = {
            cp: klass
            for g, klass in subtable.ClassDef2.classDefs.items()
            if (cp := reverse_cmap.get(g)) is not None
        }
        values = tuple(
            tuple(_pair_adjustment(rec, scale) for rec in class1_rec.Class2Record)
            for class1_rec in subtable.Class1Record
        )
        return cls(coverage, class1, class2, values)

    def lookup(self, left: int, right: int) -> float | None:
        """Return the class-pair adjustment, or None when left is uncovered."""
        if left not in self.coverage:
            return None
        row_idx = self.class1.get(left, 0)
        if row_idx >= len(self.values):
            return None
        row = self.values[row_idx]
        col_idx = self.class2.get(right, 0)
        if col_idx >= len(row):
            return None
        return row[col_idx]


def _gpos_format2(subtable, reverse_cmap, scale, pairs) -> None:
    """PairPos Format 2 eagerly expanded to pairs; compatibility path only."""
    table = _ClassKernTable.from_subtable(subtable, reverse_cmap, scale)
    rights = sorted(table.class2)
    for left in sorted(table.coverage):
        for right in rights:
            adj = table.lookup(left, right)
            if adj:
                pairs.setdefault((left, right), adj)


class FontRegistry:
    """Resolves style requests (family, bold, italic) to concrete fonts."""

    _BASE14_MAP = {
        ("helvetica", False, False): "Helvetica",
        ("helvetica", True, False): "Helvetica-Bold",
        ("helvetica", False, True): "Helvetica-Oblique",
        ("helvetica", True, True): "Helvetica-BoldOblique",
        ("times", False, False): "Times-Roman",
        ("times", True, False): "Times-Bold",
        ("times", False, True): "Times-Italic",
        ("times", True, True): "Times-BoldItalic",
        ("courier", False, False): "Courier",
        ("courier", True, False): "Courier-Bold",
        ("courier", False, True): "Courier-Oblique",
        ("courier", True, True): "Courier-BoldOblique",
        ("symbol", False, False): "Symbol",
    }

    def __init__(self) -> None:
        self._cache: dict = {}
        self._custom: dict = {}

    def register(
        self, family: str, path: str | Path, bold: bool = False, italic: bool = False
    ) -> None:
        """Register an embedded font file for a family/style combination."""
        key = (family.lower(), bold, italic)
        self._custom[key] = Path(path)
        self._cache.pop(key, None)

    def resolve(
        self, family: str, bold: bool = False, italic: bool = False
    ) -> FontMetrics:
        key = (family.lower(), bold, italic)
        if key in self._cache:
            return self._cache[key]

        if key in self._custom:
            metrics = FontMetrics.from_file(self._custom[key])
        else:
            name = self._BASE14_MAP.get(key)
            if name is None:
                # Fall back to the regular weight of a known family, then
                # to Helvetica. Never fail at render time over a font name.
                name = self._BASE14_MAP.get((family.lower(), False, False), "Helvetica")
                if bold and italic:
                    name = self._BASE14_MAP.get(
                        (family.lower(), True, True), "Helvetica-BoldOblique"
                    )
            metrics = FontMetrics.base14(name)

        self._cache[key] = metrics
        return metrics

    def is_available(self, family: str) -> bool:
        low = family.lower()
        return any(k[0] == low for k in self._BASE14_MAP) or any(
            k[0] == low for k in self._custom
        )

    def all_loaded(self) -> list:
        return list(self._cache.values())
