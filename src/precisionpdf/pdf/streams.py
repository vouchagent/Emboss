"""Content stream generation.

Text is emitted with the TJ operator so kerning pairs from the font are
applied between glyphs, rather than Tj which draws a string with default
advances. Every piece of real content is wrapped in BDC/EMC marked-content
operators carrying an MCID, which is what links the visible page to the
PDF/UA structure tree. Decorative material (rules, watermarks, running
heads, Bates numbers) is marked as /Artifact so assistive technology
skips it.

Embedded fonts use CID (2-byte hex) encoding via Identity-H; base-14
fonts use single-byte WinAnsi literal strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .objects import fmt_number

__all__ = ["ContentStream", "hex_color"]


def hex_color(value: str) -> tuple:
    """Convert 'rrggbb' to a 0-1 RGB triple."""
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise ValueError(f"invalid hex color: {value!r}")
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _escape_text(text: str) -> bytes:
    """Escape a string for a PDF literal string in a content stream."""
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


def _cid_encode_text(text: str, gid_map: dict) -> bytes:
    """Encode text as a hex string of 2-byte glyph IDs for CIDFont."""
    parts = []
    for ch in text:
        gid = gid_map.get(ord(ch), 0)
        parts.append(f"{gid:04X}")
    return b"<" + "".join(parts).encode("ascii") + b">"


def _encode_text(text: str, gid_map: dict | None) -> bytes:
    """Encode text for a PDF content stream, choosing the right mode."""
    if gid_map is not None:
        return _cid_encode_text(text, gid_map)
    return _escape_text(text)


@dataclass
class ContentStream:
    """Accumulates PDF page operators."""

    _ops: list = field(default_factory=list)
    _mcid: int = 0
    _font_stack: list = field(default_factory=list)

    def __init__(self) -> None:
        self._ops = []
        self._mcid = 0

    # -- raw emission --

    def raw(self, data: bytes) -> None:
        self._ops.append(data)

    def _num(self, value: float) -> bytes:
        return fmt_number(value)

    # -- graphics state --

    def save(self) -> None:
        self.raw(b"q")

    def restore(self) -> None:
        self.raw(b"Q")

    def set_fill(self, color: str) -> None:
        r, g, b = hex_color(color)
        self.raw(b" ".join([self._num(r), self._num(g), self._num(b), b"rg"]))

    def set_stroke(self, color: str) -> None:
        r, g, b = hex_color(color)
        self.raw(b" ".join([self._num(r), self._num(g), self._num(b), b"RG"]))

    def set_line_width(self, width: float) -> None:
        self.raw(self._num(width) + b" w")

    def set_ext_gstate(self, name: str) -> None:
        self.raw(f"/{name} gs".encode("ascii"))

    # -- marked content (accessibility) --

    def begin_marked(self, tag: str, mcid: int) -> None:
        self.raw(f"/{tag} <</MCID {mcid}>> BDC".encode("ascii"))

    def begin_artifact(self, subtype: str = "Layout") -> None:
        self.raw(f"/Artifact <</Type /Pagination /Subtype /{subtype}>> BDC"
                 .encode("ascii"))

    def end_marked(self) -> None:
        self.raw(b"EMC")

    # -- text --

    def text_line(
        self,
        text: str,
        font_key: str,
        size: float,
        x: float,
        y: float,
        color: str,
        kern_pairs=None,
        gid_map=None,
    ) -> None:
        """Draw one run of text at (x, y).

        When *gid_map* is provided (embedded CIDFont), text is encoded
        as 2-byte hex glyph IDs. Otherwise WinAnsi literal strings are used.
        """
        if not text:
            return
        self.raw(b"BT")
        self.set_fill(color)
        self.raw(f"/{font_key} ".encode("ascii") + self._num(size) + b" Tf")
        self.raw(b" ".join([self._num(x), self._num(y), b"Td"]))

        if kern_pairs:
            self.raw(self._kerned_array(text, kern_pairs, gid_map) + b" TJ")
        else:
            self.raw(_encode_text(text, gid_map) + b" Tj")
        self.raw(b"ET")

    def _kerned_array(self, text: str, kern_pairs, gid_map=None) -> bytes:
        """Build a TJ array: strings interleaved with kern adjustments.

        PDF kern values are in thousandths of an em and subtract from the
        advance, hence the sign flip.
        """
        segments = bytearray(b"[")
        previous = 0
        for index, adjustment in kern_pairs:
            if index > previous:
                segments.extend(_encode_text(text[previous:index], gid_map))
            segments.extend(b" ")
            segments.extend(fmt_number(-adjustment, precision=2))
            segments.extend(b" ")
            previous = index
        if previous < len(text):
            segments.extend(_encode_text(text[previous:], gid_map))
        segments.extend(b"]")
        return bytes(segments)

    # -- shapes --

    def rect(self, x: float, y: float, width: float, height: float,
             fill: str | None = None, stroke: str | None = None,
             line_width: float = 0.5) -> None:
        if fill:
            self.set_fill(fill)
        if stroke:
            self.set_stroke(stroke)
            self.set_line_width(line_width)
        self.raw(b" ".join([
            self._num(x), self._num(y), self._num(width), self._num(height),
            b"re",
        ]))
        if fill and stroke:
            self.raw(b"B")
        elif fill:
            self.raw(b"f")
        else:
            self.raw(b"S")

    def line(self, x1: float, y1: float, x2: float, y2: float,
             color: str = "000000", width: float = 0.5) -> None:
        self.set_stroke(color)
        self.set_line_width(width)
        self.raw(b" ".join([self._num(x1), self._num(y1), b"m"]))
        self.raw(b" ".join([self._num(x2), self._num(y2), b"l"]))
        self.raw(b"S")

    def rotated_text(self, text: str, font_key: str, size: float,
                     x: float, y: float, color: str, degrees: float,
                     gid_map=None) -> None:
        """Draw text rotated about (x, y) — used for diagonal watermarks."""
        import math

        radians = math.radians(degrees)
        cos, sin = math.cos(radians), math.sin(radians)
        self.raw(b"BT")
        self.set_fill(color)
        self.raw(f"/{font_key} ".encode("ascii") + self._num(size) + b" Tf")
        self.raw(b" ".join([
            self._num(cos), self._num(sin), self._num(-sin), self._num(cos),
            self._num(x), self._num(y), b"Tm",
        ]))
        self.raw(_encode_text(text, gid_map) + b" Tj")
        self.raw(b"ET")

    def next_mcid(self) -> int:
        value = self._mcid
        self._mcid += 1
        return value

    @property
    def mcid_count(self) -> int:
        return self._mcid

    def to_bytes(self) -> bytes:
        return b"\n".join(self._ops) + b"\n"
