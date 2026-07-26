"""Font metrics: exact glyph advances, kerning, and vertical metrics.

Embedded fonts are parsed with fontTools rather than a hand-written
TrueType parser. Font formats have decades of accumulated edge cases
(malformed cmaps, missing OS/2 tables, CFF vs glyf outlines) and
fontTools already handles them.

The base-14 PDF fonts need no embedding, so their metrics ship as data.
This lets Phase 1 produce valid PDFs with no font files present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

__all__ = ["FontMetrics", "FontRegistry", "BASE_14"]

# Widths for the standard 14 fonts, in 1000-unit em space, for the
# printable ASCII range. Values are from the Adobe Core Font AFM set.
_HELVETICA_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333,
    278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278,
    584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278,
    500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
    667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
    278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
    278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
_HELVETICA_BOLD_WIDTHS = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333,
    278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333,
    584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278,
    556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
    667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556,
    333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556,
    333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
)
_TIMES_WIDTHS = (
    250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333,
    250, 278, 500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 278, 278,
    564, 564, 564, 444, 921, 722, 667, 667, 722, 611, 556, 722, 722, 333,
    389, 722, 611, 889, 722, 722, 556, 722, 667, 556, 611, 722, 722, 944,
    722, 722, 611, 333, 278, 333, 469, 500, 333, 444, 500, 444, 500, 444,
    333, 500, 500, 278, 278, 500, 278, 778, 500, 500, 500, 500, 333, 389,
    278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541,
)
_TIMES_BOLD_WIDTHS = (
    250, 333, 555, 500, 500, 1000, 833, 278, 333, 333, 500, 570, 250, 333,
    250, 278, 500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 333, 333,
    570, 570, 570, 500, 930, 722, 667, 722, 722, 667, 611, 778, 778, 389,
    500, 778, 667, 944, 722, 778, 611, 778, 722, 556, 667, 722, 722, 1000,
    722, 722, 667, 333, 278, 333, 581, 500, 333, 500, 556, 444, 556, 444,
    333, 500, 556, 278, 333, 556, 278, 833, 556, 500, 556, 556, 444, 389,
    333, 556, 500, 722, 500, 500, 444, 394, 220, 394, 520,
)
_COURIER_WIDTHS = tuple([600] * 95)

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
    _default_width: float = _MISSING_WIDTH
    _used_codepoints: set = field(default_factory=set)
    _gid_map: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._text_width_cache: dict[tuple, float] = {}

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
        table = {
            _FIRST_PRINTABLE + i: float(w) for i, w in enumerate(widths)
        }
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
                cap_height = (
                    cap_height * scale if cap_height else ascender * 0.7
                )
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
            flags = 4 if not _is_symbolic(font) else 4
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
            metrics._kerning = _extract_kerning(font, scale)
            return metrics
        finally:
            font.close()

    # -- measurement --

    def width_of(self, codepoint: int) -> float:
        return self._widths.get(codepoint, self._default_width)

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
        for char in text:
            code = ord(char)
            total += self._widths.get(code, self._default_width)
            if kerning and previous is not None:
                total += self._kerning.get((previous, code), 0.0)
            previous = code
        result = total * size / 1000.0
        if len(self._text_width_cache) < 4096:
            self._text_width_cache[cache_key] = result
        return result

    def kern_pairs(self, text: str) -> list:
        """Return (index, adjustment) pairs for kerning inside `text`."""
        if not self._kerning or len(text) < 2:
            return []
        pairs = []
        for i in range(1, len(text)):
            adjust = self._kerning.get((ord(text[i - 1]), ord(text[i])))
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


def _extract_kerning(font, scale: float) -> dict:
    """Pull kern pairs from the legacy ``kern`` table, then supplement
    with GPOS PairPos subtables.

    Legacy kern pairs take precedence when both tables define the same
    pair, because hand-tuned kern table values are typically more
    carefully adjusted for specific pairs.
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
    _extract_gpos_kerning(font, scale, reverse_cmap, pairs)

    return pairs


def _extract_gpos_kerning(
    font, scale: float, reverse_cmap: dict, pairs: dict
) -> None:
    """Extract kerning from GPOS PairPos (Format 1 and 2) subtables.

    Uses ``setdefault`` so that legacy kern values are never overwritten.
    Wrapped in a broad ``except`` so unusual GPOS structures do not
    crash font loading.
    """
    if "GPOS" not in font:
        return
    try:
        gpos = font["GPOS"].table
        for feature_record in gpos.FeatureList.FeatureRecord:
            if feature_record.FeatureTag != "kern":
                continue
            for lookup_index in feature_record.Feature.LookupListIndex:
                lookup = gpos.LookupList.Lookup[lookup_index]
                for subtable in lookup.SubTable:
                    if subtable.Format == 1:
                        _gpos_format1(subtable, reverse_cmap, scale, pairs)
                    elif subtable.Format == 2:
                        _gpos_format2(subtable, reverse_cmap, scale, pairs)
    except Exception:
        pass


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
            adj = (
                getattr(pvr.Value1, "XAdvance", 0) if pvr.Value1 else 0
            )
            if adj:
                pairs.setdefault((first_cp, second_cp), adj * scale)


def _gpos_format2(subtable, reverse_cmap, scale, pairs) -> None:
    """PairPos Format 2: class-based pair kerning."""
    classDef1 = subtable.ClassDef1.classDefs
    classDef2 = subtable.ClassDef2.classDefs
    for cls1_idx, class1_rec in enumerate(subtable.Class1Record):
        for cls2_idx, class2_rec in enumerate(class1_rec.Class2Record):
            adj = (
                getattr(class2_rec.Value1, "XAdvance", 0)
                if class2_rec.Value1
                else 0
            )
            if not adj:
                continue
            glyphs1 = [g for g, c in classDef1.items() if c == cls1_idx]
            if cls1_idx == 0:
                glyphs1.extend(
                    g
                    for g in subtable.Coverage.glyphs
                    if g not in classDef1
                )
            glyphs2 = [g for g, c in classDef2.items() if c == cls2_idx]
            for g1 in glyphs1:
                cp1 = reverse_cmap.get(g1)
                if cp1 is None:
                    continue
                for g2 in glyphs2:
                    cp2 = reverse_cmap.get(g2)
                    if cp2 is None:
                        continue
                    pairs.setdefault((cp1, cp2), adj * scale)


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

    def register(self, family: str, path: str | Path,
                 bold: bool = False, italic: bool = False) -> None:
        """Register an embedded font file for a family/style combination."""
        key = (family.lower(), bold, italic)
        self._custom[key] = Path(path)
        self._cache.pop(key, None)

    def resolve(self, family: str, bold: bool = False,
                italic: bool = False) -> FontMetrics:
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
                name = self._BASE14_MAP.get(
                    (family.lower(), False, False), "Helvetica"
                )
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
