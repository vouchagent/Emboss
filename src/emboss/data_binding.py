"""Build tables and charts directly from a CSV file or DataFrame.

A finance or exec-brief pipeline produces figures from a data export, not a
hand-typed Python list. These helpers read the data once and hand it to the
existing ``Document.table``/``Document.chart`` construction, so every table
and chart feature (``verify_totals``, ``attach_data``, styling, captions)
composes for free -- there is no separate code path to keep in sync.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .arithmetic import parse_number

__all__ = [
    "read_csv_rows",
    "rows_from_dataframe",
    "numeric_columns",
    "series_from_columns",
]


def _is_dataframe(data) -> bool:
    """Duck-type a pandas DataFrame without importing pandas at module load."""
    return hasattr(data, "to_csv") and hasattr(data, "columns")


def rows_from_dataframe(df) -> tuple:
    """Return (headers, rows) from a pandas DataFrame, as strings.

    Imports pandas only when actually called with a DataFrame-like object,
    so pandas stays an optional, never-required dependency.
    """
    headers = [str(c) for c in df.columns]
    rows = [[("" if v is None else str(v)) for v in row] for row in df.values]
    return headers, rows


def read_csv_rows(source, *, has_header: bool = True) -> tuple:
    """Return (headers, rows) read from a CSV path, file object, or string.

    ``source`` may be a path (str/Path), an already-open text file object, a
    ``io.StringIO``/file-like object, or a DataFrame-like object (duck-typed
    via ``to_csv``/``columns``, so pandas need not be installed to use the
    rest of this module). Without a header row, columns are synthesized as
    ``Column 1``, ``Column 2``, ...
    """
    if _is_dataframe(source):
        return rows_from_dataframe(source)

    if isinstance(source, (str, Path)) and not _looks_like_csv_text(source):
        with open(source, newline="", encoding="utf-8") as fh:
            return _read_csv_stream(fh, has_header=has_header)
    if isinstance(source, (str, Path)):
        return _read_csv_stream(io.StringIO(str(source)), has_header=has_header)
    return _read_csv_stream(source, has_header=has_header)


def _looks_like_csv_text(source) -> bool:
    """Heuristic: a str with a newline, or empty, is CSV text, not a file path."""
    return isinstance(source, str) and ("\n" in source or source == "")


def _read_csv_stream(stream, *, has_header: bool) -> tuple:
    reader = csv.reader(stream)
    all_rows = [row for row in reader if row]
    if not all_rows:
        raise ValueError("no rows found in CSV source")

    if has_header:
        headers, rows = all_rows[0], all_rows[1:]
    else:
        width = max(len(r) for r in all_rows)
        headers = [f"Column {i + 1}" for i in range(width)]
        rows = all_rows
    return headers, rows


def numeric_columns(headers, rows, value_columns=None, category_column=0):
    """Pick which columns are numeric series, in header order.

    ``value_columns`` may be a list of column indices or header names; when
    omitted, every column except ``category_column`` whose cells all parse
    as numbers (via ``arithmetic.parse_number``) is used.
    """
    if isinstance(category_column, str):
        category_column = headers.index(category_column)

    if value_columns is not None:
        indices = [headers.index(c) if isinstance(c, str) else c for c in value_columns]
        return indices

    indices = []
    for i, header in enumerate(headers):
        if i == category_column:
            continue
        if rows and all(
            parse_number(row[i]) is not None for row in rows if i < len(row)
        ):
            indices.append(i)
    return indices


def series_from_columns(headers, rows, indices) -> list:
    from .spec import Series

    series = []
    for i in indices:
        values = [parse_number(row[i]) if i < len(row) else None for row in rows]
        series.append(Series(label=headers[i], values=[v or 0.0 for v in values]))
    return series
