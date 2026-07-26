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

from dataclasses import dataclass, field
from typing import Callable, Sequence

__all__ = [
    "Box", "Glue", "Penalty", "Line", "LineBreaker",
    "INFINITE_PENALTY", "build_items",
]

INFINITE_PENALTY = 10_000.0
_EJECT_PENALTY = -INFINITE_PENALTY


@dataclass(frozen=True)
class Box:
    """Unbreakable typeset material."""

    width: float
    text: str = ""
    run_index: int = 0


@dataclass(frozen=True)
class Glue:
    """Stretchable and shrinkable space."""

    width: float
    stretch: float = 0.0
    shrink: float = 0.0
    run_index: int = 0


@dataclass(frozen=True)
class Penalty:
    """A potential breakpoint.

    `width` is the material added if the break is taken here (a hyphen).
    `flagged` marks hyphen breaks so consecutive ones can be penalised.
    """

    penalty: float
    width: float = 0.0
    flagged: bool = False
    run_index: int = 0


Item = Box | Glue | Penalty


@dataclass
class Line:
    """One laid-out line: the items on it and how its glue was adjusted."""

    items: list
    start: int
    end: int
    ratio: float
    width: float
    is_last: bool = False
    hyphenated: bool = False

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


@dataclass
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


def _fitness_class(ratio: float) -> int:
    """Classify a line's looseness. Adjacent classes differing by more
    than one look visibly inconsistent, so that is penalised."""
    if ratio < -0.5:
        return 0  # tight
    if ratio <= 0.5:
        return 1  # decent
    if ratio <= 1.0:
        return 2  # loose
    return 3      # very loose


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

    def break_paragraph(
        self,
        items: Sequence,
        line_width: float | Callable = 0.0,
    ) -> list:
        """Return the optimal set of lines for `items`."""
        if not items:
            return []

        width_for = (
            line_width if callable(line_width) else (lambda _n: line_width)
        )
        sums = self._running_sums(items)

        best = self._optimize(items, sums, width_for, self.tolerance)
        if best is None:
            # Widen tolerance before giving up: a hard-to-set paragraph
            # (long URLs, narrow columns) should still produce output.
            best = self._optimize(items, sums, width_for, self.tolerance * 4)
        if best is None:
            return self._greedy(items, width_for)

        return self._assemble(items, best)

    # -- internals --

    @staticmethod
    def _running_sums(items: Sequence) -> list:
        """Cumulative width/stretch/shrink, so any span is an O(1) lookup."""
        sums = []
        width = stretch = shrink = 0.0
        for item in items:
            sums.append((width, stretch, shrink))
            if isinstance(item, Box):
                width += item.width
            elif isinstance(item, Glue):
                width += item.width
                stretch += item.stretch
                shrink += item.shrink
        sums.append((width, stretch, shrink))
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
        self, node: _Node, index: int, items: Sequence,
        sums: list, target: float,
    ) -> float:
        """How much the glue on this line must stretch (+) or shrink (-)."""
        width = sums[index][0] - node.total_width
        item = items[index]
        if isinstance(item, Penalty):
            width += item.width

        if width < target:
            stretch = sums[index][1] - node.total_stretch
            if stretch <= 0:
                return INFINITE_PENALTY
            return (target - width) / stretch
        if width > target:
            shrink = sums[index][2] - node.total_shrink
            if shrink <= 0:
                return -INFINITE_PENALTY
            return (target - width) / shrink
        return 0.0

    def _demerits(self, ratio: float, item, node: _Node, fitness: int) -> float:
        badness = 100.0 * abs(ratio) ** 3
        penalty = item.penalty if isinstance(item, Penalty) else 0.0

        if penalty >= 0:
            value = (self.line_penalty + badness + penalty) ** 2
        elif penalty > _EJECT_PENALTY:
            value = (self.line_penalty + badness) ** 2 - penalty ** 2
        else:
            value = (self.line_penalty + badness) ** 2

        if isinstance(item, Penalty) and item.flagged:
            previous = node.previous
            if previous is not None and getattr(node, "flagged", False):
                value += self.flagged_demerit

        if abs(fitness - node.fitness) > 1:
            value += self.fitness_demerit
        return value

    def _optimize(
        self, items: Sequence, sums: list,
        width_for: Callable, tolerance: float,
    ) -> _Node | None:
        active = [
            _Node(
                position=0, line=0, fitness=1,
                total_width=0.0, total_stretch=0.0, total_shrink=0.0,
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
            width = sum(
                it.width for it in segment
                if isinstance(it, (Box, Glue))
            )
            lines.append(
                Line(
                    items=segment,
                    start=start,
                    end=end,
                    ratio=chain[i].ratio,
                    width=width,
                    is_last=(i == len(chain) - 1),
                    hyphenated=hyphenated,
                )
            )
        return lines

    def _greedy(self, items: Sequence, width_for: Callable) -> list:
        """Last-resort breaker: fills each line as full as it will go.

        Also used as the comparison baseline in tests. It breaks at the
        last legal point that still fits, so lines never exceed the target
        unless a single unbreakable box is wider than the measure.
        """
        lines: list = []
        start = 0
        line_number = 0
        last_legal = None       # index of the most recent legal break
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
                lines.append(
                    Line(items=segment, start=start, end=last_legal,
                         ratio=0.0, width=width_at_legal)
                )
                broke_on = items[last_legal]
                start = (last_legal + 1 if isinstance(broke_on, Glue)
                         else last_legal)
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
                Line(items=segment, start=start, end=len(items), ratio=0.0,
                     width=width, is_last=True)
            )
        if lines:
            lines[-1].is_last = True
        return lines


def build_items(
    runs: Sequence,
    metrics_for: Callable,
    size_for: Callable,
    hyphenator=None,
    justified: bool = False,
    hyphenate: bool = False,
) -> list:
    """Convert styled text runs into a Knuth-Plass item list.

    `metrics_for(run)` returns the FontMetrics for a run and `size_for(run)`
    its point size, so mixed formatting within a paragraph measures
    correctly.
    """
    items: list = []

    for run_index, run in enumerate(runs):
        metrics = metrics_for(run)
        size = size_for(run)
        space_width = metrics.text_width(" ", size)

        # Justified text needs elastic spaces; ragged text keeps them fixed
        # so word spacing stays even and the rag falls where it falls.
        if justified:
            stretch = space_width * 0.55
            shrink = space_width * 0.35
        else:
            stretch = 0.0
            shrink = 0.0

        tokens = run.text.split(" ")
        for token_index, token in enumerate(tokens):
            if token_index > 0:
                items.append(
                    Glue(width=space_width, stretch=stretch, shrink=shrink,
                         run_index=run_index)
                )
            if not token:
                continue

            if hyphenate and hyphenator is not None and len(token) >= 5:
                points = hyphenator.break_points(token)
            else:
                points = []

            if not points:
                items.append(
                    Box(width=metrics.text_width(token, size), text=token,
                        run_index=run_index)
                )
                continue

            hyphen_width = metrics.text_width("-", size)
            previous = 0
            for point in points:
                fragment = token[previous:point]
                items.append(
                    Box(width=metrics.text_width(fragment, size),
                        text=fragment, run_index=run_index)
                )
                items.append(
                    Penalty(penalty=50.0, width=hyphen_width, flagged=True,
                            run_index=run_index)
                )
                previous = point
            tail = token[previous:]
            items.append(
                Box(width=metrics.text_width(tail, size), text=tail,
                    run_index=run_index)
            )

    # Terminate the paragraph: infinite glue absorbs the slack on the last
    # line, then a forced break ends it.
    items.append(Glue(width=0.0, stretch=INFINITE_PENALTY, shrink=0.0))
    items.append(Penalty(penalty=_EJECT_PENALTY))
    return items
