"""Named color palettes, CMYK/spot color support, and theme system.

Named color palettes with Tailwind CSS-style naming. Lets LLMs
say ``"blue-600"`` instead of ``"2563eb"`` — fewer tokens, fewer mistakes,
and documents get a consistent palette instead of random hex strings.

CMYK colors can be expressed as ``"cmyk(0,0,0,100)"`` strings or as
``CmykColor`` dataclass instances. Spot colors (Pantone, etc.) are
supported via ``SpotColor`` with a CMYK fallback.

Usage:
    from emboss.colors import resolve_color, PALETTES, CmykColor, SpotColor

    hex_val = resolve_color("blue-600")   # -> "2563eb"
    hex_val = resolve_color("ff0000")     # -> "ff0000" (pass-through)

    cmyk = CmykColor(0.0, 1.0, 1.0, 0.0)      # pure red in CMYK
    spot = SpotColor("PANTONE 485 C", 0.0, 1.0, 0.95, 0.0)
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "resolve_color", "PALETTES", "ColorTheme",
    "CmykColor", "SpotColor", "rgb_to_cmyk", "parse_cmyk",
]

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


# ---------------------------------------------------------------------------
# CMYK and spot color support
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CmykColor:
    """A color in the CMYK color space.

    Component values are floats in 0.0-1.0 range.
    """

    c: float
    m: float
    y: float
    k: float

    def __post_init__(self) -> None:
        for name, val in [("c", self.c), ("m", self.m),
                          ("y", self.y), ("k", self.k)]:
            if not (0.0 <= val <= 1.0):
                raise ValueError(
                    f"CMYK component {name} must be 0.0-1.0, got {val}"
                )

    @property
    def components(self) -> tuple[float, float, float, float]:
        return (self.c, self.m, self.y, self.k)


@dataclass(frozen=True, slots=True)
class SpotColor:
    """A spot/named color (e.g. Pantone) with a CMYK fallback.

    PDF represents spot colors as Separation color spaces with an
    alternate space (DeviceCMYK) and a tint transform function.
    """

    name: str
    c: float
    m: float
    y: float
    k: float

    @property
    def fallback_cmyk(self) -> CmykColor:
        return CmykColor(self.c, self.m, self.y, self.k)


def rgb_to_cmyk(r: float, g: float, b: float) -> CmykColor:
    """Convert an RGB color (0.0-1.0 components) to CMYK.

    Uses a basic algorithmic conversion. For production print work,
    ICC profile-based conversion is preferred.
    """
    k = 1.0 - max(r, g, b)
    if k >= 1.0:
        return CmykColor(0.0, 0.0, 0.0, 1.0)
    c = (1.0 - r - k) / (1.0 - k)
    m = (1.0 - g - k) / (1.0 - k)
    y_val = (1.0 - b - k) / (1.0 - k)
    return CmykColor(c, m, y_val, k)


def hex_to_cmyk(hex_color: str) -> CmykColor:
    """Convert a 6-digit hex RGB color to CMYK."""
    text = hex_color.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"invalid hex color for CMYK conversion: {hex_color!r}")
    r = int(text[0:2], 16) / 255.0
    g = int(text[2:4], 16) / 255.0
    b = int(text[4:6], 16) / 255.0
    return rgb_to_cmyk(r, g, b)


_CMYK_RE = re.compile(
    r"^cmyk\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,"
    r"\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)$"
)


def parse_cmyk(value: str) -> CmykColor | None:
    """Parse a ``cmyk(c,m,y,k)`` string into a CmykColor.

    Component values may be 0-100 (percentage) or 0.0-1.0 (fraction).
    Values > 1.0 are treated as percentages and divided by 100.

    Returns None if the string is not a CMYK color specification.
    """
    match = _CMYK_RE.match(value.strip())
    if not match:
        return None
    components = [float(match.group(i)) for i in range(1, 5)]
    # Auto-detect percentage vs fraction: if any value > 1.0, treat
    # all as percentages.
    if any(v > 1.0 for v in components):
        components = [v / 100.0 for v in components]
    return CmykColor(*components)


def build_spot_color_resource(assembler, name: str,
                              c: float, m: float, y: float, k: float) -> str:
    """Register a spot color as a PDF Separation color space.

    Creates a ``/ColorSpace`` entry with a ``/Separation`` array that
    uses ``/DeviceCMYK`` as the alternate space and a tint-transform
    ``/Function`` that scales the CMYK fallback by the tint value.

    Returns the resource name (e.g. ``CS0``) to use in content stream
    operators like ``/CS0 cs 1 scn``.
    """
    from .pdf.objects import PdfArray, PdfDict, PdfName, PdfStream

    # Tint transform: a Type 4 PostScript calculator function.
    # Input: tint (0-1). Output: C M Y K scaled by tint.
    func_code = (
        f"{{ dup {c:.4f} mul exch dup {m:.4f} mul exch "
        f"dup {y:.4f} mul exch {k:.4f} mul }}"
    ).encode("ascii")
    func_dict = PdfDict()
    func_dict["FunctionType"] = 4
    func_dict["Domain"] = PdfArray([0.0, 1.0])
    func_dict["Range"] = PdfArray([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    func_stream = PdfStream(data=func_code, dictionary=func_dict, compress=False)
    func_ref = assembler.add(func_stream)

    cs_array = PdfArray([
        PdfName("Separation"),
        PdfName(name),
        PdfName("DeviceCMYK"),
        func_ref,
    ])
    cs_ref = assembler.add(cs_array)

    # Return a sanitized resource name derived from the spot color name.
    safe = re.sub(r"[^A-Za-z0-9]", "", name)
    resource_name = f"CS{safe}" if safe else "CS0"
    return resource_name, cs_ref
