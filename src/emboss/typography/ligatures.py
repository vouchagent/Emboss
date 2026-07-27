"""Ligature substitution for embedded fonts that carry the ligature glyphs.

The base-14 PDF fonts expose no fi/fl ligature codepoints, so substitution
is only performed for embedded fonts whose cmap actually maps the Unicode
ligature characters (U+FB00..U+FB04). Callers gate on that support via
`available_ligatures` / `supports_ligatures`; the substitution itself is a
pure string transform.
"""

from __future__ import annotations

import re
from typing import Callable, Sequence

__all__ = [
    "apply_ligatures",
    "available_ligatures",
    "ligate",
    "supports_ligatures",
    "LIGATURE_MAP",
]

LIGATURE_MAP: dict[str, str] = {
    "ffi": "ﬃ",
    "ffl": "ﬄ",
    "ff": "ﬀ",
    "fi": "ﬁ",
    "fl": "ﬂ",
}

# Longest sequences first so ffi/ffl win over ff/fi/fl; ties break
# alphabetically for determinism.
_SUBSTITUTIONS: tuple[tuple[str, str], ...] = tuple(
    sorted(LIGATURE_MAP.items(), key=lambda kv: (-len(kv[0]), kv[0]))
)

# Ligatures must not form across word-internal boundaries such as
# snake_case underscores or hyphenated compounds.
_BOUNDARY = re.compile(r"([-_]+)")

_AVAILABLE_CACHE: dict[object, tuple[tuple[str, str], ...]] = {}


def ligate(text: str, pairs: Sequence[tuple[str, str]]) -> str:
    """Apply (sequence, glyph) substitutions, never across "-" or "_"."""
    if not pairs or "f" not in text:
        return text
    segments = _BOUNDARY.split(text)
    out = []
    for segment in segments:
        if segment and segment[0] not in "-_":
            for sequence, glyph in pairs:
                segment = segment.replace(sequence, glyph)
        out.append(segment)
    return "".join(out)


def apply_ligatures(
    text: str, font_supports: Callable[[str], bool] | None = None
) -> str:
    """Replace fi/fl/ff/ffi/ffl sequences with single ligature glyphs."""
    pairs = _SUBSTITUTIONS
    if font_supports is not None:
        pairs = tuple((seq, glyph) for seq, glyph in pairs if font_supports(glyph))
    return ligate(text, pairs)


def available_ligatures(metrics) -> tuple[tuple[str, str], ...]:
    """Ligature (sequence, glyph) pairs this font can actually render."""
    if not getattr(metrics, "is_embedded", False):
        return ()
    cached = _AVAILABLE_CACHE.get(metrics)
    if cached is None:
        cached = tuple(
            (seq, glyph) for seq, glyph in _SUBSTITUTIONS if metrics.supports(glyph)
        )
        _AVAILABLE_CACHE[metrics] = cached
    return cached


def supports_ligatures(metrics) -> bool:
    """True when an embedded font carries both the fi and fl glyphs."""
    sequences = {seq for seq, _glyph in available_ligatures(metrics)}
    return "fi" in sequences and "fl" in sequences
