"""Apply resolved reviewer comments to a document and prove the change.

Each comment resolved to a node (and, for an exact resolution, a character
range) can be turned into a targeted edit: only the objected-to phrase is
replaced, not the whole block. Applying edits produces a new document; the
existing node-keyed diff renders the redline that proves what changed.

Turning a free-text comment into a concrete replacement string is the caller's
step (often a language model). This module never invents that text; it applies
replacements deterministically and never applies anything on its own, so a
document nobody approved is never shipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from .diff import diff_documents, render_redline

__all__ = [
    "ProposedPatch",
    "propose_patches",
    "apply_comment",
    "apply_replacements",
    "redline",
]

# Element type name -> the string field an edit rewrites.
_TEXT_FIELD = {
    "Paragraph": "content",
    "Heading": "text",
    "BlockQuote": "text",
    "PullQuote": "text",
    "Callout": "text",
}


def _find(doc, node_id):
    for element in doc.content:
        if getattr(element, "id", None) == node_id:
            return element
    raise ValueError(f"no block with id {node_id!r} in this document")


def _text_field(element) -> str | None:
    return _TEXT_FIELD.get(type(element).__name__)


def apply_comment(doc, comment, replacement: str):
    """Return a new Document with *comment*'s node edited to *replacement*.

    For an ``exact`` resolution over a plain-text node, only the resolved
    character range is spliced; otherwise the node's whole text is replaced.
    Raises ``ValueError`` for a comment that did not resolve to one node
    (``spanning``/``unanchored``), which is never silently patchable.
    """
    if comment.resolution not in ("exact", "node") or not comment.node_id:
        raise ValueError(
            f"comment {comment.id} resolved as {comment.resolution!r}; "
            "only exact or node resolutions can be patched"
        )
    element = _find(doc, comment.node_id)
    field_name = _text_field(element)
    if field_name is None:
        raise ValueError(
            f"node {comment.node_id} is a {type(element).__name__}, which has "
            "no editable text field"
        )
    current = getattr(element, field_name)
    if (
        comment.resolution == "exact"
        and comment.char_range
        and isinstance(current, str)
    ):
        start, end = comment.char_range
        new_text = current[:start] + replacement + current[end:]
    else:
        new_text = replacement
    return doc.patch(comment.node_id, **{field_name: new_text})


def apply_replacements(doc, comments, replacements: dict):
    """Apply many comment edits, keyed by comment id, in one pass.

    ``replacements`` maps comment id to its replacement string. Comments
    without an entry are left untouched. Returns the new Document.
    """
    by_id = {c.id: c for c in comments}
    result = doc
    for comment_id, replacement in replacements.items():
        comment = by_id.get(comment_id)
        if comment is None:
            raise ValueError(f"no comment with id {comment_id!r}")
        result = apply_comment(result, comment, replacement)
    return result


@dataclass
class ProposedPatch:
    """A single comment turned into a concrete, reviewable edit."""

    comment_id: str
    node_id: str
    resolution: str
    before: str
    after: str
    patchable: bool = True
    note: str = ""


def propose_patches(doc, comments, replacements: dict) -> list:
    """Describe the edit each comment implies, without shipping anything.

    Returns a list of :class:`ProposedPatch`. A comment that cannot be
    patched (``spanning``/``unanchored``, or a non-text node) is reported as
    ``patchable=False`` with a note, never dropped -- so an unresolved comment
    is surfaced rather than silently skipped.
    """
    patches: list = []
    for comment in comments:
        replacement = replacements.get(comment.id)
        if comment.resolution not in ("exact", "node") or not comment.node_id:
            patches.append(
                ProposedPatch(
                    comment_id=comment.id,
                    node_id=comment.node_id or "",
                    resolution=comment.resolution,
                    before=comment.anchor_text or "",
                    after="",
                    patchable=False,
                    note=f"{comment.resolution} resolution is not patchable",
                )
            )
            continue
        if replacement is None:
            patches.append(
                ProposedPatch(
                    comment_id=comment.id,
                    node_id=comment.node_id,
                    resolution=comment.resolution,
                    before=comment.anchor_text or "",
                    after="",
                    patchable=True,
                    note="no replacement supplied for this comment",
                )
            )
            continue
        try:
            element = _find(doc, comment.node_id)
            field_name = _text_field(element)
            before = comment.anchor_text or (
                getattr(element, field_name) if field_name else ""
            )
            patches.append(
                ProposedPatch(
                    comment_id=comment.id,
                    node_id=comment.node_id,
                    resolution=comment.resolution,
                    before=before,
                    after=replacement,
                )
            )
        except ValueError as exc:
            patches.append(
                ProposedPatch(
                    comment_id=comment.id,
                    node_id=comment.node_id,
                    resolution=comment.resolution,
                    before=comment.anchor_text or "",
                    after="",
                    patchable=False,
                    note=str(exc),
                )
            )
    return patches


def redline(old_doc, new_doc) -> bytes:
    """Render a redlined PDF proving what changed between two documents."""
    diff = diff_documents(old_doc, new_doc)
    return render_redline(old_doc, new_doc, diff)
