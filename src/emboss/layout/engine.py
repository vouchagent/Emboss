"""Layout: measure content, then place it on pages under constraints.

Measurement happens before any placement, so the engine always knows how
tall a block is and where it may legally split. Overflow is therefore
impossible by construction rather than detected after the fact.

Pagination enforces widow/orphan minimums, keep-with-next for headings,
keep-together for atomic blocks, and header repetition for split tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..spec import (
    BibliographyBlock, BulletList, Callout, Chart, CodeBlock, Footnote,
    Heading, HorizontalRule, Image, MathBlock, NumberedList, PageBreak,
    Paragraph, SvgBlock, Table,
)
from ..typography.line_breaking import Box, Glue, LineBreaker, build_items

__all__ = [
    "LaidOutLine", "MeasuredBlock", "PlacedBlock", "Page",
    "LayoutEngine", "TableLayout",
]


@dataclass
class LaidOutLine:
    """One line of text with its resolved geometry."""

    fragments: list          # (text, run, x_offset) triples
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
    header_lines: list        # per column: list[LaidOutLine]
    row_lines: list           # per row, per column: list[LaidOutLine]


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

    def height_of_lines(self, count: int) -> float:
        return sum(line.height for line in self.lines[:count])

    def lines_fitting(self, available: float) -> int:
        used = 0.0
        for index, line in enumerate(self.lines):
            if used + line.height > available:
                return index
            used += line.height
        return len(self.lines)


@dataclass
class PlacedBlock:
    """A measured block positioned on a page."""

    block: MeasuredBlock
    x: float
    y: float                  # top edge, PDF coordinates
    height: float
    lines: list = field(default_factory=list)
    is_continuation: bool = False
    table_rows: list | None = None
    include_table_header: bool = True


@dataclass
class Page:
    """One output page."""

    number: int
    blocks: list = field(default_factory=list)
    cursor: float = 0.0
    spec: object = None

    def remaining(self) -> float:
        return self.cursor - self.spec.content_bottom


class LayoutEngine:
    """Measures content and composes it into pages."""

    # A heading must be followed by at least this much of its next block,
    # otherwise it moves to the next page with it.
    KEEP_WITH_NEXT_LOOKAHEAD = 34.0
    MIN_WIDOW_LINES = 2
    MIN_ORPHAN_LINES = 2
    MIN_TABLE_ROWS_PER_PAGE = 2

    def __init__(self, fonts, sheet, hyphenator=None, breaker=None):
        self.fonts = fonts
        self.sheet = sheet
        self.hyphenator = hyphenator
        self.breaker = breaker or LineBreaker()

    # -- font resolution --

    def _metrics(self, style, run=None):
        family = (run.font_family if run and run.font_family
                  else style.require("font_family"))
        bold = run.bold if run and run.bold else style.require("bold")
        italic = run.italic if run and run.italic else style.require("italic")
        return self.fonts.resolve(family, bold=bold, italic=italic)

    def _size(self, style, run=None) -> float:
        if run is not None and run.font_size:
            return run.font_size
        return style.require("font_size")

    # -- measurement --

    def measure(self, element, width: float) -> MeasuredBlock:
        if isinstance(element, Heading):
            return self._measure_text(
                element, element.runs,
                self.sheet.resolved(self.sheet.for_heading(element.level),
                                    element.style),
                width,
            )
        if isinstance(element, Paragraph):
            return self._measure_text(
                element, element.runs,
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
        if isinstance(element, PageBreak):
            return MeasuredBlock(
                element=element, height=0.0,
                style=self.sheet.resolved(self.sheet.body),
            )
        raise TypeError(f"cannot measure {type(element).__name__}")

    def _layout_runs(self, runs, style, width: float,
                     first_indent: float = 0.0) -> list:
        """Break runs into positioned lines within `width`."""
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
            return width - (first_indent if line_number == 0 else 0.0)

        raw_lines = self.breaker.break_paragraph(items, width_for)

        base_metrics = self._metrics(style)
        base_size = self._size(style)
        multiplier = style.require("line_height")
        line_height = base_metrics.line_height(base_size, multiplier)
        ascent = base_metrics.ascent(base_size)

        laid_out = []
        for index, line in enumerate(raw_lines):
            available = width_for(index)
            fragments, cursor = [], 0.0

            natural = line.width
            glue_count = sum(1 for it in line.items if isinstance(it, Glue))
            extra = 0.0
            if justified and not line.is_last and glue_count:
                slack = available - natural
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

            if offset:
                fragments = [(t, r, x + offset) for t, r, x in fragments]

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
        bullet_width = metrics.text_width(element.bullet + " ", size)
        usable = width - indent - bullet_width

        items, total = [], 0.0
        for runs, sub in element.flat_items:
            if sub is not None:
                nested = self.measure(sub, usable)
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
        last_marker = element.marker(len(element.item_runs) - 1) if element.item_runs else "1."
        marker_width = metrics.text_width(last_marker + " ", size)
        usable = width - indent - marker_width

        items, total = [], 0.0
        text_idx = 0
        for runs, sub in element.flat_items:
            if sub is not None:
                nested = self.measure(sub, usable)
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
        fn_style = style.with_(font_size=style.require("font_size") * 0.82)
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
            height=sum(l.height for l in lines) + 2.0,
            style=fn_style,
            lines=lines,
            can_split=False,
            space_before=4.0,
            space_after=2.0,
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
                [__import__('emboss.spec', fromlist=['TextRun']).TextRun(
                    element.title, bold=True
                )],
                title_style, usable,
            )
            total += sum(l.height for l in title_lines)
        content_lines = self._layout_runs(element.runs, style, usable)
        for run in element.runs:
            self._metrics(style, run).note_usage(run.text)
        total += sum(l.height for l in content_lines)
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
            metrics = self._metrics(style)
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
        style = self.sheet.resolved(self.sheet.body, element.style)
        display_w = min(element.width, width)
        display_h = element.height * (display_w / element.width)
        return MeasuredBlock(
            element=element,
            height=display_h,
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

    def _measure_bibliography(self, element, width: float) -> MeasuredBlock:
        from ..bibliography import format_bibliography
        from ..spec import TextRun

        style = self.sheet.resolved(self.sheet.body, element.style)
        metrics = self._metrics(style)
        size = self._size(style)
        line_h = metrics.line_height(size, style.require("line_height"))

        total = 0.0
        if element.title:
            heading_style = self.sheet.resolved(
                self.sheet.for_heading(element.heading_level), element.style
            )
            heading_size = self._size(heading_style)
            heading_metrics = self._metrics(heading_style)
            total += heading_metrics.line_height(
                heading_size, heading_style.require("line_height")
            )
            total += heading_style.require("space_after")

        entries = format_bibliography(element.citations, element.bib_style)
        all_lines = []
        for entry in entries:
            runs = [TextRun(entry)]
            lines = self._layout_runs(runs, style, width)
            for run in runs:
                metrics.note_usage(run.text)
            all_lines.extend(lines)
            total += sum(l.height for l in lines)
            total += style.require("space_after") * 0.5

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            lines=all_lines,
            can_split=len(all_lines) > 4,
            space_before=12.0,
            space_after=8.0,
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
            metrics = self._metrics(style)
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

    # -- tables --

    def _measure_table(self, element, width: float) -> MeasuredBlock:
        style = self.sheet.resolved(self.sheet.table_cell, element.style)
        header_style = self.sheet.resolved(self.sheet.table_header)
        pad_x = self.sheet.table_cell_padding_x
        pad_y = self.sheet.table_cell_padding_y

        columns = element.column_count
        if columns == 0:
            return MeasuredBlock(element=element, height=0.0, style=style)

        widths = self._solve_columns(element, style, header_style, width, pad_x)

        header_cells = element.header_cells
        header_lines, header_height = [], 0.0
        col_aligns: list[str | None] = [None] * columns
        if header_cells:
            for index, cell in enumerate(header_cells):
                available = widths[index] - 2 * pad_x
                col_aligns[index] = cell.align
                cell_style = header_style.with_(align=_cell_align(cell.align, None))
                lines = self._layout_runs(cell.runs, cell_style, available)
                for run in cell.runs:
                    self._metrics(cell_style, run).note_usage(run.text)
                header_lines.append(lines)
                header_height = max(
                    header_height, sum(l.height for l in lines)
                )
            header_height += 2 * pad_y

        row_lines, row_heights = [], []
        for row in element.body_rows:
            cells, height = [], 0.0
            for index in range(columns):
                cell = row[index] if index < len(row) else None
                if cell is None:
                    cells.append([])
                    continue
                available = widths[index] - 2 * pad_x
                header_align = col_aligns[index] if index < len(col_aligns) else None
                cell_style = style.with_(align=_cell_align(cell.align, header_align))
                lines = self._layout_runs(cell.runs, cell_style, available)
                for run in cell.runs:
                    self._metrics(cell_style, run).note_usage(run.text)
                cells.append(lines)
                height = max(height, sum(l.height for l in lines))
            row_lines.append(cells)
            row_heights.append(height + 2 * pad_y)

        layout = TableLayout(
            column_widths=widths,
            header_height=header_height,
            row_heights=row_heights,
            header_lines=header_lines,
            row_lines=row_lines,
        )
        total = header_height + sum(row_heights)

        return MeasuredBlock(
            element=element,
            height=total,
            style=style,
            can_split=len(row_heights) > self.MIN_TABLE_ROWS_PER_PAGE,
            space_before=8.0,
            space_after=12.0,
            table=layout,
        )

    def _solve_columns(self, element, style, header_style,
                       width: float, pad_x: float) -> list:
        """Compute column widths from actual content metrics.

        Minimum width is the widest single word (so text never overflows);
        preferred width is the longest unwrapped cell. Available space is
        distributed between the two.
        """
        columns = element.column_count
        if element.column_widths:
            total = sum(element.column_widths)
            return [width * (w / total) for w in element.column_widths]

        minimums = [0.0] * columns
        preferred = [0.0] * columns

        def consider(index: int, text: str, cell_style) -> None:
            if index >= columns:
                return
            metrics = self._metrics(cell_style)
            size = self._size(cell_style)
            full = metrics.text_width(text, size) + 2 * pad_x
            preferred[index] = max(preferred[index], full)
            widest_word = max(
                (metrics.text_width(word, size) for word in text.split()),
                default=0.0,
            )
            minimums[index] = max(minimums[index], widest_word + 2 * pad_x)

        for index, cell in enumerate(element.header_cells):
            consider(index, cell.plain_text, header_style)
        for row in element.body_rows:
            for index, cell in enumerate(row):
                consider(index, cell.plain_text, style)

        for index in range(columns):
            if preferred[index] == 0.0:
                preferred[index] = minimums[index] = 36.0

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
                if spread > 0 else minimums[i] + slack / columns
                for i in range(columns)
            ]

        # Content genuinely cannot fit: scale everything down proportionally
        # and let cell text wrap.
        return [width * (m / total_minimum) for m in minimums]

    # -- pagination --

    def paginate(self, blocks: list, page_spec) -> list:
        if page_spec.columns > 1:
            return self._paginate_multicolumn(blocks, page_spec)
        return self._paginate_single(blocks, page_spec)

    def _paginate_multicolumn(self, blocks: list, page_spec) -> list:
        cols = page_spec.columns
        gap = page_spec.column_gap
        total_w = page_spec.content_width
        col_w = (total_w - gap * (cols - 1)) / cols

        pages: list = []
        current = Page(number=1, cursor=page_spec.content_top, spec=page_spec)
        col_cursors = [page_spec.content_top] * cols
        col_idx = 0

        def col_left(c: int) -> float:
            return page_spec.margin_left + c * (col_w + gap)

        def _is_spanning(block) -> bool:
            style = getattr(block.element, "style", None)
            if style and getattr(style, "column_span", None):
                return True
            if isinstance(block.element, (Heading,)) and block.element.level <= 2:
                return False
            return False

        def _new_page():
            nonlocal current, col_idx, col_cursors
            pages.append(current)
            current = Page(number=len(pages) + 1,
                           cursor=page_spec.content_top, spec=page_spec)
            col_cursors = [page_spec.content_top] * cols
            col_idx = 0

        def _place(block, x, y):
            return PlacedBlock(
                block=block, x=x, y=y,
                height=block.height, lines=block.lines,
                table_rows=list(range(len(block.table.row_heights)))
                if block.table else None,
            )

        for block in blocks:
            if isinstance(block.element, PageBreak):
                _new_page()
                continue

            if _is_spanning(block):
                lowest = min(col_cursors)
                gap_before = block.space_before
                available = lowest - page_spec.content_bottom - gap_before
                if block.height > available:
                    _new_page()
                    lowest = page_spec.content_top
                y = lowest - gap_before
                current.blocks.append(_place(
                    block, page_spec.margin_left, y))
                new_cursor = y - block.height - block.space_after
                col_cursors = [new_cursor] * cols
                col_idx = 0
                continue

            gap_before = block.space_before if current.blocks else 0.0
            available = col_cursors[col_idx] - page_spec.content_bottom - gap_before

            if block.height <= available:
                col_cursors[col_idx] -= gap_before
                current.blocks.append(_place(
                    block, col_left(col_idx), col_cursors[col_idx]))
                col_cursors[col_idx] -= block.height + block.space_after
                continue

            col_idx += 1
            if col_idx < cols:
                current.blocks.append(_place(
                    block, col_left(col_idx), col_cursors[col_idx]))
                col_cursors[col_idx] -= block.height + block.space_after
                continue

            _new_page()
            current.blocks.append(_place(
                block, col_left(0), col_cursors[0]))
            col_cursors[0] -= block.height + block.space_after

        if current.blocks or not pages:
            pages.append(current)
        return pages

    def _paginate_single(self, blocks: list, page_spec) -> list:
        pages: list = []
        current = Page(number=1, cursor=page_spec.content_top, spec=page_spec)
        left = page_spec.margin_left

        index = 0
        while index < len(blocks):
            block = blocks[index]

            if isinstance(block.element, PageBreak):
                pages.append(current)
                current = Page(number=len(pages) + 1,
                               cursor=page_spec.content_top, spec=page_spec)
                index += 1
                continue

            if block.style.page_break_before and current.blocks:
                pages.append(current)
                current = Page(number=len(pages) + 1,
                               cursor=page_spec.content_top, spec=page_spec)

            gap = block.space_before if current.blocks else 0.0
            available = current.remaining() - gap

            # Heading that would be stranded at the foot of a page.
            if block.keep_with_next and index + 1 < len(blocks):
                nxt = blocks[index + 1]
                needed = block.height + min(
                    nxt.height, self.KEEP_WITH_NEXT_LOOKAHEAD
                )
                if needed > available and current.blocks:
                    pages.append(current)
                    current = Page(number=len(pages) + 1,
                                   cursor=page_spec.content_top, spec=page_spec)
                    gap = 0.0
                    available = current.remaining()

            if block.height <= available:
                current.cursor -= gap
                current.blocks.append(
                    PlacedBlock(
                        block=block, x=left, y=current.cursor,
                        height=block.height, lines=block.lines,
                        table_rows=list(range(len(block.table.row_heights)))
                        if block.table else None,
                    )
                )
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

                if (fitting < self.MIN_ORPHAN_LINES
                        or remaining < self.MIN_WIDOW_LINES):
                    if fitting >= self.MIN_ORPHAN_LINES and remaining > 0:
                        fitting = max(
                            self.MIN_ORPHAN_LINES,
                            len(block.lines) - self.MIN_WIDOW_LINES,
                        )
                        if block.height_of_lines(fitting) > available - gap:
                            fitting = 0
                    else:
                        fitting = 0

                if fitting == 0:
                    if not current.blocks:
                        # Block is taller than an empty page: place what
                        # fits rather than looping forever.
                        fitting = max(1, block.lines_fitting(available))
                    else:
                        pages.append(current)
                        current = Page(number=len(pages) + 1,
                                       cursor=page_spec.content_top,
                                       spec=page_spec)
                        continue

                head = block.lines[:fitting]
                current.cursor -= gap
                current.blocks.append(
                    PlacedBlock(
                        block=block, x=left, y=current.cursor,
                        height=sum(l.height for l in head), lines=head,
                    )
                )
                pages.append(current)
                current = Page(number=len(pages) + 1,
                               cursor=page_spec.content_top, spec=page_spec)

                tail = MeasuredBlock(
                    element=block.element,
                    height=sum(l.height for l in block.lines[fitting:]),
                    style=block.style,
                    lines=block.lines[fitting:],
                    can_split=True,
                    space_before=0.0,
                    space_after=block.space_after,
                )
                blocks[index] = tail
                continue

            # Atomic block that does not fit: move it to a fresh page.
            if current.blocks:
                pages.append(current)
                current = Page(number=len(pages) + 1,
                               cursor=page_spec.content_top, spec=page_spec)
                continue

            current.blocks.append(
                PlacedBlock(
                    block=block, x=left, y=current.cursor,
                    height=block.height, lines=block.lines,
                    table_rows=list(range(len(block.table.row_heights)))
                    if block.table else None,
                )
            )
            current.cursor -= block.height + block.space_after
            index += 1

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
            fresh = Page(number=len(pages) + 1, cursor=page_spec.content_top,
                         spec=page_spec)
            return fresh, None, False

        if not rows:
            rows = [0]
            used = layout.row_heights[0]

        current.cursor -= gap
        current.blocks.append(
            PlacedBlock(
                block=block, x=page_spec.margin_left, y=current.cursor,
                height=layout.header_height + used,
                table_rows=rows, include_table_header=True,
            )
        )
        current.cursor -= layout.header_height + used

        remaining = list(range(len(rows), len(layout.row_heights)))
        if not remaining:
            current.cursor -= block.space_after
            return current, None, True

        pages.append(current)
        page = Page(number=len(pages) + 1, cursor=page_spec.content_top,
                    spec=page_spec)

        tail_layout = TableLayout(
            column_widths=layout.column_widths,
            header_height=layout.header_height if repeat else 0.0,
            row_heights=[layout.row_heights[i] for i in remaining],
            header_lines=layout.header_lines if repeat else [],
            row_lines=[layout.row_lines[i] for i in remaining],
        )
        tail = MeasuredBlock(
            element=block.element,
            height=tail_layout.header_height + sum(tail_layout.row_heights),
            style=block.style,
            can_split=len(remaining) > self.MIN_TABLE_ROWS_PER_PAGE,
            space_before=0.0,
            space_after=block.space_after,
            table=tail_layout,
        )
        return page, tail, False


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
