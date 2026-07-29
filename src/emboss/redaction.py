"""Content redaction: construction-time removal, plus post-render masking.

Two models live here, and they are not equally honest:

  RedactionRule / redact_document (construction-time -- the honest kind)
      Matches whole content blocks -- by stable node id, by a regex or
      predicate over the block's plain text, or by element type -- and
      either drops them from the document outright or replaces them
      with same-shaped filler text, all *before* layout or rendering
      happens. The real text never reaches a content stream. When a
      block is replaced rather than removed, its filler's own rendered
      footprint is covered with an opaque box afterward (via
      ``RedactionMark``), so what the box conceals is filler, never the
      redacted content itself. ``Document.redact(rules)`` is the public
      entry point.

  RedactionMark / apply_redactions (post-render -- kept for existing
  callers, e.g. masking content that never went through a Document at
  all)
      Draws opaque rectangles directly onto an already-measured page's
      content stream. The underlying text is still in the content
      stream underneath the box -- fine for masking a placeholder's own
      filler (as construction-time redaction does above), but dishonest
      if used to cover real secret text, since the original bytes are
      still extractable. Wired via ``Document.redactions``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Literal, Sequence

from .colors import rgb_to_cmyk
from .spec import (
    BlockQuote,
    BulletList,
    Callout,
    CodeBlock,
    Footnote,
    Heading,
    NumberedList,
    Paragraph,
    PullQuote,
    Table,
    TextRun,
)

__all__ = [
    "RedactionMark",
    "apply_redactions",
    "RedactionRule",
    "redact_document",
    "encrypt_attachment",
    "decrypt_attachment",
]


@dataclass
class RedactionMark:
    """A rectangular region to redact on a specific page."""

    page_index: int
    x: float
    y: float
    width: float
    height: float
    replacement_text: str = ""
    color: str = "000000"


def apply_redactions(
    stream,
    marks: list[RedactionMark],
    page_index: int,
    font_key: str,
    font_size: float,
    color_mode: str = "rgb",
) -> None:
    """Draw redaction rectangles on a content stream for the given page.

    Each mark whose ``page_index`` matches is rendered as a filled rectangle
    in the mark's color. If ``replacement_text`` is set, it is drawn centered
    within the rectangle in white. ``color_mode`` defaults to the stream's
    own mode; pass ``"cmyk"`` explicitly to force DeviceCMYK operators.
    """
    mode = _effective_mode(stream, color_mode)
    previous = getattr(stream, "color_mode", None)
    override = previous is not None and previous != mode
    if override:
        stream.color_mode = mode
    try:
        _draw_marks(stream, marks, page_index, font_key, font_size, mode)
    finally:
        if override:
            stream.color_mode = previous


def _draw_marks(
    stream,
    marks: list[RedactionMark],
    page_index: int,
    font_key: str,
    font_size: float,
    mode: str,
) -> None:
    """Emit the redaction rectangles and replacement text for one page."""
    for mark in marks:
        if mark.page_index != page_index:
            continue

        stream.begin_artifact("Redaction")

        stream.rect(
            mark.x,
            mark.y,
            mark.width,
            mark.height,
            fill=mark.color,
        )

        if mark.replacement_text:
            text_color = "ffffff"
            text_x = mark.x + mark.width / 2.0
            text_y = mark.y + mark.height / 2.0 - font_size * 0.35

            stream.raw(b"BT")
            r, g, b = _hex_color(text_color)
            stream.raw(_fill_op(r, g, b, mode))
            stream.raw(f"/{font_key} {font_size:.2f} Tf".encode("ascii"))

            # Approximate text width for centering
            char_width = font_size * 0.5
            text_width = len(mark.replacement_text) * char_width
            centered_x = text_x - text_width / 2.0

            stream.raw(f"{centered_x:.4f} {text_y:.4f} Td".encode("ascii"))
            stream.raw(_escape_text(mark.replacement_text) + b" Tj")
            stream.raw(b"ET")

        stream.end_marked()


def _effective_mode(stream, color_mode: str) -> str:
    """Resolve the color mode: explicit override wins, else the stream's."""
    if color_mode != "rgb":
        return color_mode
    return getattr(stream, "color_mode", "rgb") or "rgb"


def _fill_op(r: float, g: float, b: float, mode: str) -> bytes:
    """Encode a fill-color operator for the given mode (rg or k)."""
    if mode == "cmyk":
        c, m, y, k = rgb_to_cmyk(r, g, b).components
        return f"{c:.4f} {m:.4f} {y:.4f} {k:.4f} k".encode("ascii")
    return f"{r:.4f} {g:.4f} {b:.4f} rg".encode("ascii")


def _hex_color(value: str) -> tuple[float, float, float]:
    text = value.lstrip("#")
    return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _escape_text(text: str) -> bytes:
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


# -- construction-time redaction (honest: never enters the content stream) --


@dataclass(frozen=True)
class RedactionRule:
    """One construction-time redaction match, applied before rendering.

    Selects whole content blocks by any combination of ``node_id`` (an
    exact match against the block's stable id, see ``nodeid.py``),
    ``pattern`` (a regex searched against the block's plain text),
    ``predicate`` (a callable given the block's plain text, returning
    bool), and/or ``element_type`` (an ``isinstance`` check) -- every
    criterion supplied must match for the rule to fire; at least one
    must be given. ``mode="placeholder"`` (the default) replaces a
    matched block with same-shaped filler text so layout doesn't
    visibly reflow, then covers the filler's own rendered footprint
    with an opaque box; ``mode="remove"`` drops the block outright.

    Placeholder mode is only implemented for text-bearing block types
    (``Heading``, ``Paragraph``, ``BlockQuote``, ``Callout``,
    ``Footnote``, ``PullQuote``, ``BulletList``, ``NumberedList``,
    ``Table``, ``CodeBlock``); match other element types with
    ``mode="remove"``.
    """

    name: str
    node_id: str | None = None
    pattern: "re.Pattern | str | None" = None
    predicate: "Callable[[str], bool] | None" = None
    element_type: type | None = None
    mode: Literal["remove", "placeholder"] = "placeholder"

    def __post_init__(self) -> None:
        if not any((self.node_id, self.pattern, self.predicate, self.element_type)):
            raise ValueError(
                f"RedactionRule {self.name!r} must match on at least one of "
                "node_id, pattern, predicate, or element_type"
            )


_NON_SPACE_RE = re.compile(r"\S")


def _filler_text(text: str) -> str:
    """Same-length filler preserving whitespace, so wrapped height matches."""
    return _NON_SPACE_RE.sub("X", text)


def _filler_runs(runs: Sequence[TextRun]) -> list:
    from dataclasses import replace

    return [replace(run, text=_filler_text(run.text)) for run in runs]


def _flatten_list_text(lst) -> list:
    texts: list = []
    for runs, sub in lst.flat_items:
        if runs is not None:
            texts.append("".join(r.text for r in runs))
        else:
            texts.extend(_flatten_list_text(sub))
    return texts


def _filler_list_items(lst) -> list:
    items: list = []
    for runs, sub in lst.flat_items:
        if runs is not None:
            items.append(_filler_runs(runs))
        else:
            items.append(_filler_list_items(sub))
    return items


def _element_plain_text(element) -> str:
    """Best-effort plain-text view of a block, for matching and the audit log."""
    if isinstance(element, Heading):
        return element.text
    if isinstance(element, (Paragraph, BlockQuote, Callout, Footnote)):
        return "".join(run.text for run in element.runs)
    if isinstance(element, PullQuote):
        return element.text
    if isinstance(element, (BulletList, NumberedList)):
        return " ".join(_flatten_list_text(element))
    if isinstance(element, Table):
        cells = [c.plain_text for c in element.header_cells]
        for row in element.body_rows:
            cells.extend(c.plain_text for c in row)
        return " ".join(cells)
    if isinstance(element, CodeBlock):
        return element.code
    return ""


def _placeholder_for(element, marker_id: str):
    """Return a same-type block with same-shaped filler replacing its text."""
    if isinstance(element, Heading):
        return Heading(
            text=_filler_text(element.text),
            level=element.level,
            numbering=element.numbering,
            anchor=element.anchor,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, Paragraph):
        return Paragraph(
            content=_filler_runs(element.runs), style=element.style, id=marker_id
        )
    if isinstance(element, BlockQuote):
        return BlockQuote(
            content=_filler_runs(element.runs),
            attribution=element.attribution,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, Callout):
        return Callout(
            content=_filler_runs(element.runs),
            variant=element.variant,
            title=_filler_text(element.title) if element.title else element.title,
            icon=element.icon,
            background=element.background,
            border_color=element.border_color,
            border_radius=element.border_radius,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, Footnote):
        return Footnote(
            content=_filler_runs(element.runs),
            marker=element.marker,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, PullQuote):
        return PullQuote(
            text=_filler_text(element.text),
            attribution=element.attribution,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, BulletList):
        return BulletList(
            items=_filler_list_items(element),
            bullet=element.bullet,
            checked=element.checked,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, NumberedList):
        return NumberedList(
            items=_filler_list_items(element),
            start=element.start,
            marker_style=element.marker_style,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, Table):
        return Table(
            headers=[_filler_text(c.plain_text) for c in element.header_cells],
            rows=[
                [_filler_text(c.plain_text) for c in row] for row in element.body_rows
            ],
            column_widths=element.column_widths,
            caption=element.caption,
            label=element.label,
            stripe=element.stripe,
            repeat_header=element.repeat_header,
            style=element.style,
            id=marker_id,
        )
    if isinstance(element, CodeBlock):
        return CodeBlock(
            code=_filler_text(element.code),
            language=element.language,
            line_numbers=element.line_numbers,
            theme=element.theme,
            start_line=element.start_line,
            highlight_lines=list(element.highlight_lines),
            caption=element.caption,
            label=element.label,
            style=element.style,
            id=marker_id,
        )
    raise TypeError(
        f"redact(): no construction-time placeholder for {type(element).__name__}; "
        "match it with mode='remove' instead"
    )


def _rule_matches(rule: RedactionRule, element, node_id: str | None, text: str) -> bool:
    if rule.node_id is not None and node_id != rule.node_id:
        return False
    if rule.element_type is not None and not isinstance(element, rule.element_type):
        return False
    if rule.pattern is not None:
        compiled = (
            rule.pattern
            if isinstance(rule.pattern, re.Pattern)
            else re.compile(rule.pattern)
        )
        if not compiled.search(text):
            return False
    if rule.predicate is not None and not rule.predicate(text):
        return False
    return True


def _cover_placeholders(document, marker_ids: list) -> None:
    """Draw an opaque box over each placeholder's own rendered footprint.

    Runs a render pass (via ``layout_map``) to learn where the filler
    text actually landed, then extends ``document.redactions`` with one
    ``RedactionMark`` per placement. Legitimate here specifically
    because these boxes only ever cover filler text that already
    replaced the real content before this render pass began -- nothing
    secret is in the stream underneath.
    """
    layout = document.layout_map()
    marks: list = []
    for marker_id in marker_ids:
        for box in layout.get(marker_id, []):
            marks.append(
                RedactionMark(
                    page_index=box["page"],
                    x=box["x0"],
                    y=box["y0"],
                    width=box["x1"] - box["x0"],
                    height=box["y1"] - box["y0"],
                )
            )
    if marks:
        document.redactions = list(document.redactions or []) + marks


def redact_document(document, rules: Sequence[RedactionRule]) -> tuple:
    """Apply *rules* to a copy of *document*, before any rendering happens.

    Returns ``(redacted_document, log)``. Each matched block either
    never re-enters ``redacted_document.content`` (``mode="remove"``) or
    is replaced with same-shaped filler covered by an opaque box
    (``mode="placeholder"``); either way the original text never
    reaches a content stream. ``log`` is a list of dicts -- one per
    matched block, each carrying ``node_id``, ``rule``, ``element_type``,
    ``mode``, and the block's full plain ``text`` as it existed BEFORE
    removal -- meant as a caller-held audit trail, never for embedding
    in the redacted document (see ``Document.redact``).
    """
    import copy

    from .nodeid import assign_node_ids

    redacted = copy.deepcopy(document)
    ids = assign_node_ids(redacted.content)

    log: list = []
    new_content: list = []
    marker_ids: list = []

    for ordinal, element in enumerate(redacted.content):
        node_id = ids.get(ordinal) or getattr(element, "id", None)
        text = _element_plain_text(element)
        matched = next(
            (rule for rule in rules if _rule_matches(rule, element, node_id, text)),
            None,
        )
        if matched is None:
            new_content.append(element)
            continue

        log.append(
            {
                "node_id": node_id,
                "rule": matched.name,
                "element_type": type(element).__name__,
                "mode": matched.mode,
                "text": text,
            }
        )
        if matched.mode == "remove":
            continue

        marker_id = f"redact-{ordinal}-{matched.name}"
        new_content.append(_placeholder_for(element, marker_id))
        marker_ids.append(marker_id)

    redacted.content = new_content
    if marker_ids:
        _cover_placeholders(redacted, marker_ids)
    return redacted, log


# -- encrypted attachment payloads ------------------------------------------

_PBKDF2_ITERATIONS = 390_000
_SALT_LEN = 16
_NONCE_LEN = 12
_KEY_LEN = 32


def _derive_key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_attachment(data: bytes, password: str) -> bytes:
    """Encrypt *data* with AES-256-GCM, keyed by PBKDF2-HMAC-SHA256(password).

    Returns ``salt(16 bytes) || nonce(12 bytes) || ciphertext_and_tag``:
    a self-contained blob a consumer can decrypt knowing only the
    password (``decrypt_attachment`` does exactly that). The salt and
    nonce are drawn fresh from ``os.urandom`` on every call -- the one
    legitimate use of randomness in this library, deliberately kept out
    of the deterministic render pipeline and run only when a caller
    explicitly opts in (e.g. ``Document.attach_encrypted``).
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "Encrypted attachments require the 'cryptography' package.\n"
            "  pip install emboss-pdf[signing]"
        ) from None

    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, data, None)
    return salt + nonce + ciphertext


def decrypt_attachment(blob: bytes, password: str) -> bytes:
    """Decrypt a blob produced by ``encrypt_attachment``.

    Raises ``cryptography.exceptions.InvalidTag`` if *password* is wrong
    or *blob* was tampered with.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "Decrypting attachments requires the 'cryptography' package.\n"
            "  pip install emboss-pdf[signing]"
        ) from None

    salt = blob[:_SALT_LEN]
    nonce = blob[_SALT_LEN : _SALT_LEN + _NONCE_LEN]
    ciphertext = blob[_SALT_LEN + _NONCE_LEN :]
    key = _derive_key(password, salt)
    return AESGCM(key).decrypt(nonce, ciphertext, None)
