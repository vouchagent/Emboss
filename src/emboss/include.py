"""Load code-block content from source files so examples cannot drift.

``include_source`` reads a file and returns a selected slice: a 1-based
inclusive line range (``lines="10-20"``), a named region delimited by
marker comments (``marker="name"``), or the whole file. Region markers
support both the ``# region name`` / ``# endregion`` and the
``# BEGIN name`` / ``# END name`` conventions, with the common comment
leaders (``#``, ``//``, ``--``, ``;``, ``%``). Common leading whitespace
is stripped by default.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

__all__ = ["include_source", "IncludeError"]


class IncludeError(ValueError):
    """Raised when an included file, line range, or marker cannot be found."""


_RANGE_RE = re.compile(r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*$")
_LEADER = r"(?:#|//|--|;|%|/\*|\*)*"
_START_RE = re.compile(rf"^\s*{_LEADER}\s*(?:region|begin)\s+(\S+)\b", re.IGNORECASE)
_END_RE = re.compile(
    rf"^\s*{_LEADER}\s*(?:endregion|end)(?:\s+(\S+))?\b", re.IGNORECASE
)


def _parse_range(spec: str, total: int) -> tuple[int, int]:
    """Return the 0-based [start, end) slice for a 1-based inclusive spec."""
    match = _RANGE_RE.match(spec)
    if match is None:
        raise IncludeError(f"invalid line range: {spec!r}")
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if start < 1 or end < start:
        raise IncludeError(f"invalid line range: {spec!r}")
    if start > total:
        raise IncludeError(
            f"line range {spec!r} starts past end of file ({total} lines)"
        )
    return start - 1, min(end, total)


def _extract_marker(lines: list[str], marker: str) -> list[str]:
    """Return the lines strictly between the start and end markers for name."""
    start_idx = None
    for idx, line in enumerate(lines):
        match = _START_RE.match(line)
        if match and match.group(1) == marker:
            start_idx = idx
            break
    if start_idx is None:
        raise IncludeError(f"marker region not found: {marker!r}")
    for idx in range(start_idx + 1, len(lines)):
        match = _END_RE.match(lines[idx])
        if match and (match.group(1) is None or match.group(1) == marker):
            return lines[start_idx + 1 : idx]
    raise IncludeError(f"marker region not closed: {marker!r}")


def include_source(
    path: str | Path,
    *,
    lines: str | None = None,
    marker: str | None = None,
    dedent: bool = True,
) -> str:
    """Read `path` and return a line range, named region, or the whole file."""
    if lines is not None and marker is not None:
        raise IncludeError("give only one of 'lines' or 'marker', not both")
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise IncludeError(f"included file not found: {source}") from exc
    except OSError as exc:
        raise IncludeError(f"cannot read included file {source}: {exc}") from exc

    file_lines = text.splitlines()
    if lines is not None:
        start, end = _parse_range(lines, len(file_lines))
        selected = file_lines[start:end]
    elif marker is not None:
        selected = _extract_marker(file_lines, marker)
    else:
        selected = file_lines

    body = "\n".join(selected)
    if dedent:
        body = textwrap.dedent(body)
    return body
