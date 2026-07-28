"""Tests for stable node ids, tag-tree /ID round-trip, and the layout map."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, Heading, Paragraph, Table  # noqa: E402
from emboss import assign_node_ids, layout_map_json  # noqa: E402
from emboss.nodeid import content_signature, derive_node_id  # noqa: E402
from emboss.writer import render_document  # noqa: E402


def _untagged(*blocks) -> Document:
    """A layout-only document (no title/tag-tree requirement)."""
    return Document(title="", tagged=False, content=list(blocks))


def _ids(data: bytes) -> list:
    return [m.decode("ascii") for m in re.findall(rb"/ID \(([^)]*)\)", data)]


# -- id assignment --


def test_every_top_level_block_gets_an_id():
    doc = _untagged(
        Heading("A", 1), Paragraph("body one"), Table(headers=["h"], rows=[["v"]])
    )
    layout = doc.layout_map()
    assert len(layout) == 3
    for entries in layout.values():
        assert entries and all("page" in e for e in entries)


def test_explicit_ids_are_honored():
    # Title matches the first heading, so no title block is prepended.
    doc = Document(
        title="A", content=[Heading("A", 1, id="sec-a"), Paragraph("body", id="para-1")]
    )
    layout = doc.layout_map()
    assert "sec-a" in layout
    assert "para-1" in layout
    assert b"(sec-a)" in render_document(doc)


def test_derived_ids_are_deterministic_across_runs():
    a = Document(
        title="Title", content=[Heading("Title", 1), Paragraph("some content")]
    )
    b = Document(
        title="Title", content=[Heading("Title", 1), Paragraph("some content")]
    )
    assert a.layout_map().keys() == b.layout_map().keys()
    assert render_document(a) == render_document(b)


def test_unrelated_block_change_leaves_earlier_ids_stable():
    base = assign_node_ids([Heading("A", 1), Paragraph("keep me")])
    extended = assign_node_ids(
        [Heading("A", 1), Paragraph("keep me"), Paragraph("new tail block")]
    )
    assert extended[0] == base[0]
    assert extended[1] == base[1]


def test_changing_text_changes_only_that_id():
    before = assign_node_ids([Heading("A", 1), Paragraph("original"), Heading("C", 2)])
    after = assign_node_ids([Heading("A", 1), Paragraph("edited"), Heading("C", 2)])
    assert after[0] == before[0]
    assert after[2] == before[2]
    assert after[1] != before[1]


def test_ids_are_unique_within_a_document():
    # Two identical paragraphs must still receive distinct ids.
    ids = assign_node_ids([Paragraph("same"), Paragraph("same"), Paragraph("same")])
    values = list(ids.values())
    assert len(set(values)) == len(values)


def test_derive_node_id_shape():
    node_id = derive_node_id(Paragraph("hello"), 0)
    assert node_id.startswith("n")
    assert len(node_id) == 9
    assert re.fullmatch(r"n[0-9a-f]{8}", node_id)


def test_content_signature_ignores_style_and_id():
    a = content_signature(Paragraph("text", id="x"))
    b = content_signature(Paragraph("text", id="y"))
    assert a == b


# -- tag tree round-trip --


def test_struct_tree_carries_ids_matching_layout_map():
    doc = Document(
        title="A", content=[Heading("A", 1, id="h"), Paragraph("body", id="p")]
    )
    data = render_document(doc)
    emitted = _ids(data)
    assert "h" in emitted
    assert "p" in emitted
    for node_id in doc.layout_map():
        assert node_id in emitted


def test_split_block_ids_stay_unique_in_id_tree():
    long = ("word " * 900).strip()
    doc = Document(title="Doc", content=[Paragraph(long, id="big")])
    data = render_document(doc)
    emitted = _ids(data)
    # One base id plus a disambiguated continuation, both unique.
    big_like = [i for i in emitted if i == "big" or i.startswith("big~")]
    assert "big" in big_like
    assert len(big_like) == len(set(big_like)) == 2


def test_id_tree_present_and_valid():
    pikepdf = pytest.importorskip("pikepdf")
    doc = Document(
        title="A", content=[Heading("A", 1, id="h"), Paragraph("body", id="p")]
    )
    data = render_document(doc)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        root = pdf.Root.StructTreeRoot
        names = root.IDTree.Names
        keys = [str(names[i]) for i in range(0, len(names), 2)]
        assert keys == sorted(keys)
        assert "h" in keys and "p" in keys
        assert len(keys) == len(set(keys))


# -- layout map --


def test_three_block_document_yields_three_entries():
    doc = _untagged(Paragraph("one"), Paragraph("two"), Paragraph("three"))
    layout = doc.layout_map()
    assert len(layout) == 3
    for entries in layout.values():
        assert len(entries) == 1
        (entry,) = entries
        assert set(entry) == {"page", "x0", "y0", "x1", "y1"}


def test_block_spanning_two_pages_yields_two_entries():
    long = ("word " * 900).strip()
    doc = Document(title="", tagged=False, content=[Paragraph(long, id="big")])
    result = render_document(doc, return_result=True)
    assert result.page_count == 2
    entries = result.layout_map["big"]
    assert len(entries) == 2
    assert {e["page"] for e in entries} == {0, 1}


def test_bbox_within_mediabox_and_matches_placement():
    doc = Document(title="", tagged=False, content=[Paragraph("hello", id="p")])
    page = doc.page
    (entry,) = doc.layout_map()["p"]
    # First flowed block sits at the top of the content area.
    assert entry["y1"] == round(page.content_top, 3)
    assert entry["x0"] == round(page.margin_left, 3)
    # Every coordinate stays inside the page mediabox.
    assert 0.0 <= entry["x0"] < entry["x1"] <= page.width
    assert 0.0 <= entry["y0"] < entry["y1"] <= page.height


def test_layout_map_json_is_deterministic_and_sorted():
    doc = _untagged(Heading("A", 1), Paragraph("body"), Paragraph("more"))
    first = layout_map_json(doc)
    second = layout_map_json(doc)
    assert first == second
    import json

    parsed = json.loads(first)
    assert list(parsed) == sorted(parsed)


def test_render_result_exposes_layout_map():
    doc = _untagged(Paragraph("body", id="p"))
    result = render_document(doc, return_result=True)
    assert "p" in result.layout_map


# -- regression: ids do not alter drawn output --


def test_ids_do_not_change_content_streams():
    pikepdf = pytest.importorskip("pikepdf")
    explicit = Document(
        title="A", content=[Heading("A", 1, id="h"), Paragraph("body", id="p")]
    )
    derived = Document(title="A", content=[Heading("A", 1), Paragraph("body")])

    def streams(data: bytes) -> list:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            return [bytes(p.Contents.read_bytes()) for p in pdf.pages]

    a = render_document(explicit)
    b = render_document(derived)
    # Different /ID values live only in the structure tree.
    assert a != b
    assert streams(a) == streams(b)
