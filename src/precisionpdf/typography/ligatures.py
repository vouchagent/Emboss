"""Standard ligature substitution for improved typographic quality.

Replaces common ligature sequences (fi, fl, ffi, ffl) with their
corresponding WinAnsi ligature codepoints when the font supports them.

This is a simplified version of what a full OpenType shaping engine does.
It handles the most impactful Latin ligatures that are visible in every
serif and many sans-serif fonts.
"""

from __future__ import annotations

__all__ = ["apply_ligatures", "LIGATURE_MAP"]

LIGATURE_MAP: dict[str, str] = {
    "ffi": "ﬃ",
    "ffl": "ﬄ",
    "fi": "ﬁ",
    "fl": "ﬂ",
}

_WINANSI_LIGATURES: dict[str, int] = {
    "ﬁ": 0xC0 + 1,  # fi ligature in some WinAnsi fonts
    "ﬂ": 0xC0 + 2,  # fl ligature
}

_SUBSTITUTIONS = sorted(LIGATURE_MAP.items(), key=lambda x: -len(x[0]))


def apply_ligatures(text: str, font_supports: callable | None = None) -> str:
    """Replace ligature sequences with single glyphs.

    If ``font_supports`` is provided, only substitutions where the font
    has the ligature glyph are made. Without it, all standard ligatures
    are applied.
    """
    result = text
    for pattern, replacement in _SUBSTITUTIONS:
        if font_supports and not font_supports(replacement):
            continue
        result = result.replace(pattern, replacement)
    return result
