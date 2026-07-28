"""Versioned brand definitions layered onto any document style.

A brand is defined once as an immutable, versioned object and applied on
top of a style preset at render time (see ``styles.apply_brand``). This
keeps every document a single source of truth away from a rebrand: change
the BrandKit, rebuild, and colors, fonts, and footer propagate.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

__all__ = [
    "BrandKit",
    "BUNDLED_FONTS",
    "resolve_font",
    "hex_to_rgb",
    "rgb_to_hex",
    "rgb_to_hsl",
    "hsl_to_rgb",
    "hsl_to_hex",
    "relative_luminance",
    "contrast_ratio",
    "darken_to_contrast",
]

#: Friendly bundled family names mapped to the concrete base-14 fonts.
BUNDLED_FONTS = {
    "Emboss Serif": "Times",
    "Emboss Sans": "Helvetica",
    "Emboss Mono": "Courier",
}


def resolve_font(name: str | None) -> str | None:
    """Map a bundled family name to its concrete font; pass others through."""
    if not name:
        return None
    return BUNDLED_FONTS.get(name, name)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """Convert an 'rrggbb' (or 'rgb') hex string to a 0-1 RGB triple."""
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise ValueError(f"invalid hex color: {value!r}")
    r, g, b = (int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return r, g, b


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert a 0-1 RGB triple to an 'rrggbb' hex string."""
    return "".join(f"{round(_clamp(c) * 255):02x}" for c in (r, g, b))


def rgb_to_hsl(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Convert a 0-1 RGB triple to (hue degrees, saturation, lightness)."""
    mx, mn = max(r, g, b), min(r, g, b)
    lightness = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, 0.0, lightness
    delta = mx - mn
    if lightness > 0.5:
        sat = delta / (2.0 - mx - mn)
    else:
        sat = delta / (mx + mn)
    if mx == r:
        hue = ((g - b) / delta) % 6.0
    elif mx == g:
        hue = (b - r) / delta + 2.0
    else:
        hue = (r - g) / delta + 4.0
    return hue * 60.0, sat, lightness


def hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[float, float, float]:
    """Convert (hue degrees, saturation, lightness) to a 0-1 RGB triple."""
    h = h % 360.0
    c = (1.0 - abs(2.0 * lightness - 1.0)) * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = lightness - c / 2.0
    if h < 60.0:
        rp, gp, bp = c, x, 0.0
    elif h < 120.0:
        rp, gp, bp = x, c, 0.0
    elif h < 180.0:
        rp, gp, bp = 0.0, c, x
    elif h < 240.0:
        rp, gp, bp = 0.0, x, c
    elif h < 300.0:
        rp, gp, bp = x, 0.0, c
    else:
        rp, gp, bp = c, 0.0, x
    return rp + m, gp + m, bp + m


def hsl_to_hex(h: float, s: float, lightness: float) -> str:
    """Convert an HSL triple straight to an 'rrggbb' hex string."""
    return rgb_to_hex(*hsl_to_rgb(h, s, lightness))


def relative_luminance(value: str) -> float:
    """WCAG relative luminance of an 'rrggbb' color."""
    channels = hex_to_rgb(value)
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(color_a: str, color_b: str) -> float:
    """WCAG contrast ratio between two 'rrggbb' colors."""
    lum_a, lum_b = relative_luminance(color_a), relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def darken_to_contrast(
    value: str, background: str = "ffffff", target: float = 4.5
) -> str:
    """Darken a color in HSL until it meets the target contrast on background."""
    if contrast_ratio(value, background) >= target:
        return value
    h, s, lightness = rgb_to_hsl(*hex_to_rgb(value))
    while lightness > 0.0:
        lightness = max(0.0, round(lightness - 0.02, 4))
        candidate = hsl_to_hex(h, s, lightness)
        if contrast_ratio(candidate, background) >= target:
            return candidate
    return "000000"


@dataclass(frozen=True)
class BrandKit:
    """An immutable, versioned brand applied on top of a style preset."""

    name: str
    version: str = "1.0"
    primary: str = "1f4e79"
    accent: str = "1f8a70"
    ink: str = "1a1a1a"
    muted: str = "6b7280"
    palette: tuple[str, ...] = ()
    heading_font: str | None = None
    body_font: str | None = None
    mono_font: str | None = None
    footer_text: str = ""
    logo: bytes | str | None = None

    def derived_palette(self, n: int = 5) -> list[str]:
        """Return a deterministic N-color series palette from primary+accent."""
        if n <= 0:
            return []
        if n == 1:
            return [self.primary]
        hp, sp, lp = rgb_to_hsl(*hex_to_rgb(self.primary))
        _, sa, la = rgb_to_hsl(*hex_to_rgb(self.accent))
        sat = _clamp((sp + sa) / 2.0, 0.35, 0.8)
        light = _clamp((lp + la) / 2.0, 0.32, 0.6)
        raw = [self.primary, self.accent]
        remaining = n - 2
        for i in range(remaining):
            hue = (hp + (i + 1) * (360.0 / (remaining + 1))) % 360.0
            raw.append(hsl_to_hex(hue, sat, light))
        return _distinct(raw)

    def series_palette(self, n: int = 5) -> list[str]:
        """Return the explicit palette (padded/derived) or the derived one."""
        if self.palette:
            colors = list(self.palette)
            if len(colors) >= n:
                return colors[:n]
            return colors + self.derived_palette(n)[len(colors) : n]
        return self.derived_palette(n)

    def to_dict(self) -> dict:
        """Serialize deterministically; logo bytes become base64 'logo_b64'."""
        data: dict = {
            "name": self.name,
            "version": self.version,
            "primary": self.primary,
            "accent": self.accent,
            "ink": self.ink,
            "muted": self.muted,
            "palette": list(self.palette),
            "heading_font": self.heading_font,
            "body_font": self.body_font,
            "mono_font": self.mono_font,
            "footer_text": self.footer_text,
        }
        if isinstance(self.logo, bytes):
            data["logo_b64"] = base64.b64encode(self.logo).decode("ascii")
        elif isinstance(self.logo, str):
            data["logo"] = self.logo
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "BrandKit":
        """Rebuild a BrandKit from a to_dict() mapping."""
        if data.get("logo_b64"):
            logo: bytes | str | None = base64.b64decode(data["logo_b64"])
        elif data.get("logo"):
            logo = data["logo"]
        else:
            logo = None
        return cls(
            name=data["name"],
            version=data.get("version", "1.0"),
            primary=data.get("primary", "1f4e79"),
            accent=data.get("accent", "1f8a70"),
            ink=data.get("ink", "1a1a1a"),
            muted=data.get("muted", "6b7280"),
            palette=tuple(data.get("palette", ())),
            heading_font=data.get("heading_font"),
            body_font=data.get("body_font"),
            mono_font=data.get("mono_font"),
            footer_text=data.get("footer_text", ""),
            logo=logo,
        )


def _distinct(colors: list[str]) -> list[str]:
    """Deduplicate a color list deterministically by nudging lightness down."""
    seen: set[str] = set()
    result: list[str] = []
    for color in colors:
        candidate = color
        for _ in range(48):
            if candidate not in seen:
                break
            h, s, lightness = rgb_to_hsl(*hex_to_rgb(candidate))
            candidate = hsl_to_hex(h, s, _clamp(lightness - 0.05, 0.05, 0.95))
        seen.add(candidate)
        result.append(candidate)
    return result
