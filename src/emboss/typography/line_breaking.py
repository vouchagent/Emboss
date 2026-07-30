"""Knuth-Plass optimal line breaking.

Greedy breaking fills each line as full as possible and never reconsiders,
which produces uneven spacing and rivers in justified text. Knuth-Plass
treats the paragraph as a shortest-path problem over all legal breakpoints
and minimises total demerits, so a slightly worse early line is accepted
when it makes every later line better.

The item model is from the 1981 paper:
  Box     - unbreakable material (a word)
  Glue    - space that can stretch and shrink
  Penalty - an optional breakpoint, with a cost

A greedy breaker is included as a fallback for the pathological case
where no break sequence fits within tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .ligatures import available_ligatures, ligate

__all__ = [
    "Box",
    "Glue",
    "Penalty",
    "Line",
    "LineBreaker",
    "INFINITE_PENALTY",
    "build_items",
    "detect_rivers",
    "is_cjk_codepoint",
    "split_cjk_runs",
]

INFINITE_PENALTY = 10_000.0
_EJECT_PENALTY = -INFINITE_PENALTY
_EMERGENCY_PENALTY = 800.0


@dataclass(frozen=True, slots=True)
class Box:
    """Unbreakable typeset material."""

    width: float
    text: str = ""
    run_index: int = 0
    char_widths: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class Glue:
    """Stretchable and shrinkable space."""

    width: float
    stretch: float = 0.0
    shrink: float = 0.0
    run_index: int = 0


@dataclass(frozen=True, slots=True)
class Penalty:
    """A potential breakpoint.

    `width` is the material added if the break is taken here (a hyphen).
    `flagged` marks hyphen breaks so consecutive ones can be penalised.
    `soft` marks a zero-cost break inserted between CJK characters; unlike
    a hyphenation `Penalty` it carries no visible separator, so adjacent
    boxes of the same run on either side of it are merged back into one
    rendered fragment when a line does not break there.
    """

    penalty: float
    width: float = 0.0
    flagged: bool = False
    run_index: int = 0
    soft: bool = False


Item = Box | Glue | Penalty

# Codepoint ranges where a break opportunity exists between any two
# consecutive characters whenever at least one side falls in one of these
# ranges: CJK Unified Ideographs, Extension A, Hiragana, Katakana, and
# Hangul Syllables (all within the Basic Multilingual Plane). CJK text
# carries no inter-word spaces, so without this rule a whole paragraph of
# CJK text becomes one unbreakable box.
#
# This is a minimal break-opportunity rule, not full kinsoku shori: it does
# not forbid breaking immediately before closing punctuation or after an
# opening bracket the way real Japanese/Chinese line breaking does, so a
# line may occasionally start with a closing bracket or end with an
# opening one. Vertical writing mode and RTL scripts (Arabic, Hebrew) are
# not handled here.
_CJK_RANGES = (
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0xAC00, 0xD7A3),  # Hangul Syllables
)


def is_cjk_codepoint(codepoint: int) -> bool:
    """True for CJK ideographs, hiragana, katakana, or hangul syllables."""
    return any(lo <= codepoint <= hi for lo, hi in _CJK_RANGES)


def split_cjk_runs(text: str) -> list[str]:
    """Split text so a break is permitted around every CJK character.

    Each CJK character becomes its own single-character piece; runs of
    non-CJK characters stay together as one piece. Pieces are rejoined by
    zero-cost breaks in `build_items`, so plain Latin text (no CJK
    characters present) always comes back as a single one-element list.
    """
    if not text:
        return []
    pieces: list[str] = []
    buf: list[str] = []
    for char in text:
        if is_cjk_codepoint(ord(char)):
            if buf:
                pieces.append("".join(buf))
                buf = []
            pieces.append(char)
        else:
            buf.append(char)
    if buf:
        pieces.append("".join(buf))
    return pieces


@dataclass(slots=True)
class Line:
    """One laid-out line: the items on it and how its glue was adjusted."""

    items: list
    start: int
    end: int
    ratio: float
    width: float
    is_last: bool = False
    hyphenated: bool = False
    protrusion_credit: float = 0.0
    #: True when this line ends on a real inter-word space (a `Glue`) that
    #: was discarded at the break, so text reconstructed from consecutive
    #: lines needs a space reinserted between them. False for a hyphenation
    #: or CJK `soft` break, neither of which represents a space in the
    #: source text.
    space_break: bool = True

    @property
    def text(self) -> str:
        parts = []
        for item in self.items:
            if isinstance(item, Box):
                parts.append(item.text)
            elif isinstance(item, Glue):
                parts.append(" ")
        text = "".join(parts).strip()
        return text + "-" if self.hyphenated else text


@dataclass(slots=True)
class _Node:
    """An active breakpoint in the dynamic program."""

    position: int
    line: int
    fitness: int
    total_width: float
    total_stretch: float
    total_shrink: float
    demerits: float
    previous: "_Node | None" = None
    ratio: float = 0.0
    flagged: bool = False
    ladder: int = 0


def _fitness_class(ratio: float) -> int:
    """Classify a line's looseness. Adjacent classes differing by more
    than one look visibly inconsistent, so that is penalised."""
    if ratio < -0.5:
        return 0  # tight
    if ratio <= 0.5:
        return 1  # decent
    if ratio <= 1.0:
        return 2  # loose
    return 3  # very loose


@dataclass
class LineBreaker:
    """Optimal paragraph line breaking.

    Parameters mirror TeX's: `tolerance` caps how far a line may stretch,
    `line_penalty` discourages extra lines, `hyphen_penalty` discourages
    hyphenation, and the flagged/fitness demerits penalise two hyphens in
    a row and abrupt spacing changes between adjacent lines.
    """

    tolerance: float = 2.5
    line_penalty: float = 10.0
    hyphen_penalty: float = 50.0
    flagged_demerit: float = 3000.0
    fitness_demerit: float = 3000.0
    ladder_demerit: float = 100_000_000.0
    ladder_limit: int = 3
    protrusion: bool = True
    avoid_rivers: bool = True

    def break_paragraph(
        self,
        items: Sequence,
        line_width: float | Callable = 0.0,
    ) -> list:
        """Return the optimal set of lines for `items`."""
        if not items:
            return []

        width_for = line_width if callable(line_width) else (lambda _n: line_width)
        items = self._exploded(items, width_for)
        sums = self._running_sums(items)

        best = self._optimize(items, sums, width_for, self.tolerance)
        if best is None:
            best = self._optimize(items, sums, width_for, self.tolerance * 4)
        if best is None:
            return self._greedy(items, width_for)

        lines = self._assemble(items, best)

        if self.avoid_rivers and len(lines) >= 3:
            rivers = detect_rivers(lines)
            if rivers > 0:
                tighter = self._optimize(
                    items,
                    sums,
                    width_for,
                    self.tolerance * 0.8,
                )
                if tighter is not None:
                    alt = self._assemble(items, tighter)
                    if detect_rivers(alt) < rivers:
                        lines = alt

        return lines

    # -- internals --

    @staticmethod
    def _exploded(items: Sequence, width_for: Callable) -> list:
        """Split any box wider than the narrowest measure into char boxes."""
        widest = max((it.width for it in items if isinstance(it, Box)), default=0.0)
        if widest <= 0.0:
            return list(items)
        limit = min(width_for(n) for n in range(len(items) + 1))
        if limit <= 0.0 or widest <= limit:
            return list(items)
        out: list = []
        for item in items:
            if isinstance(item, Box) and item.width > limit and len(item.text) > 1:
                out.extend(_emergency_pieces(item))
            else:
                out.append(item)
        return out

    @staticmethod
    def _running_sums(items: Sequence) -> list:
        """Cumulative width/stretch/shrink, so any span is an O(1) lookup."""
        n = len(items)
        sums = [None] * (n + 1)
        width = stretch = shrink = 0.0
        for i in range(n):
            sums[i] = (width, stretch, shrink)
            item = items[i]
            if isinstance(item, Box):
                width += item.width
            elif isinstance(item, Glue):
                width += item.width
                stretch += item.stretch
                shrink += item.shrink
        sums[n] = (width, stretch, shrink)
        return sums

    @staticmethod
    def _is_legal_break(items: Sequence, index: int) -> bool:
        item = items[index]
        if isinstance(item, Penalty):
            return item.penalty < INFINITE_PENALTY
        if isinstance(item, Glue):
            return index > 0 and isinstance(items[index - 1], Box)
        return False

    def _adjustment_ratio(
        self,
        node: _Node,
        index: int,
        items: Sequence,
        sums: list,
        target: float,
    ) -> float:
        """How much the glue on this line must stretch (+) or shrink (-)."""
        width = sums[index][0] - node.total_width
        item = items[index]
        if isinstance(item, Penalty):
            width += item.width

        effective_target = target
        if self.protrusion:
            effective_target += self._protrusion_slack(items, node.position, index)

        if width < effective_target:
            stretch = sums[index][1] - node.total_stretch
            if stretch <= 0:
                return INFINITE_PENALTY
            return (effective_target - width) / stretch
        if width > effective_target:
            shrink = sums[index][2] - node.total_shrink
            if shrink <= 0:
                return -INFINITE_PENALTY
            return (effective_target - width) / shrink
        return 0.0

    @staticmethod
    def _protrusion_slack(items: Sequence, start: int, end: int) -> float:
        from .protrusion import left_protrusion

        slack = 0.0
        for i in range(start, end):
            it = items[i]
            if isinstance(it, Box) and it.text:
                factor = left_protrusion(it.text[0])
                if factor > 0:
                    slack += it.width * factor * (1 / max(len(it.text), 1))
                break

        return slack + LineBreaker._right_credit(items, start, end)

    @staticmethod
    def _right_credit(items: Sequence, start: int, end: int) -> float:
        """Width credit when the last visible character may hang right."""
        from .protrusion import right_protrusion

        break_item = items[end] if end < len(items) else None
        if isinstance(break_item, Penalty) and break_item.width > 0:
            # The line ends in a soft hyphen; that glyph already hangs
            # via the engine's hyphen handling, so no extra credit.
            return 0.0
        for i in range(end - 1, start - 1, -1):
            it = items[i]
            if not isinstance(it, Box):
                continue
            if not it.text:
                return 0.0
            factor = right_protrusion(it.text[-1])
            if factor <= 0:
                return 0.0
            if it.char_widths and len(it.char_widths) == len(it.text):
                return it.char_widths[-1] * factor
            return it.width * factor * (1 / max(len(it.text), 1))
        return 0.0

    def _demerits(self, ratio: float, item, node: _Node, fitness: int) -> float:
        badness = 100.0 * abs(ratio) ** 3
        penalty = item.penalty if isinstance(item, Penalty) else 0.0

        if penalty >= 0:
            value = (self.line_penalty + badness + penalty) ** 2
        elif penalty > _EJECT_PENALTY:
            value = (self.line_penalty + badness) ** 2 - penalty**2
        else:
            value = (self.line_penalty + badness) ** 2

        if isinstance(item, Penalty) and item.flagged:
            if node.flagged:
                value += self.flagged_demerit
            if node.ladder >= self.ladder_limit:
                value += self.ladder_demerit

        if abs(fitness - node.fitness) > 1:
            value += self.fitness_demerit
        return value

    def _optimize(
        self,
        items: Sequence,
        sums: list,
        width_for: Callable,
        tolerance: float,
    ) -> _Node | None:
        active = [
            _Node(
                position=0,
                line=0,
                fitness=1,
                total_width=0.0,
                total_stretch=0.0,
                total_shrink=0.0,
                demerits=0.0,
            )
        ]

        for index in range(len(items)):
            if not self._is_legal_break(items, index):
                continue

            item = items[index]
            forced = isinstance(item, Penalty) and item.penalty <= _EJECT_PENALTY
            candidates: dict = {}
            survivors = []

            for node in active:
                target = width_for(node.line)
                ratio = self._adjustment_ratio(node, index, items, sums, target)

                if ratio < -1 or forced:
                    # This node can never reach a later breakpoint: the
                    # line is already overfull. Drop it from the active set.
                    pass
                else:
                    survivors.append(node)

                if -1 <= ratio <= tolerance:
                    fitness = _fitness_class(ratio)
                    demerits = node.demerits + self._demerits(
                        ratio, item, node, fitness
                    )
                    key = fitness
                    existing = candidates.get(key)
                    if existing is None or demerits < existing[0]:
                        candidates[key] = (demerits, node, ratio, fitness)

            active = survivors
            break_flagged = isinstance(item, Penalty) and item.flagged
            for demerits, parent, ratio, fitness in candidates.values():
                width, stretch, shrink = sums[index]
                if isinstance(item, Glue):
                    # Glue at a break is discarded, so the next line starts
                    # after it.
                    width += item.width
                    stretch += item.stretch
                    shrink += item.shrink
                active.append(
                    _Node(
                        position=index,
                        line=parent.line + 1,
                        fitness=fitness,
                        total_width=width,
                        total_stretch=stretch,
                        total_shrink=shrink,
                        demerits=demerits,
                        previous=parent,
                        ratio=ratio,
                        flagged=break_flagged,
                        ladder=parent.ladder + 1 if break_flagged else 0,
                    )
                )

            if not active:
                return None

        finals = [n for n in active if n.position == len(items) - 1]
        pool = finals or active
        if not pool:
            return None
        return min(pool, key=lambda n: n.demerits)

    def _assemble(self, items: Sequence, final: _Node) -> list:
        chain = []
        node = final
        while node is not None:
            chain.append(node)
            node = node.previous
        chain.reverse()

        lines = []
        for i in range(1, len(chain)):
            start = chain[i - 1].position
            end = chain[i].position
            # Skip the glue that was consumed by the previous break.
            if i > 1:
                start += 1
            segment = list(items[start:end])
            break_item = items[end] if end < len(items) else None
            hyphenated = (
                isinstance(break_item, Penalty)
                and break_item.flagged
                and break_item.width > 0
            )
            width = sum(it.width for it in segment if isinstance(it, (Box, Glue)))
            credit = self._right_credit(items, start, end) if self.protrusion else 0.0
            lines.append(
                Line(
                    items=segment,
                    start=start,
                    end=end,
                    ratio=chain[i].ratio,
                    width=width,
                    is_last=(i == len(chain) - 1),
                    hyphenated=hyphenated,
                    protrusion_credit=credit,
                    space_break=isinstance(break_item, Glue),
                )
            )
        return lines

    def _greedy(self, items: Sequence, width_for: Callable) -> list:
        """Last-resort breaker: fills each line as full as it will go.

        Also used as the comparison baseline in tests. It breaks at the
        last legal point that still fits; boxes wider than the measure are
        first split into per-character pieces so lines never overflow.
        """
        items = self._exploded(items, width_for)
        lines: list = []
        start = 0
        line_number = 0
        last_legal = None  # index of the most recent legal break
        width_at_legal = 0.0
        width = 0.0

        index = 0
        while index < len(items):
            item = items[index]
            item_width = getattr(item, "width", 0.0)
            target = width_for(line_number)

            if self._is_legal_break(items, index):
                # Record this as a candidate before adding its own width:
                # glue at a break is discarded rather than set.
                last_legal = index
                width_at_legal = width

            if width + item_width > target and last_legal is not None:
                segment = list(items[start:last_legal])
                broke_on = items[last_legal]
                lines.append(
                    Line(
                        items=segment,
                        start=start,
                        end=last_legal,
                        ratio=0.0,
                        width=width_at_legal,
                        space_break=isinstance(broke_on, Glue),
                    )
                )
                start = last_legal + 1 if isinstance(broke_on, Glue) else last_legal
                index = start
                width = 0.0
                last_legal = None
                width_at_legal = 0.0
                line_number += 1
                continue

            width += item_width
            index += 1

        if start < len(items):
            segment = list(items[start:])
            lines.append(
                Line(
                    items=segment,
                    start=start,
                    end=len(items),
                    ratio=0.0,
                    width=width,
                    is_last=True,
                )
            )
        if lines:
            lines[-1].is_last = True
        return lines


def _emergency_pieces(box: Box) -> list:
    """Split an oversized box into character boxes with flagged breaks."""
    count = len(box.text)
    if box.char_widths and len(box.char_widths) == count:
        widths = box.char_widths
    else:
        widths = (box.width / count,) * count
    pieces: list = []
    for i in range(count):
        if i:
            pieces.append(
                Penalty(
                    penalty=_EMERGENCY_PENALTY,
                    width=0.0,
                    flagged=True,
                    run_index=box.run_index,
                )
            )
        pieces.append(
            Box(
                width=widths[i],
                text=box.text[i],
                run_index=box.run_index,
                char_widths=(widths[i],),
            )
        )
    return pieces


def _char_widths(
    text: str,
    metrics,
    size: float,
    tracking: float,
) -> tuple[float, ...]:
    """Per-character advances for a box, including tracking."""
    return tuple(metrics.text_width(char, size) + tracking for char in text)


def build_items(
    runs: Sequence,
    metrics_for: Callable,
    size_for: Callable,
    hyphenator=None,
    justified: bool = False,
    hyphenate: bool = False,
    tracking: float = 0.0,
) -> list:
    """Convert styled text runs into a Knuth-Plass item list.

    `metrics_for(run)` returns the FontMetrics for a run and `size_for(run)`
    its point size, so mixed formatting within a paragraph measures
    correctly.

    `tracking` is a uniform letter-spacing adjustment in points added to
    every character advance.
    """
    items: list = []

    for run_index, run in enumerate(runs):
        metrics = metrics_for(run)
        size = size_for(run)
        space_width = metrics.text_width(" ", size)
        # Ligatures only for embedded fonts that carry the glyphs; the
        # base-14 path must stay byte-identical.
        ligatures = available_ligatures(metrics)

        # Justified text needs elastic spaces; ragged text keeps them fixed
        # so word spacing stays even and the rag falls where it falls.
        if justified:
            stretch = space_width * 0.45
            shrink = space_width * 0.30
        else:
            stretch = 0.0
            shrink = 0.0

        def word_box(text: str) -> Box:
            """Box for a word fragment, ligated when the font allows it."""
            word = ligate(text, ligatures) if ligatures else text
            width = metrics.text_width(word, size)
            if tracking:
                width += len(word) * tracking
            return Box(
                width=width,
                text=word,
                run_index=run_index,
                char_widths=_char_widths(word, metrics, size, tracking),
            )

        def emit_piece(piece: str) -> None:
            """Append items for one script-homogeneous piece of a token."""
            if hyphenate and hyphenator is not None and len(piece) >= 5:
                points = hyphenator.break_points(piece)
            else:
                points = []

            if not points:
                items.append(word_box(piece))
                return

            # Hyphenation points are found on the original letters; each
            # fragment is ligated independently afterwards, so a break
            # falling inside a would-be ligature simply stays unligated.
            hyphen_width = metrics.text_width("-", size)
            previous = 0
            for point in points:
                items.append(word_box(piece[previous:point]))
                items.append(
                    Penalty(
                        penalty=50.0,
                        width=hyphen_width,
                        flagged=True,
                        run_index=run_index,
                    )
                )
                previous = point
            items.append(word_box(piece[previous:]))

        tokens = run.text.split(" ")
        for token_index, token in enumerate(tokens):
            if token_index > 0:
                items.append(
                    Glue(
                        width=space_width,
                        stretch=stretch,
                        shrink=shrink,
                        run_index=run_index,
                    )
                )
            if not token:
                continue

            # CJK text carries no inter-word spaces; split so a break is
            # permitted around every CJK character instead of treating the
            # whole token as one unbreakable box. Plain Latin tokens come
            # back as a single piece and are completely unaffected.
            pieces = split_cjk_runs(token)
            for piece_index, piece in enumerate(pieces):
                if piece_index > 0:
                    items.append(
                        Penalty(
                            penalty=0.0,
                            width=0.0,
                            run_index=run_index,
                            soft=True,
                        )
                    )
                emit_piece(piece)

    # Terminate the paragraph: infinite glue absorbs the slack on the last
    # line, then a forced break ends it.
    items.append(Glue(width=0.0, stretch=INFINITE_PENALTY, shrink=0.0))
    items.append(Penalty(penalty=_EJECT_PENALTY))
    return items


def _space_positions(line: Line) -> list[float]:
    positions: list[float] = []
    cursor = 0.0
    for item in line.items:
        if isinstance(item, Box):
            cursor += item.width
        elif isinstance(item, Glue):
            positions.append(cursor + item.width / 2.0)
            cursor += item.width
    return positions


def detect_rivers(lines: Sequence[Line], tolerance: float = 2.0) -> int:
    """Count rivers of whitespace spanning three or more consecutive lines."""
    if len(lines) < 3:
        return 0

    all_positions = [_space_positions(line) for line in lines]

    rivers = 0
    for start in range(len(lines) - 2):
        for sx in all_positions[start]:
            depth = 1
            ref = sx
            for row in range(start + 1, len(lines)):
                matched = False
                for rx in all_positions[row]:
                    if abs(rx - ref) <= tolerance:
                        depth += 1
                        ref = rx
                        matched = True
                        break
                if not matched:
                    break
            if depth >= 3:
                rivers += 1

    return rivers
