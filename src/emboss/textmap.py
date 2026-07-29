"""Text-position index: resolve a rectangle on a page to a node and char range.

The renderer records, for every rendered text fragment, the node it belongs
to, its character offsets within that node's readable text, and its bounding
box (``RenderResult.text_index``). This module reconstructs each node's text
from those spans, serializes the index as deterministic JSON, and resolves an
arbitrary rectangle (a reviewer's highlight, for example) back to the node and
character range beneath it -- the basis for annotation round-tripping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

__all__ = [
    "TextIndex",
    "Resolution",
    "reconstruct_node_text",
    "text_map_json",
]

# A span must overlap the query rectangle by at least this fraction of its own
# height to count as covered, so a highlight on one line does not pick up the
# line above or below it.
_MIN_VERTICAL_OVERLAP = 0.35


def reconstruct_node_text(spans: list) -> str:
    """Rebuild a node's readable text from its recorded spans.

    Spans carry contiguous character offsets with single-space gaps between
    rendered fragments, so placing each span's text at its ``char_start``
    reproduces the node's text with word spacing intact.
    """
    ordered = sorted(spans, key=lambda s: s["char_start"])
    out: list = []
    cursor = 0
    for span in ordered:
        start = span["char_start"]
        if start > cursor:
            out.append(" " * (start - cursor))
        out.append(span["text"])
        cursor = span["char_end"]
    return "".join(out)


@dataclass
class Resolution:
    """The outcome of resolving one rectangle against the text index."""

    state: str  # "exact" | "node" | "spanning" | "unanchored"
    node_id: str | None = None
    char_range: list | None = None  # [start, end] for state == "exact"
    anchor_text: str | None = None
    node_ids: list = field(default_factory=list)  # all nodes, for "spanning"
    page: int | None = None
    rect: list | None = None

    @property
    def patchable(self) -> bool:
        """Whether a single node can be edited from this resolution."""
        return self.state in ("exact", "node")


class TextIndex:
    """Queryable text-position index built from a render's ``text_index``."""

    def __init__(self, index: dict, layout_map: dict | None = None) -> None:
        self._index = index
        self._layout = layout_map or {}
        self._node_text = {
            node_id: reconstruct_node_text(spans) for node_id, spans in index.items()
        }

    @classmethod
    def from_document(cls, doc) -> "TextIndex":
        """Build the index by rendering *doc* once."""
        from .writer import render_document

        result = render_document(doc, return_result=True)
        return cls(result.text_index, result.layout_map)

    def node_text(self, node_id: str) -> str:
        return self._node_text.get(node_id, "")

    def node_ids(self) -> list:
        return sorted(self._index)

    def resolve(
        self, page: int, x0: float, y0: float, x1: float, y1: float
    ) -> Resolution:
        """Resolve a rectangle on *page* to a node and character range.

        Returns a :class:`Resolution` whose ``state`` is always one of
        ``exact`` (one node, a character range), ``node`` (one node, no
        character range), ``spanning`` (two or more nodes), or ``unanchored``
        (no content beneath the rectangle). The state is never omitted, so a
        mis-resolved comment cannot pass silently.
        """
        rect = [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]
        lo, hi = min(y0, y1), max(y0, y1)
        left, right = min(x0, x1), max(x0, x1)

        hits: dict = {}
        for node_id, spans in self._index.items():
            for span in spans:
                if span["page"] != page:
                    continue
                if not self._overlaps(span, left, lo, right, hi):
                    continue
                hits.setdefault(node_id, []).append(span)

        if not hits:
            node_id = self._node_at(page, left, lo, right, hi)
            if node_id is not None:
                return Resolution(state="node", node_id=node_id, page=page, rect=rect)
            return Resolution(state="unanchored", page=page, rect=rect)

        if len(hits) > 1:
            return Resolution(
                state="spanning",
                node_ids=sorted(hits),
                page=page,
                rect=rect,
            )

        node_id, spans = next(iter(hits.items()))
        start = min(s["char_start"] for s in spans)
        end = max(s["char_end"] for s in spans)
        anchor = self._node_text.get(node_id, "")[start:end]
        return Resolution(
            state="exact",
            node_id=node_id,
            char_range=[start, end],
            anchor_text=anchor,
            page=page,
            rect=rect,
        )

    @staticmethod
    def _overlaps(span, left, lo, right, hi) -> bool:
        sh = span["y1"] - span["y0"]
        if sh <= 0:
            return False
        v = min(span["y1"], hi) - max(span["y0"], lo)
        if v < sh * _MIN_VERTICAL_OVERLAP:
            return False
        return min(span["x1"], right) - max(span["x0"], left) > 0

    def _node_at(self, page, left, lo, right, hi) -> str | None:
        """A layout-map node whose box contains the rectangle's center."""
        cx, cy = (left + right) / 2.0, (lo + hi) / 2.0
        for node_id in sorted(self._layout):
            for box in self._layout[node_id]:
                if box.get("page") != page:
                    continue
                if box["x0"] <= cx <= box["x1"] and box["y0"] <= cy <= box["y1"]:
                    return node_id
        return None

    def to_dict(self) -> dict:
        """A deterministic, JSON-ready view: node id -> text and spans."""
        out: dict = {}
        for node_id in sorted(self._index):
            spans = sorted(
                self._index[node_id],
                key=lambda s: (s["char_start"], s["page"]),
            )
            out[node_id] = {
                "text": self._node_text[node_id],
                "spans": spans,
            }
        return out


def text_map_json(doc) -> str:
    """Serialize a document's text-position index to deterministic JSON."""
    index = TextIndex.from_document(doc)
    return json.dumps(index.to_dict(), ensure_ascii=True, sort_keys=True, indent=2)
