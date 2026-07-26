"""Content redaction for generated PDFs.

Draws opaque rectangles over specified regions and optionally renders
replacement text (e.g. "[REDACTED]") centered within each mark. Redaction
marks are tagged as /Artifact so assistive technology skips them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RedactionMark", "apply_redactions"]


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
) -> None:
    """Draw redaction rectangles on a content stream for the given page.

    Each mark whose ``page_index`` matches is rendered as a filled rectangle
    in the mark's color. If ``replacement_text`` is set, it is drawn centered
    within the rectangle in white.
    """
    for mark in marks:
        if mark.page_index != page_index:
            continue

        stream.begin_artifact("Redaction")

        stream.rect(
            mark.x, mark.y, mark.width, mark.height,
            fill=mark.color,
        )

        if mark.replacement_text:
            text_color = "ffffff"
            text_x = mark.x + mark.width / 2.0
            text_y = mark.y + mark.height / 2.0 - font_size * 0.35

            stream.raw(b"BT")
            r, g, b = _hex_color(text_color)
            stream.raw(
                f"{r:.4f} {g:.4f} {b:.4f} rg".encode("ascii")
            )
            stream.raw(
                f"/{font_key} {font_size:.2f} Tf".encode("ascii")
            )

            # Approximate text width for centering
            char_width = font_size * 0.5
            text_width = len(mark.replacement_text) * char_width
            centered_x = text_x - text_width / 2.0

            stream.raw(
                f"{centered_x:.4f} {text_y:.4f} Td".encode("ascii")
            )
            stream.raw(
                _escape_text(mark.replacement_text) + b" Tj"
            )
            stream.raw(b"ET")

        stream.end_marked()


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
