"""Post-assembly verification.

Parses the bytes that were just written and checks that the file is
structurally sound. This catches assembler bugs at generation time rather
than in a reader weeks later. It is a structural check, not a conformance
check -- run veraPDF for PDF/UA and PDF/A validation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

__all__ = [
    "VerificationReport",
    "verify_pdf",
    "RuleViolation",
    "ConformanceReport",
    "verify_conformance",
    "WtpdfReport",
    "verify_wtpdf",
]

#: XMP conformsTo identifier for WTPDF 1.0 "Reuse" conformance.
_WTPDF_REUSE_ID = b"http://pdfa.org/declarations/wtpdf/#reuse1.0"

#: Structure types that carry meaningful reusable content in a Well-Tagged
#: PDF; their presence in a document is asserted where the content exists.
_WTPDF_CONTENT_TAGS = frozenset(
    {"H1", "H2", "H3", "H4", "H5", "H6", "P", "L", "Table", "Figure"}
)

_STRUCT_ELEM_RE = re.compile(rb"\d+ 0 obj\b(.*?)\bendobj", re.DOTALL)
_STRUCT_TAG_RE = re.compile(rb"/S\s*/([A-Za-z0-9]+)")

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


_VALID_FLAVOURS = frozenset({"ua1", "2b", "3b"})

_INSTALL_HINT = (
    "veraPDF not found: install it from https://verapdf.org/ and ensure "
    "'verapdf' is on PATH, or set VERAPDF_PATH to the CLI executable"
)


@dataclass(frozen=True)
class RuleViolation:
    """One failed veraPDF rule: specification clause plus failure count."""

    clause: str
    description: str
    count: int


@dataclass
class ConformanceReport:
    """Structured result of a veraPDF conformance validation run."""

    flavour: str
    compliant: bool
    violations: list = field(default_factory=list)

    def __str__(self) -> str:
        status = "compliant" if self.compliant else "NON-COMPLIANT"
        lines = [f"veraPDF conformance ({self.flavour}): {status}"]
        for violation in self.violations:
            lines.append(
                f"  clause {violation.clause} ({violation.count}x): "
                f"{violation.description}"
            )
        return "\n".join(lines)


def _find_verapdf() -> str | None:
    """Locate the veraPDF CLI via VERAPDF_PATH or PATH lookup."""
    env_path = os.environ.get("VERAPDF_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path
    return shutil.which("verapdf")


def _walk(node):
    """Yield every dict nested anywhere inside a parsed JSON payload."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _violation_count(summary: dict) -> int:
    """Extract a failure count from a veraPDF rule summary, tolerantly."""
    for key in ("failedChecks", "count", "occurrences"):
        value = summary.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
    return 1


def _parse_verapdf_json(payload, flavour: str) -> ConformanceReport:
    """Build a ConformanceReport from parsed veraPDF JSON output."""
    results = [node for node in _walk(payload) if "compliant" in node]
    if not results:
        raise RuntimeError("could not find a validation result in veraPDF output")
    compliant = all(bool(node["compliant"]) for node in results)
    violations = [
        RuleViolation(
            clause=str(node["clause"]),
            description=str(node.get("description", "")),
            count=_violation_count(node),
        )
        for node in _walk(payload)
        if "clause" in node
    ]
    return ConformanceReport(
        flavour=flavour, compliant=compliant, violations=violations
    )


def verify_conformance(pdf_bytes: bytes, flavour: str = "2b") -> ConformanceReport:
    """Validate *pdf_bytes* against an ISO flavour using the veraPDF CLI."""
    if flavour not in _VALID_FLAVOURS:
        allowed = ", ".join(sorted(_VALID_FLAVOURS))
        raise ValueError(f"unknown flavour {flavour!r}; must be one of: {allowed}")

    executable = _find_verapdf()
    if executable is None:
        raise RuntimeError(_INSTALL_HINT)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(pdf_bytes)
        pdf_path = handle.name
    try:
        completed = subprocess.run(
            [executable, "--flavour", flavour, "--format", "json", pdf_path],
            capture_output=True,
            timeout=300,
        )
    finally:
        os.unlink(pdf_path)

    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    if not stdout:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"veraPDF produced no output (exit {completed.returncode}): {stderr}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse veraPDF JSON output: {exc}") from exc
    return _parse_verapdf_json(payload, flavour)


@dataclass
class WtpdfReport:
    """Result of a WTPDF 1.0 (Reuse) tagging self-check."""

    ok: bool
    problems: list = field(default_factory=list)
    has_struct_tree: bool = False
    has_lang: bool = False
    wtpdf_declared: bool = False
    figure_count: int = 0
    figures_with_alt: int = 0
    structure_types: set = field(default_factory=set)

    def __str__(self) -> str:
        status = "conformant" if self.ok else "NON-CONFORMANT"
        lines = [
            f"WTPDF 1.0 (Reuse): {status}",
            f"  structure tree: {self.has_struct_tree}",
            f"  language set: {self.has_lang}",
            f"  WTPDF declared: {self.wtpdf_declared}",
            f"  figures: {self.figures_with_alt}/{self.figure_count} with Alt",
            f"  structure types: {', '.join(sorted(self.structure_types))}",
        ]
        lines.extend(f"  problem: {p}" for p in self.problems)
        return "\n".join(lines)


def _iter_struct_elems(data: bytes):
    """Yield the dictionary body bytes of each /StructElem object."""
    for match in _STRUCT_ELEM_RE.finditer(data):
        body = match.group(1)
        if b"stream" in body:
            continue
        if b"/Type /StructElem" in body or b"/Type/StructElem" in body:
            yield body


def verify_wtpdf(pdf_bytes: bytes) -> WtpdfReport:
    """Check the substantive WTPDF 1.0 "Reuse" tagging requirements.

    Asserts what Emboss can verify from the bytes it just wrote: a
    structure tree with a document language, the WTPDF conformsTo
    declaration in the XMP metadata, recognized structure types on the
    content, and Alt text on every /Figure element. Returns a
    :class:`WtpdfReport` in the style of :func:`verify_pdf`.
    """
    problems: list = []

    structural = verify_pdf(pdf_bytes)
    problems.extend(structural.problems)

    has_struct = structural.has_struct_tree
    if not has_struct:
        problems.append("no structure tree: WTPDF requires tagged content")
    has_lang = structural.has_lang
    if not has_lang:
        problems.append("no document language (/Lang): required by WTPDF")

    wtpdf_declared = _WTPDF_REUSE_ID in pdf_bytes
    if not wtpdf_declared:
        problems.append("WTPDF conformsTo declaration missing from XMP metadata")

    structure_types: set = set()
    figure_count = 0
    figures_with_alt = 0
    for body in _iter_struct_elems(pdf_bytes):
        tag_match = _STRUCT_TAG_RE.search(body)
        if tag_match is None:
            continue
        tag = tag_match.group(1).decode("ascii")
        structure_types.add(tag)
        if tag == "Figure":
            figure_count += 1
            if b"/Alt" in body:
                figures_with_alt += 1
            else:
                problems.append("figure structure element missing Alt text")

    if has_struct and not (structure_types & _WTPDF_CONTENT_TAGS):
        problems.append("structure tree carries no reusable content elements")

    return WtpdfReport(
        ok=not problems,
        problems=problems,
        has_struct_tree=has_struct,
        has_lang=has_lang,
        wtpdf_declared=wtpdf_declared,
        figure_count=figure_count,
        figures_with_alt=figures_with_alt,
        structure_types=structure_types,
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
