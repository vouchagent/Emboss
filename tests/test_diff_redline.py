"""Tests for node-keyed diff, redlined-PDF rendering, and Document.patch."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pikepdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emboss import Document  # noqa: E402
from emboss.diff import diff_documents, render_redline, word_diff  # noqa: E402
from emboss.recovery import document_to_spec_dict  # noqa: E402
from emboss.spec import Heading, Paragraph  # noqa: E402


def _page_content(pdf_bytes: bytes, page: int) -> bytes:
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        return bytes(pdf.pages[page].Contents.read_bytes())


def _page_count(pdf_bytes: bytes) -> int:
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def _sample_pair():
    """A base document and an edited copy: one change, one add, one remove."""
    old = Document(
        title="Report",
        content=[
            Heading("Intro", 1, id="h1"),
            Paragraph("The quick brown fox jumps.", id="p1"),
            Paragraph("Second paragraph here.", id="p2"),
        ],
    )
    new = Document(
        title="Report",
        content=[
            Heading("Intro", 1, id="h1"),
            Paragraph("The quick brown fox leaps high.", id="p1"),
            Paragraph("Brand new paragraph.", id="p3"),
        ],
    )
    return old, new


# -- word_diff ---------------------------------------------------------


class TestWordDiff:
    def test_equal_delete_insert_ops(self):
        ops = word_diff("The quick brown fox jumps.", "The quick brown fox leaps high.")
        assert ("equal", "The quick brown fox") in ops
        assert ("delete", "jumps.") in ops
        assert ("insert", "leaps high.") in ops

    def test_identical_text_is_all_equal(self):
        ops = word_diff("same words here", "same words here")
        assert ops == [("equal", "same words here")]
        assert all(op == "equal" for op, _ in ops)

    def test_deterministic(self):
        a = word_diff("alpha beta gamma", "alpha delta gamma")
        b = word_diff("alpha beta gamma", "alpha delta gamma")
        assert a == b


# -- diff_documents ------------------------------------------------------


class TestDiffDocuments:
    def test_identical_documents_have_no_changes(self):
        old, _ = _sample_pair()
        same = Document(title="Report", content=list(old.content))
        result = diff_documents(old, same)
        assert result.added == []
        assert result.removed == []
        assert result.changed == []
        assert set(result.unchanged) == {"h1", "p1", "p2"}

    def test_added_paragraph(self):
        old, new = _sample_pair()
        result = diff_documents(old, new)
        added_ids = {el.id for el in result.added}
        assert "p3" in added_ids

    def test_removed_heading(self):
        old = Document(
            title="Report",
            content=[
                Heading("Intro", 1, id="h1"),
                Heading("Old Section", 2, id="h2"),
                Paragraph("Body text.", id="p1"),
            ],
        )
        new = Document(
            title="Report",
            content=[
                Heading("Intro", 1, id="h1"),
                Paragraph("Body text.", id="p1"),
            ],
        )
        result = diff_documents(old, new)
        removed_ids = {el.id for el in result.removed}
        assert removed_ids == {"h2"}
        assert isinstance(result.removed[0], Heading)
        assert result.removed[0].text == "Old Section"

    def test_changed_paragraph_word_diff(self):
        old, new = _sample_pair()
        result = diff_documents(old, new)
        by_id = {
            new_el.id: (old_el, new_el, ops) for old_el, new_el, ops in result.changed
        }
        assert "p1" in by_id
        old_el, new_el, ops = by_id["p1"]
        assert old_el.plain_text == "The quick brown fox jumps."
        assert new_el.plain_text == "The quick brown fox leaps high."
        assert ("delete", "jumps.") in ops
        assert ("insert", "leaps high.") in ops
        assert ("equal", "The quick brown fox") in ops

    def test_unchanged_blocks_reported_by_id(self):
        old, new = _sample_pair()
        result = diff_documents(old, new)
        assert result.unchanged == ["h1"]

    def test_accepts_document_and_spec_dict(self):
        old, new = _sample_pair()
        old_spec = document_to_spec_dict(old)
        new_spec = document_to_spec_dict(new)

        doc_vs_doc = diff_documents(old, new)
        dict_vs_dict = diff_documents(old_spec, new_spec)
        doc_vs_dict = diff_documents(old, new_spec)

        for result in (doc_vs_doc, dict_vs_dict, doc_vs_dict):
            assert {el.id for el in result.added} == {"p3"}
            assert {el.id for el in result.removed} == {"p2"}
            changed_ids = {new_el.id for _, new_el, _ in result.changed}
            assert changed_ids == {"p1"}

    def test_derives_ids_when_absent(self):
        old = Document(title="", content=[Paragraph("hello world")])
        new = Document(title="", content=[Paragraph("hello world")])
        result = diff_documents(old, new)
        assert result.added == []
        assert result.removed == []
        assert result.changed == []
        assert len(result.unchanged) == 1


# -- render_redline --------------------------------------------------------


class TestRenderRedline:
    def test_produces_valid_pdf(self):
        old, new = _sample_pair()
        data = render_redline(old, new)
        assert data[:5] == b"%PDF-"
        assert _page_count(data) >= 2

    def test_strikethrough_and_underline_ops_present(self):
        old, new = _sample_pair()
        diff = diff_documents(old, new)
        data = render_redline(old, new, diff)
        # Body content starts on page 1 (page 0 is the summary page).
        body = _page_content(data, 1)
        assert b"jumps." in body
        assert b"leaps" in body
        # Strikethrough/underline are drawn as short stroked line segments
        # ("m ... l S") in the deletion/insertion colors.
        assert b"0.8627 0.0784 0.2353 RG" in body  # crimson stroke (deletion)
        assert b"0.1333 0.5451 0.1333 RG" in body  # forest-green stroke (insertion)
        assert b" m\n" in body and b" l\n" in body

    def test_added_block_change_bar_rect_present(self):
        old, new = _sample_pair()
        diff = diff_documents(old, new)
        data = render_redline(old, new, diff)
        found = False
        with pikepdf.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                content = bytes(page.Contents.read_bytes())
                if b"0.1333 0.5451 0.1333 rg" in content and b" re\nf" in content:
                    found = True
        assert found, "expected a forest-green filled rect for the added block"

    def test_summary_page_lists_counts_and_removed_excerpt(self):
        old, new = _sample_pair()
        diff = diff_documents(old, new)
        data = render_redline(old, new, diff)
        summary = _page_content(data, 0)
        assert b"(1)" in summary  # "1 block(s) added" etc, tokenized per word
        assert b"(Second)" in summary
        assert b"(paragraph)" in summary
        assert b"(here.)" in summary

    def test_removed_block_not_in_body_flow(self):
        old, new = _sample_pair()
        diff = diff_documents(old, new)
        data = render_redline(old, new, diff)
        body = b""
        with pikepdf.open(io.BytesIO(data)) as pdf:
            for i in range(1, len(pdf.pages)):
                body += bytes(pdf.pages[i].Contents.read_bytes())
        assert b"(Second)" not in body

    def test_determinism_double_render(self):
        old, new = _sample_pair()
        diff = diff_documents(old, new)
        first = render_redline(old, new, diff)
        second = render_redline(old, new, diff)
        assert first == second

    def test_diff_argument_is_optional(self):
        old, new = _sample_pair()
        data = render_redline(old, new)
        assert data[:5] == b"%PDF-"


# -- Document.patch --------------------------------------------------------


class TestDocumentPatch:
    def test_replaces_matching_block_by_id(self):
        doc = Document(
            title="",
            content=[
                Heading("A", 1, id="h1"),
                Paragraph("original text", id="p1"),
            ],
        )
        patched = doc.patch("p1", content="edited text")
        target = next(el for el in patched.content if el.id == "p1")
        assert isinstance(target, Paragraph)
        assert target.plain_text == "edited text"

    def test_leaves_other_blocks_untouched(self):
        doc = Document(
            title="",
            content=[
                Heading("A", 1, id="h1"),
                Paragraph("original text", id="p1"),
            ],
        )
        patched = doc.patch("p1", content="edited text")
        heading = next(el for el in patched.content if el.id == "h1")
        assert heading.text == "A"

    def test_returns_new_object_original_unchanged(self):
        doc = Document(
            title="",
            content=[Paragraph("original text", id="p1")],
        )
        patched = doc.patch("p1", content="edited text")
        assert patched is not doc
        assert doc.content[0].plain_text == "original text"
        assert patched.content[0].plain_text == "edited text"

    def test_unknown_id_raises_with_available_ids(self):
        doc = Document(
            title="",
            content=[
                Heading("A", 1, id="h1"),
                Paragraph("body", id="p1"),
            ],
        )
        with pytest.raises(ValueError) as excinfo:
            doc.patch("does-not-exist")
        message = str(excinfo.value)
        assert "h1" in message
        assert "p1" in message

    def test_patch_preserves_id_for_diffing(self):
        """A patch followed by diff_documents should show a 'changed' block."""
        old = Document(
            title="",
            content=[Paragraph("original text", id="p1")],
        )
        new = old.patch("p1", content="edited text")
        result = diff_documents(old, new)
        assert result.added == []
        assert result.removed == []
        changed_ids = {new_el.id for _, new_el, _ in result.changed}
        assert changed_ids == {"p1"}


# -- CLI ---------------------------------------------------------------


class TestDiffCLI:
    def test_end_to_end(self, tmp_path):
        old, new = _sample_pair()
        old_path = tmp_path / "old.pdf"
        new_path = tmp_path / "new.pdf"
        out_path = tmp_path / "redline.pdf"
        old_path.write_bytes(old.render(embed_spec=True))
        new_path.write_bytes(new.render(embed_spec=True))

        from emboss.__main__ import main

        exit_code = main(["diff", str(old_path), str(new_path), "-o", str(out_path)])
        assert exit_code == 0
        assert out_path.exists()
        data = out_path.read_bytes()
        assert data[:5] == b"%PDF-"

    def test_end_to_end_subprocess_reports_counts(self, tmp_path):
        old, new = _sample_pair()
        old_path = tmp_path / "old.pdf"
        new_path = tmp_path / "new.pdf"
        out_path = tmp_path / "redline.pdf"
        old_path.write_bytes(old.render(embed_spec=True))
        new_path.write_bytes(new.render(embed_spec=True))

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "emboss",
                "diff",
                str(old_path),
                str(new_path),
                "-o",
                str(out_path),
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            env={**__import__("os").environ, "PYTHONPATH": "src"},
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "added" in proc.stdout
        assert "removed" in proc.stdout
        assert "changed" in proc.stdout
        assert out_path.exists()

    def test_missing_file_reports_error(self, tmp_path):
        from emboss.__main__ import main

        exit_code = main(
            ["diff", str(tmp_path / "nope.pdf"), str(tmp_path / "also-nope.pdf")]
        )
        assert exit_code == 1
