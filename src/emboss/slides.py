"""Slide and presentation layout support.

Two APIs live here. `slide_document` is the original thin preset
(landscape page, large type) kept for backward compatibility. `SlideDeck`
is the full deck builder: designed slide layouts (title, section divider,
content, bullets, stats, chart, quote, code, closing), four complete
color themes, and fit-to-slide validation so no slide ever spills onto a
continuation page.

Usage::

    from emboss.slides import SlideDeck

    deck = SlideDeck("Q3 Review", presenter="Ana Ruiz", date="Oct 2026")
    deck.title_slide(subtitle="Board update")
    deck.section_divider("Results")
    deck.stat_slide("Key metrics", [("ARR", "$12.4M", "+18%")])
    deck.save("deck.pdf")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal, Sequence

from .spec import (
    BulletList,
    Callout,
    Chart,
    CodeBlock,
    BlockQuote,
    Document,
    HeaderFooter,
    Heading,
    MathBlock,
    NumberedList,
    PageBreak,
    PageSpec,
    Paragraph,
    SvgBlock,
    Table,
    TableCell,
    TextRun,
)
from .styles import Style, StyleSheet

__all__ = [
    "SlideDeck",
    "SlideTheme",
    "THEMES",
    "resolve_theme",
    "relative_luminance",
    "contrast_ratio",
    "slide_document",
    "SlideConfig",
    "SLIDE_16_9",
    "SLIDE_4_3",
    "DECK_16_9",
    "DECK_4_3",
]

SLIDE_16_9 = PageSpec(
    width=720.0,
    height=405.0,
    margin_top=36.0,
    margin_right=48.0,
    margin_bottom=36.0,
    margin_left=48.0,
)

SLIDE_4_3 = PageSpec(
    width=720.0,
    height=540.0,
    margin_top=40.0,
    margin_right=48.0,
    margin_bottom=40.0,
    margin_left=48.0,
)

#: Deck page specs: consistent 36pt margins on every side.
DECK_16_9 = PageSpec(
    width=720.0,
    height=405.0,
    margin_top=36.0,
    margin_right=36.0,
    margin_bottom=36.0,
    margin_left=36.0,
)

DECK_4_3 = PageSpec(
    width=720.0,
    height=540.0,
    margin_top=36.0,
    margin_right=36.0,
    margin_bottom=36.0,
    margin_left=36.0,
)


# -- color science helpers --


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of an 'rrggbb' color."""
    text = hex_color.lstrip("#")
    channels = [int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(color_a: str, color_b: str) -> float:
    """WCAG contrast ratio between two 'rrggbb' colors."""
    lum_a, lum_b = relative_luminance(color_a), relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


# -- deck themes --


@dataclass(frozen=True)
class SlideTheme:
    """A complete slide color system."""

    name: str
    ink: str  # body text on the white page
    title: str  # slide titles and headings
    muted: str  # captions, footers, stat labels
    accent: str  # decorative bars, bullets, panel edges
    accent_ink: str  # accent family, dark enough for large text
    panel: str  # divider / brand panel fill
    on_panel: str  # text placed on the panel
    panel_edge: str  # accent stripe on panels
    tint: str  # soft fill for takeaways and table stripes
    delta_up: str  # positive stat deltas
    delta_down: str  # negative stat deltas
    chart_palette: tuple  # deterministic chart series colors


THEMES: dict = {
    # Deep navy with a gold accent on warm white: the classic board deck.
    "boardroom": SlideTheme(
        name="boardroom",
        ink="232b38",
        title="13273f",
        muted="6d7684",
        accent="c9a227",
        accent_ink="8a6d14",
        panel="13273f",
        on_panel="fdfcf8",
        panel_edge="c9a227",
        tint="f6f1e1",
        delta_up="2e7d4f",
        delta_down="b3402e",
        chart_palette=("13273f", "c9a227", "4a6785", "8a6d14", "97a3b6"),
    ),
    # Dusk blue and coral on white: warm, editorial, optimistic.
    "horizon": SlideTheme(
        name="horizon",
        ink="2c3440",
        title="2f5d8a",
        muted="72808f",
        accent="e0653a",
        accent_ink="b34a24",
        panel="2f5d8a",
        on_panel="ffffff",
        panel_edge="e0653a",
        tint="fdeee7",
        delta_up="247a52",
        delta_down="bb3e2a",
        chart_palette=("2f5d8a", "e0653a", "6f94b8", "b34a24", "4a4f57"),
    ),
    # Near-black panels with an electric blue accent: technical, precise.
    "carbon": SlideTheme(
        name="carbon",
        ink="23262d",
        title="16181d",
        muted="6d7280",
        accent="3fa7d6",
        accent_ink="17638d",
        panel="16181d",
        on_panel="f2f3f5",
        panel_edge="3fa7d6",
        tint="e9f4fa",
        delta_up="2a7d55",
        delta_down="b23a35",
        chart_palette=("3fa7d6", "16181d", "17638d", "7bc4e3", "4b5563"),
    ),
    # Forest and spring green on white: calm, grounded, sustainable.
    "meadow": SlideTheme(
        name="meadow",
        ink="26302a",
        title="24513a",
        muted="68766d",
        accent="7fb069",
        accent_ink="2e6b47",
        panel="24513a",
        on_panel="ffffff",
        panel_edge="7fb069",
        tint="eef5ea",
        delta_up="2e6b47",
        delta_down="a9432f",
        chart_palette=("24513a", "7fb069", "2e6b47", "a9bd94", "56635b"),
    ),
}

_THEME_ALIASES: dict = {
    "default": "boardroom",
    "dark": "carbon",
    "light": "horizon",
    "minimal": "horizon",
}


def resolve_theme(theme) -> SlideTheme:
    """Resolve a theme name (or SlideTheme) to a SlideTheme."""
    if isinstance(theme, SlideTheme):
        return theme
    name = _THEME_ALIASES.get(theme, theme)
    try:
        return THEMES[name]
    except KeyError:
        available = ", ".join(sorted(THEMES))
        raise KeyError(
            f"unknown slide theme {theme!r}; available: {available}"
        ) from None


# -- deck stylesheet --

_BODY_SIZE = 18.0
_STAT_VALUE_SIZE = round(_BODY_SIZE * 2.2, 2)
_ACCENT_BAR_WIDTH = 76.0
_ACCENT_BAR_HEIGHT = 4.0


def _deck_sheet(theme: SlideTheme) -> StyleSheet:
    """Build the deck stylesheet from a theme's color system."""
    scale = (2.44, 1.5, 1.17, 1.0, 1.0, 1.0)
    line_heights = (1.08, 1.15, 1.2, 1.25, 1.25, 1.25)
    space_after = (10.0, 4.0, 4.0, 4.0, 4.0, 4.0)
    headings = {}
    for i, factor in enumerate(scale, start=1):
        headings[f"h{i}"] = Style(
            font_family="Helvetica",
            font_size=round(_BODY_SIZE * factor, 2),
            bold=True,
            color=theme.title,
            align="left",
            line_height=line_heights[i - 1],
            space_before=8.0,
            space_after=space_after[i - 1],
            keep_with_next=True,
            hyphenate=False,
        )

    return StyleSheet(
        name=f"deck-{theme.name}",
        body=Style(
            font_family="Helvetica",
            font_size=_BODY_SIZE,
            color=theme.ink,
            align="left",
            line_height=1.45,
            space_after=10.0,
            hyphenate=False,
        ),
        list_item=Style(
            align="left",
            font_size=_BODY_SIZE,
            space_after=8.0,
            indent_left=24.0,
            line_height=1.4,
            hyphenate=False,
        ),
        table_header=Style(
            font_family="Helvetica",
            font_size=15.0,
            bold=True,
            align="left",
            line_height=1.3,
            color=theme.title,
            hyphenate=False,
        ),
        table_cell=Style(
            font_family="Helvetica",
            font_size=15.0,
            align="left",
            line_height=1.3,
            hyphenate=False,
        ),
        caption=Style(
            font_family="Helvetica",
            font_size=12.5,
            italic=True,
            color=theme.muted,
            align="left",
            space_before=4.0,
            space_after=8.0,
            hyphenate=False,
        ),
        header_footer=Style(
            font_family="Helvetica",
            font_size=9.0,
            color=theme.muted,
            align="left",
            line_height=1.2,
            hyphenate=False,
        ),
        **headings,
        # Deck tables carry no hairline rules by design: structure comes
        # from zebra stripes and bold colored header text. Painting every
        # rule in page white also makes the invisible layout grids used by
        # two-column and stat slides genuinely invisible.
        table_rule_width=0.5,
        table_rule_color="ffffff",
        table_header_rule_width=0.75,
        table_header_rule_color="ffffff",
        table_cell_padding_x=8.0,
        table_cell_padding_y=6.0,
        table_stripe_color=theme.tint,
        rule_color=theme.accent,
    )


# -- composition helpers --


def _letterspaced(text: str) -> str:
    """Uppercase and letterspace a label with explicit spacing."""
    words = re.split(r"\s+", text.strip().upper())
    return "   ".join(" ".join(word) for word in words if word)


def _svg_rect(
    width: float,
    height: float,
    color: str,
    accent: str | None = None,
    accent_width: float = 0.0,
) -> str:
    """Deterministic SVG source for a solid bar with an optional accent cap."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" '
        f'height="{height:g}">',
        f'<rect x="0" y="0" width="{width:g}" height="{height:g}" fill="#{color}"/>',
    ]
    if accent and accent_width > 0.0:
        parts.append(
            f'<rect x="0" y="0" width="{accent_width:g}" height="{height:g}" '
            f'fill="#{accent}"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _accent_bar(
    color: str,
    width: float = _ACCENT_BAR_WIDTH,
    height: float = _ACCENT_BAR_HEIGHT,
    align: Literal["left", "center", "right"] = "left",
) -> SvgBlock:
    """A short thick accent bar used to underline slide titles."""
    return SvgBlock(
        source=_svg_rect(width, height, color),
        width=width,
        height=height,
        align=align,
        alt_text="",
    )


@dataclass
class _Slide:
    """One authored slide: a display name plus its block stack."""

    name: str
    blocks: list


class SlideDeck:
    """Builds a presentation deck from designed slide layouts."""

    MIN_SCALE = 0.8
    SCALE_STEP = 0.95

    def __init__(
        self,
        title: str,
        presenter: str = "",
        date: str = "",
        theme: str = "boardroom",
        aspect_ratio: str = "16:9",
    ) -> None:
        self.title = title
        self.presenter = presenter
        self.date = date
        self.theme = resolve_theme(theme)
        self.aspect_ratio = aspect_ratio
        self._page = DECK_4_3 if aspect_ratio == "4:3" else DECK_16_9
        self._sheet = _deck_sheet(self.theme)
        self._slides: list = []
        self._divider_count = 0
        self._title_first = False
        self._measurer = None

    # -- slide layouts --

    def title_slide(self, subtitle: str = "") -> "SlideDeck":
        """The opening slide: title, accent bar, byline, brand band."""
        t = self.theme
        blocks: list = [Heading(self.title, level=1)]
        blocks.append(_accent_bar(t.accent, width=96.0, height=5.0))
        if subtitle:
            blocks.append(
                Paragraph(
                    subtitle,
                    style=Style(
                        font_size=20.0,
                        color=t.muted,
                        line_height=1.35,
                        space_before=2.0,
                        space_after=8.0,
                    ),
                )
            )
        blocks.append(self._spacer(self._page.content_height * 0.2))
        byline = " · ".join(part for part in (self.presenter, self.date) if part)
        if byline:
            blocks.append(
                Paragraph(
                    byline,
                    style=Style(font_size=13.0, color=t.muted, space_after=8.0),
                )
            )
        band_width = self._page.content_width
        blocks.append(
            SvgBlock(
                source=_svg_rect(
                    band_width, 5.0, t.panel, accent=t.accent, accent_width=96.0
                ),
                width=band_width,
                height=5.0,
                align="left",
                alt_text="",
            )
        )
        if not self._slides:
            self._title_first = True
        return self._add_slide(self.title, blocks)

    def section_divider(self, title: str) -> "SlideDeck":
        """A section break: numbered kicker over a full-width theme panel."""
        t = self.theme
        self._divider_count += 1
        kicker = Paragraph(
            _letterspaced(f"Section {self._divider_count:02d}"),
            style=Style(
                font_size=11.0,
                bold=True,
                color=t.accent_ink,
                space_after=12.0,
            ),
        )
        panel = Callout(
            content=[TextRun(title, font_size=34.0, bold=True, color=t.on_panel)],
            icon="",
            background=t.panel,
            border_color=t.panel_edge,
            style=Style(
                font_size=34.0,
                line_height=2.1,
                color=t.on_panel,
                hyphenate=False,
            ),
        )
        spacer = self._spacer(self._page.content_height * 0.2)
        return self._add_slide(title, [spacer, kicker, panel])

    def content_slide(self, title: str, *blocks, layout: str = "single") -> "SlideDeck":
        """A titled slide of arbitrary blocks, single or two-column."""
        items = [self._normalize(block) for block in blocks]
        if layout == "two-column":
            body: list = [self._two_column_table(items)]
        elif layout == "single":
            body = items
        else:
            raise ValueError(
                f"unknown layout {layout!r}; expected 'single' or 'two-column'"
            )
        return self._add_slide(title, self._title_zone(title) + body)

    def bullet_slide(
        self, title: str, bullets: Sequence, takeaway: str = ""
    ) -> "SlideDeck":
        """A titled bullet list with an optional takeaway callout."""
        body: list = [BulletList(items=list(bullets))]
        if takeaway:
            body.append(self._takeaway(takeaway))
        return self._add_slide(title, self._title_zone(title) + body)

    def stat_slide(self, title: str, stats: Sequence) -> "SlideDeck":
        """Large stat values over letterspaced labels, side by side."""
        t = self.theme
        values_row, labels_row, deltas_row = [], [], []
        has_delta = False
        for stat in stats:
            label, value = stat[0], stat[1]
            delta = stat[2] if len(stat) > 2 else None
            values_row.append(
                TableCell(
                    content=[
                        TextRun(
                            str(value),
                            bold=True,
                            font_size=_STAT_VALUE_SIZE,
                            color=t.accent_ink,
                        )
                    ],
                    align="center",
                )
            )
            labels_row.append(
                TableCell(
                    content=[
                        TextRun(
                            _letterspaced(str(label)),
                            font_size=10.5,
                            color=t.muted,
                        )
                    ],
                    align="center",
                )
            )
            if delta:
                has_delta = True
                down = str(delta).lstrip().startswith(("-", "−", "▼"))
                color = t.delta_down if down else t.delta_up
                deltas_row.append(
                    TableCell(
                        content=[
                            TextRun(str(delta), bold=True, font_size=12.5, color=color)
                        ],
                        align="center",
                    )
                )
            else:
                deltas_row.append(TableCell(content="", align="center"))
        rows = [values_row, labels_row]
        if has_delta:
            rows.append(deltas_row)
        table = Table(
            headers=[],
            rows=rows,
            column_widths=[1.0] * max(len(stats), 1),
            stripe=False,
        )
        blocks = self._title_zone(title) + [self._spacer(20.0), table]
        return self._add_slide(title, blocks)

    def chart_slide(
        self, title: str, chart_element: Chart, takeaway: str = ""
    ) -> "SlideDeck":
        """A full-width themed chart sized to the slide body."""
        t = self.theme
        surround: list = self._title_zone(title)
        trailer: list = [self._takeaway(takeaway)] if takeaway else []
        used = self._stack_height(surround + trailer)
        # 16pt covers the chart's own space before/after; 4pt safety.
        chart_height = self._page.content_height - used - 16.0 - 4.0
        chart = replace(
            chart_element,
            colors=(
                list(chart_element.colors)
                if chart_element.colors
                else list(t.chart_palette)
            ),
            width=self._page.content_width,
            height=round(max(chart_height, 100.0), 2),
        )
        return self._add_slide(title, surround + [chart] + trailer)

    def quote_slide(self, text: str, attribution: str = "") -> "SlideDeck":
        """A large attributed pull quote."""
        t = self.theme
        quote = BlockQuote(
            content=[TextRun(f"“{text}”", font_size=26.0)],
            attribution=attribution or None,
            style=Style(
                font_size=26.0,
                line_height=1.5,
                color=t.title,
                hyphenate=False,
            ),
        )
        spacer = self._spacer(self._page.content_height * 0.16)
        name = text if len(text) <= 40 else text[:37] + "..."
        return self._add_slide(name, [spacer, _accent_bar(t.accent), quote])

    def code_slide(self, title: str, code: str, language: str = "text") -> "SlideDeck":
        """A titled syntax-highlighted code panel."""
        block = CodeBlock(
            code=code,
            language=language,
            line_numbers=True,
            style=Style(font_size=15.0),
        )
        return self._add_slide(title, self._title_zone(title) + [block])

    def closing_slide(self, message: str, contact: str = "") -> "SlideDeck":
        """The final slide: centered message, accent bar, contact line."""
        t = self.theme
        blocks: list = [
            self._spacer(self._page.content_height * 0.28),
            Paragraph(
                message,
                style=Style(
                    font_size=30.0,
                    bold=True,
                    color=t.title,
                    align="center",
                    line_height=1.25,
                    space_after=8.0,
                ),
            ),
            _accent_bar(t.accent, width=56.0, align="center"),
        ]
        if contact:
            blocks.append(
                Paragraph(
                    contact,
                    style=Style(
                        font_size=13.0,
                        color=t.muted,
                        align="center",
                        space_before=6.0,
                    ),
                )
            )
        return self._add_slide(message, blocks)

    # -- build & output --

    def build(self) -> Document:
        """Assemble, fit-check, and return the deck as a Document."""
        from .layout.engine import LayoutEngine
        from .typography.hyphenation import Hyphenator

        t = self.theme
        footer = HeaderFooter(
            left=self.title,
            right="{page} / {pages}",
            font_size=9.0,
            color=t.muted,
            first_page=not self._title_first,
        )
        document = Document(
            title=self.title,
            author=self.presenter,
            style=self._sheet,
            page=self._page,
            footer=footer,
            toc=False,
        )
        engine = LayoutEngine(
            document.fonts,
            self._sheet,
            hyphenator=Hyphenator(language=document.language),
        )
        width = self._page.content_width
        limit = self._page.content_height
        slides = list(self._slides)
        if slides and self._needs_masthead(slides[0]):
            slides[0] = _Slide(
                name=slides[0].name,
                blocks=[self._masthead()] + slides[0].blocks,
            )
        for index, slide in enumerate(slides):
            blocks = self._fit(engine, slide, width, limit, index)
            if index:
                document.add(PageBreak())
            document.extend(blocks)
        return document

    def render(self) -> bytes:
        """Render the deck to PDF bytes."""
        return self.build().render()

    def save(self, path) -> None:
        """Render the deck and write it to `path`."""
        self.build().save(path)

    @property
    def slide_count(self) -> int:
        return len(self._slides)

    # -- internal composition --

    def _add_slide(self, name: str, blocks: list) -> "SlideDeck":
        self._slides.append(_Slide(name=name, blocks=blocks))
        return self

    def _title_zone(self, title: str) -> list:
        """Slide title with its accent underline bar."""
        return [Heading(title, level=2), _accent_bar(self.theme.accent)]

    def _needs_masthead(self, first_slide) -> bool:
        """True when slide 1 does not already open with the deck title."""
        blocks = first_slide.blocks
        return not (
            blocks and isinstance(blocks[0], Heading) and blocks[0].text == self.title
        )

    def _masthead(self) -> Heading:
        """A compact deck-title line for decks without a title slide."""
        return Heading(
            self.title,
            level=1,
            style=Style(
                font_size=10.5,
                color=self.theme.muted,
                line_height=1.2,
                space_before=0.0,
                space_after=10.0,
            ),
        )

    def _spacer(self, points: float) -> Paragraph:
        """Vertical whitespace expressed as an empty line of fixed size."""
        return Paragraph(
            " ",
            style=Style(
                font_size=round(points, 2),
                line_height=1.0,
                space_before=0.0,
                space_after=0.0,
            ),
        )

    def _takeaway(self, text: str) -> Callout:
        """A tinted takeaway callout with a bold accent lead-in."""
        t = self.theme
        return Callout(
            content=[
                TextRun("Takeaway — ", bold=True, color=t.accent_ink),
                TextRun(text),
            ],
            icon="",
            background=t.tint,
            border_color=t.accent,
            style=Style(
                font_size=15.0,
                color=t.ink,
                line_height=1.35,
                hyphenate=False,
            ),
        )

    def _normalize(self, block):
        """Coerce loose input to spec elements and apply theme defaults."""
        if isinstance(block, str):
            return Paragraph(block)
        if isinstance(block, PageBreak):
            raise ValueError(
                "PageBreak is not allowed inside a slide; call a layout "
                "method once per slide instead"
            )
        if isinstance(block, Table):
            return replace(block, stripe=True)
        if isinstance(block, Chart):
            colors = (
                list(block.colors) if block.colors else list(self.theme.chart_palette)
            )
            width, height = block.width, block.height
            max_height = round(self._page.content_height * 0.55, 2)
            if height > max_height:
                factor = max_height / height
                width, height = round(width * factor, 2), max_height
            return replace(block, colors=colors, width=width, height=height)
        return block

    def _two_column_table(self, items: list) -> Table:
        """Two-column layout as a rule-less table with a gutter column."""
        mid = (len(items) + 1) // 2
        left_units = self._column_units(items[:mid])
        right_units = self._column_units(items[mid:])
        rows = []
        for i in range(max(len(left_units), len(right_units))):
            left = left_units[i] if i < len(left_units) else ""
            right = right_units[i] if i < len(right_units) else ""
            rows.append(
                [
                    TableCell(content=left),
                    TableCell(content=""),
                    TableCell(content=right),
                ]
            )
        return Table(
            headers=[],
            rows=rows,
            column_widths=[1.0, 0.12, 1.0],
            stripe=False,
        )

    def _column_units(self, blocks: list) -> list:
        """Flatten column blocks into per-row run lists for the grid."""
        t = self.theme
        units: list = []
        for block in blocks:
            if isinstance(block, str):
                units.append([TextRun(block)])
            elif isinstance(block, Paragraph):
                units.append(list(block.runs))
            elif isinstance(block, Heading):
                units.append(
                    [TextRun(block.text, bold=True, font_size=17.0, color=t.title)]
                )
            elif isinstance(block, BulletList):
                units.extend(self._list_units(block, marker="•"))
            elif isinstance(block, NumberedList):
                units.extend(self._list_units(block, marker=None))
            else:
                raise TypeError(
                    "two-column slides support text blocks (headings, "
                    "paragraphs, lists); use layout='single' or chart_slide "
                    f"for {type(block).__name__}"
                )
        return units

    def _list_units(self, element, marker: str | None) -> list:
        """One grid row per list item, marker colored in the accent."""
        t = self.theme
        units: list = []
        text_index = 0
        for runs, sub in element.flat_items:
            if sub is not None:
                for sub_runs, _ in sub.flat_items:
                    if sub_runs is not None:
                        units.append(
                            [TextRun("      –  ", color=t.accent_ink)] + list(sub_runs)
                        )
                continue
            if marker is None:
                prefix = element.marker(text_index) + "  "
                text_index += 1
            else:
                prefix = marker + "  "
            units.append([TextRun(prefix, bold=True, color=t.accent_ink)] + list(runs))
        return units

    # -- fit-to-slide (7.2) --

    def _measure_engine(self):
        """A lazily built engine for slide-time measurements."""
        if self._measurer is None:
            from .layout.engine import LayoutEngine
            from .typography.font_metrics import FontRegistry

            self._measurer = LayoutEngine(FontRegistry(), self._sheet)
        return self._measurer

    def _stack_height(self, blocks: list) -> float:
        """Height of a block stack as the paginator will see it."""
        engine = self._measure_engine()
        return _stack_height(engine, blocks, self._page.content_width)

    def _fit(self, engine, slide, width: float, limit: float, index: int) -> list:
        """Return the slide's blocks, scaled down stepwise until they fit."""
        scale = 1.0
        while True:
            if scale == 1.0:
                blocks = slide.blocks
            else:
                blocks = [_scale_block(el, scale, self._sheet) for el in slide.blocks]
            height = _stack_height(engine, blocks, width)
            if height <= limit + 0.5:
                return blocks
            if scale <= self.MIN_SCALE + 1e-9:
                raise ValueError(
                    f"slide {index + 1} ({slide.name!r}) is "
                    f"{height - limit:.1f}pt too tall for one slide even at "
                    f"the minimum {self.MIN_SCALE}x type scale; split its "
                    "content across slides"
                )
            scale = max(self.MIN_SCALE, round(scale * self.SCALE_STEP, 6))


def _stack_height(engine, blocks: list, width: float) -> float:
    """Total height the paginator needs for `blocks` on one page."""
    measured = [engine.measure(element, width) for element in blocks]
    total = 0.0
    for index, block in enumerate(measured):
        if index:
            total += measured[index - 1].space_after + block.space_before
        total += block.height
    return total


# -- fit-to-slide scaling --


def _scale_run(run: TextRun, scale: float) -> TextRun:
    if run.font_size:
        return replace(run, font_size=round(run.font_size * scale, 2))
    return run


def _scale_runs(runs, scale: float) -> list:
    return [_scale_run(run, scale) for run in runs]


def _scale_content(content, scale: float):
    if isinstance(content, TextRun):
        return _scale_run(content, scale)
    if isinstance(content, str):
        return content
    return [
        _scale_run(item, scale) if isinstance(item, TextRun) else item
        for item in content
    ]


def _scale_cell(cell: TableCell, scale: float) -> TableCell:
    return TableCell(
        content=_scale_content(cell.content, scale),
        align=cell.align,
        bold=cell.bold,
        colspan=cell.colspan,
        background=cell.background,
    )


def _scale_item(item, scale: float, sheet: StyleSheet):
    if isinstance(item, TextRun):
        return _scale_run(item, scale)
    if isinstance(item, (BulletList, NumberedList)):
        return _scale_block(item, scale, sheet)
    if isinstance(item, (list, tuple)):
        return [_scale_item(entry, scale, sheet) for entry in item]
    return item


def _scaled_style(element_style, resolved, scale: float) -> Style:
    """Bake scaled size and spacing into a per-block override style."""
    base = element_style if element_style is not None else Style()
    return base.with_(
        font_size=round(resolved.require("font_size") * scale, 2),
        space_before=round(resolved.require("space_before") * scale, 2),
        space_after=round(resolved.require("space_after") * scale, 2),
    )


def _scale_block(element, scale: float, sheet: StyleSheet):
    """Copy a block with its type sizes multiplied by `scale`."""
    if isinstance(element, Heading):
        resolved = sheet.resolved(sheet.for_heading(element.level), element.style)
        return replace(element, style=_scaled_style(element.style, resolved, scale))
    if isinstance(element, Paragraph):
        resolved = sheet.resolved(sheet.body, element.style)
        return Paragraph(
            content=_scale_runs(element.runs, scale),
            style=_scaled_style(element.style, resolved, scale),
        )
    if isinstance(element, BlockQuote):
        resolved = sheet.resolved(sheet.body, element.style)
        return BlockQuote(
            content=_scale_runs(element.runs, scale),
            attribution=element.attribution,
            style=_scaled_style(element.style, resolved, scale),
        )
    if isinstance(element, Callout):
        resolved = sheet.resolved(sheet.body, element.style)
        return Callout(
            content=_scale_runs(element.runs, scale),
            variant=element.variant,
            title=element.title,
            icon=element.icon,
            background=element.background,
            border_color=element.border_color,
            border_radius=element.border_radius,
            style=_scaled_style(element.style, resolved, scale),
        )
    if isinstance(element, BulletList):
        resolved = sheet.resolved(sheet.list_item, element.style)
        return BulletList(
            items=[_scale_item(item, scale, sheet) for item in element.items],
            bullet=element.bullet,
            checked=element.checked,
            style=_scaled_style(element.style, resolved, scale),
        )
    if isinstance(element, NumberedList):
        resolved = sheet.resolved(sheet.list_item, element.style)
        return NumberedList(
            items=[_scale_item(item, scale, sheet) for item in element.items],
            start=element.start,
            marker_style=element.marker_style,
            style=_scaled_style(element.style, resolved, scale),
        )
    if isinstance(element, Table):
        resolved = sheet.resolved(sheet.table_cell, element.style)
        return Table(
            headers=[_scale_cell(cell, scale) for cell in element.header_cells],
            rows=[
                [_scale_cell(cell, scale) for cell in row] for row in element.body_rows
            ],
            column_widths=element.column_widths,
            caption=element.caption,
            label=element.label,
            stripe=element.stripe,
            repeat_header=element.repeat_header,
            style=_scaled_style(element.style, resolved, scale),
        )
    if isinstance(element, (CodeBlock, MathBlock)):
        resolved = sheet.resolved(sheet.body, element.style)
        return replace(element, style=_scaled_style(element.style, resolved, scale))
    if isinstance(element, Chart):
        # Charts are vector art, so shrinking them is a true resize.
        return replace(
            element,
            width=round(element.width * scale, 2),
            height=round(element.height * scale, 2),
        )
    return element


# -- original preset API (backward compatible) --


@dataclass
class SlideConfig:
    """Configuration for slide-based documents."""

    aspect_ratio: str = "16:9"
    theme: str = "default"
    slide_numbers: bool = True

    @property
    def page_spec(self) -> PageSpec:
        if self.aspect_ratio == "4:3":
            return SLIDE_4_3
        return SLIDE_16_9


def slide_document(
    title: str,
    subtitle: str = "",
    author: str = "",
    aspect_ratio: str = "16:9",
    theme: str = "default",
    slide_numbers: bool = True,
) -> Document:
    """Create a Document pre-configured for slide presentation.

    Returns a Document with a title slide already added. Subsequent
    content separated by ``page_break()`` becomes additional slides.
    """
    config = SlideConfig(
        aspect_ratio=aspect_ratio,
        theme=theme,
        slide_numbers=slide_numbers,
    )
    sheet = _build_slide_sheet(theme)

    doc = Document(
        title=title,
        author=author,
        page=config.page_spec,
        style=sheet,
        page_numbers=config.slide_numbers,
    )

    doc.heading(title, level=1)
    if subtitle:
        doc.paragraph(
            subtitle,
            style=Style(
                font_size=20.0,
                italic=True,
                color="64748b",
                align="center",
            ),
        )
    if author:
        doc.paragraph(
            author,
            style=Style(
                font_size=16.0,
                color="94a3b8",
                align="center",
            ),
        )
    doc.page_break()

    return doc


_THEMES: dict = {
    "default": {
        "body_color": "1e293b",
        "heading_color": "0f172a",
        "accent_color": "1e40af",
        "muted_color": "64748b",
        "table_header_rule": "0f172a",
        "table_rule": "cbd5e1",
        "table_stripe": "f8fafc",
    },
    "dark": {
        "body_color": "e2e8f0",
        "heading_color": "f1f5f9",
        "accent_color": "60a5fa",
        "muted_color": "94a3b8",
        "table_header_rule": "e2e8f0",
        "table_rule": "475569",
        "table_stripe": "1e293b",
    },
    "minimal": {
        "body_color": "334155",
        "heading_color": "1e293b",
        "accent_color": "475569",
        "muted_color": "94a3b8",
        "table_header_rule": "334155",
        "table_rule": "e2e8f0",
        "table_stripe": "f8fafc",
    },
}


def _build_slide_sheet(theme: str) -> StyleSheet:
    """Build a stylesheet tuned for slide presentations."""
    colors = _THEMES.get(theme, _THEMES["default"])

    body_size = 18.0
    scale = (2.0, 1.55, 1.22, 1.0, 1.0, 1.0)
    h_space_before = (14.0, 12.0, 10.0, 8.0, 8.0, 8.0)
    h_space_after = (12.0, 10.0, 8.0, 6.0, 6.0, 6.0)

    headings = {}
    for i, factor in enumerate(scale, start=1):
        headings[f"h{i}"] = Style(
            font_family="Helvetica",
            font_size=round(body_size * factor, 2),
            bold=True,
            color=colors["heading_color"],
            align="center" if i == 1 else "left",
            line_height=1.2,
            space_before=h_space_before[i - 1],
            space_after=h_space_after[i - 1],
            keep_with_next=True,
            hyphenate=False,
        )

    return StyleSheet(
        name=f"slide-{theme}",
        body=Style(
            font_family="Helvetica",
            font_size=body_size,
            color=colors["body_color"],
            align="left",
            line_height=1.5,
            space_after=10.0,
            hyphenate=False,
        ),
        list_item=Style(
            align="left",
            font_size=body_size,
            space_after=8.0,
            indent_left=24.0,
            line_height=1.5,
            hyphenate=False,
        ),
        table_header=Style(
            font_family="Helvetica",
            font_size=round(body_size * 0.85, 2),
            bold=True,
            align="left",
            line_height=1.25,
            color=colors["heading_color"],
            hyphenate=False,
        ),
        table_cell=Style(
            font_family="Helvetica",
            font_size=round(body_size * 0.85, 2),
            align="left",
            line_height=1.3,
            hyphenate=False,
        ),
        caption=Style(
            font_family="Helvetica",
            font_size=round(body_size * 0.75, 2),
            italic=True,
            color=colors["muted_color"],
            align="left",
            space_before=4.0,
            space_after=8.0,
            hyphenate=False,
        ),
        header_footer=Style(
            font_family="Helvetica",
            font_size=9.0,
            color=colors["muted_color"],
            align="left",
            line_height=1.2,
            hyphenate=False,
        ),
        **headings,
        table_rule_color=colors["table_rule"],
        table_header_rule_color=colors["table_header_rule"],
        table_stripe_color=colors["table_stripe"],
    )
