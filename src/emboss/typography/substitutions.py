"""Deterministic ASCII substitutions for characters a font cannot render."""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Callable

__all__ = ["SUBSTITUTIONS", "substitute_unsupported"]

# Structural whitespace is never substituted: it is layout input, not a
# glyph, and mapping it through the last-resort path would corrupt text.
_PASSTHROUGH = frozenset("\t\n\r\x0b\x0c")


def _box_drawing_map() -> dict[str, str]:
    """Map box-drawing characters onto '-', '|', '/', and '+' by name."""
    table: dict[str, str] = {}
    for code in range(0x2500, 0x2580):
        name = unicodedata.name(chr(code), "")
        if not name:
            continue
        if "DIAGONAL" in name:
            table[chr(code)] = "/"
        elif "AND" not in name and any(
            word in name for word in ("HORIZONTAL", "LEFT", "RIGHT")
        ):
            table[chr(code)] = "-"
        elif "AND" not in name and any(
            word in name for word in ("VERTICAL", "UP", "DOWN")
        ):
            table[chr(code)] = "|"
        else:
            table[chr(code)] = "+"
    return table


# Curated replacements for characters LLMs emit freely but WinAnsi-encoded
# base-14 fonts cannot render. Values are printable ASCII. Notable choices:
# a check mark becomes "*" and a ballot cross becomes "x" (readable in
# professional output); typographic spaces collapse to a regular space
# (NBSP is untouched because base-14 metrics carry U+00A0); zero-width
# characters vanish entirely. Entries whose character a font does support
# (for example U+00BD "1/2" in WinAnsi) are never consulted for that font.
SUBSTITUTIONS: dict[str, str] = {
    # Arrows
    "←": "<-",
    "↑": "^",
    "→": "->",
    "↓": "v",
    "↔": "<->",
    "↩": "<-",
    "↪": "->",
    "⇐": "<=",
    "⇒": "=>",
    "⇔": "<=>",
    "➡": "->",
    "⬅": "<-",
    # Comparison and math operators
    "⁄": "/",
    "−": "-",
    "∓": "-+",
    "∕": "/",
    "∗": "*",
    "∙": "*",
    "≈": "~",
    "≠": "!=",
    "≡": "==",
    "≤": "<=",
    "≥": ">=",
    "⋅": "*",
    # Typographic spaces (en, em, thin, hair, figure, ...)
    **{chr(code): " " for code in range(0x2000, 0x200B)},
    " ": " ",  # Ogham space mark
    "\u2028": " ",  # line separator
    "\u2029": " ",  # paragraph separator
    " ": " ",  # narrow no-break space
    " ": " ",  # medium mathematical space
    "　": " ",  # ideographic space
    # Zero-width characters
    "᠎": "",  # Mongolian vowel separator
    "​": "",  # zero-width space
    "‌": "",  # zero-width non-joiner
    "‍": "",  # zero-width joiner
    "⁠": "",  # word joiner
    "﻿": "",  # zero-width no-break space / BOM
    # Check and cross marks, checkboxes
    "✓": "*",
    "✔": "*",
    "✗": "x",
    "✘": "x",
    "☐": "[ ]",
    "☑": "[*]",
    "☒": "[x]",
    # Bullets and geometric shapes
    "‣": "*",
    "■": "#",
    "□": "#",
    "▪": "*",
    "○": "o",
    "●": "*",
    "◦": "o",
    # Superscript and subscript digits and signs
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁰": "0",
    "ⁱ": "i",
    **{chr(0x2074 + i): str(4 + i) for i in range(6)},
    "⁺": "+",
    "⁻": "-",
    "⁼": "=",
    "⁽": "(",
    "⁾": ")",
    "ⁿ": "n",
    **{chr(0x2080 + i): str(i) for i in range(10)},
    "₊": "+",
    "₋": "-",
    "₌": "=",
    "₍": "(",
    "₎": ")",
    # Vulgar fractions
    "¼": "1/4",
    "½": "1/2",
    "¾": "3/4",
    "⅐": "1/7",
    "⅑": "1/9",
    "⅒": "1/10",
    "⅓": "1/3",
    "⅔": "2/3",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅚": "5/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
    # Dashes, hyphens, primes
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "―": "--",
    "′": "'",
    "″": '"',
    "‴": "'''",
    # Latin letters without an NFKD decomposition
    "Æ": "AE",
    "æ": "ae",
    "Ð": "D",
    "Ø": "O",
    "Þ": "Th",
    "ß": "ss",
    "ð": "d",
    "ø": "o",
    "þ": "th",
    "Đ": "D",
    "đ": "d",
    "Ł": "L",
    "ł": "l",
    "Œ": "OE",
    "œ": "oe",
    # Box drawing
    **_box_drawing_map(),
}


@lru_cache(maxsize=4096)
def _fallback_for(char: str, supports: Callable[[str], bool]) -> str:
    """Best supported replacement for one unsupported character."""
    candidate = SUBSTITUTIONS.get(char)
    if candidate is not None and all(supports(c) for c in candidate):
        return candidate
    decomposed = unicodedata.normalize("NFKD", char)
    if decomposed != char:
        parts: list[str] = []
        resolved = True
        for piece in decomposed:
            mapped = SUBSTITUTIONS.get(piece)
            if supports(piece):
                parts.append(piece)
            elif mapped is not None and all(supports(c) for c in mapped):
                parts.append(mapped)
            elif unicodedata.category(piece) == "Mn":
                continue  # strip the diacritic, keep the base letter
            else:
                resolved = False
                break
        if resolved and parts:
            return "".join(parts)
    return "?"


def substitute_unsupported(
    text: str, supports: Callable[[str], bool]
) -> tuple[str, tuple[str, ...]]:
    """Replace characters `supports` rejects; return new text + originals."""
    pieces: list[str] = []
    replaced: list[str] = []
    for char in text:
        if char in _PASSTHROUGH or supports(char):
            pieces.append(char)
        else:
            pieces.append(_fallback_for(char, supports))
            replaced.append(char)
    if not replaced:
        return text, ()
    return "".join(pieces), tuple(replaced)
