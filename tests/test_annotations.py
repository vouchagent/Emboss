"""Tests for reading reviewer markup back out of a PDF and resolving it.

Annotations are added to real rendered PDFs with pikepdf (genuine /Annots,
not mocks), then extracted and resolved against the embedded text map.
"""

import io

import pytest

from emboss import Document
from emboss.annotations import (
    extract_comments,
    merge_comments,
    unresolved_count,
)

pikepdf = pytest.importorskip("pikepdf")


def _span(doc, node_id, word):
    idx = doc.text_index()
    return next(s for s in idx._index[node_id] if s["text"] == word)


def _annotate(pdf_bytes, specs):
    """Add markup annotations to a PDF. Each spec: (page, rect, subtype, T, C)."""
    with pikepdf.open(io.BytesIO(pdf_bytes)) as p:
        by_page = {}
        for page_i, rect, subtype, author, contents in specs:
            x0, y0, x1, y1 = rect
            quad = [x0, y1, x1, y1, x0, y0, x1, y0]
            annot = pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name(subtype),
                Rect=[x0, y0, x1, y1],
                QuadPoints=quad,
                T=author,
                Contents=contents,
            )
            by_page.setdefault(page_i, []).append(p.make_indirect(annot))
        for page_i, annots in by_page.items():
            p.pages[page_i].Annots = pikepdf.Array(annots)
        out = io.BytesIO()
        p.save(out)
        return out.getvalue()


def _doc():
    doc = Document(title="Report")
    doc.heading("Risk", level=1)
    doc.paragraph("The exposure exceeds four million dollars this quarter.", id="p1")
    doc.paragraph("A second paragraph follows with more detail here.", id="p2")
    return doc


class TestExtractExact:
    def test_highlight_resolves_to_node_and_range(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        s = _span(doc, "p1", "exceeds")
        marked = _annotate(
            pdf,
            [
                (
                    0,
                    [s["x0"], s["y0"], s["x1"], s["y1"]],
                    "/Highlight",
                    "R. Patel",
                    "Overstates it",
                )
            ],
        )
        comments = extract_comments(marked)
        assert len(comments) == 1
        c = comments[0]
        assert c.type == "highlight"
        assert c.author == "R. Patel"
        assert c.resolution == "exact"
        assert c.node_id == "p1"
        assert c.anchor_text == "exceeds"
        assert c.comment == "Overstates it"

    def test_strikeout_type_preserved(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        s = _span(doc, "p1", "four")
        marked = _annotate(
            pdf,
            [
                (
                    0,
                    [s["x0"], s["y0"], s["x1"], s["y1"]],
                    "/StrikeOut",
                    "M. Osei",
                    "wrong number",
                )
            ],
        )
        c = extract_comments(marked)[0]
        assert c.type == "strikeout"
        assert c.resolution == "exact"
        assert c.anchor_text == "four"


class TestResolutionStates:
    def test_spanning_two_paragraphs(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        a = _span(doc, "p1", "quarter.")
        b = _span(doc, "p2", "second")
        rect = [
            min(a["x0"], b["x0"]),
            min(a["y0"], b["y0"]),
            max(a["x1"], b["x1"]),
            max(a["y1"], b["y1"]),
        ]
        marked = _annotate(pdf, [(0, rect, "/Highlight", "R. Patel", "check")])
        c = extract_comments(marked)[0]
        assert c.resolution == "spanning"
        assert set(c.node_ids) == {"p1", "p2"}
        assert c.char_range is None

    def test_unanchored_over_empty_area(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        marked = _annotate(
            pdf, [(0, [430, 60, 520, 80], "/Highlight", "R. Patel", "stray")]
        )
        c = extract_comments(marked)[0]
        assert c.resolution == "unanchored"
        assert c.node_id is None
        assert c.page == 0
        assert c.rect is not None


class TestMissingTextmap:
    def test_raises_without_embedded_textmap(self):
        doc = _doc()
        pdf = doc.render()  # no embed_spec -> no text map
        s = _span(doc, "p1", "exceeds")
        marked = _annotate(
            pdf, [(0, [s["x0"], s["y0"], s["x1"], s["y1"]], "/Highlight", "R", "x")]
        )
        with pytest.raises(ValueError, match="emboss-textmap"):
            extract_comments(marked)


class TestMultiReviewer:
    def test_merge_unions_and_renumbers(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        s1 = _span(doc, "p1", "exceeds")
        s2 = _span(doc, "p2", "detail")
        legal = extract_comments(
            _annotate(
                pdf,
                [
                    (
                        0,
                        [s1["x0"], s1["y0"], s1["x1"], s1["y1"]],
                        "/Highlight",
                        "Legal",
                        "a",
                    )
                ],
            )
        )
        finance = extract_comments(
            _annotate(
                pdf,
                [
                    (
                        0,
                        [s2["x0"], s2["y0"], s2["x1"], s2["y1"]],
                        "/StrikeOut",
                        "Finance",
                        "b",
                    )
                ],
            )
        )
        merged = merge_comments(legal, finance)
        assert len(merged) == 2
        assert [c.id for c in merged] == ["c-01", "c-02"]
        assert {c.author for c in merged} == {"Legal", "Finance"}

    def test_merge_dedupes_identical(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        s = _span(doc, "p1", "exceeds")
        one = extract_comments(
            _annotate(
                pdf,
                [
                    (
                        0,
                        [s["x0"], s["y0"], s["x1"], s["y1"]],
                        "/Highlight",
                        "Legal",
                        "same",
                    )
                ],
            )
        )
        merged = merge_comments(one, list(one))
        assert len(merged) == 1


class TestUnresolvedCount:
    def test_counts_spanning_and_unanchored(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        s = _span(doc, "p1", "exceeds")
        marked = _annotate(
            pdf,
            [
                (0, [s["x0"], s["y0"], s["x1"], s["y1"]], "/Highlight", "R", "ok"),
                (0, [430, 60, 520, 80], "/Highlight", "R", "stray"),
            ],
        )
        comments = extract_comments(marked)
        assert unresolved_count(comments) == 1


class TestDeterminism:
    def test_ids_stable_across_extractions(self):
        doc = _doc()
        pdf = doc.render(embed_spec=True)
        s1 = _span(doc, "p1", "exceeds")
        s2 = _span(doc, "p2", "detail")
        marked = _annotate(
            pdf,
            [
                (0, [s1["x0"], s1["y0"], s1["x1"], s1["y1"]], "/Highlight", "A", "1"),
                (0, [s2["x0"], s2["y0"], s2["x1"], s2["y1"]], "/Highlight", "B", "2"),
            ],
        )
        first = [(c.id, c.node_id) for c in extract_comments(marked)]
        second = [(c.id, c.node_id) for c in extract_comments(marked)]
        assert first == second
