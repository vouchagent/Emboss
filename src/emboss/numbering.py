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
