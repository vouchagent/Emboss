"""Named color palettes and theme system.

Named color palettes with Tailwind CSS-style naming. Lets LLMs
say ``"blue-600"`` instead of ``"2563eb"`` — fewer tokens, fewer mistakes,
and documents get a consistent palette instead of random hex strings.

Usage:
    from precisionpdf.colors import resolve_color, PALETTES

    hex_val = resolve_color("blue-600")   # -> "2563eb"
    hex_val = resolve_color("ff0000")     # -> "ff0000" (pass-through)
"""

from __future__ import annotations

__all__ = ["resolve_color", "PALETTES", "ColorTheme"]

PALETTES: dict[str, dict[str, str]] = {
    "slate": {
        "50": "f8fafc", "100": "f1f5f9", "200": "e2e8f0", "300": "cbd5e1",
        "400": "94a3b8", "500": "64748b", "600": "475569", "700": "334155",
        "800": "1e293b", "900": "0f172a", "950": "020617",
    },
    "gray": {
        "50": "f9fafb", "100": "f3f4f6", "200": "e5e7eb", "300": "d1d5db",
        "400": "9ca3af", "500": "6b7280", "600": "4b5563", "700": "374151",
        "800": "1f2937", "900": "111827", "950": "030712",
    },
    "red": {
        "50": "fef2f2", "100": "fee2e2", "200": "fecaca", "300": "fca5a5",
        "400": "f87171", "500": "ef4444", "600": "dc2626", "700": "b91c1c",
        "800": "991b1b", "900": "7f1d1d", "950": "450a0a",
    },
    "orange": {
        "50": "fff7ed", "100": "ffedd5", "200": "fed7aa", "300": "fdba74",
        "400": "fb923c", "500": "f97316", "600": "ea580c", "700": "c2410c",
        "800": "9a3412", "900": "7c2d12", "950": "431407",
    },
    "amber": {
        "50": "fffbeb", "100": "fef3c7", "200": "fde68a", "300": "fcd34d",
        "400": "fbbf24", "500": "f59e0b", "600": "d97706", "700": "b45309",
        "800": "92400e", "900": "78350f", "950": "451a03",
    },
    "green": {
        "50": "f0fdf4", "100": "dcfce7", "200": "bbf7d0", "300": "86efac",
        "400": "4ade80", "500": "22c55e", "600": "16a34a", "700": "15803d",
        "800": "166534", "900": "14532d", "950": "052e16",
    },
    "blue": {
        "50": "eff6ff", "100": "dbeafe", "200": "bfdbfe", "300": "93c5fd",
        "400": "60a5fa", "500": "3b82f6", "600": "2563eb", "700": "1d4ed8",
        "800": "1e40af", "900": "1e3a8a", "950": "172554",
    },
    "indigo": {
        "50": "eef2ff", "100": "e0e7ff", "200": "c7d2fe", "300": "a5b4fc",
        "400": "818cf8", "500": "6366f1", "600": "4f46e5", "700": "4338ca",
        "800": "3730a3", "900": "312e81", "950": "1e1b4b",
    },
    "purple": {
        "50": "faf5ff", "100": "f3e8ff", "200": "e9d5ff", "300": "d8b4fe",
        "400": "c084fc", "500": "a855f7", "600": "9333ea", "700": "7e22ce",
        "800": "6b21a8", "900": "581c87", "950": "3b0764",
    },
    "pink": {
        "50": "fdf2f8", "100": "fce7f3", "200": "fbcfe8", "300": "f9a8d4",
        "400": "f472b6", "500": "ec4899", "600": "db2777", "700": "be185d",
        "800": "9d174d", "900": "831843", "950": "500724",
    },
    "teal": {
        "50": "f0fdfa", "100": "ccfbf1", "200": "99f6e4", "300": "5eead4",
        "400": "2dd4bf", "500": "14b8a6", "600": "0d9488", "700": "0f766e",
        "800": "115e59", "900": "134e4a", "950": "042f2e",
    },
}

# Semantic aliases
_SEMANTIC: dict[str, str] = {
    "primary": "blue-600",
    "secondary": "slate-500",
    "success": "green-600",
    "warning": "amber-500",
    "danger": "red-600",
    "info": "teal-600",
    "muted": "gray-400",
    "dark": "gray-900",
    "light": "gray-100",
    "accent": "indigo-600",
}

import re

_HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_NAMED_RE = re.compile(r"^([a-z]+)-(\d{2,3})$")


def resolve_color(value: str) -> str:
    """Resolve a named color to a hex string.

    Accepts:
      - A 6-digit hex string (pass-through): ``"2563eb"``
      - A named shade: ``"blue-600"`` -> ``"2563eb"``
      - A semantic name: ``"primary"`` -> ``"2563eb"``

    Returns the 6-digit hex color without ``#``.
    """
    if _HEX_RE.match(value):
        return value.lower()

    if value in _SEMANTIC:
        return resolve_color(_SEMANTIC[value])

    match = _NAMED_RE.match(value)
    if match:
        family, shade = match.group(1), match.group(2)
        palette = PALETTES.get(family)
        if palette and shade in palette:
            return palette[shade]

    raise ValueError(
        f"unknown color {value!r}; use a 6-digit hex, "
        f"a named shade (e.g. 'blue-600'), or a semantic name "
        f"(e.g. 'primary')"
    )


class ColorTheme:
    """A reusable set of named colors for a document.

    Allows defining document-level color names that resolve to hex values:

        theme = ColorTheme(brand="1e40af", highlight="f59e0b")
        theme.resolve("brand")  # -> "1e40af"
        theme.resolve("blue-600")  # -> "2563eb" (falls through)
    """

    def __init__(self, **colors: str) -> None:
        self._colors: dict[str, str] = {}
        for name, value in colors.items():
            self._colors[name] = resolve_color(value)

    def resolve(self, value: str) -> str:
        if value in self._colors:
            return self._colors[value]
        return resolve_color(value)

    def __contains__(self, name: str) -> bool:
        return name in self._colors
