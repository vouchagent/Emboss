"""Bundled OFL font set: an embedded serif, sans, and mono family."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from .typography.font_metrics import FontRegistry

__all__ = ["BUNDLED_FAMILIES", "bundled_font_path", "register_bundled_fonts"]

# Canonical family name -> (bold, italic) -> bundled filename. The font
# binaries are unmodified upstream releases (SIL OFL 1.1; see the
# LICENSE-*.txt files next to them and the repository NOTICE file).
BUNDLED_FAMILIES: dict[str, dict[tuple[bool, bool], str]] = {
    "Source Serif 4": {
        (False, False): "SourceSerif4-Regular.ttf",
        (True, False): "SourceSerif4-Bold.ttf",
        (False, True): "SourceSerif4-It.ttf",
        (True, True): "SourceSerif4-BoldIt.ttf",
    },
    "Source Sans 3": {
        (False, False): "SourceSans3-Regular.ttf",
        (True, False): "SourceSans3-Bold.ttf",
        (False, True): "SourceSans3-It.ttf",
        (True, True): "SourceSans3-BoldIt.ttf",
    },
    "Source Code Pro": {
        (False, False): "SourceCodePro-Regular.ttf",
        (True, False): "SourceCodePro-Bold.ttf",
    },
}

# Friendly Emboss-branded aliases resolving to the canonical families.
FAMILY_ALIASES: dict[str, str] = {
    "emboss serif": "Source Serif 4",
    "emboss sans": "Source Sans 3",
    "emboss mono": "Source Code Pro",
}

_LICENSE_FILES = (
    "LICENSE-SourceSerif4.txt",
    "LICENSE-SourceSans3.txt",
    "LICENSE-SourceCodePro.txt",
)


def _font_dir() -> Path:
    """Return the on-disk directory holding the bundled font files."""
    try:
        candidate = Path(str(resources.files("emboss") / "fonts"))
        if candidate.is_dir():
            return candidate
    except Exception:
        pass
    return Path(__file__).resolve().parent / "fonts"


def _canonical(family: str) -> str:
    """Map a requested family name to its canonical bundled family."""
    low = family.strip().lower()
    if low in FAMILY_ALIASES:
        return FAMILY_ALIASES[low]
    for name in BUNDLED_FAMILIES:
        if name.lower() == low:
            return name
    raise KeyError(f"{family!r} is not a bundled font family")


def bundled_font_path(family: str, bold: bool = False, italic: bool = False) -> Path:
    """Path to the bundled font file for a family/style combination."""
    canonical = _canonical(family)
    styles = BUNDLED_FAMILIES[canonical]
    filename = (
        styles.get((bold, italic))
        or styles.get((bold, False))
        or styles[(False, False)]
    )
    return _font_dir() / filename


def register_bundled_fonts(registry: FontRegistry | None = None) -> FontRegistry:
    """Register the bundled families (and aliases) with a FontRegistry."""
    if registry is None:
        registry = FontRegistry()
    directory = _font_dir()
    for canonical, styles in sorted(BUNDLED_FAMILIES.items()):
        names = [canonical] + sorted(
            alias for alias, target in FAMILY_ALIASES.items() if target == canonical
        )
        for bold in (False, True):
            for italic in (False, True):
                filename = (
                    styles.get((bold, italic))
                    or styles.get((bold, False))
                    or styles[(False, False)]
                )
                path = directory / filename
                if not path.is_file():
                    continue
                for name in names:
                    registry.register(name, path, bold=bold, italic=italic)
    return registry
