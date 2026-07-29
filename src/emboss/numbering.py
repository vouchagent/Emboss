"""Auto-numbering for document elements.

Assigns sequential numbers to captioned elements (Figure 1, Table 1,
Equation 1, Listing 1) and hierarchical numbers to headings (1., 1.1.).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NumberingContext:
    """Auto-incrementing counters for document elements."""

    _counters: dict = field(
        default_factory=lambda: {
            "figure": 0,
            "table": 0,
            "equation": 0,
            "listing": 0,
        }
    )
    _heading: list = field(default_factory=lambda: [0] * 6)
    _labels: dict = field(default_factory=dict)

    def next(self, kind: str) -> int:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        return self._counters[kind]

    def register(self, label: str, kind: str, number: int) -> None:
        prefix = kind.capitalize()
        self._labels[label] = f"{prefix} {number}"

    def resolve(self, label: str) -> str | None:
        return self._labels.get(label)

    def next_heading(self, level: int) -> str:
        self._heading[level - 1] += 1
        for i in range(level, 6):
            self._heading[i] = 0
        return ".".join(str(self._heading[i]) for i in range(level))


def _alpha_upper(value: int) -> str:
    """Spreadsheet-style uppercase letters: 1 -> A, 26 -> Z, 27 -> AA."""
    label = ""
    while value > 0:
        value, rem = divmod(value - 1, 26)
        label = chr(ord("A") + rem) + label
    return label


@dataclass
class AppendixNumberingContext:
    """Letters top-level appendices (A, B, ...) with flat `A.1` sub-numbers.

    Sub-heading numbering is flat within each appendix regardless of
    heading level, restarting whenever `next_appendix` starts a new one.
    """

    _letter_index: int = 0
    _sub_counter: int = 0

    def next_appendix(self) -> str:
        self._letter_index += 1
        self._sub_counter = 0
        return _alpha_upper(self._letter_index)

    def next_heading(self, level: int = 1) -> str:
        self._sub_counter += 1
        letter = _alpha_upper(self._letter_index) if self._letter_index else "A"
        return f"{letter}.{self._sub_counter}"
