"""Binary PDF assembly with exact byte-offset tracking.

The xref table is built from real offsets recorded as objects are written,
so it cannot drift from the file contents. Output is byte-reproducible:
no timestamps, no random IDs, no hash-ordered iteration.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .objects import PdfDict, PdfName, PdfObject, PdfRef, PdfStream, serialize

__all__ = ["PDFAssembler", "AssemblyError"]

PDF_VERSION = b"%PDF-1.7"
# Binary comment marking the file as containing 8-bit data (per spec advice).
BINARY_MARKER = b"%\xe2\xe3\xcf\xd3"


class AssemblyError(RuntimeError):
    """Raised when the object graph cannot be serialized correctly."""


@dataclass
class PDFAssembler:
    """Writes a PDF object graph to bytes, tracking offsets exactly."""

    _buffer: bytearray = field(default_factory=bytearray)
    _offsets: dict = field(default_factory=dict)
    _objects: dict = field(default_factory=dict)
    _next_id: int = 1
    _finalized: bool = False

    def allocate(self) -> int:
        """Reserve an object id without writing it yet.

        Needed because PDF graphs are cyclic (Pages refers to Page, Page
        refers back to Pages), so ids must exist before content does.
        """
        obj_id = self._next_id
        self._next_id += 1
        return obj_id

    def add(self, obj: PdfObject, obj_id: int | None = None) -> PdfRef:
        """Register an object, returning a reference to it."""
        if obj_id is None:
            obj_id = self.allocate()
        if obj_id in self._objects:
            raise AssemblyError(f"object {obj_id} already assigned")
        self._objects[obj_id] = obj
        return PdfRef(obj_id)

    def _write(self, data: bytes) -> None:
        self._buffer.extend(data)

    def _write_object(self, obj_id: int, obj: PdfObject) -> None:
        # Record the offset BEFORE writing anything for this object.
        self._offsets[obj_id] = len(self._buffer)
        self._write(f"{obj_id} 0 obj\n".encode("ascii"))
        self._write(serialize(obj))
        self._write(b"\nendobj\n")

    def _document_id(self, catalog_ref: PdfRef) -> bytes:
        """Derive a stable /ID from content rather than time or randomness.

        PDF requires a file identifier. Most writers use a timestamp or
        random bytes, which destroys reproducibility. Hashing the body
        gives a value that is stable for identical input and still changes
        when the document changes.
        """
        digest = hashlib.sha256()
        digest.update(bytes(self._buffer))
        digest.update(str(catalog_ref.obj_id).encode("ascii"))
        return digest.digest()[:16]

    def build(self, catalog_ref: PdfRef, info: PdfDict | None = None) -> bytes:
        """Serialize all registered objects into a complete PDF file."""
        if self._finalized:
            raise AssemblyError("assembler already finalized")
        self._finalized = True

        missing = set(range(1, self._next_id)) - set(self._objects)
        if missing:
            raise AssemblyError(
                f"allocated but never populated object ids: {sorted(missing)}"
            )

        self._write(PDF_VERSION + b"\n")
        self._write(BINARY_MARKER + b"\n")

        # Ascending id order keeps output stable and matches the xref layout.
        for obj_id in sorted(self._objects):
            self._write_object(obj_id, self._objects[obj_id])

        info_ref = None
        if info is not None:
            info_id = self.allocate()
            self._write_object(info_id, info)
            info_ref = PdfRef(info_id)

        file_id = self._document_id(catalog_ref)
        xref_offset = self._write_xref()
        self._write_trailer(catalog_ref, info_ref, file_id, xref_offset)
        return bytes(self._buffer)

    def _write_xref(self) -> int:
        """Write the cross-reference table. Entries are exactly 20 bytes."""
        xref_offset = len(self._buffer)
        count = self._next_id
        self._write(b"xref\n")
        self._write(f"0 {count}\n".encode("ascii"))
        self._write(b"0000000000 65535 f \n")
        for obj_id in range(1, count):
            offset = self._offsets.get(obj_id)
            if offset is None:
                raise AssemblyError(f"no recorded offset for object {obj_id}")
            entry = f"{offset:010d} 00000 n \n".encode("ascii")
            if len(entry) != 20:
                raise AssemblyError("xref entry is not 20 bytes")
            self._write(entry)
        return xref_offset

    def _write_trailer(
        self,
        catalog_ref: PdfRef,
        info_ref: PdfRef | None,
        file_id: bytes,
        xref_offset: int,
    ) -> None:
        trailer = PdfDict()
        trailer["Size"] = self._next_id
        trailer["Root"] = catalog_ref
        if info_ref is not None:
            trailer["Info"] = info_ref
        # Both halves identical: original and current version are the same.
        trailer["ID"] = [file_id, file_id]

        self._write(b"trailer\n")
        self._write(serialize(trailer))
        self._write(b"\nstartxref\n")
        self._write(str(xref_offset).encode("ascii"))
        self._write(b"\n%%EOF\n")

    # -- introspection helpers used by the verifier and tests --

    @property
    def object_count(self) -> int:
        return self._next_id - 1

    def offset_of(self, obj_id: int) -> int:
        return self._offsets[obj_id]
