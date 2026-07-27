"""Tests for hyperlink annotations and PDF/UA Link tagging."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document, TextRun  # noqa: E402
from emboss.pdf.verify import verify_pdf  # noqa: E402


def _link_doc(url: str = "https://example.com", **kw) -> Document:
    doc = Document(title="Link Test", **kw)
    doc.paragraph(
        [
            TextRun("Visit "),
            TextRun("the site", link=url),
            TextRun(" for details."),
        ]
    )
    return doc


def _rects(data: bytes) -> list:
    rects = []
    for match in re.finditer(rb"/Rect \[([-\d. ]+)\]", data):
        rects.append([float(v) for v in match.group(1).split()])
    return rects


class TestLinkAnnotations:
    def test_external_link_emits_annotation(self):
        data = _link_doc().render()
        assert b"/Annots" in data
        assert b"/Subtype /Link" in data
        assert b"/URI (https://example.com)" in data
        assert b"/Border [0 0 0]" in data

    def test_mailto_link_emits_annotation(self):
        data = _link_doc("mailto:someone@example.com").render()
        assert b"/URI (mailto:someone@example.com)" in data

    def test_rect_within_page(self):
        doc = _link_doc()
        data = doc.render()
        rects = _rects(data)
        assert len(rects) == 1
        x0, y0, x1, y1 = rects[0]
        assert 0 <= x0 < x1 <= doc.page.width
        assert 0 <= y0 < y1 <= doc.page.height

    def test_adjacent_fragments_merge_into_one_annot(self):
        doc = Document(title="Merged Link")
        doc.paragraph(
            [
                TextRun("click ", link="https://example.com"),
                TextRun("here", link="https://example.com"),
            ]
        )
        data = doc.render()
        assert data.count(b"/Subtype /Link") == 1

    def test_distinct_links_get_separate_annots(self):
        doc = Document(title="Two Links")
        doc.paragraph(
            [
                TextRun("first", link="https://example.com/a"),
                TextRun(" and "),
                TextRun("second", link="https://example.com/b"),
            ]
        )
        data = doc.render()
        assert data.count(b"/Subtype /Link") == 2
        assert b"/URI (https://example.com/a)" in data
        assert b"/URI (https://example.com/b)" in data

    def test_double_render_is_byte_identical(self):
        assert _link_doc().render() == _link_doc().render()

    def test_unknown_internal_anchor_is_skipped(self):
        data = _link_doc("#nowhere").render()
        assert b"/Annots" not in data
        assert b"/Subtype /Link" not in data

    def test_no_links_means_no_annots(self):
        doc = Document(title="Plain")
        doc.paragraph("No hyperlinks in this paragraph at all.")
        data = doc.render()
        assert b"/Annots" not in data
        assert b"/OBJR" not in data

    def test_verification_passes(self):
        report = verify_pdf(_link_doc().render())
        assert report.ok, report.problems


class TestLinkTagging:
    def test_tagged_output_contains_objr(self):
        data = _link_doc().render()
        assert b"/OBJR" in data
        assert b"/Link" in data

    def test_annot_has_struct_parent_after_page_keys(self):
        data = _link_doc().render()
        match = re.search(rb"/StructParent (\d+)", data)
        assert match is not None
        assert int(match.group(1)) >= 1

    def test_parent_tree_next_key_covers_annotations(self):
        data = _link_doc().render()
        match = re.search(rb"/ParentTreeNextKey (\d+)", data)
        assert match is not None
        assert int(match.group(1)) == 2

    def test_untagged_document_still_gets_annots(self):
        data = _link_doc(tagged=False).render()
        assert b"/Subtype /Link" in data
        assert b"/StructParent" not in data
        assert b"/OBJR" not in data

    def test_links_on_second_page_reference_that_page(self):
        doc = Document(title="Paged Links")
        for _ in range(40):
            doc.paragraph("Filler paragraph to push content down the page. " * 3)
        doc.paragraph([TextRun("late link", link="https://example.com/late")])
        result_data = doc.render()
        assert b"/URI (https://example.com/late)" in result_data
        report = verify_pdf(result_data)
        assert report.ok, report.problems
