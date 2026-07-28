"""Stable node identity for block elements and the layout map.

Every top-level block carries a stable ``id``: an explicit one when the
author set it, otherwise a deterministic token derived from the element's
type, ordinal position, and a canonical serialization of its content. The
same document therefore assigns the same ids on any machine and across
runs, which is what lets diff, node-scoped patching, ``from_pdf`` recovery,
and annotation round-tripping key off them.

The layout map records where each node landed: a mapping of node id to the
list of page-and-bounding-box entries the renderer produced, in PDF
coordinates (bottom-left origin). A block split across pages or columns
contributes one entry per placement.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

__all__ = [
    "assign_node_ids",
    "derive_node_id",
    "content_signature",
    "round_bbox",
    "layout_map_json",
]

#: Precision for layout-map coordinates; pinned for reproducible output.
_COORD_PRECISION = 3

#: Fields never contributing to a content signature (style, identity,
#: and dataclass-computed caches that merely mirror content fields).
_IGNORED_FIELDS = frozenset({"style", "id"})


def _canon_value(value):
    """Canonicalize one field value into a JSON-serializable, stable form."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return content_signature(value)
    if isinstance(value, (bytes, bytearray)):
        return "b:" + hashlib.sha1(bytes(value)).hexdigest()
    if isinstance(value, (list, tuple)):
        return [_canon_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _canon_value(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def content_signature(element) -> list:
    """Return a canonical, order-stable description of an element's content."""
    if not (dataclasses.is_dataclass(element) and not isinstance(element, type)):
        return [type(element).__name__, repr(element)]
    parts: list = [type(element).__name__]
    for field in dataclasses.fields(element):
        if field.name in _IGNORED_FIELDS or not field.init:
            continue
        parts.append([field.name, _canon_value(getattr(element, field.name))])
    return parts


def derive_node_id(element, ordinal: int) -> str:
    """Deterministic content-position id, e.g. ``n1a2b3c4``.

    The digest covers the element type, its ordinal position, and a
    canonical serialization of its content fields, so an unrelated block
    appended later leaves earlier ids untouched while any content change
    moves only that block's id.
    """
    payload = json.dumps(
        [type(element).__name__, ordinal, content_signature(element)],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=False,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return "n" + digest[:8]


def assign_node_ids(content: list) -> dict[int, str]:
    """Assign a stable ``id`` to every block, returning ordinal -> id.

    Explicit ids are honored; the rest are derived deterministically.
    Two blocks resolving to the same token are disambiguated by appending
    the ordinal, keeping every id unique within the document. Elements are
    mutated in place, so callers must pass copies they own (the render
    pipeline assigns onto the validator's deep copy).
    """
    assigned: dict[int, str] = {}
    used: set[str] = set()

    explicit = {
        ordinal
        for ordinal, element in enumerate(content)
        if getattr(element, "id", None)
    }
    for ordinal in explicit:
        used.add(content[ordinal].id)

    for ordinal, element in enumerate(content):
        existing = getattr(element, "id", None)
        if existing:
            assigned[ordinal] = existing
            continue
        node_id = derive_node_id(element, ordinal)
        if node_id in used:
            node_id = f"{node_id}-{ordinal}"
        used.add(node_id)
        if hasattr(element, "id"):
            element.id = node_id
        assigned[ordinal] = node_id
    return assigned


def round_bbox(x0: float, y0: float, x1: float, y1: float) -> dict:
    """Round a bounding box to fixed precision for deterministic output."""
    return {
        "x0": round(float(x0), _COORD_PRECISION),
        "y0": round(float(y0), _COORD_PRECISION),
        "x1": round(float(x1), _COORD_PRECISION),
        "y1": round(float(y1), _COORD_PRECISION),
    }


def layout_map_json(doc) -> str:
    """Serialize a document's layout map to deterministic, sorted JSON."""
    layout = doc.layout_map()
    ordered = {node_id: layout[node_id] for node_id in sorted(layout)}
    return json.dumps(ordered, ensure_ascii=True, sort_keys=True, indent=2)
