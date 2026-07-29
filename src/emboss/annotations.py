"""Read reviewer markup out of a PDF and resolve it against the spec.

A reviewer highlights, strikes out, or comments on a rendered PDF in Acrobat,
Preview, or Chrome. Because the PDF carries a text-position index
(``emboss-textmap.json``), each annotation resolves back to the node and
character range it covers, not a guess at a region. The result is a structured
comment list keyed to stable node ids that a person or a model can act on.
"""

from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .textmap import Resolution, TextIndex

__all__ = [
    "Comment",
    "extract_comments",
    "merge_comments",
    "comments_to_json",
    "unresolved_count",
]

# PDF markup subtypes we understand, mapped to the comment `type` we emit.
_MARKUP_TYPES = {
    "/Highlight": "highlight",
    "/StrikeOut": "strikeout",
    "/Underline": "underline",
    "/Squiggly": "squiggly",
    "/Text": "note",
    "/FreeText": "note",
}


@dataclass
class Comment:
    """One reviewer annotation resolved against the document's nodes."""

    id: str
    type: str
    author: str | None
    page: int
    comment: str
    resolution: str  # exact | node | spanning | unanchored
    status: str = "open"
    node_id: str | None = None
    node_path: str | None = None
    anchor_text: str | None = None
    char_range: list | None = None
    node_ids: list = field(default_factory=list)
    rect: list | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _read_bytes(source) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return Path(source).read_bytes()


def _quad_rects(annot) -> list:
    """Bounding rectangles for a markup annotation, from QuadPoints or Rect.

    QuadPoints group eight numbers per marked line; the four corners can be
    emitted in different orders by different tools, so the bounding box is
    taken from the min/max of each line's coordinates -- order independent.
    """
    quads = annot.get("/QuadPoints")
    rects: list = []
    if quads is not None:
        nums = [float(v) for v in quads]
        for i in range(0, len(nums) - 7, 8):
            xs = nums[i : i + 8 : 2]
            ys = nums[i + 1 : i + 8 : 2]
            rects.append([min(xs), min(ys), max(xs), max(ys)])
    if not rects:
        rect = annot.get("/Rect")
        if rect is not None:
            x0, y0, x1, y1 = (float(v) for v in rect)
            rects.append([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)])
    return rects


def _combine(index: TextIndex, page: int, rects: list) -> Resolution:
    """Resolve every rectangle of one annotation and combine into one result.

    An annotation covering several lines within a node yields one ``exact``
    range spanning them; one crossing node boundaries yields ``spanning`` with
    every node id; one over no text yields ``node`` (if a figure sits beneath)
    or ``unanchored`` -- never a silent drop.
    """
    resolutions = [index.resolve(page, *r) for r in rects]
    anchored = [r for r in resolutions if r.state in ("exact", "node")]
    nodes = {r.node_id for r in anchored if r.node_id}
    spanning = [r for r in resolutions if r.state == "spanning"]

    all_nodes = set(nodes)
    for r in spanning:
        all_nodes.update(r.node_ids)

    if len(all_nodes) > 1:
        return Resolution(
            state="spanning",
            node_ids=sorted(all_nodes),
            page=page,
            rect=rects[0],
        )
    if len(all_nodes) == 1:
        node_id = next(iter(all_nodes))
        exacts = [r for r in anchored if r.node_id == node_id and r.char_range]
        if exacts:
            start = min(r.char_range[0] for r in exacts)
            end = max(r.char_range[1] for r in exacts)
            anchor = index.node_text(node_id)[start:end]
            return Resolution(
                state="exact",
                node_id=node_id,
                char_range=[start, end],
                anchor_text=anchor,
                page=page,
                rect=rects[0],
            )
        return Resolution(state="node", node_id=node_id, page=page, rect=rects[0])
    return Resolution(state="unanchored", page=page, rect=rects[0])


def _sort_key(entry) -> tuple:
    page, rect, subtype, contents, author = entry
    top = -rect[3] if rect else 0.0
    left = rect[0] if rect else 0.0
    return (page, round(top, 2), round(left, 2), subtype, author or "", contents)


def extract_comments(source) -> list:
    """Extract and resolve reviewer annotations from a marked-up PDF.

    Requires pikepdf and a PDF that carries the ``emboss-textmap.json``
    attachment (from ``render(embed_spec=True)``). Raises ``ValueError`` if the
    text map is absent, since without it a comment cannot be resolved to a
    character range and silently returning region-only guesses would be worse.
    """
    import pikepdf

    data = _read_bytes(source)
    index = TextIndex.from_pdf(data)
    if index is None:
        raise ValueError(
            "no emboss-textmap.json in this PDF; render it with "
            "embed_spec=True so annotations can resolve to nodes"
        )

    raw: list = []
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            annots = page.get("/Annots")
            if annots is None:
                continue
            for annot in annots:
                subtype = str(annot.get("/Subtype", ""))
                if subtype not in _MARKUP_TYPES:
                    continue
                rects = _quad_rects(annot)
                if not rects:
                    continue
                author = annot.get("/T")
                contents = annot.get("/Contents")
                raw.append(
                    (
                        page_index,
                        rects,
                        subtype,
                        str(contents) if contents is not None else "",
                        str(author) if author is not None else None,
                    )
                )

    # Deterministic ids: sort top-to-bottom, then left-to-right, per page.
    keyed = sorted(raw, key=lambda e: _sort_key((e[0], e[1][0], e[2], e[3], e[4])))
    comments: list = []
    for n, (page_index, rects, subtype, contents, author) in enumerate(keyed, 1):
        res = _combine(index, page_index, rects)
        comments.append(
            Comment(
                id=f"c-{n:02d}",
                type=_MARKUP_TYPES[subtype],
                author=author,
                page=page_index,
                comment=contents,
                resolution=res.state,
                node_id=res.node_id,
                anchor_text=res.anchor_text,
                char_range=res.char_range,
                node_ids=res.node_ids,
                rect=[round(v, 2) for v in res.rect] if res.rect else None,
            )
        )
    return comments


def unresolved_count(comments: list) -> int:
    """How many comments did not resolve to a single patchable node."""
    return sum(1 for c in comments if c.resolution in ("spanning", "unanchored"))


def merge_comments(*comment_lists: list) -> list:
    """Merge comment lists from several reviewers into one, renumbered.

    Comments are unioned and re-sorted top-to-bottom per page across all
    reviewers, so several returned PDFs collapse into a single list. Identical
    comments (same author, type, node, range, and text) are de-duplicated.
    """
    seen: set = set()
    merged: list = []
    for comments in comment_lists:
        for c in comments:
            key = (
                c.author,
                c.type,
                c.node_id,
                tuple(c.char_range) if c.char_range else None,
                c.comment,
                c.page,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(c)

    merged.sort(
        key=lambda c: _sort_key(
            (c.page, c.rect or [0, 0, 0, 0], c.type, c.comment, c.author)
        )
    )
    for n, c in enumerate(merged, 1):
        c.id = f"c-{n:02d}"
    return merged


def comments_to_json(comments: list) -> str:
    """Serialize comments to deterministic JSON."""
    return json.dumps(
        [c.to_dict() for c in comments],
        ensure_ascii=True,
        sort_keys=True,
        indent=2,
    )
