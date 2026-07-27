"""Tests for flagged-break demerits, the hyphen ladder cap, and
emergency character-level breaking of oversized words."""

from __future__ import annotations

import pytest

from emboss.typography.line_breaking import (
    Box,
    Glue,
    INFINITE_PENALTY,
    LineBreaker,
    Penalty,
    build_items,
)


class _FlatMetrics:
    """Fake metrics giving every character a fixed 6pt advance."""

    def text_width(self, text: str, size: float) -> float:
        return 6.0 * len(text)


class _Run:
    """Minimal stand-in for a styled text run."""

    def __init__(self, text: str) -> None:
        self.text = text


def _terminate(items: list) -> list:
    """Append the standard paragraph terminator (glue + forced break)."""
    items.append(Glue(width=0.0, stretch=INFINITE_PENALTY, shrink=0.0))
    items.append(Penalty(penalty=-INFINITE_PENALTY))
    return items


def _hyphen_chain(words: int) -> list:
    """Words joined by a cheap flagged break and a costly unflagged one."""
    items: list = []
    for i in range(words):
        items.append(Box(width=60.0, text="hyhyhy"))
        if i < words - 1:
            items.append(Penalty(penalty=10.0, width=5.0, flagged=True))
            items.append(Penalty(penalty=300.0, width=5.0, flagged=False))
    return _terminate(items)


def _flagged_run_lengths(lines: list, items: list) -> list[int]:
    """Lengths of consecutive runs of lines ending at a flagged break."""
    runs: list[int] = []
    current = 0
    for line in lines:
        break_item = items[line.end] if line.end < len(items) else None
        if isinstance(break_item, Penalty) and break_item.flagged:
            current += 1
        else:
            runs.append(current)
            current = 0
    runs.append(current)
    return runs


def _double_hyphen_items() -> list:
    """Three boxes forced to break at two consecutive flagged penalties."""
    items = [
        Box(width=65.0, text="aaa"),
        Penalty(penalty=50.0, width=5.0, flagged=True),
        Box(width=65.0, text="bbb"),
        Penalty(penalty=50.0, width=5.0, flagged=True),
        Box(width=65.0, text="ccc"),
    ]
    return _terminate(items)


class TestLadderCap:
    """At most three consecutive lines may end in a flagged break."""

    def test_at_most_three_consecutive_flagged_lines(self):
        items = _hyphen_chain(10)
        breaker = LineBreaker(protrusion=False, avoid_rivers=False)
        lines = breaker.break_paragraph(items, 65.0)
        runs = _flagged_run_lengths(lines, items)
        assert lines
        assert max(runs) <= 3
        assert sum(runs) >= 5  # the paragraph does hyphenate repeatedly

    def test_cap_is_enforced_by_ladder_demerit(self):
        items = _hyphen_chain(10)
        uncapped = LineBreaker(
            protrusion=False,
            avoid_rivers=False,
            ladder_demerit=0.0,
        )
        lines = uncapped.break_paragraph(items, 65.0)
        assert max(_flagged_run_lengths(lines, items)) > 3


class TestFlaggedDemerits:
    """The double-hyphen demerit must actually affect the optimisation."""

    def test_flagged_demerit_changes_total_demerits(self):
        totals = {}
        for value in (0.0, 3000.0):
            breaker = LineBreaker(
                flagged_demerit=value,
                protrusion=False,
                avoid_rivers=False,
            )
            items = _double_hyphen_items()
            sums = breaker._running_sums(items)
            best = breaker._optimize(
                items,
                sums,
                lambda _n: 70.0,
                breaker.tolerance,
            )
            assert best is not None
            totals[value] = best.demerits
        assert totals[3000.0] > totals[0.0]
        assert totals[3000.0] - totals[0.0] == pytest.approx(3000.0)

    def test_double_hyphen_lines_are_flagged(self):
        breaker = LineBreaker(protrusion=False, avoid_rivers=False)
        lines = breaker.break_paragraph(_double_hyphen_items(), 70.0)
        assert [line.text for line in lines] == ["aaa-", "bbb-", "ccc"]


class TestEmergencyBreaking:
    """A single token wider than the measure must be split, not overflow."""

    def _items(self) -> tuple[list, str]:
        metrics = _FlatMetrics()
        token = "https://example.com/" + "a" * 70  # 90 chars = 540pt
        run = _Run("see " + token + " end")
        items = build_items(
            [run],
            lambda _r: metrics,
            lambda _r: 12.0,
            justified=True,
        )
        return items, token

    def test_oversized_token_never_overflows(self):
        items, _token = self._items()
        lines = LineBreaker().break_paragraph(items, 200.0)
        assert len(lines) >= 3
        assert all(line.width <= 200.0 + 1e-9 for line in lines)

    def test_no_hyphen_character_is_added(self):
        items, token = self._items()
        lines = LineBreaker().break_paragraph(items, 200.0)
        assert all(not line.hyphenated for line in lines)
        joined = "".join(
            item.text for line in lines for item in line.items if isinstance(item, Box)
        )
        assert joined == "see" + token + "end"

    def test_greedy_path_never_overflows(self):
        items, _token = self._items()
        breaker = LineBreaker()
        lines = breaker._greedy(items, lambda _n: 200.0)
        assert len(lines) >= 3
        assert all(line.width <= 200.0 + 1e-9 for line in lines)

    def test_build_items_populates_char_widths(self):
        metrics = _FlatMetrics()
        items = build_items(
            [_Run("word list")],
            lambda _r: metrics,
            lambda _r: 10.0,
        )
        boxes = [item for item in items if isinstance(item, Box)]
        assert boxes
        for box in boxes:
            assert box.char_widths == (6.0,) * len(box.text)
            assert sum(box.char_widths) == pytest.approx(box.width)


class TestNormalTextRegression:
    """Normal paragraphs must break exactly as they did before the fix."""

    def _items(self) -> list:
        metrics = _FlatMetrics()
        run = _Run("the quick brown fox jumps over the lazy dog again and again")
        return build_items(
            [run],
            lambda _r: metrics,
            lambda _r: 12.0,
            justified=True,
        )

    def test_explosion_leaves_normal_items_unchanged(self):
        items = self._items()
        breaker = LineBreaker(avoid_rivers=False)
        assert breaker._exploded(items, lambda _n: 150.0) == items

    def test_break_output_matches_pre_explosion_pipeline(self):
        items = self._items()
        breaker = LineBreaker(avoid_rivers=False)
        sums = breaker._running_sums(items)
        best = breaker._optimize(
            items,
            sums,
            lambda _n: 150.0,
            breaker.tolerance,
        )
        assert best is not None  # the optimal path, not the greedy fallback
        expected = breaker._assemble(items, best)
        got = breaker.break_paragraph(items, 150.0)
        key = [
            (line.start, line.end, line.width, line.ratio, line.text) for line in got
        ]
        assert key == [
            (line.start, line.end, line.width, line.ratio, line.text)
            for line in expected
        ]
