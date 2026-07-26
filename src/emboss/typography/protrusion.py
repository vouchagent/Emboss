"""Optical margin alignment (hanging punctuation) and character protrusion.

Protrusion tables map characters to the fraction of their width that may
extend past the margin.  This is the mechanism behind LaTeX microtype's
``protrusion`` feature: punctuation hangs into the margin so the text
edge looks optically straight, and certain letter shapes (A, V, W, T)
protrude slightly so they do not create a visual indent.

Each entry maps a character to a ``(left, right)`` pair of factors in the
range 0.0--1.0.  A factor of 0.7 means the character may protrude 70 %
of its advance width past the margin on that side.
"""

from __future__ import annotations

__all__ = [
    "PROTRUSION_TABLE",
    "left_protrusion",
    "right_protrusion",
    "protrusion_width",
]

# ---- protrusion table ----
# (left_factor, right_factor)

PROTRUSION_TABLE: dict[str, tuple[float, float]] = {
    # Punctuation -- these hang substantially
    "-":  (0.7, 0.7),
    "‐": (0.7, 0.7),   # hyphen
    "‑": (0.7, 0.7),   # non-breaking hyphen
    "–": (0.5, 0.5),   # en-dash
    "—": (0.3, 0.3),   # em-dash
    ".":  (0.0, 0.7),
    ",":  (0.0, 0.7),
    ":":  (0.0, 0.5),
    ";":  (0.0, 0.5),
    # Quotes
    "“": (0.5, 0.0),   # left double quote
    "”": (0.0, 0.5),   # right double quote
    "‘": (0.5, 0.0),   # left single quote
    "’": (0.0, 0.5),   # right single quote
    '"':  (0.5, 0.5),
    "'":  (0.5, 0.5),
    # Parentheses / brackets
    "(":  (0.3, 0.0),
    ")":  (0.0, 0.3),
    "[":  (0.3, 0.0),
    "]":  (0.0, 0.3),

    # ---- letter protrusion (microtype signature) ----
    # Uppercase
    "A":  (0.05, 0.05),
    "V":  (0.05, 0.05),
    "W":  (0.05, 0.05),
    "T":  (0.05, 0.05),
    "F":  (0.0, 0.05),
    "Y":  (0.05, 0.05),
    "J":  (0.0, 0.03),
    # Lowercase
    "v":  (0.03, 0.03),
    "w":  (0.03, 0.03),
    "y":  (0.03, 0.03),
}


def left_protrusion(char: str) -> float:
    """Return the left protrusion factor for *char* (0.0 if none)."""
    entry = PROTRUSION_TABLE.get(char)
    return entry[0] if entry else 0.0


def right_protrusion(char: str) -> float:
    """Return the right protrusion factor for *char* (0.0 if none)."""
    entry = PROTRUSION_TABLE.get(char)
    return entry[1] if entry else 0.0


def protrusion_width(char: str, char_width: float, side: str) -> float:
    """Return the absolute protrusion amount for *char* on *side*.

    *side* is ``"left"`` or ``"right"``.
    """
    factor = left_protrusion(char) if side == "left" else right_protrusion(char)
    return char_width * factor
