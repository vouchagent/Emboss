"""Tests for applying resolved comments and the HTML triage report."""

import pytest

from emboss import Document
from emboss.annotations import Comment
from emboss.review import (
    apply_comment,
    apply_replacements,
    propose_patches,
    redline,
)
from emboss.review_html import review_html


def _doc():
    doc = Document(title="Report")
    doc.paragraph("The exposure exceeds four million dollars this quarter.", id="p1")
    return doc


def _exact_comment(doc, phrase, replacement_note="fix"):
    idx = doc.text_index()
    nt = idx.node_text("p1")
    start = nt.index(phrase)
    return Comment(
        id="c-01",
        type="strikeout",
        author="Legal",
        page=0,
        comment=replacement_note,
        resolution="exact",
        node_id="p1",
        anchor_text=phrase,
        char_range=[start, start + len(phrase)],
    )


class TestApply:
    def test_exact_splices_only_the_range(self):
        doc = _doc()
        c = _exact_comment(doc, "four million")
        new = apply_comment(doc, c, "the netted 2.8 million")
        assert new.content[0].content == (
            "The exposure exceeds the netted 2.8 million dollars this quarter."
        )
        # Original is untouched.
        assert "four million" in doc.content[0].content

    def test_node_resolution_replaces_whole_text(self):
        doc = _doc()
        c = Comment(
            id="c-01",
            type="note",
            author="R",
            page=0,
            comment="rewrite",
            resolution="node",
            node_id="p1",
        )
        new = apply_comment(doc, c, "Rewritten.")
        assert new.content[0].content == "Rewritten."

    def test_spanning_is_not_patchable(self):
        doc = _doc()
        c = Comment(
            id="c-01",
            type="highlight",
            author="R",
            page=0,
            comment="x",
            resolution="spanning",
            node_ids=["p1", "p2"],
        )
        with pytest.raises(ValueError, match="spanning"):
            apply_comment(doc, c, "nope")

    def test_apply_replacements_by_id(self):
        doc = _doc()
        c = _exact_comment(doc, "exceeds")
        new = apply_replacements(doc, [c], {"c-01": "tops"})
        assert "tops" in new.content[0].content


class TestPropose:
    def test_patchable_reports_before_after(self):
        doc = _doc()
        c = _exact_comment(doc, "four million")
        patches = propose_patches(doc, [c], {"c-01": "2.8 million"})
        assert patches[0].patchable
        assert patches[0].before == "four million"
        assert patches[0].after == "2.8 million"

    def test_unpatchable_surfaced_not_dropped(self):
        doc = _doc()
        c = Comment(
            id="c-01",
            type="highlight",
            author="R",
            page=0,
            comment="x",
            resolution="unanchored",
        )
        patches = propose_patches(doc, [c], {})
        assert len(patches) == 1
        assert not patches[0].patchable
        assert "unanchored" in patches[0].note

    def test_missing_replacement_surfaced(self):
        doc = _doc()
        c = _exact_comment(doc, "exceeds")
        patches = propose_patches(doc, [c], {})
        assert patches[0].patchable
        assert "no replacement" in patches[0].note


class TestRedline:
    def test_redline_renders_pdf(self):
        doc = _doc()
        c = _exact_comment(doc, "four million")
        new = apply_comment(doc, c, "2.8 million")
        assert redline(doc, new).startswith(b"%PDF")


class TestExplicitIdRoundTrip:
    def test_explicit_id_survives_spec_json(self):
        from emboss.recovery import document_to_spec_dict, spec_dict_to_json

        doc = Document(title="R")
        doc.paragraph("Hello.", id="p1")
        doc.heading("H", level=2, id="h1")
        spec = spec_dict_to_json(document_to_spec_dict(doc)).decode()
        loaded = Document.from_json(spec)
        assert loaded.content[0].id == "p1"
        assert loaded.content[1].id == "h1"


class TestReviewHtml:
    def test_reports_unresolved_count(self):
        comments = [
            Comment(
                id="c-01",
                type="highlight",
                author="A",
                page=0,
                comment="ok",
                resolution="exact",
                node_id="p1",
                anchor_text="x",
            ),
            Comment(
                id="c-02",
                type="highlight",
                author="B",
                page=0,
                comment="stray",
                resolution="unanchored",
            ),
        ]
        out = review_html(comments)
        assert "1 of 2 unresolved" in out
        assert out.startswith("<!doctype html>")

    def test_all_resolved_message(self):
        comments = [
            Comment(
                id="c-01",
                type="highlight",
                author="A",
                page=0,
                comment="ok",
                resolution="exact",
                node_id="p1",
                anchor_text="x",
            ),
        ]
        assert "all 1 comments resolved" in review_html(comments)

    def test_escapes_reviewer_text(self):
        comments = [
            Comment(
                id="c-01",
                type="note",
                author="A",
                page=0,
                comment="<script>alert(1)</script>",
                resolution="node",
                node_id="p1",
            ),
        ]
        out = review_html(comments)
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out
