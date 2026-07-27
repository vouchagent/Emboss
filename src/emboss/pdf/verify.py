"""Post-assembly verification.

Parses the bytes that were just written and checks that the file is
structurally sound. This catches assembler bugs at generation time rather
than in a reader weeks later. It is a structural check, not a conformance
check -- run veraPDF for PDF/UA and PDF/A validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["VerificationReport", "verify_pdf"]

_XREF_ENTRY = re.compile(rb"^(\d{10}) (\d{5}) ([nf]) ?$")


@dataclass
class VerificationReport:
    ok: bool
    problems: list = field(default_factory=list)
    object_count: int = 0
    page_count: int = 0
    has_struct_tree: bool = False
    has_lang: bool = False

    def __str__(self) -> str:
        status = "valid" if self.ok else "INVALID"
        lines = [
            f"PDF structure: {status}",
            f"  objects: {self.object_count}",
            f"  pages: {self.page_count}",
            f"  tagged: {self.has_struct_tree}",
            f"  language set: {self.has_lang}",
        ]
        lines.extend(f"  problem: {p}" for p in self.problems)
        return "\n".join(lines)


def verify_pdf(data: bytes) -> VerificationReport:
    """Check the structural integrity of a generated PDF."""
    problems: list = []

    if not data.startswith(b"%PDF-"):
        problems.append("missing %PDF header")
    if not data.rstrip().endswith(b"%%EOF"):
        problems.append("missing %%EOF trailer")

    startxref_index = data.rfind(b"startxref")
    xref_offset = None
    if startxref_index == -1:
        problems.append("missing startxref")
    else:
        tail = data[startxref_index + len(b"startxref") :].strip()
        match = re.match(rb"(\d+)", tail)
        if not match:
            problems.append("startxref value is not a number")
        else:
            xref_offset = int(match.group(1))
            if xref_offset >= len(data):
                problems.append(f"startxref points past end of file ({xref_offset})")
            elif not data[xref_offset : xref_offset + 4] == b"xref":
                problems.append(
                    f"startxref {xref_offset} does not point at an xref table"
                )

    object_count = 0
    if xref_offset is not None and xref_offset < len(data):
        object_count = _verify_xref(data, xref_offset, problems)

    page_count = data.count(b"/Type /Page\n") + data.count(b"/Type /Page ")
    count_match = re.search(rb"/Count (\d+)", data)
    declared = int(count_match.group(1)) if count_match else 0

    has_struct = b"/StructTreeRoot" in data
    has_lang = b"/Lang" in data

    if has_struct and b"/ParentTree" not in data:
        problems.append("structure tree present but ParentTree is missing")
    if has_struct and b"/MarkInfo" not in data:
        problems.append("structure tree present but MarkInfo is missing")

    return VerificationReport(
        ok=not problems,
        problems=problems,
        object_count=object_count,
        page_count=declared or page_count,
        has_struct_tree=has_struct,
        has_lang=has_lang,
    )


def _verify_xref(data: bytes, offset: int, problems: list) -> int:
    """Check that every xref entry points at the object it claims."""
    _ = data[offset : offset + 40]
    lines = data[offset:].split(b"\n", 2)
    if len(lines) < 2:
        problems.append("xref table is truncated")
        return 0

    header = lines[1].strip()
    parts = header.split()
    if len(parts) != 2:
        problems.append(f"malformed xref subsection header: {header!r}")
        return 0

    start, count = int(parts[0]), int(parts[1])
    entries_start = offset + len(lines[0]) + 1 + len(lines[1]) + 1
    checked = 0

    for index in range(count):
        entry_offset = entries_start + index * 20
        entry = data[entry_offset : entry_offset + 20]
        if len(entry) < 18:
            problems.append(f"xref entry {index} is truncated")
            break
        match = _XREF_ENTRY.match(entry.rstrip(b"\r\n "))
        if not match:
            problems.append(f"xref entry {index} is malformed: {entry!r}")
            continue
        target, _gen, kind = int(match.group(1)), match.group(2), match.group(3)
        if kind == b"f":
            continue
        expected = f"{start + index} 0 obj".encode("ascii")
        actual = data[target : target + len(expected)]
        if actual != expected:
            problems.append(
                f"xref entry {start + index} points to offset {target} "
                f"which holds {actual!r}, expected {expected!r}"
            )
        checked += 1

    return checked
