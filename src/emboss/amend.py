"""Append-only incremental amendment of PDF documents.

An amendment never rewrites the bytes already in a file: it appends a new
body section, a cross-reference table, and a trailer whose ``/Prev`` points
at the previous ``startxref``, continuing object numbering from the prior
maximum (ISO 32000-1 7.5.6, incremental updates). The original bytes remain
a byte-exact prefix of the result, which is what lets a later signature's
``/ByteRange`` attest to everything written before it.

Public surface:

  amend_pdf          append a non-signature attestation revision
  prepare_signature  append a signature revision with a real ``/ByteRange``
                     and an empty ``/Contents`` placeholder (for external
                     signing)
  amend_sign         prepare_signature plus a PKCS#7 signature injected into
                     the placeholder (reuses ``signing.sign_pdf``)
  revision_history   walk the ``/Prev`` chain and classify each revision
  coverage_report    which revisions a later signature's ByteRange covers
  format_history     the plaintext revision/coverage table

Amended files are valid but no longer linearized: the appended revision sits
after the original ``%%EOF``, so fast-web-view linearization is lost. This is
inherent to incremental updates and is the price of never rewriting prior
bytes.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from .pdf.objects import (
    PdfArray,
    PdfDict,
    PdfName,
    PdfObject,
    PdfRef,
    PdfStream,
    PdfString,
    serialize,
)
from .signing import SignatureField, sign_pdf

__all__ = [
    "Attestation",
    "Revision",
    "CoverageReport",
    "amend_pdf",
    "prepare_signature",
    "amend_sign",
    "amend_sign_pades",
    "revision_history",
    "coverage_report",
    "format_history",
    "verify_amended",
]

#: Default fixed timestamp; callers pass their own to stay deterministic.
_DEFAULT_TIMESTAMP = "D:20240101000000Z"

#: Byte length of the ``/Contents`` placeholder; matches ``signing.py`` so
#: ``sign_pdf`` recognizes the placeholder it injects into.
_CONTENTS_PLACEHOLDER_BYTES = 8192
_CONTENTS_HEX_PLACEHOLDER = b"<" + b"0" * (_CONTENTS_PLACEHOLDER_BYTES * 2) + b">"

#: Annotation subtypes an amendment may append under DocMDP /P >= 3.
_ANNOT_SUBTYPE = "Text"

_KIND_BASE = "base"
_KIND_SIGNATURE = "signature"
_KIND_ANNOTATIONS = "annotations"
_KIND_ATTACHMENT = "attachment"
_KIND_OTHER = "other"

_DOCMDP_ALLOWED = {
    1: frozenset(),
    2: frozenset({_KIND_SIGNATURE}),
    3: frozenset({_KIND_SIGNATURE, _KIND_ANNOTATIONS}),
}


# -- public data models ------------------------------------------------------


@dataclass
class Attestation:
    """A non-signature attestation appended as one incremental revision.

    ``kind`` is ``"annotations"`` (a text annotation placed on a page) or
    ``"attachment"`` (an embedded file associated with the document).
    """

    kind: str = _KIND_ANNOTATIONS
    name: str = ""
    reason: str = ""
    page_index: int = 0
    rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    text: str = ""
    filename: str = ""
    payload: bytes = b""

    def __post_init__(self) -> None:
        if self.kind not in (_KIND_ANNOTATIONS, _KIND_ATTACHMENT):
            raise ValueError(
                f"Attestation.kind must be 'annotations' or 'attachment'; "
                f"got {self.kind!r}"
            )
        if self.kind == _KIND_ATTACHMENT and not self.filename:
            raise ValueError("attachment attestation requires a filename")


@dataclass
class Revision:
    """One revision in a PDF's incremental-update chain."""

    index: int
    kind: str
    byte_range: tuple[int, int]
    signer: str | None = None
    reason: str | None = None
    signed: bool = False
    sig_byte_range: tuple[int, int, int, int] | None = None
    covered: bool = False
    covered_by: list[int] = field(default_factory=list)


@dataclass
class CoverageReport:
    """Which revisions are covered by a later signature's ByteRange."""

    revisions: list[Revision]
    fully_covered: bool
    uncovered: list[int]
    signatures: list[int]

    def __str__(self) -> str:
        return format_history(self.revisions)


# -- base-file inspection ----------------------------------------------------


@dataclass
class _BaseInfo:
    size: int
    root_ref: PdfRef
    root_dict: PdfDict
    id_pair: tuple[bytes, bytes] | None
    prev_startxref: int
    page_refs: list[PdfRef]
    page_dicts: list[PdfDict]
    acroform_ref: PdfRef | None
    acroform_dict: PdfDict | None


def _require_pikepdf():
    """Import pikepdf or raise a clear install hint."""
    try:
        import pikepdf
    except ImportError:
        raise ImportError(
            "incremental amendment requires the 'pikepdf' package.\n"
            "  pip install emboss-pdf[verify]"
        ) from None
    return pikepdf


def _convert(value):
    """Convert a pikepdf value to an Emboss PDF object, indirects as refs."""
    import decimal

    pikepdf = _require_pikepdf()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, (float, decimal.Decimal)):
        return float(value)
    if isinstance(value, str):
        return PdfString(value)
    if value is None:
        return None
    if getattr(value, "is_indirect", False):
        objgen = value.objgen
        return PdfRef(objgen[0], objgen[1])
    if isinstance(value, pikepdf.Name):
        text = str(value)
        return PdfName(text[1:] if text.startswith("/") else text)
    if isinstance(value, pikepdf.String):
        raw = bytes(value)
        try:
            return PdfString(raw.decode("ascii"))
        except UnicodeDecodeError:
            return PdfString(raw, hex_mode=True)
    if isinstance(value, pikepdf.Array):
        return PdfArray([_convert(item) for item in value])
    if isinstance(value, pikepdf.Dictionary):
        return _clone_shallow(value)
    raise TypeError(f"cannot convert pikepdf value of type {type(value).__name__}")


def _clone_shallow(pobj) -> PdfDict:
    """Clone a pikepdf dictionary; indirect children become references."""
    out = PdfDict()
    for key, value in pobj.items():
        name = key[1:] if key.startswith("/") else key
        out[name] = _convert(value)
    return out


def _resolve_indirect(pdf_bytes: bytes, obj_id: int):
    """Return a shallow clone of an indirect array or dictionary object."""
    pikepdf = _require_pikepdf()
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        obj = pdf.get_object(obj_id, 0)
        if isinstance(obj, pikepdf.Array):
            return PdfArray([_convert(item) for item in obj])
        return _clone_shallow(obj)


def _ensure_not_encrypted(pdf_bytes: bytes) -> None:
    """Raise a clear ValueError if the base PDF is encrypted."""
    pikepdf = _require_pikepdf()
    message = (
        "cannot amend an encrypted PDF: incremental amendments must match the "
        "base's encryption, which is not supported"
    )
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            if pdf.is_encrypted:
                raise ValueError(message)
    except pikepdf.PasswordError:
        raise ValueError(message) from None


def _read_base_info(pdf_bytes: bytes) -> _BaseInfo:
    """Read everything an amendment needs from the base file, via pikepdf."""
    pikepdf = _require_pikepdf()
    prev = _find_startxref(pdf_bytes)
    if prev is None:
        raise ValueError("base PDF has no startxref; cannot amend")
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        if pdf.is_encrypted:
            raise ValueError(
                "cannot amend an encrypted PDF: incremental amendments must "
                "match the base's encryption, which is not supported"
            )
        size = int(pdf.trailer.Size)
        root = pdf.Root
        root_ref = PdfRef(root.objgen[0], root.objgen[1])
        root_dict = _clone_shallow(root)
        id_obj = pdf.trailer.get("/ID")
        id_pair = None
        if id_obj is not None and len(id_obj) == 2:
            id_pair = (bytes(id_obj[0]), bytes(id_obj[1]))
        page_refs: list[PdfRef] = []
        page_dicts: list[PdfDict] = []
        for page in pdf.pages:
            page_refs.append(PdfRef(page.objgen[0], page.objgen[1]))
            page_dicts.append(_clone_shallow(page))
        acroform = root.get("/AcroForm")
        acroform_ref = None
        acroform_dict = None
        if acroform is not None:
            if acroform.is_indirect:
                acroform_ref = PdfRef(acroform.objgen[0], acroform.objgen[1])
                acroform_dict = _clone_shallow(acroform)
            else:
                acroform_dict = _clone_shallow(acroform)
    size = max(size, _max_objnum(pdf_bytes) + 1)
    return _BaseInfo(
        size=size,
        root_ref=root_ref,
        root_dict=root_dict,
        id_pair=id_pair,
        prev_startxref=prev,
        page_refs=page_refs,
        page_dicts=page_dicts,
        acroform_ref=acroform_ref,
        acroform_dict=acroform_dict,
    )


def _find_startxref(pdf_bytes: bytes) -> int | None:
    """Return the offset the last ``startxref`` points at, or None."""
    index = pdf_bytes.rfind(b"startxref")
    if index == -1:
        return None
    match = re.match(rb"\s*(\d+)", pdf_bytes[index + len(b"startxref") :])
    return int(match.group(1)) if match else None


def _max_objnum(pdf_bytes: bytes) -> int:
    """Highest indirect-object number written as ``N G obj`` in the file."""
    highest = 0
    for match in re.finditer(rb"(\d+)\s+\d+\s+obj\b", pdf_bytes):
        highest = max(highest, int(match.group(1)))
    return highest


# -- incremental writer ------------------------------------------------------


@dataclass
class _Increment:
    """Collects the objects a single incremental revision adds or overrides."""

    _next: int
    _objects: dict = field(default_factory=dict)

    def allocate(self) -> int:
        obj_id = self._next
        self._next += 1
        return obj_id

    def add(self, obj: PdfObject, obj_id: int | None = None) -> PdfRef:
        """Register a new object, or override an existing one by id."""
        if obj_id is None:
            obj_id = self.allocate()
        self._objects[obj_id] = obj
        return PdfRef(obj_id)


class _FixedInt(PdfObject):
    """An integer that always serializes to a fixed zero-padded width.

    Keeps a ``/ByteRange`` value the same byte length before and after its
    numbers are known, so filling it in never shifts later offsets.
    """

    def __init__(self, width: int = 10) -> None:
        self.width = width
        self.value = 0

    def serialize(self) -> bytes:
        return f"{self.value:0{self.width}d}".encode("ascii")


def _group_runs(ids: list[int]) -> list[tuple[int, list[int]]]:
    """Group ascending ids into contiguous runs (start, [ids])."""
    runs: list[tuple[int, list[int]]] = []
    for obj_id in ids:
        if runs and obj_id == runs[-1][0] + len(runs[-1][1]):
            runs[-1][1].append(obj_id)
        else:
            runs.append((obj_id, [obj_id]))
    return runs


def _serialize_increment(
    prefix: bytes,
    objects: dict,
    *,
    root_ref: PdfRef,
    prev_startxref: int,
    id_pair: tuple[bytes, bytes] | None,
    size: int,
) -> bytes:
    """Append a body, xref table, and trailer to *prefix*; never rewrite it."""
    if not objects:
        raise ValueError("an incremental revision must add at least one object")
    buf = bytearray(prefix)
    if buf and buf[-1] not in b"\r\n":
        buf.append(0x0A)

    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(buf)
        buf.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        buf.extend(serialize(objects[obj_id]))
        buf.extend(b"\nendobj\n")

    xref_offset = len(buf)
    buf.extend(b"xref\n")
    buf.extend(b"0 1\n")
    buf.extend(b"0000000000 65535 f \n")
    for start, run in _group_runs(sorted(objects)):
        buf.extend(f"{start} {len(run)}\n".encode("ascii"))
        for obj_id in run:
            entry = f"{offsets[obj_id]:010d} 00000 n \n".encode("ascii")
            if len(entry) != 20:
                raise ValueError("xref entry is not 20 bytes")
            buf.extend(entry)

    trailer = PdfDict()
    trailer["Size"] = size
    trailer["Root"] = root_ref
    trailer["Prev"] = prev_startxref
    if id_pair is not None:
        trailer["ID"] = PdfArray(
            [PdfString(id_pair[0], hex_mode=True), PdfString(id_pair[1], hex_mode=True)]
        )
    buf.extend(b"trailer\n")
    buf.extend(serialize(trailer))
    buf.extend(b"\nstartxref\n")
    buf.extend(str(xref_offset).encode("ascii"))
    buf.extend(b"\n%%EOF\n")
    return bytes(buf)


def _increment_size(base: _BaseInfo, inc: _Increment) -> int:
    """/Size for the new trailer: covers every id in base and this revision."""
    highest = max(inc._objects) if inc._objects else 0
    return max(base.size, highest + 1)


# -- attestation builders ----------------------------------------------------


def _extend_array_entry(
    container: PdfDict,
    key: str,
    new_ref: PdfRef,
    pdf_bytes: bytes,
    inc: _Increment,
) -> None:
    """Append *new_ref* to ``container[key]``, resolving an indirect array."""
    current = container.get(key)
    if current is None:
        container[key] = PdfArray([new_ref])
    elif isinstance(current, PdfArray):
        current.append(new_ref)
    elif isinstance(current, PdfRef):
        resolved = _resolve_indirect(pdf_bytes, current.obj_id)
        if not isinstance(resolved, PdfArray):
            raise ValueError(f"/{key} is not an array object")
        resolved.append(new_ref)
        inc.add(resolved, current.obj_id)
    else:
        raise ValueError(f"/{key} has an unexpected type: {type(current).__name__}")


def _add_annotation(
    inc: _Increment,
    base: _BaseInfo,
    pdf_bytes: bytes,
    page_index: int,
    annot: PdfDict,
) -> None:
    """Append an annotation and wire it into the target page's /Annots."""
    if not 0 <= page_index < len(base.page_refs):
        raise ValueError(f"page_index {page_index} out of range")
    annot["P"] = base.page_refs[page_index]
    annot_ref = inc.add(annot)

    page = base.page_dicts[page_index]
    current = page.get("Annots")
    if isinstance(current, PdfRef):
        _extend_array_entry(page, "Annots", annot_ref, pdf_bytes, inc)
    else:
        _extend_array_entry(page, "Annots", annot_ref, pdf_bytes, inc)
        inc.add(page, base.page_refs[page_index].obj_id)


def _build_annotation_attestation(
    inc: _Increment,
    base: _BaseInfo,
    pdf_bytes: bytes,
    att: Attestation,
    timestamp: str,
) -> PdfRef:
    """Append a text annotation recording an approval; return the root ref."""
    annot = PdfDict()
    annot["Type"] = PdfName("Annot")
    annot["Subtype"] = PdfName(_ANNOT_SUBTYPE)
    annot["Rect"] = PdfArray(list(att.rect))
    annot["F"] = 4
    annot["M"] = timestamp
    body = att.text or att.reason or "Attestation"
    annot["Contents"] = body
    if att.name:
        annot["T"] = att.name
    _add_annotation(inc, base, pdf_bytes, att.page_index, annot)
    return base.root_ref


def _build_attachment_attestation(
    inc: _Increment,
    base: _BaseInfo,
    pdf_bytes: bytes,
    att: Attestation,
) -> PdfRef:
    """Append an embedded file associated with the document; return root ref."""
    ef_dict = PdfDict()
    ef_dict["Type"] = PdfName("EmbeddedFile")
    ef_ref = inc.add(PdfStream(data=att.payload, dictionary=ef_dict))

    filespec = PdfDict()
    filespec["Type"] = PdfName("Filespec")
    filespec["F"] = att.filename
    filespec["UF"] = att.filename
    ef_entry = PdfDict()
    ef_entry["F"] = ef_ref
    filespec["EF"] = ef_entry
    filespec["AFRelationship"] = PdfName("Supplement")
    if att.reason:
        filespec["Desc"] = att.reason
    fs_ref = inc.add(filespec)

    root = base.root_dict
    _extend_array_entry(root, "AF", fs_ref, pdf_bytes, inc)
    _wire_embedded_files_name(root, att.filename, fs_ref, pdf_bytes, inc)
    inc.add(root, base.root_ref.obj_id)
    return base.root_ref


def _wire_embedded_files_name(
    root: PdfDict,
    filename: str,
    fs_ref: PdfRef,
    pdf_bytes: bytes,
    inc: _Increment,
) -> None:
    """Add *fs_ref* to the catalog's /Names/EmbeddedFiles name tree."""
    names = root.get("Names")
    if isinstance(names, PdfRef):
        names = _resolve_indirect(pdf_bytes, names.obj_id)
        root["Names"] = names
    if names is None:
        names = PdfDict()
        root["Names"] = names
    if not isinstance(names, PdfDict):
        raise ValueError("/Names is not a dictionary")

    ef_tree = names.get("EmbeddedFiles")
    if isinstance(ef_tree, PdfRef):
        ef_tree = _resolve_indirect(pdf_bytes, ef_tree.obj_id)
        names["EmbeddedFiles"] = ef_tree
    if ef_tree is None:
        ef_tree = PdfDict()
        ef_tree["Names"] = PdfArray([])
        names["EmbeddedFiles"] = ef_tree
    _extend_array_entry(ef_tree, "Names", PdfString(filename), pdf_bytes, inc)
    ef_tree["Names"].append(fs_ref)


# -- amend_pdf ---------------------------------------------------------------


def amend_pdf(
    pdf_bytes: bytes,
    *,
    attestation: Attestation | None = None,
    build=None,
    kind: str | None = None,
    timestamp: str | None = None,
    enforce_docmdp: bool = True,
) -> bytes:
    """Append one incremental revision to *pdf_bytes*, preserving its prefix.

    Pass exactly one of ``attestation`` (a high-level approval to append) or
    ``build`` (a callback ``build(inc, base) -> PdfRef | None`` that adds and
    overrides objects on the ``_Increment`` and returns the trailer's /Root,
    defaulting to the base catalog). ``timestamp`` is recorded verbatim and
    must be supplied for deterministic output; ``datetime.now`` is never
    called. When ``enforce_docmdp`` is set, an amendment that exceeds a
    restrictive DocMDP certification's permitted scope raises ``ValueError``.

    The result begins with *pdf_bytes* byte-for-byte; the revision is appended
    after the original ``%%EOF`` and is therefore no longer linearized.
    """
    if (attestation is None) == (build is None):
        raise ValueError("pass exactly one of attestation= or build=")

    _ensure_not_encrypted(pdf_bytes)
    base = _read_base_info(pdf_bytes)
    resolved_kind = (
        attestation.kind if attestation is not None else (kind or _KIND_OTHER)
    )
    if enforce_docmdp:
        _check_docmdp_permits(pdf_bytes, resolved_kind)

    inc = _Increment(_next=base.size)
    stamp = timestamp or _DEFAULT_TIMESTAMP
    if attestation is not None:
        if attestation.kind == _KIND_ANNOTATIONS:
            root_ref = _build_annotation_attestation(
                inc, base, pdf_bytes, attestation, stamp
            )
        else:
            root_ref = _build_attachment_attestation(inc, base, pdf_bytes, attestation)
    else:
        root_ref = build(inc, base) or base.root_ref

    return _serialize_increment(
        pdf_bytes,
        inc._objects,
        root_ref=root_ref,
        prev_startxref=base.prev_startxref,
        id_pair=base.id_pair,
        size=_increment_size(base, inc),
    )


# -- signature revisions -----------------------------------------------------


def _build_signature_value(
    sig: SignatureField, timestamp: str, *, pades: bool = False
) -> tuple[PdfDict, list]:
    """Build a /V signature dict with a fixed-width /ByteRange placeholder."""
    byte_range = [_FixedInt(), _FixedInt(), _FixedInt(), _FixedInt()]
    value = PdfDict()
    value["Type"] = PdfName("Sig")
    value["Filter"] = PdfName("Adobe.PPKLite")
    subfilter = "ETSI.CAdES.detached" if pades else "adbe.pkcs7.detached"
    value["SubFilter"] = PdfName(subfilter)
    if sig.signer_name:
        value["Name"] = sig.signer_name
    if sig.reason:
        value["Reason"] = sig.reason
    if sig.location:
        value["Location"] = sig.location
    value["M"] = timestamp
    value["ByteRange"] = PdfArray(byte_range)
    value["Contents"] = b"\x00" * _CONTENTS_PLACEHOLDER_BYTES
    return value, byte_range


def _wire_signature_field(
    inc: _Increment,
    base: _BaseInfo,
    pdf_bytes: bytes,
    sig: SignatureField,
    value_ref: PdfRef,
) -> PdfRef:
    """Append the widget for a signature field and wire the AcroForm."""
    widget = PdfDict()
    widget["Type"] = PdfName("Annot")
    widget["Subtype"] = PdfName("Widget")
    widget["FT"] = PdfName("Sig")
    widget["T"] = sig.field_name
    widget["V"] = value_ref
    widget["Rect"] = PdfArray([sig.x, sig.y, sig.x + sig.width, sig.y + sig.height])
    widget["F"] = 4
    _add_annotation(inc, base, pdf_bytes, sig.page_index, widget)
    widget_ref = _last_widget_ref(inc, widget)

    if base.acroform_ref is not None:
        acroform = base.acroform_dict
        _extend_array_entry(acroform, "Fields", widget_ref, pdf_bytes, inc)
        acroform["SigFlags"] = 3
        inc.add(acroform, base.acroform_ref.obj_id)
        return base.root_ref
    if base.acroform_dict is not None:
        acroform = base.acroform_dict
        _extend_array_entry(acroform, "Fields", widget_ref, pdf_bytes, inc)
        acroform["SigFlags"] = 3
    else:
        acroform = PdfDict()
        acroform["Fields"] = PdfArray([widget_ref])
        acroform["SigFlags"] = 3
    base.root_dict["AcroForm"] = acroform
    inc.add(base.root_dict, base.root_ref.obj_id)
    return base.root_ref


def _last_widget_ref(inc: _Increment, widget: PdfDict) -> PdfRef:
    """Find the id the increment assigned to *widget*."""
    for obj_id, obj in inc._objects.items():
        if obj is widget:
            return PdfRef(obj_id)
    raise ValueError("widget was not registered in the increment")


def prepare_signature(
    pdf_bytes: bytes,
    *,
    page_index: int = 0,
    rect: tuple[float, float, float, float] | None = None,
    name: str = "",
    reason: str = "",
    location: str = "",
    field_name: str = "Signature1",
    timestamp: str | None = None,
    enforce_docmdp: bool = True,
    pades: bool = False,
) -> bytes:
    """Append a signature revision with a real /ByteRange, empty /Contents.

    The returned PDF is ready for external signing: its /ByteRange spans the
    whole file except the /Contents placeholder, and its prefix is *pdf_bytes*
    byte-for-byte. ``amend_sign`` calls this then fills /Contents with a PKCS#7
    signature. Passing ``pades=True`` marks the field's /SubFilter as
    ``ETSI.CAdES.detached`` for a PAdES-BASELINE signature. Deterministic given
    a fixed ``timestamp``.
    """
    _ensure_not_encrypted(pdf_bytes)
    if enforce_docmdp:
        _check_docmdp_permits(pdf_bytes, _KIND_SIGNATURE)
    base = _read_base_info(pdf_bytes)
    x0, y0, x1, y1 = rect if rect is not None else (0.0, 0.0, 0.0, 0.0)
    sig = SignatureField(
        page_index=page_index,
        x=x0,
        y=y0,
        width=x1 - x0,
        height=y1 - y0,
        signer_name=name,
        reason=reason,
        location=location,
        field_name=field_name,
    )
    stamp = timestamp or _DEFAULT_TIMESTAMP

    inc = _Increment(_next=base.size)
    value, byte_range = _build_signature_value(sig, stamp, pades=pades)
    value_ref = inc.add(value)
    root_ref = _wire_signature_field(inc, base, pdf_bytes, sig, value_ref)

    kwargs = dict(
        root_ref=root_ref,
        prev_startxref=base.prev_startxref,
        id_pair=base.id_pair,
        size=_increment_size(base, inc),
    )
    first = _serialize_increment(pdf_bytes, inc._objects, **kwargs)

    start = first.find(_CONTENTS_HEX_PLACEHOLDER)
    if start == -1:
        raise ValueError("signature Contents placeholder not found after assembly")
    end = start + len(_CONTENTS_HEX_PLACEHOLDER)
    byte_range[0].value = 0
    byte_range[1].value = start
    byte_range[2].value = end
    byte_range[3].value = len(first) - end

    second = _serialize_increment(pdf_bytes, inc._objects, **kwargs)
    if second.find(_CONTENTS_HEX_PLACEHOLDER) != start:
        raise ValueError("ByteRange fill-in shifted the Contents placeholder")
    return second


def amend_sign(
    pdf_bytes: bytes,
    *,
    cert: str,
    key: str,
    reason: str = "",
    location: str = "",
    name: str = "",
    password: bytes | None = None,
    page_index: int = 0,
    rect: tuple[float, float, float, float] | None = None,
    field_name: str = "Signature1",
    timestamp: str | None = None,
    enforce_docmdp: bool = True,
) -> bytes:
    """Append a cryptographically signed revision, reusing ``signing.sign_pdf``.

    Prepares a signature revision (``prepare_signature``) whose /ByteRange
    covers every prior revision, then injects a PKCS#7 detached signature into
    the /Contents placeholder. The crypto is entirely ``signing.sign_pdf``'s;
    this only lays out the append. The result's prefix is *pdf_bytes*
    byte-for-byte. Requires ``pip install emboss-pdf[signing]``.
    """
    prepared = prepare_signature(
        pdf_bytes,
        page_index=page_index,
        rect=rect,
        name=name,
        reason=reason,
        location=location,
        field_name=field_name,
        timestamp=timestamp,
        enforce_docmdp=enforce_docmdp,
    )
    return sign_pdf(prepared, key, cert, password)


def amend_sign_pades(
    pdf_bytes: bytes,
    *,
    cert: str,
    key: str,
    reason: str = "",
    location: str = "",
    name: str = "",
    password: bytes | None = None,
    page_index: int = 0,
    rect: tuple[float, float, float, float] | None = None,
    field_name: str = "Signature1",
    timestamp: str | None = None,
    enforce_docmdp: bool = True,
    tsa_url: str | None = None,
    timestamp_token: bytes | None = None,
    signing_time=None,
) -> bytes:
    """Append a PAdES-BASELINE signed revision, reusing ``pades.sign_pdf_pades``.

    Prepares a signature revision whose field is marked ``ETSI.CAdES.detached``
    and whose /ByteRange covers every prior revision, then injects a CAdES-BES
    CMS into the /Contents placeholder. Passing ``tsa_url`` or a pre-fetched
    ``timestamp_token`` upgrades the signature from B-B to B-T. The result's
    prefix is *pdf_bytes* byte-for-byte. Requires
    ``pip install emboss-pdf[signing]``.
    """
    from .pades import sign_pdf_pades

    prepared = prepare_signature(
        pdf_bytes,
        page_index=page_index,
        rect=rect,
        name=name,
        reason=reason,
        location=location,
        field_name=field_name,
        timestamp=timestamp,
        enforce_docmdp=enforce_docmdp,
        pades=True,
    )
    return sign_pdf_pades(
        prepared,
        key,
        cert,
        password,
        tsa_url=tsa_url,
        timestamp_token=timestamp_token,
        signing_time=signing_time,
    )


# -- DocMDP enforcement ------------------------------------------------------


def _read_docmdp_permission(pdf_bytes: bytes) -> int | None:
    """Return the base's DocMDP /P value, or None if it is not certified."""
    pikepdf = _require_pikepdf()
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        perms = pdf.Root.get("/Perms")
        if perms is None:
            return None
        docmdp = perms.get("/DocMDP")
        if docmdp is None:
            return None
        reference = docmdp.get("/Reference")
        if not reference:
            return None
        transform = reference[0]
        params = transform.get("/TransformParams")
        if params is None or "/P" not in params:
            return None
        return int(params["/P"])


def _check_docmdp_permits(pdf_bytes: bytes, kind: str) -> None:
    """Raise ValueError if *kind* exceeds the base's DocMDP permission."""
    permission = _read_docmdp_permission(pdf_bytes)
    if permission is None:
        return
    allowed = _DOCMDP_ALLOWED.get(permission, frozenset())
    if kind in allowed:
        return
    detail = {
        1: "no changes are permitted",
        2: "only form fill-in and signing are permitted",
        3: "only form fill-in, signing, and annotations are permitted",
    }.get(permission, "the change is not permitted")
    raise ValueError(
        f"amendment of kind {kind!r} violates the base document's DocMDP "
        f"certification (/P={permission}): {detail}"
    )


# -- revision history and coverage -------------------------------------------


def _prev_of_xref(pdf_bytes: bytes, xref_offset: int) -> int | None:
    """Return the /Prev offset declared by the revision at *xref_offset*."""
    eof = pdf_bytes.find(b"%%EOF", xref_offset)
    region = pdf_bytes[xref_offset : eof if eof != -1 else len(pdf_bytes)]
    match = re.search(rb"/Prev\s+(\d+)", region)
    return int(match.group(1)) if match else None


def _eof_end(pdf_bytes: bytes, from_offset: int) -> int:
    """End offset (past trailing EOL) of the first %%EOF at/after *from_offset*."""
    index = pdf_bytes.find(b"%%EOF", from_offset)
    if index == -1:
        return len(pdf_bytes)
    end = index + len(b"%%EOF")
    while end < len(pdf_bytes) and pdf_bytes[end] in b"\r\n":
        end += 1
    return end


_BYTE_RANGE_RE = re.compile(rb"/ByteRange\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\]")
_NAME_RE = re.compile(rb"/Name\s*\(([^)]*)\)")
_REASON_RE = re.compile(rb"/Reason\s*\(([^)]*)\)")
_CONTENTS_RE = re.compile(rb"/Contents\s*<([0-9A-Fa-f]*)>")


def _classify(region: bytes, is_base: bool) -> str:
    """Classify a revision from the object bytes it contributed."""
    if b"/ByteRange" in region or b"/Type /Sig" in region or b"/Type/Sig" in region:
        return (
            _KIND_BASE if is_base and b"/ByteRange" not in region else _KIND_SIGNATURE
        )
    if is_base:
        return _KIND_BASE
    if b"/EmbeddedFile" in region or b"/Filespec" in region:
        return _KIND_ATTACHMENT
    if b"/Subtype /Widget" in region:
        return _KIND_SIGNATURE
    if (
        b"/Annot" in region
        or b"/Subtype /Text" in region
        or b"/Subtype /Stamp" in region
    ):
        return _KIND_ANNOTATIONS
    return _KIND_OTHER


def _parse_signature(
    region: bytes,
) -> tuple[tuple[int, int, int, int] | None, str | None, str | None, bool]:
    """Extract ByteRange, signer, reason, and signed-state from a revision."""
    br_match = _BYTE_RANGE_RE.search(region)
    byte_range = None
    if br_match is not None:
        byte_range = tuple(int(br_match.group(i)) for i in range(1, 5))
    name_match = _NAME_RE.search(region)
    signer = name_match.group(1).decode("latin-1") if name_match else None
    reason_match = _REASON_RE.search(region)
    reason = reason_match.group(1).decode("latin-1") if reason_match else None
    contents_match = _CONTENTS_RE.search(region)
    signed = False
    if contents_match is not None:
        signed = contents_match.group(1).strip(b"0") != b""
    return byte_range, signer, reason, signed


def revision_history(pdf_bytes: bytes) -> list[Revision]:
    """Walk the /Prev chain and classify every revision in the file.

    Returns revisions in chronological order (base first). Each carries its
    byte range, a ``kind`` (base | signature | annotations | attachment |
    other), signer/reason for signatures, whether a signature's /Contents is
    actually populated (``signed``), and ``covered`` -- whether a later
    signature's /ByteRange attests to that revision's bytes. Content appended
    after the last signature is reported as not covered, which is the point.
    """
    last = _find_startxref(pdf_bytes)
    if last is None:
        raise ValueError("PDF has no startxref; cannot read revision history")

    offsets: list[int] = []
    seen: set[int] = set()
    cursor: int | None = last
    while cursor is not None and cursor not in seen:
        seen.add(cursor)
        offsets.append(cursor)
        cursor = _prev_of_xref(pdf_bytes, cursor)
    offsets.reverse()

    revisions: list[Revision] = []
    start = 0
    for index, xref_offset in enumerate(offsets):
        end = _eof_end(pdf_bytes, xref_offset)
        region = pdf_bytes[start:xref_offset]
        kind = _classify(region, is_base=index == 0)
        byte_range, signer, reason, signed = (None, None, None, False)
        if kind == _KIND_SIGNATURE or (index == 0 and b"/ByteRange" in region):
            byte_range, signer, reason, signed = _parse_signature(region)
        revisions.append(
            Revision(
                index=index,
                kind=kind,
                byte_range=(start, end),
                signer=signer,
                reason=reason,
                signed=signed,
                sig_byte_range=byte_range,
            )
        )
        start = end

    _assign_coverage(revisions)
    return revisions


def _assign_coverage(revisions: list[Revision]) -> None:
    """Mark each revision covered by every signature whose ByteRange spans it."""
    signatures = [
        r
        for r in revisions
        if r.sig_byte_range is not None and r.sig_byte_range[0] == 0
    ]
    for rev in revisions:
        _, rev_end = rev.byte_range
        for sig in signatures:
            cover_end = sig.sig_byte_range[2] + sig.sig_byte_range[3]
            if cover_end >= rev_end:
                rev.covered = True
                rev.covered_by.append(sig.index)


def coverage_report(pdf_bytes: bytes) -> CoverageReport:
    """Summarize which revisions a later signature's ByteRange covers."""
    revisions = revision_history(pdf_bytes)
    uncovered = [r.index for r in revisions if not r.covered]
    signatures = [r.index for r in revisions if r.sig_byte_range is not None]
    return CoverageReport(
        revisions=revisions,
        fully_covered=not uncovered,
        uncovered=uncovered,
        signatures=signatures,
    )


def format_history(source) -> str:
    """Render a plaintext revision/coverage table.

    Accepts either raw PDF bytes or a list of ``Revision`` objects.
    """
    if isinstance(source, (bytes, bytearray)):
        revisions = revision_history(bytes(source))
    else:
        revisions = list(source)

    header = f"{'Rev':>3}  {'Kind':<11} {'Bytes':<17} {'Signer':<16} Coverage"
    lines = [header, "-" * len(header)]
    for rev in revisions:
        span = f"{rev.byte_range[0]}-{rev.byte_range[1]}"
        signer = rev.signer or ""
        if rev.sig_byte_range is not None:
            coverage = "signed" if rev.signed else "prepared (unsigned)"
        elif rev.covered:
            coverage = "covers by rev " + ",".join(str(i) for i in rev.covered_by)
        else:
            coverage = "NOT covered by any signature"
        lines.append(
            f"{rev.index:>3}  {rev.kind:<11} {span:<17} {signer:<16} {coverage}"
        )
    uncovered = [r.index for r in revisions if not r.covered]
    if uncovered:
        lines.append("")
        lines.append(
            "uncovered revisions (no signature attests to them): "
            + ", ".join(str(i) for i in uncovered)
        )
    return "\n".join(lines)


# -- re-validation -----------------------------------------------------------


def verify_amended(pdf_bytes: bytes):
    """Structurally verify an amended PDF and confirm it still parses.

    Runs ``pdf.verify.verify_pdf`` on the appended revision's xref and, when
    pikepdf is available, reopens the file to confirm the /Prev chain resolves.
    Amended files are valid but no longer linearized.
    """
    from .pdf.verify import verify_pdf

    report = verify_pdf(pdf_bytes)
    try:
        pikepdf = _require_pikepdf()
    except ImportError:
        return report
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            _ = len(pdf.pages)
    except Exception as exc:  # pragma: no cover - defensive
        report.ok = False
        report.problems.append(f"pikepdf could not open the amended PDF: {exc}")
    return report
