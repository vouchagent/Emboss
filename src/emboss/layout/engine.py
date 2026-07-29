"""Layout: measure content, then place it on pages under constraints.

Measurement happens before any placement, so the engine always knows how
tall a block is and where it may legally split. Overflow is therefore
impossible by construction rather than detected after the fact.

Pagination enforces widow/orphan minimums, keep-with-next for headings,
keep-together for atomic blocks, header repetition for split tables,
and float placement for figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..spec import (
    Abstract,
    Authors,
    BibliographyBlock,
    BlockQuote,
    BulletList,
    Callout,
    Chart,
    CodeBlock,
    CoverPage,
    Footnote,
    Glossary,
    Heading,
    HorizontalRule,
    Image,
    MathBlock,
    NumberedList,
    PageBreak,
    Paragraph,
    PullQuote,
    StatTiles,
    SvgBlock,
    Table,
    TextRun,
)
from ..typography.font_metrics import small_caps_segments
from ..typography.line_breaking import Box, Glue, LineBreaker, build_items
from ..typography.substitutions import substitute_unsupported

__all__ = [
    "LaidOutLine",
    "MeasuredBlock",
    "PlacedBlock",
    "PlacedFootnote",
    "Page",
    "LayoutEngine",
    "TableLayout",
    "annotation_heights",
    "annotation_sizes",
]


@dataclass(slots=True)
class LaidOutLine:
    """One line of text with its resolved geometry."""

    fragments: list  # (text, run, x_offset) triples
    width: float
    height: float
    ascent: float
    ratio: float = 0.0
    is_last: bool = False
    hyphenated: bool = False


@dataclass
class TableLayout:
    """Resolved table geometry: column widths and per-cell line content."""

    column_widths: list
    header_height: float
    row_heights: list
    header_lines: list  # per column: list[LaidOutLine]
    row_lines: list  # per row, per column: list[LaidOutLine]
    header_spans: list | None = None  # per column: colspan, 0 when covered
    row_spans: list | None = None  # per row, per column: colspan, 0 when covered


@dataclass
class MeasuredBlock:
    """A content block with computed dimensions and legal split points."""

    element: object
    height: float
    style: object
    lines: list = field(default_factory=list)
    can_split: bool = False
    keep_with_next: bool = False
    space_before: float = 0.0
    space_after: float = 0.0
    table: TableLayout | None = None
    list_items: list = field(default_factory=list)
    line_groups: list | None = None
    footnotes: list = field(default_factory=list)
    full_page: bool = False
    extras: dict = field(default_factory=dict)

    def height_of_lines(self, count: int) -> float:
        return sum(line.height for line in self.lines[:count])

    def lines_fitting(self, available: float) -> int:
        used = 0.0
        for index, line in enumerate(self.lines):
            if used + line.height > available:
                return index
            used += line.height
        return len(self.lines)


def annotation_sizes(style) -> tuple[float, float, float]:
    """Return (headline_size, subtitle_size, source_line_size) in points."""
    body = style.require("font_size")
    return body + 1.0, body * 0.92, 7.5


def annotation_heights(headline, subtitle, source_line, style) -> tuple:
    """Return reserved (headline_h, subtitle_h, source_h) for resolved text.

    Callers resolve the headline first (e.g. via ``chart_facts.resolve_headline``)
    so measurement and rendering always reserve/consume the same space.
    """
    headline_size, subtitle_size, source_size = annotation_sizes(style)
    headline_h = headline_size + 4.0 if headline else 0.0
    subtitle_h = subtitle_size + 3.0 if subtitle else 0.0
    source_h = source_size + 4.0 if source_line else 0.0
    return headline_h, subtitle_h, source_h


@dataclass(slots=True)
class PlacedBlock:
    """A measured block positioned on a page."""

    block: MeasuredBlock
    x: float
    y: float  # top edge, PDF coordinates
    height: float
    lines: list = field(default_factory=list)
    is_continuation: bool = False
    table_rows: list | None = None
    include_table_header: bool = True


@dataclass(slots=True)
class PlacedFootnote:
    """A footnote positioned in a page's bottom note area."""

    block: MeasuredBlock
    x: float
    y: float  # top edge, PDF coordinates
    width: float  # measure of the region, for the separator rule
    separator: bool = False


@dataclass
class Page:
    """One output page."""

    number: int
    blocks: list = field(default_factory=list)
    cursor: float = 0.0
    spec: object = None
    footnotes: list = field(default_factory=list)
    suppress_chrome: bool = False

    def remaining(self) -> float:
        return self.cursor - self.spec.content_bottom


@dataclass
class _FloatEntry:
    block: MeasuredBlock
    float_type: str
    origin_page: int


_FLOATABLE_TYPES = (Image, Chart, SvgBlock)


class LayoutEngine:
    """Measures content and composes it into pages."""

    # A heading must be followed by at least this much of its next block,
    # otherwise it moves to the next page with it.
    KEEP_WITH_NEXT_LOOKAHEAD = 34.0
    MIN_WIDOW_LINES = 2
    MIN_ORPHAN_LINES = 2
    MIN_TABLE_ROWS_PER_PAGE = 2

    FLOAT_AUTO_THRESHOLD = 0.40
    FLOAT_MIN_TEXT_SPACE = 0.15
    FLOAT_MAX_DRIFT = 2

    NESTED_LIST_INDENT = 14.0
    BLOCKQUOTE_INDENT = 14.0
    FOOTNOTE_SEPARATION = 8.0
    CHECKBOX_SIZE = 7.0
    CHECKBOX_GAP = 5.0

    def __init__(
        self, fonts, sheet, hyphenator=None, breaker=None, optimize_layout=True
    ):
        self.fonts = fonts
        self.sheet = sheet
        self.hyphenator = hyphenator
        self.breaker = breaker or LineBreaker()
        self.optimize_layout = optimize_layout
        self.warnings: list = []
        self._warned: set = set()

    # -- font resolution --

    def _metrics(self, style, run=None):
        family = (
            run.font_family if run and run.font_family else style.require("font_family")
        )
        bold = run.bold if run and run.bold else style.require("bold")
        italic = run.italic if run and run.italic else style.require("italic")
        return self.fonts.resolve(family, bold=bold, italic=italic)

    def _size(self, style, run=None) -> float:
        if run is not None and run.font_size:
            return run.font_size
        return style.require("font_size")

    # -- glyph availability --

    def _substituted_runs(self, runs, style) -> list:
        """Copy runs, replacing characters their resolved font cannot render."""
        out = None
        for index, run in enumerate(runs):
            metrics = self._metrics(style, run)
            new_text, replaced = substitute_unsupported(run.text, metrics.supports)
            if not replaced:
                continue
            if out is None:
                out = list(runs)
            out[index] = replace(run, text=new_text)
            metrics.note_usage(new_text)
            for char in sorted(set(replaced)):
                key = (char, metrics.name)
                if key not in self._warned:
                    self._warned.add(key)
                    self.warnings.append(
                        f"U+{ord(char):04X} {char!r} is not renderable by "
                        f"{metrics.name}; substituted"
                    )
        return runs if out is None else out

    def segment_run(self, style, run) -> list:
        """Fallback-font (segment, metrics) pairs for one run's text.

        Exposed for writer-side per-segment font wiring; measurement itself
        currently substitutes instead of switching fonts mid-run.
        """
        metrics = self._metrics(style, run)
        segment = getattr(self.fonts, "segment_runs", None)
        if segment is None:
            return [(run.text, metrics)]
        return segment(run.text, metrics)

    # -- measurement --

    def measure(self, element, width: float) -> MeasuredBlock:
        if isinstance(element, Heading):
            return self._measure_text(
                element,
                element.runs,
                self.sheet.resolved(
                    self.sheet.for_heading(element.level), element.style
                ),
                width,
            )
        if isinstance(element, Paragraph):
            return self._measure_text(
                element,
                element.runs,
                self.sheet.resolved(self.sheet.body, element.style),
                width,
            )
        if isinstance(element, BulletList):
            return self._measure_list(element, width)
        if isinstance(element, NumberedList):
            return self._measure_numbered_list(element, width)
        if isinstance(element, Table):
            return self._measure_table(element, width)
        if isinstance(element, HorizontalRule):
            return MeasuredBlock(
                element=element,
                height=element.thickness,
                style=self.sheet.resolved(self.sheet.body),
                space_before=element.space_before,
                space_after=element.space_after,
            )
        if isinstance(element, Footnote):
            return self._measure_footnote(element, width)
        if isinstance(element, Callout):
            return self._measure_callout(element, width)
        if isinstance(element, BlockQuote):
            return self._measure_blockquote(element, width)
        if isinstance(element, Image):
            return self._measure_image(element, width)
        if isinstance(element, Chart):
            return self._measure_chart(element, width)
        if isinstance(element, CodeBlock):
            return self._measure_code_block(element, width)
        if isinstance(element, MathBlock):
            return self._measure_math(element, width)
        if isinstance(element, BibliographyBlock):
            return self._measure_bibliography(element, width)
        if isinstance(element, SvgBlock):
            return self._measure_svg(element, width)
        if isinstance(element, CoverPage):
            return self._measure_cover(element, width)
        if isinstance(element, Abstract):
            return self._measure_abstract(element, width)
        if isinstance(element, Authors):
            return self._measure_authors(element, width)
        if isinstance(element, PullQuote):
            return self._measure_pullquote(element, width)
        if isinstance(element, StatTiles):
            return self._measure_stat_tiles(element, width)
        if isinstance(element, Glossary):
            return self._measure_glossary(element, width)
        if isinstance(element, PageBreak):
            return MeasuredBlock(
                element=element,
                height=0.0,
                style=self.sheet.resolved(self.sheet.body),
            )
        raise TypeError(f"cannot measure {type(element).__name__}")

    def _accent_color(self) -> str:
        """The stylesheet accent used for rules and emphasis marks."""
        return getattr(self.sheet, "table_header_rule_color", "44403c")

    def _muted_color(self) -> str:
        """The stylesheet muted/secondary text color."""
        return self.sheet.caption.color or "57534e"

    def _styled_lines(
        self,
        text,
        base_style,
        width,
        size,
        *,
        bold=False,
        italic=False,
        color=None,
        align="center",
    ) -> list:
        """Lay out one string as lines whose run carries all its attributes.

        Baking size/weight/color into the run means measurement and any
        later render pass agree regardless of the block's base style.
        """
        run = TextRun(text, bold=bold, italic=italic, font_size=size, color=color)
        st = base_style.with_(align=align, hyphenate=False)
        lines = self._layout_runs([run], st, width)
        self._metrics(st, run).note_usage(text)
        return lines

    def _expand_small_caps(self, runs, style) -> list:
        """Replace small-caps runs with sized segments via the shared helper.

        The same segment runs feed measurement and rendering, so widths
        cannot diverge; each segment records its original casing in
        ``_sc_actual`` for ActualText extraction.
        """
        if not any(getattr(r, "small_caps", False) and r.text for r in runs):
            return runs
        out: list = []
        for run in runs:
            if not getattr(run, "small_caps", False) or not run.text:
                out.append(run)
                continue
            base = self._size(style, run)
            segments = small_caps_segments(run.text, base)
            originals: list = []
            for ch in run.text:
                low = ch.islower()
                if originals and originals[-1][1] == low:
                    originals[-1][0] += ch
                else:
                    originals.append([ch, low])
            for (seg_text, seg_size), (orig_text, _low) in zip(segments, originals):
                seg = replace(run, text=seg_text, font_size=seg_size, small_caps=False)
                seg._sc_actual = orig_text
                self._metrics(style, seg).note_usage(seg_text)
                out.append(seg)
        return out

    def _layout_runs(
        self,
        runs,
        style,
        width: float,
        first_indent: float = 0.0,
        hanging_indent: float = 0.0,
    ) -> list:
        """Break runs into positioned lines within `width`."""
        runs = self._substituted_runs(runs, style)
        runs = self._expand_small_caps(runs, style)
        align = style.require("align")
        justified = align == "justify"
        hyphenate = bool(style.hyphenate) and self.hyphenator is not None

        items = build_items(
            runs,
            metrics_for=lambda r: self._metrics(style, r),
            size_for=lambda r: self._size(style, r),
            hyphenator=self.hyphenator,
            justified=justified,
            hyphenate=hyphenate,
        )

        def width_for(line_number: int) -> float:
            if line_number == 0:
                return width - first_indent
            return width - hanging_indent

        raw_lines = self.breaker.break_paragraph(items, width_for)

        base_metrics = self._metrics(style)
        base_size = self._size(style)
        multiplier = style.require("line_height")
        base_line_height = base_metrics.line_height(base_size, multiplier)
        base_ascent = base_metrics.ascent(base_size)

        laid_out = []
        for index, line in enumerate(raw_lines):
            available = width_for(index)
            fragments, cursor = [], 0.0

            natural = line.width
            glue_count = sum(1 for it in line.items if isinstance(it, Glue))
            extra = 0.0
            if justified and not line.is_last and glue_count:
                # Right-protrusion credit widens the usable measure so the
                # closing punctuation hangs past the margin at render time.
                credit = getattr(line, "protrusion_credit", 0.0)
                slack = available + credit - natural
                if line.hyphenated:
                    slack -= 0.0
                extra = slack / glue_count

            for item in line.items:
                if isinstance(item, Box):
                    if item.text:
                        fragments.append((item.text, runs[item.run_index], cursor))
                    cursor += item.width
                elif isinstance(item, Glue):
                    cursor += item.width + extra

            content_width = cursor
            if line.hyphenated and fragments:
                text, run, offset = fragments[-1]
                fragments[-1] = (text + "-", run, offset)
                metrics = self._metrics(style, run)
                content_width += metrics.text_width("-", self._size(style, run))

            offset = 0.0
            if not justified or line.is_last:
                if align == "center":
                    offset = (available - content_width) / 2.0
                elif align == "right":
                    offset = available - content_width
            if index == 0 and first_indent:
                offset += first_indent
            if index > 0 and hanging_indent:
                offset += hanging_indent

            if offset:
                fragments = [(t, r, x + offset) for t, r, x in fragments]

            line_height, ascent = base_line_height, base_ascent
            for _text, run, _x in fragments:
                run_metrics = self._metrics(style, run)
                run_size = self._size(style, run)
                line_height = max(
                    line_height, run_metrics.line_height(run_size, multiplier)
                )
                ascent = max(ascent, run_metrics.ascent(run_size))

            laid_out.append(
                LaidOutLine(
                    fragments=fragments,
                    width=content_width,
                    height=line_height,
                    ascent=ascent,
                    ratio=line.ratio,
                    is_last=line.is_last,
                    hyphenated=line.hyphenated,
                )
            )
        return laid_out

    def _measure_text(self, element, runs, style, width: float) -> MeasuredBlock:
        indent_left = style.require("indent_left")
        indent_right = style.require("indent_right")
        usable = width - indent_left - indent_right
        lines = self._layout_runs(
            runs, style, usable, first_indent=style.require("indent_first")
        )
        for run in runs:
            self._metrics(style, run).note_usage(run.text)

        return MeasuredBlock(
            element=element,
            height=sum(line.height for line in lines),
            style=style,
            lines=lines,
            can_split=len(lines) > (self.MIN_WIDOW_LINES + self.MIN_ORPHAN_LINES - 1)
            and not style.require("keep_together"),
            keep_with_next=style.require("keep_with_next"),
            space_before=style.require("space_before"),
            space_after=style.require("space_after"),
        )

    def _measure_list(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.list_item, element.style)
        indent = style.require("indent_left")
        metrics = self._metrics(style)
        size = self._size(style)
        if getattr(element, "checked", None):
            bullet_width = self.CHECKBOX_SIZE + self.CHECKBOX_GAP
        else:
            bullet_width = metrics.text_width(element.bullet + " ", size)
        usable = width - indent - bullet_width

        items, total = [], 0.0
        for runs, sub in element.flat_items:
            if sub is not None:
                nested = self.measure(sub, width - self.NESTED_LIST_INDENT)
                items.append(nested)
                total += nested.height + nested.space_before + nested.space_after
            else:
                lines = self._layout_runs(runs, style, usable)
                for run in runs:
                    self._metrics(style, run).note_usage(run.text)
                metrics.note_usage(element.bullet)
                height = sum(line.height for line in lines)
                items.append(lines)
                total += height + style.require("space_after")

        total -= style.require("space_after") if items else 0.0
        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=style.require("space_before"),
            space_after=style.require("space_after") + 2.0,
            list_items=items,
        )

    def _measure_numbered_list(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.list_item, element.style)
        indent = style.require("indent_left")
        metrics = self._metrics(style)
        size = self._size(style)
        last_marker = (
            element.marker(len(element.item_runs) - 1) if element.item_runs else "1."
        )
        marker_width = metrics.text_width(last_marker + " ", size)
        usable = width - indent - marker_width

        items, total = [], 0.0
        text_idx = 0
        for runs, sub in element.flat_items:
            if sub is not None:
                nested = self.measure(sub, width - self.NESTED_LIST_INDENT)
                items.append(nested)
                total += nested.height + nested.space_before + nested.space_after
            else:
                lines = self._layout_runs(runs, style, usable)
                for run in runs:
                    self._metrics(style, run).note_usage(run.text)
                metrics.note_usage(element.marker(text_idx))
                height = sum(line.height for line in lines)
                items.append(lines)
                total += height + style.require("space_after")
                text_idx += 1

        total -= style.require("space_after") if items else 0.0
        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=style.require("space_before"),
            space_after=style.require("space_after") + 2.0,
            list_items=items,
        )

    def _measure_footnote(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.body, element.style)
        fn_style = style.with_(font_size=style.require("font_size") * 0.85)
        marker_text = element.marker or "*"
        marker_width = self._metrics(fn_style).text_width(
            marker_text + " ", self._size(fn_style)
        )
        usable = width - marker_width
        lines = self._layout_runs(element.runs, fn_style, usable)
        for run in element.runs:
            self._metrics(fn_style, run).note_usage(run.text)
        return MeasuredBlock(
            element=element,
            height=sum(line.height for line in lines) + 2.0,
            style=fn_style,
            lines=lines,
            can_split=False,
            space_before=4.0,
            space_after=2.0,
        )

    def _measure_blockquote(self, element, width: float) -> MeasuredBlock:
        from ..spec import TextRun

        style = self.sheet.resolved(self.sheet.body, element.style)
        quote_style = style.with_(italic=True)
        usable = width - 2 * self.BLOCKQUOTE_INDENT
        lines = self._layout_runs(element.runs, quote_style, usable)
        for run in element.runs:
            self._metrics(quote_style, run).note_usage(run.text)
        if element.attribution:
            attr_style = quote_style.with_(
                font_size=self._size(quote_style) * 0.85, align="right"
            )
            attr_runs = [TextRun("— " + element.attribution)]
            attr_lines = self._layout_runs(attr_runs, attr_style, usable)
            for run in attr_runs:
                self._metrics(attr_style, run).note_usage(run.text)
            lines = lines + attr_lines
        return MeasuredBlock(
            element=element,
            height=sum(line.height for line in lines),
            style=quote_style,
            lines=lines,
            can_split=False,
            space_before=8.0,
            space_after=8.0,
        )

    def _measure_callout(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.body, element.style)
        padding = 10.0
        usable = width - 2 * padding - 4.0
        total = 2 * padding
        title_lines = []
        if element.title:
            title_style = style.with_(bold=True)
            title_lines = self._layout_runs(
                [
                    __import__("emboss.spec", fromlist=["TextRun"]).TextRun(
                        element.title, bold=True
                    )
                ],
                title_style,
                usable,
            )
            total += sum(line.height for line in title_lines)
        content_lines = self._layout_runs(element.runs, style, usable)
        for run in element.runs:
            self._metrics(style, run).note_usage(run.text)
        total += sum(line.height for line in content_lines)
        all_lines = title_lines + content_lines
        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            lines=all_lines,
            can_split=False,
            space_before=8.0,
            space_after=8.0,
        )

    def _measure_image(self, element, width: float) -> MeasuredBlock:
        from ..images import load_image

        style = self.sheet.resolved(self.sheet.body, element.style)
        img = load_image(element.source)
        display_w = element.width or min(img.width, width)
        if display_w > width:
            display_w = width
        scale = display_w / img.width
        display_h = element.height or img.height * scale
        total = display_h
        if element.caption:
            cap_size = self._size(style) * 0.85
            total += cap_size + 4.0
        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=8.0,
            space_after=8.0,
        )

    def _measure_chart(self, element, width: float) -> MeasuredBlock:
        from ..chart_facts import resolve_headline

        style = self.sheet.resolved(self.sheet.body, element.style)
        display_w = min(element.width, width)
        display_h = element.height * (display_w / element.width)
        headline = resolve_headline(element)
        headline_h, subtitle_h, source_h = annotation_heights(
            headline, element.subtitle, element.source_line, style
        )
        total = headline_h + subtitle_h + display_h + source_h
        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=8.0,
            space_after=8.0,
        )

    def _measure_math(self, element, width: float) -> MeasuredBlock:
        from ..math_render import parse_math, MathLayoutEngine

        style = self.sheet.resolved(self.sheet.body, element.style)
        size = self._size(style)
        if element.display:
            size *= 1.2
        engine = MathLayoutEngine(base_size=size)
        node = parse_math(element.source)
        layout = engine.layout(node)
        height = layout.height + layout.depth + size * 0.5
        if element.caption:
            height += size * 0.85 + 4.0
        return MeasuredBlock(
            element=element,
            height=height,
            style=style,
            can_split=False,
            space_before=8.0,
            space_after=8.0,
        )

    def _measure_code_block(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.body, element.style)
        code_size = style.require("font_size") * 0.85
        metrics = self.fonts.resolve("Courier", bold=False, italic=False)
        line_height = metrics.line_height(code_size, 1.4)

        lines = element.code.split("\n")
        padding = 10.0
        total = 2 * padding + len(lines) * line_height

        if element.caption:
            total += code_size + 6.0

        metrics.note_usage(element.code)
        if element.line_numbers:
            max_num = str(element.start_line + len(lines) - 1)
            metrics.note_usage(max_num)

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=8.0,
            space_after=8.0,
        )

    BIBLIOGRAPHY_HANGING_INDENT = 18.0

    def _measure_bibliography(self, element, width: float) -> MeasuredBlock:
        from ..bibliography import format_bibliography
        from ..spec import TextRun

        style = self.sheet.resolved(self.sheet.body, element.style)

        all_lines: list = []
        groups: list = []

        if element.title:
            heading_style = self.sheet.resolved(
                self.sheet.for_heading(element.heading_level), element.style
            )
            title_runs = [TextRun(element.title)]
            title_lines = self._layout_runs(title_runs, heading_style, width)
            for run in title_runs:
                self._metrics(heading_style, run).note_usage(run.text)
            if title_lines:
                title_lines[-1].height += heading_style.require("space_after")
                all_lines.extend(title_lines)
                groups.append(("title", len(title_lines)))

        entries = format_bibliography(element.citations, element.bib_style)
        spacing = style.require("space_after") * 0.5
        for entry in entries:
            runs = [TextRun(entry)]
            lines = self._layout_runs(
                runs,
                style,
                width,
                hanging_indent=self.BIBLIOGRAPHY_HANGING_INDENT,
            )
            for run in runs:
                self._metrics(style, run).note_usage(run.text)
            if lines:
                lines[-1].height += spacing
                all_lines.extend(lines)
                groups.append(("entry", len(lines)))

        return MeasuredBlock(
            element=element,
            height=sum(line.height for line in all_lines),
            style=style,
            lines=all_lines,
            line_groups=groups,
            can_split=len(groups) > 1,
            space_before=12.0,
            space_after=8.0,
        )

    GLOSSARY_HANGING_INDENT = 18.0
    GLOSSARY_ENTRY_GAP = 6.0

    def _measure_glossary(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.body, element.style)
        title_style = self.sheet.resolved(self.sheet.h2, element.style)

        title_lines = self._styled_lines(
            element.title,
            style,
            width,
            title_style.require("font_size"),
            bold=True,
            color=title_style.require("color"),
            align="left",
        )
        if title_lines:
            title_lines[-1].height += 8.0

        all_lines: list = list(title_lines)
        groups: list = [("title", len(title_lines))] if title_lines else []

        entries = sorted(element.entry_list, key=lambda e: e.term.lower())
        for entry in entries:
            runs = [
                TextRun(entry.term, bold=True),
                TextRun("  " + entry.definition),
            ]
            lines = self._layout_runs(
                runs, style, width, hanging_indent=self.GLOSSARY_HANGING_INDENT
            )
            for run in runs:
                self._metrics(style, run).note_usage(run.text)
            if lines:
                lines[-1].height += self.GLOSSARY_ENTRY_GAP
                all_lines.extend(lines)
                groups.append(("entry", len(lines)))

        return MeasuredBlock(
            element=element,
            height=sum(line.height for line in all_lines),
            style=style,
            lines=all_lines,
            line_groups=groups,
            can_split=len(groups) > 1,
            space_before=12.0,
            space_after=12.0,
        )

    def _measure_svg(self, element, width: float) -> MeasuredBlock:
        from ..svg import parse_svg

        style = self.sheet.resolved(self.sheet.body, element.style)
        svg = parse_svg(element.source)
        display_w = element.width or min(svg.width, width)
        if display_w > width:
            display_w = width
        scale = display_w / svg.aspect_width if svg.aspect_width else 1.0
        display_h = element.height or svg.aspect_height * scale
        total = display_h
        if element.caption:
            cap_size = self._size(style) * 0.85
            total += cap_size + 4.0
        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=8.0,
            space_after=8.0,
        )

    # -- front matter --

    COVER_RULE_WIDTH = 64.0
    ABSTRACT_INDENT = 40.0
    PULLQUOTE_INDENT = 26.0
    STAT_TILE_GAP = 12.0

    def _measure_cover(self, element, width: float) -> MeasuredBlock:
        sheet = self.sheet
        body = sheet.resolved(sheet.body, element.style)
        h1 = sheet.resolved(sheet.h1, element.style)
        body_size = body.require("font_size")
        accent = self._accent_color()
        muted = self._muted_color()
        heading_color = h1.require("color")
        body_color = body.require("color")

        parts: list = []

        def add(text, size, color, gap, *, bold=False, italic=False):
            if not text:
                return
            lines = self._styled_lines(
                text, body, width, size, bold=bold, italic=italic, color=color
            )
            parts.append({"lines": lines, "gap": gap})

        if element.kicker:
            add(element.kicker.upper(), body_size * 0.95, accent, 14.0, bold=True)
        add(
            element.title,
            h1.require("font_size") * 1.25,
            heading_color,
            12.0,
            bold=True,
        )
        parts.append({"rule": accent, "gap": 16.0})
        if element.subtitle:
            add(element.subtitle, body_size * 1.3, muted, 22.0, italic=True)
        authors = [str(a) for a in element.authors if str(a)]
        if authors:
            add("    ".join(authors), body_size * 1.05, body_color, 6.0)
        if element.date:
            add(element.date, body_size * 0.95, muted, 0.0)

        return MeasuredBlock(
            element=element,
            height=0.0,
            style=body,
            full_page=True,
            extras={"cover": parts, "width": width},
        )

    def _measure_abstract(self, element, width: float) -> MeasuredBlock:
        sheet = self.sheet
        style = sheet.resolved(sheet.body, element.style)
        size = style.require("font_size")
        indent = self.ABSTRACT_INDENT
        usable = max(72.0, width - 2 * indent)
        accent = self._accent_color()

        label_lines = self._styled_lines(
            "ABSTRACT",
            style,
            usable,
            size * 0.82,
            bold=True,
            color=accent,
            align="left",
        )
        body_lines = self._styled_lines(
            element.text, style, usable, size * 0.95, align=style.require("align")
        )
        keyword_lines: list = []
        keywords = [str(k) for k in element.keywords if str(k)]
        if keywords:
            kw_text = "Keywords: " + ", ".join(keywords)
            keyword_lines = self._styled_lines(
                kw_text, style, usable, size * 0.85, italic=True, align="left"
            )

        total = 4.0
        total += sum(line.height for line in label_lines)
        total += sum(line.height for line in body_lines)
        if keyword_lines:
            total += 6.0 + sum(line.height for line in keyword_lines)

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=10.0,
            space_after=12.0,
            extras={
                "abstract": {
                    "indent": indent,
                    "label": label_lines,
                    "body": body_lines,
                    "keywords": keyword_lines,
                }
            },
        )

    def _measure_authors(self, element, width: float) -> MeasuredBlock:
        sheet = self.sheet
        style = sheet.resolved(sheet.body, element.style)
        size = style.require("font_size")
        muted = self._muted_color()
        authors = element.author_list
        if not authors:
            return MeasuredBlock(element=element, height=0.0, style=style)

        cols = min(len(authors), 3)
        col_w = width / cols
        cell_w = col_w - 12.0

        cells: list = []
        for author in authors:
            lines: list = []
            lines += self._styled_lines(
                author.name, style, cell_w, size * 1.05, bold=True
            )
            if author.affiliation:
                lines += self._styled_lines(
                    author.affiliation, style, cell_w, size * 0.9, color=muted
                )
            if author.email:
                lines += self._styled_lines(
                    author.email, style, cell_w, size * 0.85, italic=True, color=muted
                )
            cells.append(lines)

        rows = [cells[i : i + cols] for i in range(0, len(cells), cols)]
        row_heights = [
            max(sum(line.height for line in cell) for cell in row) for row in rows
        ]
        total = sum(row_heights) + 10.0 * (len(rows) - 1)

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=8.0,
            space_after=12.0,
            extras={"authors": {"rows": rows, "cols": cols, "col_w": col_w}},
        )

    def _measure_pullquote(self, element, width: float) -> MeasuredBlock:
        sheet = self.sheet
        style = sheet.resolved(sheet.body, element.style)
        size = style.require("font_size")
        accent = self._accent_color()
        indent = self.PULLQUOTE_INDENT
        usable = max(72.0, width - 2 * indent)

        lines = self._styled_lines(
            element.text, style, usable, size * 1.5, italic=True, color=accent
        )
        attr_lines: list = []
        if element.attribution:
            attr_text = "— " + element.attribution
            attr_lines = self._styled_lines(
                attr_text, style, usable, size * 0.95, color=self._muted_color()
            )

        total = 12.0 + sum(line.height for line in lines)
        if attr_lines:
            total += 6.0 + sum(line.height for line in attr_lines)

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=14.0,
            space_after=14.0,
            extras={
                "pullquote": {
                    "indent": indent,
                    "usable": usable,
                    "lines": lines,
                    "attr": attr_lines,
                    "accent": accent,
                }
            },
        )

    def _measure_stat_tiles(self, element, width: float) -> MeasuredBlock:
        sheet = self.sheet
        style = sheet.resolved(sheet.body, element.style)
        size = style.require("font_size")
        accent = self._accent_color()
        muted = self._muted_color()
        stats = element.stat_list
        if not stats:
            return MeasuredBlock(element=element, height=0.0, style=style)

        n = len(stats)
        gap = self.STAT_TILE_GAP
        tile_w = (width - gap * (n - 1)) / n
        pad = 10.0
        inner = tile_w - 2 * pad

        from ..spec import TextRun as _TextRun

        reg_metrics = self._metrics(style)
        bold_metrics = self._metrics(style, _TextRun("", bold=True))

        def _fit(text: str, base: float, floor: float, m) -> float:
            """Shrink the font so the widest word fits, never breaking a word.

            Measures with the weight the value renders in, so a bold value
            is not sized against the narrower regular metrics.
            """
            target = inner * 0.92
            words = text.split() or [text]
            widest = max((m.text_width(w, base) for w in words), default=0.0)
            if widest <= target or widest <= 0 or target <= 0:
                return base
            return max(floor, base * target / widest)

        tiles: list = []
        content_h = 0.0
        for stat in stats:
            value_size = _fit(stat.value, size * 1.9, size, bold_metrics)
            label_size = _fit(stat.label.upper(), size * 0.78, size * 0.6, reg_metrics)
            value_lines = self._styled_lines(
                stat.value, style, inner, value_size, bold=True, color=accent
            )
            label_lines = self._styled_lines(
                stat.label.upper(), style, inner, label_size, color=muted
            )
            delta_lines: list = []
            delta_color = muted
            if stat.delta:
                delta_color = _delta_color(stat.delta, muted)
                delta_lines = self._styled_lines(
                    stat.delta, style, inner, size * 0.85, color=delta_color
                )
            tile_content = (
                sum(line.height for line in value_lines)
                + sum(line.height for line in label_lines)
                + sum(line.height for line in delta_lines)
            )
            content_h = max(content_h, tile_content)
            tiles.append(
                {
                    "value": value_lines,
                    "label": label_lines,
                    "delta": delta_lines,
                    "delta_color": delta_color,
                }
            )

        tile_h = content_h + 2 * pad + 6.0
        return MeasuredBlock(
            element=element,
            height=tile_h,
            style=style,
            can_split=False,
            space_before=10.0,
            space_after=12.0,
            extras={
                "stattiles": {
                    "tiles": tiles,
                    "tile_w": tile_w,
                    "gap": gap,
                    "pad": pad,
                    "tile_h": tile_h,
                    "accent": accent,
                }
            },
        )

    # -- visible table of contents --

    TOC_INDENT_STEP = 16.0
    TOC_LEADER_GAP = 6.0

    def measure_toc(self, element, width: float, rows: list) -> MeasuredBlock:
        """Lay out a visible contents listing with dot leaders.

        `rows` are (text, level, page_label, link_key) tuples; the caller
        supplies real page labels after each pagination pass.
        """
        sheet = self.sheet
        style = sheet.resolved(sheet.body, element.style)
        size = style.require("font_size")
        muted = self._muted_color()
        title_style = sheet.resolved(sheet.h2, element.style)

        lines: list = []
        title_lines = self._styled_lines(
            element.title,
            style,
            width,
            title_style.require("font_size"),
            bold=True,
            color=title_style.require("color"),
            align="left",
        )
        for line in title_lines:
            line.height += 6.0
        lines.extend(title_lines)

        entry_metrics = self._metrics(style)
        dot_w = entry_metrics.text_width(".", size)
        for text, level, page_label, link_key in rows:
            indent = (max(1, level) - 1) * self.TOC_INDENT_STEP
            text_run = TextRun(text, link=f"#{link_key}" if link_key else None)
            num_run = TextRun(page_label or "")
            entry_metrics.note_usage(text)
            entry_metrics.note_usage(page_label or "")
            text_w = entry_metrics.text_width(text, size)
            max_text_w = width - indent - 48.0
            if text_w > max_text_w and max_text_w > 0:
                text, text_w = self._truncate(text, entry_metrics, size, max_text_w)
                text_run = TextRun(text, link=f"#{link_key}" if link_key else None)
            num_w = entry_metrics.text_width(page_label or "", size)
            num_x = width - num_w
            text_x = indent
            leader_start = text_x + text_w + self.TOC_LEADER_GAP
            leader_end = num_x - self.TOC_LEADER_GAP
            fragments = [(text, text_run, text_x)]
            if dot_w > 0 and leader_end > leader_start:
                dot_count = int((leader_end - leader_start) // dot_w)
                if dot_count > 0:
                    dots = "." * dot_count
                    dot_x = num_x - self.TOC_LEADER_GAP - dot_count * dot_w
                    fragments.append((dots, TextRun(dots, color=muted), dot_x))
            if page_label:
                fragments.append((page_label, num_run, num_x))
            line_height = entry_metrics.line_height(size, style.require("line_height"))
            lines.append(
                LaidOutLine(
                    fragments=fragments,
                    width=width,
                    height=line_height,
                    ascent=entry_metrics.ascent(size),
                )
            )

        return MeasuredBlock(
            element=element,
            height=sum(line.height for line in lines),
            style=style,
            lines=lines,
            can_split=len(lines) > (self.MIN_WIDOW_LINES + self.MIN_ORPHAN_LINES),
            space_before=10.0,
            space_after=12.0,
        )

    INDEX_COLUMN_GAP = 24.0

    def measure_index(self, element, width: float, rows: list) -> MeasuredBlock:
        """Lay out a two-column back-of-book index.

        `rows` are (term, comma_joined_pages) tuples, alphabetized by the
        caller, with real page numbers filled in after each pagination
        pass of the same two-pass loop the visible TOC uses.
        """
        sheet = self.sheet
        style = sheet.resolved(sheet.body, element.style)
        size = style.require("font_size") * 0.92
        title_style = sheet.resolved(sheet.h2, element.style)

        title_lines = self._styled_lines(
            element.title,
            style,
            width,
            title_style.require("font_size"),
            bold=True,
            color=title_style.require("color"),
            align="left",
        )
        for line in title_lines:
            line.height += 8.0

        gap = self.INDEX_COLUMN_GAP
        col_w = (width - gap) / 2.0
        entry_metrics = self._metrics(style)
        line_height = entry_metrics.line_height(size, style.require("line_height"))

        entry_lines: list = []
        for term, pages_label in rows:
            rest = f", {pages_label}" if pages_label else ""
            term_run = TextRun(term, bold=True, font_size=size)
            rest_run = TextRun(rest, font_size=size)
            entry_metrics.note_usage(term)
            if rest:
                entry_metrics.note_usage(rest)
            term_w = entry_metrics.text_width(term, size)
            fragments = [(term, term_run, 0.0)]
            if rest:
                fragments.append((rest, rest_run, term_w))
            entry_lines.append(
                LaidOutLine(
                    fragments=fragments,
                    width=col_w,
                    height=line_height,
                    ascent=entry_metrics.ascent(size),
                )
            )

        half = -(-len(entry_lines) // 2)  # ceil division
        left_col = entry_lines[:half]
        right_col = entry_lines[half:]
        col_height = max(
            sum(line.height for line in left_col),
            sum(line.height for line in right_col),
        )
        total = sum(line.height for line in title_lines) + col_height

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=False,
            space_before=12.0,
            space_after=12.0,
            extras={
                "index": {
                    "title_lines": title_lines,
                    "left": left_col,
                    "right": right_col,
                    "col_w": col_w,
                    "gap": gap,
                }
            },
        )

    @staticmethod
    def _truncate(text, metrics, size, max_w) -> tuple:
        """Trim text to fit `max_w`, appending an ellipsis; returns (text, w)."""
        ell = "…"
        ell_w = metrics.text_width(ell, size)
        out = ""
        w = 0.0
        for ch in text:
            cw = metrics.text_width(ch, size)
            if w + cw + ell_w > max_w:
                break
            out += ch
            w += cw
        out = out.rstrip() + ell
        return out, metrics.text_width(out, size)

    # -- tables --

    @staticmethod
    def _grid_column_count(element) -> int:
        """Number of grid columns once colspans are expanded."""
        counts = [sum(max(1, cell.colspan) for cell in element.header_cells)]
        for row in element.body_rows:
            counts.append(sum(max(1, cell.colspan) for cell in row))
        return max(counts) if counts else 0

    @staticmethod
    def _grid_cells(cells: list, columns: int) -> tuple:
        """Place row cells on the grid: (cells by column, span-per-column).

        Spans are the cell's colspan at its start column, 0 for columns a
        span covers, and 1 for columns the row simply does not reach.
        """
        grid: list = [None] * columns
        spans: list = [1] * columns
        col = 0
        for cell in cells:
            if col >= columns:
                break
            span = min(max(1, int(cell.colspan)), columns - col)
            grid[col] = cell
            spans[col] = span
            for covered in range(col + 1, col + span):
                spans[covered] = 0
            col += span
        return grid, spans

    def _decimal_widths(self, cell, style) -> tuple:
        """Widths of a cell's integer and fraction parts, split at the last dot."""
        text = "".join(run.text for run in cell.runs)
        cut = text.rfind(".")
        if cut < 0:
            cut = len(text)
        int_w = frac_w = 0.0
        pos = 0
        for run in cell.runs:
            metrics = self._metrics(style, run)
            size = self._size(style, run)
            end = pos + len(run.text)
            if end <= cut:
                int_w += metrics.text_width(run.text, size)
            elif pos >= cut:
                frac_w += metrics.text_width(run.text, size)
            else:
                split = cut - pos
                int_w += metrics.text_width(run.text[:split], size)
                frac_w += metrics.text_width(run.text[split:], size)
            pos = end
        return int_w, frac_w

    def _decimal_column_extents(self, element, style, columns: int) -> tuple:
        """Per-column max integer- and fraction-part widths of decimal cells."""
        header_aligns: list = [None] * columns
        if element.header_cells:
            grid, spans = self._grid_cells(element.header_cells, columns)
            for index in range(columns):
                cell = grid[index]
                if cell is None:
                    continue
                for col in range(index, index + max(1, spans[index])):
                    if col < columns and header_aligns[col] is None:
                        header_aligns[col] = cell.align
        int_max = [0.0] * columns
        frac_max = [0.0] * columns
        for row in element.body_rows:
            grid, spans = self._grid_cells(row, columns)
            for index in range(columns):
                cell = grid[index]
                if cell is None or spans[index] == 0:
                    continue
                effective = (
                    cell.align if cell.align is not None else header_aligns[index]
                )
                if effective != "decimal":
                    continue
                int_w, frac_w = self._decimal_widths(cell, style)
                int_max[index] = max(int_max[index], int_w)
                frac_max[index] = max(frac_max[index], frac_w)
        return int_max, frac_max

    def _caption_allowance(self, style) -> float:
        """Vertical space a table caption occupies below the last rule."""
        return self._size(style) * 0.85 + 8.0

    def _measure_table(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.table_cell, element.style)
        header_style = self.sheet.resolved(self.sheet.table_header)
        pad_x = self.sheet.table_cell_padding_x
        pad_y = self.sheet.table_cell_padding_y

        columns = self._grid_column_count(element)
        if columns == 0:
            return MeasuredBlock(element=element, height=0.0, style=style)

        widths = self._solve_columns(element, style, header_style, width, pad_x)
        _int_max, frac_max = self._decimal_column_extents(element, style, columns)

        header_cells = element.header_cells
        header_lines: list = []
        header_spans: list | None = None
        header_height = 0.0
        col_aligns: list = [None] * columns
        if header_cells:
            grid, spans = self._grid_cells(header_cells, columns)
            count = columns
            while count and grid[count - 1] is None and spans[count - 1] == 1:
                count -= 1
            header_spans = spans[:count]
            for index in range(count):
                cell = grid[index]
                if cell is None:
                    header_lines.append([])
                    continue
                span = spans[index]
                available = sum(widths[index : index + span]) - 2 * pad_x
                for col in range(index, index + span):
                    col_aligns[col] = cell.align
                cell_style = header_style.with_(align=_cell_align(cell.align, None))
                lines = self._layout_runs(cell.runs, cell_style, available)
                for run in cell.runs:
                    self._metrics(cell_style, run).note_usage(run.text)
                header_lines.append(lines)
                header_height = max(header_height, sum(line.height for line in lines))
            header_height += 2 * pad_y

        row_lines, row_spans, row_heights = [], [], []
        for row in element.body_rows:
            grid, spans = self._grid_cells(row, columns)
            cells: list = []
            height = 0.0
            for index in range(columns):
                cell = grid[index]
                if cell is None:
                    cells.append([])
                    continue
                span = spans[index]
                available = sum(widths[index : index + span]) - 2 * pad_x
                header_align = col_aligns[index] if index < len(col_aligns) else None
                effective = cell.align if cell.align is not None else header_align
                if effective == "decimal":
                    cell_style = style.with_(align="left")
                else:
                    cell_style = style.with_(
                        align=_cell_align(cell.align, header_align)
                    )
                lines = self._layout_runs(cell.runs, cell_style, available)
                if effective == "decimal":
                    int_w, _frac_w = self._decimal_widths(cell, style)
                    shift = max(0.0, available - frac_max[index] - int_w)
                    if shift:
                        for line in lines:
                            line.fragments = [
                                (t, r, x + shift) for t, r, x in line.fragments
                            ]
                for run in cell.runs:
                    self._metrics(cell_style, run).note_usage(run.text)
                cells.append(lines)
                height = max(height, sum(line.height for line in lines))
            row_lines.append(cells)
            row_spans.append(spans)
            row_heights.append(height + 2 * pad_y)

        layout = TableLayout(
            column_widths=widths,
            header_height=header_height,
            row_heights=row_heights,
            header_lines=header_lines,
            row_lines=row_lines,
            header_spans=header_spans,
            row_spans=row_spans,
        )
        total = header_height + sum(row_heights)
        if element.caption:
            total += self._caption_allowance(style)
        headline_h, subtitle_h, source_h = annotation_heights(
            element.headline, element.subtitle, element.source_line, style
        )
        total += headline_h + subtitle_h + source_h

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=len(row_heights) > self.MIN_TABLE_ROWS_PER_PAGE,
            space_before=8.0,
            space_after=12.0,
            table=layout,
        )

    @staticmethod
    def _raise_to(values: list, start: int, end: int, needed: float) -> None:
        """Raise values[start:end] proportionally so their sum reaches needed."""
        total = sum(values[start:end])
        if end <= start or total >= needed:
            return
        deficit = needed - total
        for index in range(start, end):
            share = values[index] / total if total > 0 else 1.0 / (end - start)
            values[index] += deficit * share

    def _solve_columns(
        self, element, style, header_style, width: float, pad_x: float
    ) -> list:
        """Compute column widths from actual content metrics.

        Minimum width is the widest single word (so text never overflows);
        preferred width is the longest unwrapped cell. A spanning cell
        constrains the sum of its columns. Available space is distributed
        between the minimum and preferred widths.
        """
        columns = self._grid_column_count(element)
        if element.column_widths:
            total = sum(element.column_widths)
            return [width * (w / total) for w in element.column_widths]

        minimums = [0.0] * columns
        preferred = [0.0] * columns
        span_constraints: list = []

        def consider(index: int, span: int, text: str, cell_style) -> None:
            if index >= columns:
                return
            metrics = self._metrics(cell_style)
            size = self._size(cell_style)
            full = metrics.text_width(text, size) + 2 * pad_x
            widest_word = max(
                (metrics.text_width(word, size) for word in text.split()),
                default=0.0,
            )
            if span > 1:
                span_constraints.append((index, span, widest_word + 2 * pad_x, full))
                return
            preferred[index] = max(preferred[index], full)
            minimums[index] = max(minimums[index], widest_word + 2 * pad_x)

        grid, spans = self._grid_cells(element.header_cells, columns)
        for index in range(columns):
            if grid[index] is not None:
                consider(index, spans[index], grid[index].plain_text, header_style)
        for row in element.body_rows:
            grid, spans = self._grid_cells(row, columns)
            for index in range(columns):
                if grid[index] is not None:
                    consider(index, spans[index], grid[index].plain_text, style)

        int_max, frac_max = self._decimal_column_extents(element, style, columns)
        for index in range(columns):
            need = int_max[index] + frac_max[index]
            if need > 0.0:
                need += 2 * pad_x
                preferred[index] = max(preferred[index], need)
                minimums[index] = max(minimums[index], need)

        for index in range(columns):
            if preferred[index] == 0.0:
                preferred[index] = minimums[index] = 36.0

        for start, span, min_need, pref_need in span_constraints:
            end = min(start + span, columns)
            self._raise_to(minimums, start, end, min_need)
            self._raise_to(preferred, start, end, pref_need)
        for index in range(columns):
            preferred[index] = max(preferred[index], minimums[index])

        total_preferred = sum(preferred)
        if total_preferred <= width:
            slack = width - total_preferred
            return [w + slack * (w / total_preferred) for w in preferred]

        total_minimum = sum(minimums)
        if total_minimum <= width:
            slack = width - total_minimum
            spread = total_preferred - total_minimum
            return [
                minimums[i] + slack * ((preferred[i] - minimums[i]) / spread)
                if spread > 0
                else minimums[i] + slack / columns
                for i in range(columns)
            ]

        # Content genuinely cannot fit: scale everything down proportionally
        # and let cell text wrap.
        return [width * (m / total_minimum) for m in minimums]

    # -- baseline grid --

    _GRID_SNAP_TYPES = (Heading, Paragraph, BlockQuote, BibliographyBlock, Footnote)

    def _grid_snap_delta(self, block: MeasuredBlock, top: float, page_spec) -> float:
        """Downward shift putting the block's first baseline on the grid."""
        grid = getattr(self.sheet, "baseline_grid", None)
        if not grid or not block.lines:
            return 0.0
        if not isinstance(block.element, self._GRID_SNAP_TYPES):
            return 0.0
        baseline = top - block.lines[0].ascent
        offset = page_spec.content_top - baseline
        delta = (-offset) % grid
        if grid - delta < 1e-6:
            delta = 0.0
        return delta

    # -- float helpers --

    @staticmethod
    def _get_float_type(block: MeasuredBlock) -> str | None:
        element = block.element
        if isinstance(element, _FLOATABLE_TYPES):
            ft = getattr(element, "float", None)
            if ft and ft != "here":
                return ft
        return None

    # -- pagination --

    def _attach_footnotes(self, blocks: list) -> list:
        """Attach footnote blocks to their nearest preceding text block."""
        if not any(isinstance(block.element, Footnote) for block in blocks):
            return blocks
        out: list = []
        orphans: list = []
        last_attachable: MeasuredBlock | None = None
        for block in blocks:
            if isinstance(block.element, Footnote):
                if last_attachable is not None:
                    last_attachable.footnotes.append(block)
                else:
                    orphans.append(block)
                continue
            attachable = (
                not isinstance(block.element, PageBreak)
                and self._get_float_type(block) is None
            )
            if attachable and orphans:
                block.footnotes.extend(orphans)
                orphans = []
            if attachable:
                last_attachable = block
            out.append(block)
        if last_attachable is None:
            # Nothing to anchor to: keep the notes flowing in place.
            return blocks
        if orphans:
            last_attachable.footnotes.extend(orphans)
        return out

    def paginate(self, blocks: list, page_spec) -> list:
        blocks = self._attach_footnotes(blocks)
        has_footnotes = any(block.footnotes for block in blocks)
        if page_spec.columns > 1:
            pages = self._paginate_multicolumn(blocks, page_spec)
            self._mark_chrome_suppression(pages)
            return pages
        pages = self._paginate_single(blocks, page_spec)
        # The two-pass optimizer reflows without grid awareness (and without
        # footnote-reservation awareness), so it is skipped in both cases.
        if (
            self.optimize_layout
            and not getattr(self.sheet, "baseline_grid", None)
            and not has_footnotes
        ):
            pages = self._optimize_pages(pages, page_spec)
        self._mark_chrome_suppression(pages)
        return pages

    @staticmethod
    def _mark_chrome_suppression(pages: list) -> None:
        """Suppress running header/footer on any page holding a cover."""
        for page in pages:
            if any(isinstance(pb.block.element, CoverPage) for pb in page.blocks):
                page.suppress_chrome = True

    def _paginate_multicolumn(self, blocks: list, page_spec) -> list:
        cols = page_spec.columns
        gap = page_spec.column_gap
        total_w = page_spec.content_width
        col_w = (total_w - gap * (cols - 1)) / cols

        pages: list = []
        current = Page(number=1, cursor=page_spec.content_top, spec=page_spec)
        col_cursors = [page_spec.content_top] * cols
        col_idx = 0
        col_fn_pending: list = [[] for _ in range(cols)]
        col_fn_reserved: list = [0.0] * cols
        # Column-flowed blocks on the current page, used to rebalance the
        # final page after the greedy pass.
        flow_blocks: list = []
        flow_placed: list = []
        flow_top = page_spec.content_top

        def col_left(c: int) -> float:
            return page_spec.margin_left + c * (col_w + gap)

        def _footnote_extra(block, c: int) -> float:
            if not block.footnotes:
                return 0.0
            extra = sum(note.height for note in block.footnotes)
            if not col_fn_pending[c]:
                extra += self.FOOTNOTE_SEPARATION
            return extra

        def _register_footnotes(block, c: int, extra: float) -> None:
            if block.footnotes:
                col_fn_pending[c].extend(block.footnotes)
                col_fn_reserved[c] += extra

        def _flush_footnotes() -> None:
            for c in range(cols):
                pending = col_fn_pending[c]
                if not pending:
                    continue
                y = page_spec.content_bottom + sum(note.height for note in pending)
                for position, note in enumerate(pending):
                    current.footnotes.append(
                        PlacedFootnote(
                            block=note,
                            x=col_left(c),
                            y=y,
                            width=col_w,
                            separator=position == 0,
                        )
                    )
                    y -= note.height
                col_fn_pending[c] = []
                col_fn_reserved[c] = 0.0

        def _is_spanning(block) -> bool:
            style = getattr(block.element, "style", None)
            if style and getattr(style, "column_span", None):
                return True
            if isinstance(block.element, (Heading,)) and block.element.level <= 2:
                return False
            return False

        def _new_page():
            nonlocal current, col_idx, col_cursors
            nonlocal flow_blocks, flow_placed, flow_top
            _flush_footnotes()
            pages.append(current)
            current = Page(
                number=len(pages) + 1, cursor=page_spec.content_top, spec=page_spec
            )
            col_cursors = [page_spec.content_top] * cols
            col_idx = 0
            flow_blocks = []
            flow_placed = []
            flow_top = page_spec.content_top

        def _place(block, x, y):
            return PlacedBlock(
                block=block,
                x=x,
                y=y,
                height=block.height,
                lines=block.lines,
                table_rows=list(range(len(block.table.row_heights)))
                if block.table
                else None,
            )

        def _flow_place(block, c, y):
            placed = _place(block, col_left(c), y)
            current.blocks.append(placed)
            flow_blocks.append(block)
            flow_placed.append(placed)

        for block in blocks:
            if isinstance(block.element, PageBreak):
                _new_page()
                continue

            if block.full_page:
                if current.blocks:
                    _new_page()
                current.suppress_chrome = True
                current.blocks.append(
                    PlacedBlock(
                        block=block,
                        x=page_spec.margin_left,
                        y=page_spec.content_top,
                        height=page_spec.content_height,
                        lines=block.lines,
                    )
                )
                _new_page()
                continue

            if _is_spanning(block):
                lowest = min(col_cursors)
                gap_before = block.space_before
                gap_before += self._grid_snap_delta(
                    block, lowest - gap_before, page_spec
                )
                available = lowest - page_spec.content_bottom - gap_before
                if block.height > available:
                    _new_page()
                    lowest = page_spec.content_top
                    gap_before = block.space_before
                    gap_before += self._grid_snap_delta(
                        block, lowest - gap_before, page_spec
                    )
                y = lowest - gap_before
                current.blocks.append(_place(block, page_spec.margin_left, y))
                new_cursor = y - block.height - block.space_after
                col_cursors = [new_cursor] * cols
                col_idx = 0
                flow_blocks = []
                flow_placed = []
                flow_top = new_cursor
                continue

            gap_before = block.space_before if current.blocks else 0.0
            gap_before += self._grid_snap_delta(
                block, col_cursors[col_idx] - gap_before, page_spec
            )
            fn_extra = _footnote_extra(block, col_idx)
            available = (
                col_cursors[col_idx]
                - page_spec.content_bottom
                - gap_before
                - col_fn_reserved[col_idx]
            )

            if block.height + fn_extra <= available:
                col_cursors[col_idx] -= gap_before
                _flow_place(block, col_idx, col_cursors[col_idx])
                _register_footnotes(block, col_idx, fn_extra)
                col_cursors[col_idx] -= block.height + block.space_after
                continue

            col_idx += 1
            if col_idx < cols:
                col_cursors[col_idx] -= self._grid_snap_delta(
                    block, col_cursors[col_idx], page_spec
                )
                _flow_place(block, col_idx, col_cursors[col_idx])
                _register_footnotes(block, col_idx, _footnote_extra(block, col_idx))
                col_cursors[col_idx] -= block.height + block.space_after
                continue

            _new_page()
            col_cursors[0] -= self._grid_snap_delta(block, col_cursors[0], page_spec)
            _flow_place(block, 0, col_cursors[0])
            _register_footnotes(block, 0, _footnote_extra(block, 0))
            col_cursors[0] -= block.height + block.space_after

        _flush_footnotes()
        if current.blocks or not pages:
            pages.append(current)
            if cols > 1 and len(flow_blocks) > 1 and not current.footnotes:
                self._balance_last_page(
                    current,
                    flow_blocks,
                    flow_placed,
                    flow_top,
                    cols,
                    col_left,
                    page_spec,
                )
        return pages

    def _flow_columns(
        self,
        blocks: list,
        flow_top: float,
        height: float,
        cols: int,
        page_spec,
        first_gap: bool,
    ) -> list | None:
        """First-fit blocks into columns of `height`; None when they overflow."""
        placements: list = []
        col = 0
        used = 0.0
        for index, block in enumerate(blocks):
            before = block.space_before if (index > 0 or first_gap) else 0.0
            before += self._grid_snap_delta(block, flow_top - used - before, page_spec)
            if used + before + block.height <= height + 1e-6:
                placements.append((block, col, flow_top - used - before))
                used += before + block.height + block.space_after
                continue
            col += 1
            if col >= cols:
                return None
            delta = self._grid_snap_delta(block, flow_top, page_spec)
            if delta + block.height > height + 1e-6:
                return None
            placements.append((block, col, flow_top - delta))
            used = delta + block.height + block.space_after
        return placements

    def _balance_last_page(
        self,
        page,
        blocks: list,
        placed: list,
        flow_top: float,
        cols: int,
        col_left,
        page_spec,
    ) -> None:
        """Reflow the final page's columns at the minimal balanced height."""
        max_h = flow_top - page_spec.content_bottom
        if max_h <= 0:
            return
        first_gap = len(page.blocks) > len(placed)

        def fits(h: float) -> list | None:
            return self._flow_columns(blocks, flow_top, h, cols, page_spec, first_gap)

        if fits(max_h) is None:
            return
        low, high = 0.0, max_h
        for _ in range(60):
            mid = (low + high) / 2.0
            if fits(mid) is not None:
                high = mid
            else:
                low = mid
        result = fits(high)
        if result is None:
            return
        placed_ids = {id(pb) for pb in placed}
        kept = [pb for pb in page.blocks if id(pb) not in placed_ids]
        page.blocks = kept + [
            PlacedBlock(
                block=block,
                x=col_left(col),
                y=y,
                height=block.height,
                lines=block.lines,
                table_rows=list(range(len(block.table.row_heights)))
                if block.table
                else None,
            )
            for block, col, y in result
        ]

    def _paginate_single(self, blocks: list, page_spec) -> list:
        pages: list = []
        current = Page(number=1, cursor=page_spec.content_top, spec=page_spec)
        left = page_spec.margin_left
        content_height = page_spec.content_height

        float_queue: list[_FloatEntry] = []
        bottom_floats: list[_FloatEntry] = []
        bottom_reserved: float = 0.0
        fn_pending: list = []
        fn_reserved: float = 0.0
        measure_w = page_spec.content_width

        def _eff_remaining() -> float:
            return current.cursor - (
                page_spec.content_bottom + bottom_reserved + fn_reserved
            )

        def _footnote_extra(block) -> float:
            if not block.footnotes:
                return 0.0
            extra = sum(note.height for note in block.footnotes)
            if not fn_pending:
                extra += self.FOOTNOTE_SEPARATION
            return extra

        def _register_footnotes(block, extra: float) -> None:
            nonlocal fn_reserved
            if block.footnotes:
                fn_pending.extend(block.footnotes)
                fn_reserved += extra

        def _flush_footnotes() -> None:
            nonlocal fn_pending, fn_reserved
            if not fn_pending:
                return
            y = page_spec.content_bottom + sum(note.height for note in fn_pending)
            for position, note in enumerate(fn_pending):
                current.footnotes.append(
                    PlacedFootnote(
                        block=note,
                        x=left,
                        y=y,
                        width=measure_w,
                        separator=position == 0,
                    )
                )
                y -= note.height
            fn_pending = []
            fn_reserved = 0.0

        def _place_bottom_floats() -> None:
            if not bottom_floats:
                return
            y = page_spec.content_bottom + fn_reserved
            for entry in bottom_floats:
                blk = entry.block
                y += blk.height
                current.blocks.append(
                    PlacedBlock(
                        block=blk,
                        x=left,
                        y=y,
                        height=blk.height,
                        lines=blk.lines,
                    )
                )
                y += blk.space_before

        def _start_new_page() -> None:
            nonlocal current, bottom_floats, bottom_reserved
            _place_bottom_floats()
            _flush_footnotes()
            pages.append(current)
            current = Page(
                number=len(pages) + 1, cursor=page_spec.content_top, spec=page_spec
            )
            bottom_floats = []
            bottom_reserved = 0.0
            _flush_top_floats()

        def _flush_top_floats() -> None:
            nonlocal float_queue
            remaining: list[_FloatEntry] = []
            for entry in float_queue:
                blk = entry.block
                gap_f = blk.space_before if current.blocks else 0.0
                needed = blk.height + gap_f
                if needed <= _eff_remaining():
                    current.cursor -= gap_f
                    current.blocks.append(
                        PlacedBlock(
                            block=blk,
                            x=left,
                            y=current.cursor,
                            height=blk.height,
                            lines=blk.lines,
                        )
                    )
                    current.cursor -= blk.height + blk.space_after
                else:
                    remaining.append(entry)
            float_queue = remaining

        def _force_overdue_floats() -> None:
            nonlocal float_queue
            current_page_num = len(pages) + 1
            remaining: list[_FloatEntry] = []
            for entry in float_queue:
                if current_page_num - entry.origin_page > self.FLOAT_MAX_DRIFT:
                    blk = entry.block
                    gap_f = blk.space_before if current.blocks else 0.0
                    if blk.height + gap_f > _eff_remaining():
                        _start_new_page()
                        gap_f = blk.space_before if current.blocks else 0.0
                    current.cursor -= gap_f
                    current.blocks.append(
                        PlacedBlock(
                            block=blk,
                            x=left,
                            y=current.cursor,
                            height=blk.height,
                            lines=blk.lines,
                        )
                    )
                    current.cursor -= blk.height + blk.space_after
                else:
                    remaining.append(entry)
            float_queue = remaining

        index = 0
        while index < len(blocks):
            block = blocks[index]

            if block.full_page:
                if current.blocks:
                    _start_new_page()
                current.suppress_chrome = True
                current.blocks.append(
                    PlacedBlock(
                        block=block,
                        x=left,
                        y=page_spec.content_top,
                        height=content_height,
                        lines=block.lines,
                    )
                )
                current.cursor = page_spec.content_bottom
                _start_new_page()
                index += 1
                continue

            if float_queue:
                _force_overdue_floats()

            if isinstance(block.element, PageBreak):
                _start_new_page()
                index += 1
                continue

            float_type = self._get_float_type(block)
            if float_type:
                current_page_num = len(pages) + 1
                if float_type == "top":
                    float_queue.append(
                        _FloatEntry(
                            block=block,
                            float_type="top",
                            origin_page=current_page_num,
                        )
                    )
                    index += 1
                    continue
                elif float_type == "bottom":
                    needed = block.height + block.space_before
                    min_text = self.FLOAT_MIN_TEXT_SPACE * content_height
                    if needed + min_text <= _eff_remaining():
                        bottom_reserved += needed
                        bottom_floats.append(
                            _FloatEntry(
                                block=block,
                                float_type="bottom",
                                origin_page=current_page_num,
                            )
                        )
                    else:
                        float_queue.append(
                            _FloatEntry(
                                block=block,
                                float_type="top",
                                origin_page=current_page_num,
                            )
                        )
                    index += 1
                    continue
                elif float_type == "auto":
                    frac = _eff_remaining() / content_height if content_height else 0
                    if frac < self.FLOAT_AUTO_THRESHOLD:
                        float_queue.append(
                            _FloatEntry(
                                block=block,
                                float_type="top",
                                origin_page=current_page_num,
                            )
                        )
                        index += 1
                        continue

            if block.style.page_break_before and current.blocks:
                _start_new_page()

            gap = block.space_before if current.blocks else 0.0
            available = current.remaining() - gap - fn_reserved

            # Heading that would be stranded at the foot of a page.
            if block.keep_with_next and index + 1 < len(blocks):
                nxt = blocks[index + 1]
                needed = block.height + min(nxt.height, self.KEEP_WITH_NEXT_LOOKAHEAD)
                if needed > available and current.blocks:
                    _start_new_page()
                    gap = 0.0
                    available = current.remaining()

            # Baseline grid: absorb the snap into the gap before the block
            # so every remaining-height check sees the snapped position.
            snap = self._grid_snap_delta(block, current.cursor - gap, page_spec)
            if snap:
                gap += snap
                available = current.remaining() - gap - fn_reserved

            fn_extra = _footnote_extra(block)

            if block.height + fn_extra <= available:
                current.cursor -= gap
                current.blocks.append(
                    PlacedBlock(
                        block=block,
                        x=left,
                        y=current.cursor,
                        height=block.height,
                        lines=block.lines,
                        table_rows=list(range(len(block.table.row_heights)))
                        if block.table
                        else None,
                    )
                )
                _register_footnotes(block, fn_extra)
                current.cursor -= block.height + block.space_after
                index += 1
                continue

            # A block and its footnotes move to the next page as one unit.
            if block.footnotes:
                if current.blocks:
                    _start_new_page()
                    continue
                current.blocks.append(
                    PlacedBlock(
                        block=block,
                        x=left,
                        y=current.cursor,
                        height=block.height,
                        lines=block.lines,
                        table_rows=list(range(len(block.table.row_heights)))
                        if block.table
                        else None,
                    )
                )
                _register_footnotes(block, fn_extra)
                current.cursor -= block.height + block.space_after
                index += 1
                continue

            if block.table is not None and block.can_split:
                current, tail, consumed = self._split_table(
                    block, current, pages, page_spec, gap
                )
                if tail is not None:
                    blocks[index] = tail
                elif consumed:
                    index += 1
                continue

            if block.can_split and block.lines:
                fitting = block.lines_fitting(available - gap)
                remaining = len(block.lines) - fitting

                if fitting < self.MIN_ORPHAN_LINES or remaining < self.MIN_WIDOW_LINES:
                    if fitting >= self.MIN_ORPHAN_LINES and remaining > 0:
                        fitting = max(
                            self.MIN_ORPHAN_LINES,
                            len(block.lines) - self.MIN_WIDOW_LINES,
                        )
                        if block.height_of_lines(fitting) > available - gap:
                            fitting = 0
                    else:
                        fitting = 0

                if block.line_groups:
                    fitting = _snap_to_groups(block.line_groups, fitting)

                if fitting == 0:
                    if not current.blocks:
                        fitting = max(1, block.lines_fitting(available))
                        if block.line_groups:
                            fitting = (
                                _snap_to_groups(block.line_groups, fitting)
                                or block.line_groups[0][1]
                            )
                    else:
                        _start_new_page()
                        continue

                head = block.lines[:fitting]
                current.cursor -= gap
                current.blocks.append(
                    PlacedBlock(
                        block=block,
                        x=left,
                        y=current.cursor,
                        height=sum(line.height for line in head),
                        lines=head,
                    )
                )
                _start_new_page()

                tail_groups = None
                if block.line_groups:
                    tail_groups = _remaining_groups(block.line_groups, fitting)
                tail = MeasuredBlock(
                    element=block.element,
                    height=sum(line.height for line in block.lines[fitting:]),
                    style=block.style,
                    lines=block.lines[fitting:],
                    can_split=True,
                    space_before=0.0,
                    space_after=block.space_after,
                    line_groups=tail_groups,
                )
                blocks[index] = tail
                continue

            if current.blocks:
                _start_new_page()
                continue

            current.blocks.append(
                PlacedBlock(
                    block=block,
                    x=left,
                    y=current.cursor,
                    height=block.height,
                    lines=block.lines,
                    table_rows=list(range(len(block.table.row_heights)))
                    if block.table
                    else None,
                )
            )
            current.cursor -= block.height + block.space_after
            index += 1

        leftover = list(float_queue)
        float_queue.clear()
        for entry in leftover:
            blk = entry.block
            gap_f = blk.space_before if current.blocks else 0.0
            if blk.height + gap_f > _eff_remaining():
                _place_bottom_floats()
                _flush_footnotes()
                pages.append(current)
                current = Page(
                    number=len(pages) + 1, cursor=page_spec.content_top, spec=page_spec
                )
                bottom_floats = []
                bottom_reserved = 0.0
                gap_f = blk.space_before if current.blocks else 0.0
            current.cursor -= gap_f
            current.blocks.append(
                PlacedBlock(
                    block=blk,
                    x=left,
                    y=current.cursor,
                    height=blk.height,
                    lines=blk.lines,
                )
            )
            current.cursor -= blk.height + blk.space_after

        if bottom_floats:
            _place_bottom_floats()
        _flush_footnotes()

        if current.blocks or not pages:
            pages.append(current)
        return pages

    def _split_table(self, block, current, pages, page_spec, gap):
        """Place as many table rows as fit, repeating the header.

        Returns (active_page, tail_block_or_None, consumed). When a tail
        block is returned the caller substitutes it for the original and
        re-runs placement, so no layout state lives outside this call.
        """
        layout = block.table
        repeat = getattr(block.element, "repeat_header", True)
        available = current.remaining() - gap - layout.header_height

        rows, used = [], 0.0
        for row_index, height in enumerate(layout.row_heights):
            if used + height > available:
                break
            rows.append(row_index)
            used += height

        # Too little room for a meaningful chunk: start a fresh page and
        # retry the whole table there.
        if len(rows) < self.MIN_TABLE_ROWS_PER_PAGE and current.blocks:
            pages.append(current)
            fresh = Page(
                number=len(pages) + 1, cursor=page_spec.content_top, spec=page_spec
            )
            return fresh, None, False

        if not rows:
            rows = [0]
            used = layout.row_heights[0]

        current.cursor -= gap
        current.blocks.append(
            PlacedBlock(
                block=block,
                x=page_spec.margin_left,
                y=current.cursor,
                height=layout.header_height + used,
                table_rows=rows,
                include_table_header=True,
            )
        )
        current.cursor -= layout.header_height + used

        remaining = list(range(len(rows), len(layout.row_heights)))
        if not remaining:
            current.cursor -= block.space_after
            return current, None, True

        pages.append(current)
        page = Page(number=len(pages) + 1, cursor=page_spec.content_top, spec=page_spec)

        tail_layout = TableLayout(
            column_widths=layout.column_widths,
            header_height=layout.header_height if repeat else 0.0,
            row_heights=[layout.row_heights[i] for i in remaining],
            header_lines=layout.header_lines if repeat else [],
            row_lines=[layout.row_lines[i] for i in remaining],
            header_spans=layout.header_spans if repeat else None,
            row_spans=[layout.row_spans[i] for i in remaining]
            if layout.row_spans
            else None,
        )
        tail_height = tail_layout.header_height + sum(tail_layout.row_heights)
        if getattr(block.element, "caption", None):
            tail_height += self._caption_allowance(block.style)
        _headline_h, _subtitle_h, source_h = annotation_heights(
            None, None, getattr(block.element, "source_line", None), block.style
        )
        tail_height += source_h
        tail = MeasuredBlock(
            element=block.element,
            height=tail_height,
            style=block.style,
            can_split=len(remaining) > self.MIN_TABLE_ROWS_PER_PAGE,
            space_before=0.0,
            space_after=block.space_after,
            table=tail_layout,
        )
        return page, tail, False

    # -- two-pass optimization --

    def _optimize_pages(self, pages: list, page_spec) -> list:
        if len(pages) < 2:
            return pages

        content_height = page_spec.content_height
        left = page_spec.margin_left
        changed = True
        iterations = 0

        while changed and iterations < 3:
            changed = False
            iterations += 1
            i = 0
            while i < len(pages) - 1:
                page = pages[i]
                next_page = pages[i + 1]

                if not page.blocks or not next_page.blocks:
                    i += 1
                    continue

                last_pb = page.blocks[-1]
                page_bottom_edge = last_pb.y - last_pb.height
                remaining = page_bottom_edge - page_spec.content_bottom
                empty_frac = remaining / content_height if content_height else 0.0

                first_next = next_page.blocks[0]

                if empty_frac > 0.30 and isinstance(
                    first_next.block.element, _FLOATABLE_TYPES
                ):
                    fig_needed = first_next.height + first_next.block.space_before
                    if fig_needed <= remaining:
                        y = page_bottom_edge - first_next.block.space_before
                        next_page.blocks.pop(0)
                        page.blocks.append(
                            PlacedBlock(
                                block=first_next.block,
                                x=left,
                                y=y,
                                height=first_next.height,
                                lines=first_next.lines,
                            )
                        )
                        page.cursor = (
                            y - first_next.height - first_next.block.space_after
                        )
                        self._reflow_page(next_page, page_spec)
                        changed = True
                        if not next_page.blocks:
                            pages.pop(i + 1)
                        continue

                if first_next.lines and len(first_next.lines) == 1 and page.blocks:
                    last_this = page.blocks[-1]
                    if (
                        last_this.block.element is first_next.block.element
                        and last_this.lines
                    ):
                        widow_line = first_next.lines[0]
                        if widow_line.height <= remaining:
                            new_lines = list(last_this.lines) + [widow_line]
                            new_height = sum(line.height for line in new_lines)
                            page.blocks[-1] = PlacedBlock(
                                block=last_this.block,
                                x=last_this.x,
                                y=last_this.y,
                                height=new_height,
                                lines=new_lines,
                            )
                            page.cursor = (
                                last_this.y - new_height - last_this.block.space_after
                            )
                            next_page.blocks.pop(0)
                            self._reflow_page(next_page, page_spec)
                            changed = True
                            if not next_page.blocks:
                                pages.pop(i + 1)
                            continue

                if last_pb.lines and len(last_pb.lines) == 1 and next_page.blocks:
                    first_next_blk = next_page.blocks[0]
                    if (
                        first_next_blk.block.element is last_pb.block.element
                        and first_next_blk.lines
                    ):
                        orphan_line = last_pb.lines[0]
                        new_next_lines = [orphan_line] + list(first_next_blk.lines)
                        new_next_height = sum(line.height for line in new_next_lines)
                        next_page.blocks[0] = PlacedBlock(
                            block=first_next_blk.block,
                            x=first_next_blk.x,
                            y=page_spec.content_top,
                            height=new_next_height,
                            lines=new_next_lines,
                        )
                        page.blocks.pop()
                        if page.blocks:
                            prev = page.blocks[-1]
                            page.cursor = prev.y - prev.height - prev.block.space_after
                        else:
                            page.cursor = page_spec.content_top
                        self._reflow_page(next_page, page_spec)
                        changed = True
                        if not page.blocks:
                            pages.pop(i)
                            continue
                        continue

                i += 1

        for idx, pg in enumerate(pages):
            pg.number = idx + 1

        return pages

    @staticmethod
    def _reflow_page(page: Page, page_spec) -> None:
        cursor = page_spec.content_top
        for idx, pb in enumerate(page.blocks):
            gap = pb.block.space_before if idx > 0 else 0.0
            cursor -= gap
            page.blocks[idx] = PlacedBlock(
                block=pb.block,
                x=pb.x,
                y=cursor,
                height=pb.height,
                lines=pb.lines,
                is_continuation=pb.is_continuation,
                table_rows=pb.table_rows,
                include_table_header=pb.include_table_header,
            )
            cursor -= pb.height + pb.block.space_after
        page.cursor = cursor


def _delta_color(delta: str, neutral: str) -> str:
    """Color a signed delta: green for gains, red for losses, else neutral."""
    text = delta.strip()
    if text.startswith(("+", "▲", "↑")):
        return "1a7f37"
    if text.startswith(("-", "−", "▼", "↓")):
        return "b91c1c"
    return neutral


def _snap_to_groups(groups: list, fitting: int) -> int:
    """Largest cumulative group boundary at or below `fitting`."""
    boundary, cumulative = 0, 0
    for _kind, count in groups:
        if cumulative + count > fitting:
            break
        cumulative += count
        boundary = cumulative
    return boundary


def _remaining_groups(groups: list, consumed: int) -> list:
    """Group list left after `consumed` leading lines are placed."""
    remaining = []
    for kind, count in groups:
        if consumed >= count:
            consumed -= count
        elif consumed:
            remaining.append((kind, count - consumed))
            consumed = 0
        else:
            remaining.append((kind, count))
    return remaining


def _cell_align(align: str | None, header_align: str | None = None) -> str:
    """Map cell alignment to a text alignment the line layout understands.

    When a body cell has no explicit alignment (None), it inherits
    from its column header. This keeps numeric columns aligned
    consistently without requiring per-cell annotation.
    """
    effective = align if align is not None else header_align
    if effective is None:
        return "left"
    if effective == "decimal":
        return "right"
    return effective
