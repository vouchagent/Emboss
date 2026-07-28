"""Embedded files with /AF associated-file relationships (PDF/A-3, ISO 32000-2).

Document-level wiring (writer.py, where the catalog dict is assembled):

    attach_files(assembler, catalog, [FileAttachment(name, data, mime)])

Element-level wiring (any page or structure-element PdfDict):

    element_dict["AF"] = af_array([filespec_ref])
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream, PdfString

__all__ = [
    "VALID_RELATIONSHIPS",
    "FileAttachment",
    "build_embedded_file",
    "build_names_tree",
    "attach_files",
    "af_array",
]

VALID_RELATIONSHIPS = frozenset(
    {
        "Source",
        "Data",
        "Alternative",
        "Supplement",
        "EncryptedPayload",
        "FormData",
        "Schema",
        "Unspecified",
    }
)


@dataclass(frozen=True)
class FileAttachment:
    """One file to embed: payload bytes plus its associated-file metadata."""

    name: str
    data: bytes
    mime: str = "application/octet-stream"
    description: str = ""
    relationship: str = "Supplement"
    creation_date: str | None = None


def _validate_relationship(relationship: str) -> None:
    """Reject /AFRelationship values outside the ISO 32000-2 vocabulary."""
    if relationship not in VALID_RELATIONSHIPS:
        allowed = ", ".join(sorted(VALID_RELATIONSHIPS))
        raise ValueError(
            f"invalid AFRelationship {relationship!r}; must be one of: {allowed}"
        )


def build_embedded_file(
    assembler,
    name: str,
    data: bytes,
    mime: str,
    description: str = "",
    relationship: str = "Supplement",
    creation_date: str | None = None,
) -> tuple[PdfRef, PdfRef]:
    """Register an /EmbeddedFile stream plus its /Filespec; return both refs."""
    _validate_relationship(relationship)
    if not name:
        raise ValueError("embedded file name must be non-empty")

    params = PdfDict()
    params["Size"] = len(data)
    params["CheckSum"] = PdfString(hashlib.md5(data).digest(), hex_mode=True)
    if creation_date is not None:
        date = creation_date if creation_date.startswith("D:") else f"D:{creation_date}"
        params["CreationDate"] = PdfString(date)

    stream = PdfStream(data=data, compress=True)
    stream.dictionary["Type"] = PdfName("EmbeddedFile")
    stream.dictionary["Subtype"] = PdfName(mime)
    stream.dictionary["Params"] = params
    ef_stream_ref = assembler.add(stream)

    embedded = PdfDict()
    embedded["F"] = ef_stream_ref
    embedded["UF"] = ef_stream_ref

    filespec = PdfDict()
    filespec["Type"] = PdfName("Filespec")
    filespec["F"] = PdfString(name)
    filespec["UF"] = PdfString(name)
    filespec["EF"] = embedded
    filespec["AFRelationship"] = PdfName(relationship)
    filespec["Desc"] = PdfString(description)
    filespec_ref = assembler.add(filespec)

    return filespec_ref, ef_stream_ref


def build_names_tree(entries: list) -> PdfDict:
    """Build the /Names /EmbeddedFiles name-tree root from (name, ref) pairs."""
    names = [name for name, _ref in entries]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate embedded file names: {sorted(names)}")
    pairs = PdfArray()
    for name, ref in sorted(entries, key=lambda entry: entry[0]):
        pairs.append(PdfString(name))
        pairs.append(ref)
    tree = PdfDict()
    tree["Names"] = pairs
    return tree


def af_array(refs: list) -> PdfArray:
    """Build an /AF array of filespec refs for a catalog, page, or element."""
    return PdfArray(list(refs))


def attach_files(assembler, catalog_dict, files: list) -> list:
    """Embed *files*, wiring the catalog /Names tree and /AF array; return refs."""
    if not files:
        return []
    entries = []
    refs = []
    for item in files:
        filespec_ref, _ef_ref = build_embedded_file(
            assembler,
            name=item.name,
            data=item.data,
            mime=item.mime,
            description=item.description,
            relationship=item.relationship,
            creation_date=item.creation_date,
        )
        entries.append((item.name, filespec_ref))
        refs.append(filespec_ref)

    tree_ref = assembler.add(build_names_tree(entries))
    names = catalog_dict.get("Names")
    if names is None:
        names = PdfDict()
        catalog_dict["Names"] = names
    names["EmbeddedFiles"] = tree_ref
    catalog_dict["AF"] = af_array(refs)
    return refs
