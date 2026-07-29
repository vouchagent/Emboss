"""Node-keyed document diff and redlined-PDF rendering.

``diff_documents`` matches blocks between two documents by their stable
``id`` (see ``nodeid.py``), classifying each as added, removed, changed
(same id, different content, plus a word-level diff for text-bearing
blocks), or unchanged. ``render_redline`` turns that diff into a real
PDF: the new document's content runs through the normal
measure/paginate/render pipeline with deleted words struck through,
inserted words underlined, added blocks marked with a margin change-bar,
and a prepended summary page listing what was removed.

Diffing only detects a genuine "change" (rather than a remove+add pair)
when both documents already carry the same id for that block — typically
because the id was assigned once (an explicit ``id=``, a prior render, or
``Document.patch``, which preserves it) and the same element was edited
in place rather than replaced.
"""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field

from .nodeid import assign_node_ids, content_signature
from .recovery import document_from_spec_dict
from .redaction import RedactionMark
from .spec import (
    BlockQuote,
    BulletList,
    Callout,
    Document,
    Footnote,
    Heading,
    PageBreak,
    Paragraph,
    PullQuote,
    TextRun,
)

__all__ = ["DiffResult", "diff_documents", "render_redline", "word_diff"]

#: Redline colors: deletions in crimson, insertions/additions in forest green.
_DELETE_COLOR = "dc143c"
_INSERT_COLOR = "228b22"
_ADD_BAR_COLOR = "228b22"
_ADD_BAR_WIDTH = 2.5
_ADD_BAR_GAP = 10.0
_EXCERPT_LIMIT = 80


@dataclass
class DiffResult:
    """Node-keyed diff between two documents' content trees."""

    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)


def _as_document(source) -> Document:
    if isinstance(source, dict):
        return document_from_spec_dict(source)
    if isinstance(source, Document):
        return source
    raise TypeError(f"expected Document or spec dict, got {type(source).__name__}")


def _normalize_content(source) -> list:
    """Deep-copy a document's content and ensure every block has an id."""
    document = _as_document(source)
    content = copy.deepcopy(document.content)
    assign_node_ids(content)
    return content


def _block_text(el) -> str | None:
    """Plain text of a text-bearing block, or None for anything else."""
    if isinstance(el, Heading):
        return el.text
    if isinstance(el, PullQuote):
        return el.text
    if isinstance(el, (Paragraph, BlockQuote, Callout, Footnote)):
        return "".join(run.text for run in el.runs)
    return None


def word_diff(old_text: str, new_text: str) -> list:
    """Word-level diff between two strings, tokenized on whitespace.

    Returns a list of ``(op, text)`` pairs with ``op`` in
    ``{"equal", "insert", "delete"}``, built from
    ``difflib.SequenceMatcher`` opcodes and therefore deterministic given
    deterministic input order.
    """
    old_words = old_text.split()
    new_words = new_text.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    ops: list = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append(("equal", " ".join(old_words[i1:i2])))
        elif tag == "delete":
            ops.append(("delete", " ".join(old_words[i1:i2])))
        elif tag == "insert":
            ops.append(("insert", " ".join(new_words[j1:j2])))
        else:  # "replace"
            ops.append(("delete", " ".join(old_words[i1:i2])))
            ops.append(("insert", " ".join(new_words[j1:j2])))
    return ops


def _word_diff_for_blocks(old_el, new_el) -> list | None:
    old_text = _block_text(old_el)
    new_text = _block_text(new_el)
    if old_text is None or new_text is None:
        return None
    return word_diff(old_text, new_text)


def diff_documents(old, new) -> DiffResult:
    """Diff two documents (``Document`` or EmbossSpec dict) by node id.

    Blocks are matched on their stable ``id`` (assigned via
    ``assign_node_ids`` for any block that doesn't already carry one). A
    matched pair is "changed" when ``nodeid.content_signature`` (which
    ignores ``style``/``id``) differs; text-bearing blocks (``Heading``,
    ``Paragraph``, ``BlockQuote``, ``PullQuote``, ``Callout``,
    ``Footnote``) additionally get a word-level diff. Blocks whose id
    only exists on one side are added or removed.
    """
    old_content = _normalize_content(old)
    new_content = _normalize_content(new)
    old_by_id = {el.id: el for el in old_content}
    new_by_id = {el.id: el for el in new_content}

    added = [el for el in new_content if el.id not in old_by_id]
    removed = [el for el in old_content if el.id not in new_by_id]

    changed: list = []
    unchanged: list = []
    for el in new_content:
        old_el = old_by_id.get(el.id)
        if old_el is None:
            continue
        if content_signature(old_el) == content_signature(el):
            unchanged.append(el.id)
        else:
            changed.append((old_el, el, _word_diff_for_blocks(old_el, el)))

    return DiffResult(
        added=added, removed=removed, changed=changed, unchanged=unchanged
    )


# -- redline rendering -----------------------------------------------------


def _apply_word_diff_runs(word_diff_ops: list) -> list:
    """Turn word-diff ops into TextRuns: deletions struck, insertions underlined."""
    runs: list = []
    parts = [(op, text) for op, text in word_diff_ops if text]
    for index, (op, text) in enumerate(parts):
        if index:
            runs.append(TextRun(" "))
        if op == "delete":
            runs.append(TextRun(text, strikethrough=True, color=_DELETE_COLOR))
        elif op == "insert":
            runs.append(TextRun(text, underline=True, color=_INSERT_COLOR))
        else:
            runs.append(TextRun(text))
    return runs


def _redline_block(old_el, new_el, word_diff_ops: list | None) -> list:
    """Return the replacement block(s) for one changed block.

    Blocks that hold a runs list (Paragraph, BlockQuote, Callout,
    Footnote) get the word diff inlined directly. Heading and PullQuote
    only carry a single plain-text field with no per-run styling, so the
    new heading/quote is kept as-is (preserving its structure tag and
    pagination role) and a small redlined note paragraph is appended
    right after it showing the word diff.
    """
    if word_diff_ops is None:
        return [new_el]
    runs = _apply_word_diff_runs(word_diff_ops)
    if isinstance(new_el, Paragraph):
        return [Paragraph(content=runs, style=new_el.style, id=new_el.id)]
    if isinstance(new_el, BlockQuote):
        return [
            BlockQuote(
                content=runs,
                attribution=new_el.attribution,
                style=new_el.style,
                id=new_el.id,
            )
        ]
    if isinstance(new_el, Callout):
        return [
            Callout(
                content=runs,
                variant=new_el.variant,
                title=new_el.title,
                icon=new_el.icon,
                background=new_el.background,
                border_color=new_el.border_color,
                border_radius=new_el.border_radius,
                style=new_el.style,
                id=new_el.id,
            )
        ]
    if isinstance(new_el, Footnote):
        return [
            Footnote(
                content=runs, marker=new_el.marker, style=new_el.style, id=new_el.id
            )
        ]
    if isinstance(new_el, (Heading, PullQuote)):
        return [new_el, Paragraph(content=runs)]
    return [new_el]


def _removed_excerpt(el) -> str:
    """A short ``[Type] first ~80 chars`` line for the summary page."""
    text = _block_text(el)
    if text is None:
        text = getattr(el, "caption", None) or getattr(el, "title", None) or ""
    text = " ".join(str(text).split())
    label = type(el).__name__
    excerpt = text[:_EXCERPT_LIMIT]
    return f"[{label}] {excerpt}" if excerpt else f"[{label}]"


def _summary_blocks(diff: DiffResult, title: str) -> list:
    # The heading text is made to match the redline Document's own title so
    # the render pipeline's title-block dedup (writer._prepend_title_block)
    # recognizes this as the title heading rather than prepending a second,
    # redundant one.
    blocks: list = [
        Heading(title, level=1),
        Paragraph(
            f"{len(diff.added)} block(s) added, {len(diff.removed)} removed, "
            f"{len(diff.changed)} changed, {len(diff.unchanged)} unchanged."
        ),
    ]
    if diff.removed:
        blocks.append(Heading("Removed content", level=2))
        blocks.append(BulletList(items=[_removed_excerpt(el) for el in diff.removed]))
    blocks.append(PageBreak())
    return blocks


def _change_bar_marks(layout_map: dict, added_ids: set) -> list:
    """RedactionMark rects for a thin green bar left of each added block."""
    marks: list = []
    for node_id in sorted(added_ids):
        for entry in layout_map.get(node_id, []):
            height = max(entry["y1"] - entry["y0"], 1.0)
            marks.append(
                RedactionMark(
                    page_index=entry["page"],
                    x=max(entry["x0"] - _ADD_BAR_GAP, 0.0),
                    y=entry["y0"],
                    width=_ADD_BAR_WIDTH,
                    height=height,
                    color=_ADD_BAR_COLOR,
                )
            )
    return marks


def render_redline(old, new, diff: DiffResult | None = None) -> bytes:
    """Render the new document with revision marks against the old one.

    Unchanged blocks render normally. Changed text-bearing blocks get
    their word diff inlined (deleted words struck through in crimson,
    inserted words underlined in forest green); changed headings and
    pull quotes keep their new text and gain a redlined note paragraph
    underneath. Added blocks get a real, measured green change-bar in
    the left margin (drawn from a first render pass's layout map, then
    baked in on a second pass — no fake overlay). Removed blocks are not
    re-added to the flow; they are listed with ~80-char excerpts on a
    prepended summary page alongside the added/removed/changed counts.
    """
    new_content = _normalize_content(new)
    if diff is None:
        diff = diff_documents(old, new)

    added_ids = {el.id for el in diff.added if el.id}
    changed_by_id = {
        new_el.id: (old_el, ops) for old_el, new_el, ops in diff.changed if new_el.id
    }

    body: list = []
    for el in new_content:
        pair = changed_by_id.get(el.id)
        if pair is not None:
            body.extend(_redline_block(pair[0], el, pair[1]))
        else:
            body.append(el)

    new_doc = _as_document(new)
    title = f"{new_doc.title} — Redline" if new_doc.title else "Redline"
    redline_doc = Document(
        title=title,
        author=new_doc.author,
        style=new_doc.style,
        page=new_doc.page,
        language=new_doc.language,
        content=_summary_blocks(diff, title) + body,
    )

    from .writer import render_document

    probe = render_document(redline_doc, return_result=True)
    marks = _change_bar_marks(probe.layout_map, added_ids)
    if not marks:
        return probe.data
    redline_doc.redactions = marks
    return render_document(redline_doc)
