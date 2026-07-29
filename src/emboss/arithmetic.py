"""Check that a table's total rows and columns actually add up.

A financial table that labels a row "Total" is asserting an arithmetic fact.
``check_table_totals`` verifies it: every numeric cell in a total row must
equal the sum of the data cells above it in that column, and a "Total" column
must equal the sum of the row's other numeric cells. A document can set
``verify_totals=True`` on a table to make a mismatch a hard validation error,
so an internally inconsistent table is refused rather than rendered.
"""

from __future__ import annotations

import re

__all__ = ["parse_number", "check_table_totals"]

_TOTAL_LABEL_RE = re.compile(r"^\s*(grand\s+)?(sub)?total\b|\bsum\b", re.IGNORECASE)

# Comparison tolerance, in the table's own units (covers cent rounding).
_TOLERANCE = 0.02


def _is_total_label(text: str) -> bool:
    return bool(_TOTAL_LABEL_RE.search(text or ""))


def parse_number(cell: str) -> float | None:
    """Parse a formatted numeric cell to a float, or None if it is not a number.

    Handles a leading currency symbol, thousands separators, a trailing
    percent sign, and accounting-style parentheses for negatives. Both
    ``1,234.50`` and ``1.234,50`` are understood; the last separator is the
    decimal point.
    """
    s = (cell or "").strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s or s in ("-", ".", ","):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]) and parts[0]:
            s = s.replace(",", "")  # thousands grouping
        else:
            s = s.replace(",", ".")  # decimal comma
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def _cell(rows, r: int, c: int) -> str:
    row = rows[r]
    return row[c] if c < len(row) else ""


def check_table_totals(headers, rows, tolerance: float = _TOLERANCE) -> list:
    """Return a list of human-readable discrepancy messages, empty if consistent.

    ``headers`` and ``rows`` are sequences of plain-text cells. A total row is
    one whose first cell reads Total / Subtotal / Grand Total / Sum; a total
    column is one whose header reads the same.
    """
    headers = [str(h) for h in headers]
    rows = [[str(c) for c in row] for row in rows]
    if not rows:
        return []
    ncols = max([len(headers)] + [len(r) for r in rows])

    total_rows = {i for i, r in enumerate(rows) if r and _is_total_label(r[0])}
    data_rows = [i for i in range(len(rows)) if i not in total_rows]
    messages: list = []

    # Total rows: each numeric column equals the sum of the data cells above.
    for ti in sorted(total_rows):
        above = [i for i in data_rows if i < ti]
        for c in range(1, ncols):
            declared = parse_number(_cell(rows, ti, c))
            if declared is None:
                continue
            nums = [parse_number(_cell(rows, i, c)) for i in above]
            nums = [n for n in nums if n is not None]
            if not nums:
                continue
            actual = sum(nums)
            if abs(actual - declared) > tolerance:
                col = headers[c] if c < len(headers) else f"column {c + 1}"
                messages.append(
                    f"total row: {col!r} shows {declared:g} but its cells "
                    f"sum to {actual:g}"
                )

    # A trailing "Total" column equals the sum of the row's other cells.
    if ncols >= 3 and headers and _is_total_label(headers[-1]):
        tc = ncols - 1
        for i in data_rows:
            declared = parse_number(_cell(rows, i, tc))
            if declared is None:
                continue
            nums = [parse_number(_cell(rows, i, c)) for c in range(1, tc)]
            nums = [n for n in nums if n is not None]
            if not nums:
                continue
            actual = sum(nums)
            if abs(actual - declared) > tolerance:
                label = _cell(rows, i, 0) or f"row {i + 1}"
                messages.append(
                    f"total column: {label!r} shows {declared:g} but its cells "
                    f"sum to {actual:g}"
                )

    return messages
