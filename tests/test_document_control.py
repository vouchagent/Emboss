"""Tests for the controlled-document control block."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import (  # noqa: E402
    Approval,
    Document,
    DocumentControl,
    RevisionEntry,
    document_to_spec_dict,
)
from emboss.adapters.html_export import to_html  # noqa: E402
from emboss.adapters.markdown_export import to_markdown  # noqa: E402
from emboss.recovery import spec_dict_to_json  # noqa: E402

pikepdf = pytest.importorskip("pikepdf")

_LITERAL = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _squashed(page) -> bytes:
    stream = bytes(page.Contents.read_bytes())
    text = b"".join(m.group(1) for m in _LITERAL.finditer(stream))
    return text.replace(b" ", b"")


def _all_text(data: bytes) -> bytes:
    pdf = pikepdf.open(io.BytesIO(data))
    return b"".join(_squashed(p) for p in pdf.pages)


def _sample_control(**overrides) -> DocumentControl:
    kwargs = dict(
        doc_id="QMS-001",
        title="Cleaning SOP",
        version="3.2",
        status="Released",
        effective_date="2026-01-15",
        classification="Controlled",
        owner="Quality",
        approvals=[
            Approval("Ada Reviewer", "QA Lead", "2026-01-10"),
            Approval("Ben Boss", "Director", "2026-01-12"),
        ],
        revisions=[
            RevisionEntry("3.2", "2026-01-15", "Jane Doe", "Annual review update."),
            RevisionEntry("3.1", "2025-06-01", "Jane Doe", "Fixed step ordering."),
        ],
    )
    kwargs.update(overrides)
    return DocumentControl(**kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_fluent_api_builds_element():
    doc = Document(title="SOP")
    doc.document_control(doc_id="QMS-001", version="1.0", status="Draft")
    assert isinstance(doc.content[0], DocumentControl)
    assert doc.content[0].doc_id == "QMS-001"


def test_dict_input_normalizes_to_dataclasses():
    control = DocumentControl(
        doc_id="D-1",
        approvals=[{"name": "A. One", "role": "QA", "date": "2026-01-01"}],
        revisions=[
            {"version": "1.0", "date": "2026-01-01", "author": "X", "summary": "y"}
        ],
    )
    approvals = control.approval_list
    revisions = control.revision_list
    assert approvals[0].name == "A. One"
    assert approvals[0].statement == "Approved"
    assert revisions[0].version == "1.0"


def test_metadata_pairs_skip_empty_fields():
    control = DocumentControl(doc_id="D-1", version="2.0")
    labels = [label for label, _value in control.metadata_pairs]
    assert labels == ["Document ID", "Version"]


def test_both_inputs_render_to_pdf():
    fluent = Document(title="A")
    fluent.document_control(doc_id="D-1", version="1.0", status="Draft")
    assert fluent.render().startswith(b"%PDF-")

    loose = Document(title="B")
    loose.add(
        DocumentControl(
            doc_id="D-2",
            approvals=[{"name": "Q", "role": "QA", "date": "2026-01-01"}],
        )
    )
    assert loose.render().startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_rendered_pdf_contains_all_fields():
    doc = Document(title="SOP")
    doc.add(_sample_control())
    text = _all_text(doc.render())
    for probe in (b"QMS-001", b"3.2", b"Released", b"AdaReviewer", b"Annualreview"):
        assert probe in text, probe


def test_tables_are_tagged():
    doc = Document(title="SOP")
    doc.add(_sample_control())
    data = doc.render()
    # The two data tables are emitted as real /Table structures with header
    # cells scoped /TH; body cells are /TD in /TR rows.
    assert b"/S /Table" in data
    assert b"/S /TH" in data
    assert b"/S /TD" in data


def test_document_stays_pdf_ua_valid():
    from emboss.pdf.verify import verify_pdf

    doc = Document(title="SOP")
    doc.add(_sample_control())
    report = verify_pdf(doc.render())
    assert report.ok, report.problems


def test_render_is_deterministic():
    def make() -> bytes:
        doc = Document(title="SOP")
        doc.add(_sample_control())
        return doc.render()

    assert make() == make()


def test_long_revision_history_paginates():
    revisions = [
        RevisionEntry(
            f"{i}.0",
            f"2026-01-{(i % 28) + 1:02d}",
            f"Author {i}",
            f"Revision number {i} described in some detail for pagination.",
        )
        for i in range(1, 120)
    ]
    doc = Document(title="History")
    doc.document_control(
        doc_id="X-1", version="119.0", status="Released", revisions=revisions
    )
    data = doc.render()
    assert data.startswith(b"%PDF-")
    pdf = pikepdf.open(io.BytesIO(data))
    assert len(pdf.pages) > 1


def test_empty_control_still_renders():
    doc = Document(title="Empty")
    doc.add(DocumentControl())
    assert doc.render().startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_spec_dict_round_trip_preserves_fields():
    doc = Document(title="SOP")
    doc.add(_sample_control(id="ctrl-1"))
    spec = document_to_spec_dict(doc)
    restored = Document.from_json(spec_dict_to_json(spec).decode("utf-8"))
    element = restored.content[0]
    assert isinstance(element, DocumentControl)
    assert element.id == "ctrl-1"
    assert element.doc_id == "QMS-001"
    assert element.version == "3.2"
    assert element.status == "Released"
    assert element.classification == "Controlled"
    assert len(element.approval_list) == 2
    assert element.approval_list[0].name == "Ada Reviewer"
    assert len(element.revision_list) == 2
    assert element.revision_list[0].summary == "Annual review update."


def test_manual_parse_builds_control():
    from emboss.generate import _manual_parse

    data = {
        "title": "SOP",
        "content": [
            {
                "type": "document_control",
                "doc_id": "M-1",
                "version": "2.0",
                "approvals": [{"name": "Q. A.", "role": "QA", "date": "2026-01-01"}],
                "revisions": [
                    {
                        "version": "2.0",
                        "date": "2026-01-01",
                        "author": "X",
                        "summary": "Init.",
                    }
                ],
            }
        ],
    }
    doc = _manual_parse(data)
    element = doc.content[0]
    assert isinstance(element, DocumentControl)
    assert element.doc_id == "M-1"
    assert element.approval_list[0].name == "Q. A."


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def test_html_export_renders_tables():
    doc = Document(title="SOP")
    doc.add(_sample_control())
    html = to_html(doc)
    assert "document-control" in html
    assert "QMS-001" in html
    assert "<th>Name</th>" in html.replace(" ", "")
    assert "Ada Reviewer" in html


def test_markdown_export_renders_tables():
    doc = Document(title="SOP")
    doc.add(_sample_control())
    md = to_markdown(doc)
    assert "QMS-001" in md
    assert "| Version" in md
    assert "Ada Reviewer" in md
