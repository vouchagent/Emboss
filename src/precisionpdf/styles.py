"""Cascading style system for print.

Styles carry only the properties that are explicitly set; unset values
fall through to the parent. That is what allows a document-level theme
to define everything and individual elements to override one property
without restating the rest.

The presets encode design decisions (type scale, leading, spacing,
table rules) so that output looks authored without the caller choosing
a single measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Literal

__all__ = ["Style", "StyleSheet", "resolve_preset", "PRESETS"]

Alignment = Literal["left", "center", "right", "justify"]


@dataclass(frozen=True)
class Style:
    """A set of print style properties. `None` means "inherit"."""

    font_family: str | None = None
    font_size: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = None
    align: Alignment | None = None
    line_height: float | None = None
    space_before: float | None = None
    space_after: float | None = None
    indent_first: float | None = None
    indent_left: float | None = None
    indent_right: float | None = None
    keep_with_next: bool | None = None
    keep_together: bool | None = None
    page_break_before: bool | None = None
    hyphenate: bool | None = None

    def inherit_from(self, parent: "Style") -> "Style":
        """Return a style where unset values are taken from `parent`."""
        merged = {}
        for f in fields(self):
            own = getattr(self, f.name)
            merged[f.name] = own if own is not None else getattr(parent, f.name)
        return Style(**merged)

    def merge(self, override: "Style | None") -> "Style":
        """Apply an override style on top of this one."""
        if override is None:
            return self
        return override.inherit_from(self)

    def with_(self, **kw) -> "Style":
        return replace(self, **kw)

    # Resolved accessors: these assume the style has been fully cascaded
    # from a complete base, so they must never be None.

    def require(self, name: str):
        value = getattr(self, name)
        if value is None:
            raise ValueError(
                f"style property {name!r} was never resolved; "
                "cascade from a complete base style"
            )
        return value


#: A complete base style. Every property is set, so any cascade
#: terminating here is guaranteed to be fully resolved.
BASE_STYLE = Style(
    font_family="Helvetica",
    font_size=10.5,
    bold=False,
    italic=False,
    color="1a1a1a",
    align="left",
    line_height=1.42,
    space_before=0.0,
    space_after=7.0,
    indent_first=0.0,
    indent_left=0.0,
    indent_right=0.0,
    keep_with_next=False,
    keep_together=False,
    page_break_before=False,
    hyphenate=False,
)


@dataclass(frozen=True)
class StyleSheet:
    """Named styles for each semantic element type."""

    name: str
    body: Style
    h1: Style
    h2: Style
    h3: Style
    h4: Style
    h5: Style
    h6: Style
    list_item: Style
    table_header: Style
    table_cell: Style
    caption: Style
    header_footer: Style
    # Visual details that are not per-block text styles.
    table_rule_width: float = 0.5
    table_rule_color: str = "c8ccd0"
    table_header_rule_width: float = 1.0
    table_header_rule_color: str = "44403c"
    table_cell_padding_x: float = 6.0
    table_cell_padding_y: float = 4.5
    table_stripe_color: str = "f5f5f4"
    rule_color: str = "d6d3d1"

    def for_heading(self, level: int) -> Style:
        return getattr(self, f"h{level}")

    def resolved(self, style: Style, override: Style | None = None) -> Style:
        """Cascade: BASE -> body -> element style -> per-block override."""
        base = BASE_STYLE.merge(self.body)
        resolved = base.merge(style)
        return resolved.merge(override)


def _sheet(
    name: str,
    body_font: str,
    heading_font: str,
    body_size: float,
    align: Alignment,
    line_height: float,
    scale: tuple,
    color: str = "1a1a1a",
    heading_color: str = "111111",
    **extra,
) -> StyleSheet:
    """Build a stylesheet from a type scale.

    `scale` gives heading sizes as multipliers of the body size, which is
    what keeps headings visually related rather than arbitrary.
    """
    h_space_before = (18.0, 15.0, 12.0, 10.0, 9.0, 8.0)
    h_space_after = (7.0, 6.0, 5.0, 4.0, 4.0, 4.0)
    headings = {}
    for i, factor in enumerate(scale, start=1):
        headings[f"h{i}"] = Style(
            font_family=heading_font,
            font_size=round(body_size * factor, 2),
            bold=True,
            color=heading_color,
            align="left",
            line_height=1.22,
            space_before=h_space_before[i - 1],
            space_after=h_space_after[i - 1],
            keep_with_next=True,
            hyphenate=False,
        )

    return StyleSheet(
        name=name,
        body=Style(
            font_family=body_font,
            font_size=body_size,
            color=color,
            align=align,
            line_height=line_height,
            space_after=round(body_size * 0.62, 2),
            hyphenate=(align == "justify"),
        ),
        list_item=Style(
            align="left",
            space_after=round(body_size * 0.3, 2),
            indent_left=16.0,
            hyphenate=False,
        ),
        table_header=Style(
            font_family=heading_font,
            font_size=round(body_size * 0.88, 2),
            bold=True,
            align="left",
            line_height=1.25,
            color=heading_color,
            hyphenate=False,
        ),
        table_cell=Style(
            font_family=body_font,
            font_size=round(body_size * 0.9, 2),
            align="left",
            line_height=1.3,
            hyphenate=False,
        ),
        caption=Style(
            font_family=body_font,
            font_size=round(body_size * 0.82, 2),
            italic=True,
            color="57534e",
            align="left",
            space_before=4.0,
            space_after=10.0,
            hyphenate=False,
        ),
        header_footer=Style(
            font_family=body_font,
            font_size=8.5,
            color="78716c",
            align="left",
            line_height=1.2,
            hyphenate=False,
        ),
        **headings,
        **extra,
    )


PRESETS: dict = {
    # Contracts, pleadings, briefs: serif, justified, generous leading.
    "legal": _sheet(
        name="legal",
        body_font="Times",
        heading_font="Times",
        body_size=11.5,
        align="justify",
        line_height=1.5,
        scale=(1.35, 1.18, 1.05, 1.0, 1.0, 1.0),
        table_rule_color="d4d0c8",
        table_header_rule_color="2b2b2b",
    ),
    # Reports and filings: sans, left-aligned, tight tabular feel.
    "finance": _sheet(
        name="finance",
        body_font="Helvetica",
        heading_font="Helvetica",
        body_size=10.0,
        align="left",
        line_height=1.4,
        scale=(1.6, 1.32, 1.14, 1.0, 1.0, 1.0),
        heading_color="0f172a",
        table_rule_color="cbd5e1",
        table_header_rule_color="0f172a",
        table_stripe_color="f8fafc",
    ),
    # Papers and dissertations: serif, justified, classic proportions.
    "academic": _sheet(
        name="academic",
        body_font="Times",
        heading_font="Times",
        body_size=11.0,
        align="justify",
        line_height=1.48,
        scale=(1.45, 1.25, 1.1, 1.0, 1.0, 1.0),
    ),
    # Memos, policies, manuals: sans, readable, roomy.
    "corporate": _sheet(
        name="corporate",
        body_font="Helvetica",
        heading_font="Helvetica",
        body_size=10.5,
        align="left",
        line_height=1.45,
        scale=(1.55, 1.3, 1.12, 1.0, 1.0, 1.0),
        heading_color="1c1917",
    ),
    # Data-heavy exports: compact, minimal ornament.
    "minimal": _sheet(
        name="minimal",
        body_font="Helvetica",
        heading_font="Helvetica",
        body_size=9.5,
        align="left",
        line_height=1.35,
        scale=(1.4, 1.2, 1.08, 1.0, 1.0, 1.0),
        table_rule_width=0.4,
        table_stripe_color="fafaf9",
    ),
}


def resolve_preset(name: str) -> StyleSheet:
    """Look up a built-in stylesheet by name."""
    try:
        return PRESETS[name]
    except KeyError:
        available = ", ".join(sorted(PRESETS))
        raise KeyError(
            f"unknown style preset {name!r}; available: {available}"
        ) from None
