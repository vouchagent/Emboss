"""Tests for display-equation numbering and @eq / \\eqref resolution."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.spec import MathBlock  # noqa: E402

pikepdf = pytest.importorskip("pikepdf")

_LITERAL = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _all_text(data: bytes) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        streams = [bytes(p.Contents.read_bytes()) for p in pdf.pages]
    raw = b"".join(m.group(1) for s in streams for m in _LITERAL.finditer(s))
    return raw.replace(rb"\(", b"(").replace(rb"\)", b")")


def test_equations_number_sequentially():
    doc = Document(title="Math", style="academic")
    for src in ("E = mc^2", "a^2 + b^2 = c^2", "F = ma"):
        doc.add(MathBlock(src, number=True))
    text = _all_text(doc.render())
    assert b"(1)" in text
    assert b"(2)" in text
    assert b"(3)" in text


def test_reference_resolves_to_number_with_goto():
    doc = Document(title="Math", style="academic")
    doc.paragraph("Mass-energy equivalence is @eq:energy.")
    doc.add(MathBlock("E = mc^2", number=True, label="eq:energy"))
    data = doc.render()
    text = _all_text(data)
    # The @eq token resolved to the bare equation number.
    assert b"(1)" in text
    # A GoTo link annotation points at the equation's page.
    with pikepdf.open(io.BytesIO(data)) as pdf:
        dests = []
        for page in pdf.pages:
            for annot in page.get("/Annots") or []:
                if annot.get("/Dest") is not None:
                    dests.append(annot)
        assert dests, "expected an internal GoTo annotation for @eq:energy"


def test_eqref_command_resolves():
    doc = Document(title="Math", style="academic")
    doc.paragraph("See \\eqref{energy} for details.")
    doc.add(MathBlock("E = mc^2", number=True, label="eq:energy"))
    text = _all_text(doc.render())
    assert b"(1)" in text
    # The raw command text must not survive.
    assert b"eqref" not in text


def test_tag_overrides_number_text():
    doc = Document(title="Math", style="academic")
    doc.add(MathBlock("E = mc^2", number=True, tag="(3a)"))
    text = _all_text(doc.render())
    assert b"(3a)" in text


def test_unnumbered_equation_has_no_number():
    doc = Document(title="Math", style="academic")
    doc.add(MathBlock("x + y", number=False))
    text = _all_text(doc.render())
    assert b"(1)" not in text


def test_equation_numbering_determinism():
    doc = Document(title="Math", style="academic")
    doc.paragraph("Refer to @eq:e.")
    doc.add(MathBlock("E = mc^2", number=True, label="eq:e"))
    doc.add(MathBlock("F = ma", number=True))
    assert doc.render() == doc.render()
