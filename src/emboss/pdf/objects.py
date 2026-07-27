"""PDF object model with deterministic serialization.

Every object serializes to bytes in a stable, reproducible way. Float
formatting is pinned so the same document always produces the same bytes.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Union

__all__ = [
    "PdfName",
    "PdfString",
    "PdfRef",
    "PdfDict",
    "PdfArray",
    "PdfStream",
    "fmt_number",
    "serialize",
]


def fmt_number(value: float, precision: int = 4) -> bytes:
    """Format a number for PDF output, deterministically.

    PDF has no notion of float repr stability across platforms, so we
    normalize here: fixed precision, trailing zeros stripped, no exponent,
    and negative zero collapsed to zero.
    """
    if isinstance(value, int):
        return str(value).encode("ascii")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"non-finite number in PDF output: {value}")
    quantized = round(float(value), precision)
    if quantized == 0:
        return b"0"
    text = f"{quantized:.{precision}f}".rstrip("0").rstrip(".")
    return (text or "0").encode("ascii")


class PdfObject:
    def serialize(self) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class PdfName(PdfObject):
    """A PDF name object, e.g. /Type. Special chars are #-escaped."""

    value: str

    def serialize(self) -> bytes:
        out = bytearray(b"/")
        for byte in self.value.encode("utf-8"):
            if 0x21 <= byte <= 0x7E and byte not in b"#()<>[]{}/%":
                out.append(byte)
            else:
                out.extend(f"#{byte:02X}".encode("ascii"))
        return bytes(out)


@dataclass(frozen=True)
class PdfString(PdfObject):
    """A literal or hex PDF string.

    Text destined for metadata uses UTF-16BE with a BOM, which is what
    PDF readers expect for non-ASCII document information.
    """

    value: Union[str, bytes]
    hex_mode: bool = False

    def serialize(self) -> bytes:
        if isinstance(self.value, bytes):
            raw = self.value
        elif self.value.isascii():
            raw = self.value.encode("ascii")
        else:
            raw = b"\xfe\xff" + self.value.encode("utf-16-be")

        if self.hex_mode or not raw.isascii():
            return b"<" + raw.hex().upper().encode("ascii") + b">"

        out = bytearray(b"(")
        for byte in raw:
            if byte in b"()\\":
                out.append(0x5C)
                out.append(byte)
            elif byte == 0x0A:
                out.extend(b"\\n")
            elif byte == 0x0D:
                out.extend(b"\\r")
            elif byte < 0x20 or byte > 0x7E:
                out.extend(f"\\{byte:03o}".encode("ascii"))
            else:
                out.append(byte)
        out.append(0x29)
        return bytes(out)


@dataclass(frozen=True)
class PdfRef(PdfObject):
    """An indirect reference: `12 0 R`."""

    obj_id: int
    generation: int = 0

    def serialize(self) -> bytes:
        return f"{self.obj_id} {self.generation} R".encode("ascii")


@dataclass
class PdfArray(PdfObject):
    items: list = field(default_factory=list)

    def append(self, item) -> None:
        self.items.append(item)

    def __len__(self) -> int:
        return len(self.items)

    def serialize(self) -> bytes:
        return b"[" + b" ".join(serialize(i) for i in self.items) + b"]"


@dataclass
class PdfDict(PdfObject):
    """A PDF dictionary.

    Key order follows insertion order, which Python guarantees. That is
    what makes output byte-reproducible: we never iterate an unordered set.
    """

    entries: dict = field(default_factory=dict)

    def __setitem__(self, key: str, value) -> None:
        self.entries[key] = value

    def __getitem__(self, key: str):
        return self.entries[key]

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def get(self, key: str, default=None):
        return self.entries.get(key, default)

    def serialize(self) -> bytes:
        out = bytearray(b"<<")
        for key, value in self.entries.items():
            out.extend(PdfName(key).serialize())
            out.extend(b" ")
            out.extend(serialize(value))
            out.extend(b"\n")
        out.extend(b">>")
        return bytes(out)


@dataclass
class PdfStream(PdfObject):
    """A stream object: a dictionary plus binary data.

    Compression is deterministic: zlib level is pinned, so the same input
    always yields the same compressed bytes.
    """

    data: bytes
    dictionary: PdfDict = field(default_factory=PdfDict)
    compress: bool = True
    _COMPRESSION_LEVEL = 6

    def serialize(self) -> bytes:
        payload = self.data
        if self.compress and len(payload) > 128:
            payload = zlib.compress(payload, self._COMPRESSION_LEVEL)
            self.dictionary["Filter"] = PdfName("FlateDecode")
        self.dictionary["Length"] = len(payload)
        return self.dictionary.serialize() + b"\nstream\n" + payload + b"\nendstream"


def serialize(obj) -> bytes:
    """Serialize any supported Python or PDF value to PDF syntax."""
    if isinstance(obj, PdfObject):
        return obj.serialize()
    if obj is None:
        return b"null"
    if isinstance(obj, bool):
        return b"true" if obj else b"false"
    if isinstance(obj, (int, float)):
        return fmt_number(obj)
    if isinstance(obj, str):
        return PdfString(obj).serialize()
    if isinstance(obj, bytes):
        return PdfString(obj, hex_mode=True).serialize()
    if isinstance(obj, list):
        return PdfArray(obj).serialize()
    if isinstance(obj, dict):
        return PdfDict(obj).serialize()
    raise TypeError(f"cannot serialize {type(obj).__name__} to PDF")
