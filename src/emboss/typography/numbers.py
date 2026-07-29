"""Deterministic, locale-independent numeric formatting for display text.

This is presentation formatting for values headed into text runs or table
cells (an LLM writing "$1,234.50" instead of raw "1234.5"); it is not the
`align="decimal"` table-cell alignment mechanism, which operates on
already-formatted strings at layout time.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["format_number"]

NumberStyle = Literal["plain", "thousands", "currency", "percent"]

_STYLES = ("plain", "thousands", "currency", "percent")
_DEFAULT_DECIMALS = {"plain": 0, "thousands": 0, "currency": 2, "percent": 1}


def format_number(
    value,
    style: NumberStyle = "plain",
    currency_symbol: str = "$",
    decimals: int | None = None,
) -> str:
    """Format a number for display: thousands grouping, currency, or percent.

    `style="percent"` treats `value` as a fraction (0.123 -> "12.3%").
    `decimals` overrides the style's default decimal-place count. Grouping
    is done by hand rather than through the `locale` module, so output is
    identical on every machine regardless of process locale state.
    """
    if style not in _STYLES:
        raise ValueError(f"unknown number style: {style!r}; expected one of {_STYLES}")

    places = _DEFAULT_DECIMALS[style] if decimals is None else decimals
    if places < 0:
        raise ValueError("decimals must be >= 0")

    number = float(value)
    if style == "percent":
        number *= 100.0

    negative = number < 0
    magnitude = abs(number)
    text = f"{magnitude:.{places}f}"
    int_part, _, frac_part = text.partition(".")

    if style in ("thousands", "currency"):
        int_part = _group_thousands(int_part)

    result = int_part + (f".{frac_part}" if frac_part else "")
    if style == "currency":
        result = f"{currency_symbol}{result}"
    if style == "percent":
        result = f"{result}%"
    if negative:
        result = f"-{result}"
    return result


def _group_thousands(digits: str) -> str:
    """Insert a comma every three digits from the right of an integer string."""
    if len(digits) <= 3:
        return digits
    groups: list[str] = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return ",".join(groups)
